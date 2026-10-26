# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CARLA rear-view camera to Cuttlefish virtio-media FIFO streaming logic."""

# pylint: disable=import-error, broad-exception-caught, invalid-name, too-many-instance-attributes

import fcntl
import os
import queue
import select
import stat
import threading
from typing import Optional

import carla
import numpy as np


DEFAULT_CAMERA_FIFO_PATH = "/tmp/v4l2_fifo"
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_FOV = 110.0

# Linux fcntl command to set pipe capacity (F_SETPIPE_SZ = 1031)
F_SETPIPE_SZ = 1031
PIPE_BUFFER_SIZE_BYTES = 1048576  # 1 MiB (fits >2 full 460,800-byte frames)

# Automatic gear enum value for Reverse (matches get_automatic_gear_data)
REVERSE_GEAR_MODE = 1


def bgra_to_ym12(bgra_array: np.ndarray) -> bytes:
    """Converts a (H, W, 4) uint8 BGRA array into 3-plane YM12 (YUV420M) bytes.

    Uses standard BT.601 limited-range integer conversion matching Cuttlefish's
    vhu_media_v4l2_stream_proxy and the Display Safety guest consumer.
    """
    b = bgra_array[:, :, 0].astype(np.int32)
    g = bgra_array[:, :, 1].astype(np.int32)
    r = bgra_array[:, :, 2].astype(np.int32)

    y = np.clip(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16, 0, 255).astype(
        np.uint8
    )

    r_sub = r[0::2, 0::2]
    g_sub = g[0::2, 0::2]
    b_sub = b[0::2, 0::2]

    u = np.clip(
        ((-38 * r_sub - 74 * g_sub + 112 * b_sub + 128) >> 8) + 128, 0, 255
    ).astype(np.uint8)
    v = np.clip(
        ((112 * r_sub - 94 * g_sub - 18 * b_sub + 128) >> 8) + 128, 0, 255
    ).astype(np.uint8)

    return y.tobytes() + u.tobytes() + v.tobytes()


class RearCameraStreamer:
    """Streams a rear-facing CARLA RGB camera into a host V4L2 named pipe (FIFO).

    The CARLA camera sensor is actively listening and rendering only when the
    tracked vehicle is in Reverse gear (gear_mode == 1).
    """

    def __init__(self, fifo_path: str = DEFAULT_CAMERA_FIFO_PATH):
        self.fifo_path = fifo_path
        self.sensor = None
        self.is_streaming = False
        self.frames_written = 0
        self._frame_queue: "queue.Queue[Optional[carla.Image]]" = queue.Queue(
            maxsize=1
        )
        self._stop_event = threading.Event()
        self._ensure_fifo()
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="RearCameraFifoWriter", daemon=True
        )
        self._writer_thread.start()

    def _ensure_fifo(self):
        parent_dir = os.path.dirname(self.fifo_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        if os.path.exists(self.fifo_path):
            mode = os.stat(self.fifo_path).st_mode
            if not stat.S_ISFIFO(mode):
                print(
                    f"\n[Camera] Warning: {self.fifo_path} exists and is not a"
                    " FIFO. Recreating as FIFO..."
                )
                if stat.S_ISREG(mode):
                    os.unlink(self.fifo_path)
                    os.mkfifo(self.fifo_path, 0o666)
        else:
            os.mkfifo(self.fifo_path, 0o666)
            print(f"\n[Camera] Created named pipe (FIFO) at {self.fifo_path}")

    def attach_to_vehicle(self, world, vehicle):
        """Spawns and attaches the rear-view camera sensor to the ego vehicle."""
        self.destroy_sensor()
        bound_x = 0.5 + vehicle.bounding_box.extent.x
        bound_z = 0.5 + vehicle.bounding_box.extent.z
        transform = carla.Transform(
            carla.Location(x=-bound_x, y=0.0, z=0.8 * bound_z),
            carla.Rotation(pitch=-10.0, yaw=180.0, roll=0.0),
        )
        bp = world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(CAMERA_WIDTH))
        bp.set_attribute("image_size_y", str(CAMERA_HEIGHT))
        bp.set_attribute("fov", str(CAMERA_FOV))
        bp.set_attribute("sensor_tick", str(1.0 / CAMERA_FPS))

        self.sensor = world.spawn_actor(
            bp,
            transform,
            attach_to=vehicle,
            attachment_type=carla.AttachmentType.Rigid,
        )
        self.is_streaming = False
        print(
            f"\n[Camera] Attached rear-view camera sensor (ID: {self.sensor.id},"
            f" {CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}fps) to vehicle"
            f" {vehicle.id} (FIFO: {self.fifo_path})"
        )

    def update_gear_state(self, gear_mode: int):
        """Starts or stops the CARLA camera sensor based on reverse gear state."""
        if self.sensor is None:
            return
        should_stream = gear_mode == REVERSE_GEAR_MODE
        if should_stream and not self.is_streaming:
            self.sensor.listen(self._on_carla_image)
            self.is_streaming = True
            print(
                f"\n[Camera] Reverse gear engaged: started rear camera stream to"
                f" {self.fifo_path}"
            )
        elif not should_stream and self.is_streaming:
            self.sensor.stop()
            self.is_streaming = False
            self._clear_frame_queue()
            print("\n[Camera] Left reverse gear: paused rear camera stream")

    def _clear_frame_queue(self):
        try:
            self._frame_queue.get_nowait()
        except queue.Empty:
            pass

    def _on_carla_image(self, image):
        if not self.is_streaming or self._stop_event.is_set():
            return
        self._clear_frame_queue()
        try:
            self._frame_queue.put_nowait(image)
        except queue.Full:
            pass

    def _writer_loop(self):
        fd = None
        while not self._stop_event.is_set():
            try:
                image = self._frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if image is None:
                break

            if fd is None:
                try:
                    fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        fcntl.fcntl(fd, F_SETPIPE_SZ, PIPE_BUFFER_SIZE_BYTES)
                    except OSError:
                        pass
                    print(
                        f"\n[Camera] Connected to FIFO reader on {self.fifo_path}"
                    )
                except OSError:
                    # E.g. errno.ENXIO when no reader has opened the FIFO yet
                    fd = None
                    continue

            bgra = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                (image.height, image.width, 4)
            )
            frame_bytes = bgra_to_ym12(bgra)
            view = memoryview(frame_bytes)
            total_len = len(frame_bytes)
            written = 0
            write_failed = False

            while written < total_len and not self._stop_event.is_set():
                try:
                    n = os.write(fd, view[written:])
                    written += n
                except BlockingIOError:
                    _, wlist, _ = select.select([], [fd], [], 0.5)
                    if not wlist and written == 0:
                        # No bytes of this frame written yet; drop stale frame
                        break
                except (BrokenPipeError, OSError):
                    write_failed = True
                    break

            if write_failed:
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = None
            elif written == total_len:
                self.frames_written += 1

        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def destroy_sensor(self):
        """Stops and destroys the CARLA camera sensor actor if present."""
        if self.sensor is not None:
            try:
                if self.is_streaming:
                    self.sensor.stop()
            except Exception:
                pass
            self.is_streaming = False
            try:
                if self.sensor.is_alive:
                    self.sensor.destroy()
            except Exception:
                pass
            self.sensor = None

    def shutdown(self):
        """Stops the background writer thread and destroys the CARLA sensor."""
        self._stop_event.set()
        self.destroy_sensor()
        self._clear_frame_queue()
        try:
            self._frame_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._writer_thread.is_alive():
            self._writer_thread.join(timeout=2.0)
