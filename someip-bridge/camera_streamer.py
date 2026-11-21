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

"""CARLA camera to Cuttlefish virtio-media FIFO streaming logic."""

# pylint: disable=import-error, broad-exception-caught, invalid-name, too-many-instance-attributes

import argparse
import fcntl
import os
import queue
import select
import signal
import stat
import threading
import time
from typing import Optional

import carla
import numpy as np


DEFAULT_CAMERA_FIFO_PATH = "/tmp/v4l2_fifo"
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_FOV = 110.0

DEFAULT_FRONT_CAMERA_FIFO_PATH = "/tmp/v4l2_front_fifo"
FRONT_CAMERA_WIDTH = 1920
FRONT_CAMERA_HEIGHT = 1080
FRONT_CAMERA_FPS = 5
FRONT_CAMERA_FOV = 90.0

# Linux fcntl command to set pipe capacity (F_SETPIPE_SZ = 1031)
F_SETPIPE_SZ = 1031
PIPE_BUFFER_SIZE_BYTES = 1048576  # 1 MiB (matches default unprivileged pipe max)
READER_POLL_INTERVAL_S = 0.2

# Automatic gear enum value for Reverse (matches get_automatic_gear_data)
REVERSE_GEAR_MODE = 1


def bgra_to_ym12(bgra_array: np.ndarray) -> bytes:
    """Converts a (H, W, 4) uint8 BGRA array into 3-plane YM12 (YUV420M) bytes.

    Uses standard BT.601 limited-range integer conversion matching Cuttlefish's
    vhu_media_v4l2_stream_proxy and guest virtio-media V4L2 consumers.
    """
    if bgra_array.ndim != 3 or bgra_array.shape[2] != 4:
        raise ValueError(
            f"Expected (H, W, 4) BGRA array, got shape {bgra_array.shape}"
        )
    height, width, _ = bgra_array.shape
    if height <= 0 or width <= 0 or (height % 2) != 0 or (width % 2) != 0:
        raise ValueError(
            f"YM12 requires positive even dimensions, got {width}x{height}"
        )

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


class _BaseCameraFifoStreamer:
    """Base streamer pushing CARLA RGB camera frames as YM12 into a host FIFO."""

    def __init__(
        self,
        fifo_path: str,
        width: int,
        height: int,
        fps: int,
        fov: float,
        thread_name: str,
        log_tag: str,
        on_demand: bool = False,
    ):
        if width <= 0 or height <= 0 or (width % 2) != 0 or (height % 2) != 0:
            raise ValueError(
                f"Camera dimensions must be positive even integers, got {width}x{height}"
            )
        if fps <= 0:
            raise ValueError(f"Camera FPS must be positive, got {fps}")
        self.fifo_path = fifo_path
        self.width = width
        self.height = height
        self.fps = fps
        self.fov = fov
        self._log_tag = log_tag
        self._on_demand = on_demand
        self._sensor_lock = threading.Lock()
        self.sensor = None
        self.is_streaming = False
        self.frames_written = 0
        self._frame_queue: "queue.Queue[Optional[carla.Image]]" = queue.Queue(
            maxsize=1
        )
        self._stop_event = threading.Event()
        self._ensure_fifo()
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name=thread_name, daemon=True
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
                    f"\n[{self._log_tag}] Warning: {self.fifo_path} exists and"
                    " is not a FIFO. Recreating as FIFO..."
                )
                if stat.S_ISREG(mode):
                    os.unlink(self.fifo_path)
                    os.mkfifo(self.fifo_path, 0o666)
        else:
            os.mkfifo(self.fifo_path, 0o666)
            print(
                f"\n[{self._log_tag}] Created named pipe (FIFO) at"
                f" {self.fifo_path}"
            )

    def _spawn_camera_sensor(self, world, vehicle, transform: "carla.Transform"):
        bp = world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(self.width))
        bp.set_attribute("image_size_y", str(self.height))
        bp.set_attribute("fov", str(self.fov))
        bp.set_attribute("sensor_tick", str(1.0 / self.fps))

        self.sensor = world.spawn_actor(
            bp,
            transform,
            attach_to=vehicle,
            attachment_type=carla.AttachmentType.Rigid,
        )

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

    def _start_sensor_listening(self) -> bool:
        with self._sensor_lock:
            if self.sensor is None or self.is_streaming:
                return self.is_streaming
            self.sensor.listen(self._on_carla_image)
            self.is_streaming = True
            return True

    def _stop_sensor_listening(self):
        with self._sensor_lock:
            if self.sensor is not None and self.is_streaming:
                try:
                    self.sensor.stop()
                except Exception:
                    pass
            self.is_streaming = False
        self._clear_frame_queue()

    def _try_open_fifo_writer(self) -> Optional[int]:
        try:
            fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            # E.g. errno.ENXIO when no reader has opened the FIFO yet.
            return None
        try:
            fcntl.fcntl(fd, F_SETPIPE_SZ, PIPE_BUFFER_SIZE_BYTES)
        except OSError:
            pass
        print(
            f"\n[{self._log_tag}] Connected to FIFO reader on {self.fifo_path}",
            flush=True,
        )
        return fd

    @staticmethod
    def _is_fifo_reader_closed(fd: int) -> bool:
        poller = select.poll()
        poller.register(fd, select.POLLERR | select.POLLHUP)
        events = poller.poll(0)
        return any(ev & (select.POLLERR | select.POLLHUP) for _, ev in events)

    def _close_fifo_writer(self, fd: Optional[int], stop_sensor: bool = False):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if stop_sensor:
            was_streaming = self.is_streaming
            self._stop_sensor_listening()
            if was_streaming:
                print(
                    f"\n[{self._log_tag}] FIFO reader disconnected: paused"
                    f" camera sensor on {self.fifo_path}",
                    flush=True,
                )

    def _writer_loop(self):
        fd = None
        while not self._stop_event.is_set():
            if self._on_demand and fd is None:
                if self.sensor is None:
                    self._stop_event.wait(READER_POLL_INTERVAL_S)
                    continue
                fd = self._try_open_fifo_writer()
                if fd is None:
                    self._stop_event.wait(READER_POLL_INTERVAL_S)
                    continue
                self._start_sensor_listening()
            elif self._on_demand and fd is not None and not self.is_streaming:
                if self.sensor is not None and not self._is_fifo_reader_closed(fd):
                    self._start_sensor_listening()

            try:
                image = self._frame_queue.get(timeout=READER_POLL_INTERVAL_S)
            except queue.Empty:
                if (
                    self._on_demand
                    and fd is not None
                    and (self.sensor is None or self._is_fifo_reader_closed(fd))
                ):
                    self._close_fifo_writer(fd, stop_sensor=True)
                    fd = None
                continue

            if image is None:
                break

            if fd is None:
                fd = self._try_open_fifo_writer()
                if fd is None:
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
                self._close_fifo_writer(fd, stop_sensor=self._on_demand)
                fd = None
            elif written == total_len:
                self.frames_written += 1

        self._close_fifo_writer(fd, stop_sensor=False)

    def destroy_sensor(self):
        """Stops and destroys the CARLA camera sensor actor if present."""
        with self._sensor_lock:
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


class RearCameraStreamer(_BaseCameraFifoStreamer):
    """Streams a rear-facing CARLA RGB camera into a host V4L2 named pipe (FIFO).

    The CARLA camera sensor is actively listening and rendering only when the
    tracked vehicle is in Reverse gear (gear_mode == 1).
    """

    def __init__(self, fifo_path: str = DEFAULT_CAMERA_FIFO_PATH):
        super().__init__(
            fifo_path=fifo_path,
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fps=CAMERA_FPS,
            fov=CAMERA_FOV,
            thread_name="RearCameraFifoWriter",
            log_tag="Camera",
        )

    def attach_to_vehicle(self, world, vehicle):
        """Spawns and attaches the rear-view camera sensor to the ego vehicle."""
        self.destroy_sensor()
        bound_x = 0.5 + vehicle.bounding_box.extent.x
        bound_z = 0.5 + vehicle.bounding_box.extent.z
        transform = carla.Transform(
            carla.Location(x=-bound_x, y=0.0, z=0.8 * bound_z),
            carla.Rotation(pitch=-10.0, yaw=180.0, roll=0.0),
        )
        self._spawn_camera_sensor(world, vehicle, transform)
        self.is_streaming = False
        print(
            f"\n[Camera] Attached rear-view camera sensor (ID: {self.sensor.id},"
            f" {self.width}x{self.height}@{self.fps}fps) to vehicle"
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
                "\n[Camera] Reverse gear engaged: started rear camera stream to"
                f" {self.fifo_path}"
            )
        elif not should_stream and self.is_streaming:
            self.sensor.stop()
            self.is_streaming = False
            self._clear_frame_queue()
            print("\n[Camera] Left reverse gear: paused rear camera stream")


class FrontCameraStreamer(_BaseCameraFifoStreamer):
    """Streams a front-facing CARLA RGB camera on demand into a host FIFO.

    By default (`on_demand=True`), the CARLA camera sensor stays paused while
    no reader has `fifo_path` open so CARLA pays zero GPU/CPU rendering cost
    when no Android Automotive consumer (such as Argus / Context Buffer) is
    actively streaming. As soon as a FIFO reader connects (e.g. Cuttlefish's
    `vhu_media_v4l2_stream_proxy` on `VIDIOC_STREAMON`), the sensor starts
    listening automatically, and stops again as soon as the reader closes.
    """

    def __init__(
        self,
        fifo_path: str = DEFAULT_FRONT_CAMERA_FIFO_PATH,
        width: int = FRONT_CAMERA_WIDTH,
        height: int = FRONT_CAMERA_HEIGHT,
        fps: int = FRONT_CAMERA_FPS,
        fov: float = FRONT_CAMERA_FOV,
        on_demand: bool = True,
    ):
        super().__init__(
            fifo_path=fifo_path,
            width=width,
            height=height,
            fps=fps,
            fov=fov,
            thread_name="FrontCameraFifoWriter",
            log_tag="FrontCamera",
            on_demand=on_demand,
        )

    def attach_to_vehicle(self, world, vehicle):
        """Spawns and attaches the front-facing camera sensor."""
        self.destroy_sensor()
        bound_x = 0.5 + vehicle.bounding_box.extent.x
        bound_z = 0.5 + vehicle.bounding_box.extent.z
        transform = carla.Transform(
            carla.Location(x=bound_x, y=0.0, z=0.8 * bound_z),
            carla.Rotation(pitch=-2.0, yaw=0.0, roll=0.0),
        )
        with self._sensor_lock:
            self._spawn_camera_sensor(world, vehicle, transform)
            if not self._on_demand:
                self.is_streaming = True
                self.sensor.listen(self._on_carla_image)
        mode_desc = "on-demand (waiting for FIFO reader)" if self._on_demand else "continuous"
        print(
            f"\n[FrontCamera] Attached front camera sensor (ID:"
            f" {self.sensor.id}, {self.width}x{self.height}@{self.fps}fps,"
            f" {mode_desc}) on vehicle {vehicle.id} (FIFO: {self.fifo_path})",
            flush=True,
        )


def _find_hero_vehicle(world):
    fallback = None
    for actor in world.get_actors().filter("vehicle.*"):
        if fallback is None:
            fallback = actor
        if actor.attributes.get("role_name") == "hero":
            return actor
    return fallback


def _run_standalone_front_camera(args):
    """Standalone runner attaching a FrontCameraStreamer to a live CARLA hero."""
    stop_requested = threading.Event()

    def _handle_sig(_signum, _frame):
        stop_requested.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    client = carla.Client(args.host, args.port)
    client.set_timeout(15.0)
    world = client.get_world()
    streamer = FrontCameraStreamer(
        fifo_path=args.fifo_path,
        width=args.width,
        height=args.height,
        fps=args.fps,
        fov=args.fov,
    )
    current_vehicle_id = None
    last_log = 0.0
    try:
        while not stop_requested.is_set():
            try:
                world.wait_for_tick(5.0)
            except RuntimeError:
                time.sleep(0.5)
                continue
            vehicle = _find_hero_vehicle(world)
            if vehicle is None:
                if current_vehicle_id is not None:
                    streamer.destroy_sensor()
                    current_vehicle_id = None
                time.sleep(1.0)
                continue
            if (
                current_vehicle_id != vehicle.id
                or streamer.sensor is None
                or not streamer.sensor.is_alive
            ):
                streamer.attach_to_vehicle(world, vehicle)
                current_vehicle_id = vehicle.id
            now = time.time()
            if now - last_log >= 10.0:
                print(
                    f"[FrontCamera] hero={current_vehicle_id}"
                    f" frames_written={streamer.frames_written}"
                    f" fifo={streamer.fifo_path}",
                    flush=True,
                )
                last_log = now
            stop_requested.wait(1.0)
    finally:
        streamer.shutdown()
        print("[FrontCamera] Standalone streamer stopped.", flush=True)


def _build_standalone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone CARLA front-facing camera FIFO streamer"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument(
        "--fifo-path", default=DEFAULT_FRONT_CAMERA_FIFO_PATH
    )
    parser.add_argument("--width", type=int, default=FRONT_CAMERA_WIDTH)
    parser.add_argument("--height", type=int, default=FRONT_CAMERA_HEIGHT)
    parser.add_argument("--fps", type=int, default=FRONT_CAMERA_FPS)
    parser.add_argument("--fov", type=float, default=FRONT_CAMERA_FOV)
    return parser


if __name__ == "__main__":
    _run_standalone_front_camera(_build_standalone_parser().parse_args())
