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

"""Unit tests for CARLA rear and front camera FIFO streaming."""

import asyncio
import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

import numpy as np

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _make_fake_carla_module():
    """Creates a minimal fake `carla` module for offline unit testing."""
    carla_mod = types.ModuleType("carla")

    class Location:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x = x
            self.y = y
            self.z = z

    class Rotation:
        def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
            self.pitch = pitch
            self.yaw = yaw
            self.roll = roll

    class Transform:
        def __init__(self, location=None, rotation=None):
            self.location = location or Location()
            self.rotation = rotation or Rotation()

    class AttachmentType:
        Rigid = "Rigid"

    class Image:
        def __init__(self, width, height, raw_data):
            self.width = width
            self.height = height
            self.raw_data = raw_data

    carla_mod.Location = Location
    carla_mod.Rotation = Rotation
    carla_mod.Transform = Transform
    carla_mod.AttachmentType = AttachmentType
    carla_mod.Image = Image
    carla_mod.VehicleLightState = types.SimpleNamespace(
        NONE=0,
        Position=1,
        LowBeam=2,
        HighBeam=4,
        Brake=8,
        RightBlinker=16,
        LeftBlinker=32,
        Reverse=64,
        Fog=128,
        Interior=256,
        Special1=512,
        Special2=1024,
        All=0xFFFF,
    )
    return carla_mod


class _FakeBlueprint:
    def __init__(self, name):
        self.name = name
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _FakeSensor:
    def __init__(self, sensor_id, blueprint, transform, vehicle, attachment):
        self.id = sensor_id
        self.blueprint = blueprint
        self.transform = transform
        self.vehicle = vehicle
        self.attachment = attachment
        self.is_alive = True
        self.callback = None
        self.listen_calls = 0
        self.stop_calls = 0
        self.destroy_calls = 0

    def listen(self, callback):
        self.callback = callback
        self.listen_calls += 1

    def stop(self):
        self.callback = None
        self.stop_calls += 1

    def destroy(self):
        self.is_alive = False
        self.destroy_calls += 1

    def emit(self, image):
        if self.callback is not None:
            self.callback(image)


class _FakeActorList(list):
    def filter(self, _pattern):
        return self


class _FakeVehicle:
    def __init__(self, actor_id=42, role_name="hero", extent=(2.0, 1.0, 0.8)):
        self.id = actor_id
        self.type_id = "vehicle.mini.cooper_s_2021"
        self.attributes = {"role_name": role_name}
        self.bounding_box = types.SimpleNamespace(
            extent=types.SimpleNamespace(x=extent[0], y=extent[1], z=extent[2])
        )
        self.destroyed = False

    def set_autopilot(self, _enabled):
        pass

    def destroy(self):
        self.destroyed = True


class _FakeWorld:
    def __init__(self, actors=None):
        self._next_id = 100
        self.spawned_sensors = []
        self._actors = list(actors or [])
        self.tick_calls = 0

    def get_blueprint_library(self):
        class _BpLib:
            def find(self, name):
                return _FakeBlueprint(name)

            def filter(self, name):
                return [_FakeBlueprint(name)]

        return _BpLib()

    def get_map(self):
        return types.SimpleNamespace(get_spawn_points=lambda: ["sp0"])

    def get_actors(self):
        return _FakeActorList(self._actors)

    def spawn_actor(self, bp, transform, attach_to=None, attachment_type=None):
        if attach_to is None:
            v = _FakeVehicle(actor_id=99, role_name="hero")
            self._actors.append(v)
            return v
        sensor = _FakeSensor(
            self._next_id, bp, transform, attach_to, attachment_type
        )
        self._next_id += 1
        self.spawned_sensors.append(sensor)
        return sensor

    def tick(self):
        self.tick_calls += 1


def _load_camera_streamer():
    if BRIDGE_DIR not in sys.path:
        sys.path.insert(0, BRIDGE_DIR)
    sys.modules["carla"] = _make_fake_carla_module()
    if "camera_streamer" in sys.modules:
        return importlib.reload(sys.modules["camera_streamer"])
    return importlib.import_module("camera_streamer")


def _read_exact_from_fifo(fifo_path, num_bytes, timeout=5.0):
    """Reads `num_bytes` from a named pipe on a helper thread."""
    result = bytearray()
    errors = []

    def _reader():
        fd = None
        try:
            fd = os.open(fifo_path, os.O_RDONLY)
            deadline = time.monotonic() + timeout
            while len(result) < num_bytes and time.monotonic() < deadline:
                chunk = os.read(fd, min(262144, num_bytes - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
        except Exception as exc:  # pragma: no cover - debug safety
            errors.append(exc)
        finally:
            if fd is not None:
                os.close(fd)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread, result, errors


def _wait_for_condition(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestBgraToYm12(unittest.TestCase):
    """Tests BT.601 limited-range BGRA -> YM12 (I420 / YUV420M) conversion."""

    @classmethod
    def setUpClass(cls):
        cls.cs = _load_camera_streamer()

    def test_output_sizes_match_yuv420_3_planes(self):
        for width, height in [(4, 4), (640, 480), (1920, 1080)]:
            bgra = np.zeros((height, width, 4), dtype=np.uint8)
            ym12 = self.cs.bgra_to_ym12(bgra)
            expected = width * height * 3 // 2
            self.assertEqual(len(ym12), expected)

    def test_bt601_primary_colors_verify_plane_ordering(self):
        # 2x2 solid tiles verify Y, U (Cb), and V (Cr) plane order (not swapped).
        # Pure black -> (Y=16, U=128, V=128)
        # Pure white -> (Y=235, U=128, V=128)
        # Pure red   (BGRA: 0, 0, 255, 255)   -> Y=82,  U=90,  V=240
        # Pure green (BGRA: 0, 255, 0, 255)   -> Y=145, U=54,  V=34
        # Pure blue  (BGRA: 255, 0, 0, 255)   -> Y=41,  U=240, V=110
        cases = [
            ("black", (0, 0, 0, 255), (16, 128, 128)),
            ("white", (255, 255, 255, 255), (235, 128, 128)),
            ("red", (0, 0, 255, 255), (82, 90, 240)),
            ("green", (0, 255, 0, 255), (144, 54, 34)),
            ("blue", (255, 0, 0, 255), (41, 240, 110)),
        ]
        for name, bgra_px, (exp_y, exp_u, exp_v) in cases:
            with self.subTest(color=name):
                img = np.empty((2, 2, 4), dtype=np.uint8)
                img[:, :] = bgra_px
                out = self.cs.bgra_to_ym12(img)
                self.assertEqual(len(out), 6)  # 4 Y + 1 U + 1 V
                y_plane = list(out[:4])
                u_val = out[4]
                v_val = out[5]
                self.assertEqual(y_plane, [exp_y] * 4)
                self.assertAlmostEqual(u_val, exp_u, delta=1)
                self.assertAlmostEqual(v_val, exp_v, delta=1)

    def test_rejects_invalid_shape_and_odd_dimensions(self):
        with self.assertRaises(ValueError):
            self.cs.bgra_to_ym12(np.zeros((4, 4, 3), dtype=np.uint8))
        with self.assertRaises(ValueError):
            self.cs.bgra_to_ym12(np.zeros((5, 4, 4), dtype=np.uint8))
        with self.assertRaises(ValueError):
            self.cs.bgra_to_ym12(np.zeros((4, 5, 4), dtype=np.uint8))


class TestCameraStreamers(unittest.TestCase):
    """Tests RearCameraStreamer, FrontCameraStreamer, and real FIFO transport."""

    def setUp(self):
        self.cs = _load_camera_streamer()
        self.tmpdir = tempfile.mkdtemp(prefix="test_cam_streamer_")
        self.streamers = []

    def tearDown(self):
        for s in self.streamers:
            s.shutdown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _track(self, streamer):
        self.streamers.append(streamer)
        return streamer

    def test_defaults_use_separate_fifos(self):
        self.assertEqual(self.cs.DEFAULT_CAMERA_FIFO_PATH, "/tmp/v4l2_fifo")
        self.assertEqual(
            self.cs.DEFAULT_FRONT_CAMERA_FIFO_PATH, "/tmp/v4l2_front_fifo"
        )
        self.assertNotEqual(
            self.cs.DEFAULT_CAMERA_FIFO_PATH,
            self.cs.DEFAULT_FRONT_CAMERA_FIFO_PATH,
        )
        self.assertEqual((self.cs.CAMERA_WIDTH, self.cs.CAMERA_HEIGHT), (640, 480))
        self.assertEqual(
            (self.cs.FRONT_CAMERA_WIDTH, self.cs.FRONT_CAMERA_HEIGHT), (1920, 1080)
        )
        self.assertEqual(self.cs.FRONT_CAMERA_FPS, 5)

    def test_replaces_stale_regular_file_with_fifo(self):
        fifo = os.path.join(self.tmpdir, "nested", "front_fifo")
        os.makedirs(os.path.dirname(fifo), exist_ok=True)
        with open(fifo, "wb") as f:
            f.write(b"stale")
        self._track(self.cs.FrontCameraStreamer(fifo_path=fifo, width=4, height=4))
        self.assertTrue(stat.S_ISFIFO(os.stat(fifo).st_mode))

    def test_validates_dimensions_and_fps(self):
        fifo = os.path.join(self.tmpdir, "bad_fifo")
        with self.assertRaises(ValueError):
            self.cs.FrontCameraStreamer(fifo_path=fifo, width=641, height=480)
        with self.assertRaises(ValueError):
            self.cs.FrontCameraStreamer(fifo_path=fifo, width=640, height=0)
        with self.assertRaises(ValueError):
            self.cs.FrontCameraStreamer(fifo_path=fifo, fps=0)

    def test_rear_camera_only_streams_in_reverse_gear(self):
        fifo = os.path.join(self.tmpdir, "rear_fifo")
        streamer = self._track(self.cs.RearCameraStreamer(fifo_path=fifo))
        world = _FakeWorld()
        vehicle = _FakeVehicle(actor_id=7, extent=(2.0, 1.0, 0.8))

        streamer.attach_to_vehicle(world, vehicle)
        sensor = streamer.sensor
        self.assertIsNotNone(sensor)
        self.assertFalse(streamer.is_streaming)
        self.assertEqual(sensor.listen_calls, 0)
        # Rear mount: x = -(0.5 + 2.0) = -2.5, yaw = 180, pitch = -10
        self.assertAlmostEqual(sensor.transform.location.x, -2.5)
        self.assertAlmostEqual(sensor.transform.rotation.yaw, 180.0)
        self.assertAlmostEqual(sensor.transform.rotation.pitch, -10.0)
        self.assertEqual(sensor.blueprint.attributes["image_size_x"], "640")
        self.assertEqual(sensor.blueprint.attributes["image_size_y"], "480")

        # Park (0), Neutral (2), Drive (3) keep streaming off.
        for gear in (0, 2, 3):
            streamer.update_gear_state(gear)
            self.assertFalse(streamer.is_streaming)
            self.assertEqual(sensor.listen_calls, 0)

        # Reverse (1) starts listening.
        streamer.update_gear_state(self.cs.REVERSE_GEAR_MODE)
        self.assertTrue(streamer.is_streaming)
        self.assertEqual(sensor.listen_calls, 1)

        # Leaving Reverse stops listening.
        streamer.update_gear_state(3)
        self.assertFalse(streamer.is_streaming)
        self.assertEqual(sensor.stop_calls, 1)

    def test_front_camera_starts_continuously_on_attach(self):
        fifo = os.path.join(self.tmpdir, "front_fifo")
        streamer = self._track(self.cs.FrontCameraStreamer(fifo_path=fifo))
        world = _FakeWorld()
        vehicle = _FakeVehicle(actor_id=199, extent=(1.9, 0.9, 0.7))

        streamer.attach_to_vehicle(world, vehicle)
        sensor = streamer.sensor
        self.assertIsNotNone(sensor)
        self.assertTrue(streamer.is_streaming)
        self.assertEqual(sensor.listen_calls, 1)
        # Front mount: x = +(0.5 + 1.9) = +2.4, yaw = 0, pitch = -2
        self.assertAlmostEqual(sensor.transform.location.x, 2.4)
        self.assertAlmostEqual(sensor.transform.location.z, 0.8 * (0.5 + 0.7))
        self.assertAlmostEqual(sensor.transform.rotation.yaw, 0.0)
        self.assertAlmostEqual(sensor.transform.rotation.pitch, -2.0)
        self.assertEqual(sensor.blueprint.attributes["image_size_x"], "1920")
        self.assertEqual(sensor.blueprint.attributes["image_size_y"], "1080")
        self.assertEqual(sensor.blueprint.attributes["fov"], "90.0")
        self.assertEqual(sensor.blueprint.attributes["sensor_tick"], "0.2")

        # Re-attaching destroys the previous sensor cleanly.
        streamer.attach_to_vehicle(world, vehicle)
        self.assertEqual(sensor.stop_calls, 1)
        self.assertEqual(sensor.destroy_calls, 1)
        self.assertFalse(sensor.is_alive)
        self.assertIsNot(streamer.sensor, sensor)

    def test_front_camera_1080p_multi_chunk_fifo_roundtrip(self):
        """Verifies a full 3,110,400-byte 1080p YM12 frame traverses the 1 MiB FIFO intact."""
        fifo = os.path.join(self.tmpdir, "front_1080p_fifo")
        streamer = self._track(
            self.cs.FrontCameraStreamer(
                fifo_path=fifo, width=1920, height=1080, fps=5
            )
        )
        world = _FakeWorld()
        streamer.attach_to_vehicle(world, _FakeVehicle())

        # Non-uniform BGRA frame so any offset/truncation would be detected.
        bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)
        bgra[:, :, 0] = np.arange(1920, dtype=np.uint8)
        bgra[:, :, 1] = np.arange(1080, dtype=np.uint8)[:, None]
        bgra[:, :, 2] = 180
        bgra[:, :, 3] = 255
        expected = self.cs.bgra_to_ym12(bgra)
        self.assertEqual(len(expected), 1920 * 1080 * 3 // 2)

        reader_thread, received, errors = _read_exact_from_fifo(
            fifo, len(expected), timeout=5.0
        )
        # Emit after opening reader so non-blocking O_WRONLY connects.
        time.sleep(0.05)
        img = sys.modules["carla"].Image(1920, 1080, bgra.tobytes())
        streamer.sensor.emit(img)

        reader_thread.join(timeout=5.0)
        self.assertEqual(errors, [])
        self.assertEqual(bytes(received), expected)
        self.assertTrue(_wait_for_condition(lambda: streamer.frames_written == 1))

    def test_front_and_rear_stream_simultaneously_without_cross_talk(self):
        rear_fifo = os.path.join(self.tmpdir, "rear_iso_fifo")
        front_fifo = os.path.join(self.tmpdir, "front_iso_fifo")
        rear = self._track(self.cs.RearCameraStreamer(fifo_path=rear_fifo))
        front = self._track(
            self.cs.FrontCameraStreamer(fifo_path=front_fifo, width=8, height=8, fps=5)
        )
        world = _FakeWorld()
        vehicle = _FakeVehicle()
        rear.attach_to_vehicle(world, vehicle)
        front.attach_to_vehicle(world, vehicle)
        rear.update_gear_state(self.cs.REVERSE_GEAR_MODE)

        rear_bgra = np.full((480, 640, 4), (0, 0, 255, 255), dtype=np.uint8)
        front_bgra = np.full((8, 8, 4), (255, 0, 0, 255), dtype=np.uint8)
        exp_rear = self.cs.bgra_to_ym12(rear_bgra)
        exp_front = self.cs.bgra_to_ym12(front_bgra)

        rt, rear_buf, rerr = _read_exact_from_fifo(rear_fifo, len(exp_rear))
        ft, front_buf, ferr = _read_exact_from_fifo(front_fifo, len(exp_front))
        time.sleep(0.05)

        rear.sensor.emit(sys.modules["carla"].Image(640, 480, rear_bgra.tobytes()))
        front.sensor.emit(sys.modules["carla"].Image(8, 8, front_bgra.tobytes()))
        rt.join(timeout=5.0)
        ft.join(timeout=5.0)

        self.assertEqual(rerr, [])
        self.assertEqual(ferr, [])
        self.assertEqual(bytes(rear_buf), exp_rear)
        self.assertEqual(bytes(front_buf), exp_front)

    def test_drops_frames_gracefully_when_no_reader_present(self):
        fifo = os.path.join(self.tmpdir, "no_reader_fifo")
        streamer = self._track(
            self.cs.FrontCameraStreamer(fifo_path=fifo, width=4, height=4, fps=5)
        )
        world = _FakeWorld()
        streamer.attach_to_vehicle(world, _FakeVehicle())
        img = sys.modules["carla"].Image(4, 4, bytes(4 * 4 * 4))
        streamer.sensor.emit(img)
        time.sleep(0.15)
        self.assertEqual(streamer.frames_written, 0)
        self.assertTrue(streamer._writer_thread.is_alive())

    def test_recovers_after_fifo_reader_disconnect_and_reconnect(self):
        fifo = os.path.join(self.tmpdir, "reconnect_fifo")
        streamer = self._track(
            self.cs.FrontCameraStreamer(fifo_path=fifo, width=4, height=4, fps=5)
        )
        world = _FakeWorld()
        streamer.attach_to_vehicle(world, _FakeVehicle())

        frame_a = np.full((4, 4, 4), (10, 20, 30, 255), dtype=np.uint8)
        frame_b = np.full((4, 4, 4), (200, 150, 100, 255), dtype=np.uint8)
        exp_a = self.cs.bgra_to_ym12(frame_a)
        exp_b = self.cs.bgra_to_ym12(frame_b)

        # First reader receives frame A and closes.
        t1, buf1, _ = _read_exact_from_fifo(fifo, len(exp_a))
        time.sleep(0.05)
        streamer.sensor.emit(sys.modules["carla"].Image(4, 4, frame_a.tobytes()))
        t1.join(timeout=5.0)
        self.assertEqual(bytes(buf1), exp_a)
        self.assertTrue(_wait_for_condition(lambda: streamer.frames_written == 1))

        # Trigger EPIPE / BrokenPipeError by emitting while no reader exists.
        streamer.sensor.emit(sys.modules["carla"].Image(4, 4, frame_a.tobytes()))
        time.sleep(0.15)

        # Second reader opens FIFO and receives a fresh byte-0-aligned frame B.
        t2, buf2, _ = _read_exact_from_fifo(fifo, len(exp_b))
        time.sleep(0.05)
        streamer.sensor.emit(sys.modules["carla"].Image(4, 4, frame_b.tobytes()))
        t2.join(timeout=5.0)
        self.assertEqual(bytes(buf2), exp_b)
        self.assertTrue(_wait_for_condition(lambda: streamer.frames_written == 2))

    def test_find_hero_vehicle_preference_and_fallback(self):
        other = _FakeVehicle(actor_id=1, role_name="npc")
        hero = _FakeVehicle(actor_id=2, role_name="hero")
        self.assertIs(
            self.cs._find_hero_vehicle(_FakeWorld([other, hero])), hero
        )
        self.assertIs(
            self.cs._find_hero_vehicle(_FakeWorld([other])), other
        )
        self.assertIsNone(self.cs._find_hero_vehicle(_FakeWorld([])))


class TestBridgeAndLauncherIntegration(unittest.TestCase):
    """Tests carla_someip_client CLI/lifecycle hooks and launcher shell flags."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_bridge_cam_")
        self._saved_modules = {}
        # Stub out optional runtime deps (`someipy`, `carla`) so we can import
        # `carla_someip_client` without the full SOME/IP stack installed.
        _load_camera_streamer()
        fake_someipy = types.ModuleType("someipy")
        fake_someipy.ServiceBuilder = object
        fake_someipy.EventGroup = object
        fake_someipy.TransportLayerProtocol = types.SimpleNamespace(UDP=0)
        fake_someipy.MethodResult = object
        fake_someipy.ReturnCode = object
        fake_someipy.MessageType = object
        fake_someipy.construct_server_service_instance = lambda *a, **kw: None
        fake_logging = types.ModuleType("someipy.logging")
        fake_logging._log_level = 0
        fake_someipy.logging = fake_logging
        fake_serialize = types.ModuleType("someipy.serialization")
        class _FakePayload:
            pass
        fake_serialize.SomeIpPayload = _FakePayload
        for dtype in ("Bool", "Float32", "Float64", "Sint64", "Uint8", "Uint32", "Uint64"):
            setattr(fake_serialize, dtype, object)
        fake_sd = types.ModuleType("someipy.service_discovery")
        fake_sd.construct_service_discovery = lambda *a, **kw: None
        fake_svc = types.ModuleType("someipy.service")
        fake_svc.Method = object
        for name, mod in [
            ("someipy", fake_someipy),
            ("someipy.logging", fake_logging),
            ("someipy.serialization", fake_serialize),
            ("someipy.service_discovery", fake_sd),
            ("someipy.service", fake_svc),
        ]:
            self._saved_modules[name] = sys.modules.get(name)
            sys.modules[name] = mod

    def tearDown(self):
        for name, orig in self._saved_modules.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _import_client(self):
        if "carla_someip_client" in sys.modules:
            return importlib.reload(sys.modules["carla_someip_client"])
        return importlib.import_module("carla_someip_client")

    def test_arg_parser_flags_and_defaults(self):
        client = self._import_client()
        parser = client.build_arg_parser()

        defaults = parser.parse_args([])
        self.assertFalse(defaults.enable_camera_stream)
        self.assertEqual(defaults.camera_fifo_path, "/tmp/v4l2_fifo")
        self.assertFalse(defaults.enable_front_camera_stream)
        self.assertEqual(
            defaults.front_camera_fifo_path, "/tmp/v4l2_front_fifo"
        )

        custom = parser.parse_args([
            "--enable-camera-stream",
            "--camera-fifo-path=/tmp/custom_rear",
            "--enable-front-camera-stream",
            "--front-camera-fifo-path=/tmp/custom_front",
        ])
        self.assertTrue(custom.enable_camera_stream)
        self.assertEqual(custom.camera_fifo_path, "/tmp/custom_rear")
        self.assertTrue(custom.enable_front_camera_stream)
        self.assertEqual(custom.front_camera_fifo_path, "/tmp/custom_front")

    def test_bridge_enables_rear_and_front_independently(self):
        client = self._import_client()
        rear_fifo = os.path.join(self.tmpdir, "rear_only")
        front_fifo = os.path.join(self.tmpdir, "front_both")

        rear_only = client.CarlaSomeipBridge(
            enable_camera_stream=True,
            camera_fifo_path=rear_fifo,
            enable_front_camera_stream=False,
        )
        try:
            self.assertIsNotNone(rear_only.camera_streamer)
            self.assertIsNone(rear_only.front_camera_streamer)
        finally:
            rear_only.destroy()

        both = client.CarlaSomeipBridge(
            mode=client.BridgeMode.ManualWASD,
            enable_camera_stream=True,
            camera_fifo_path=rear_fifo,
            enable_front_camera_stream=True,
            front_camera_fifo_path=front_fifo,
        )
        try:
            world = _FakeWorld([_FakeVehicle(actor_id=199, role_name="hero")])
            both.world = world
            asyncio.run(both.acquire_vehicle())
            self.assertEqual(len(world.spawned_sensors), 2)
            self.assertFalse(both.camera_streamer.is_streaming)
            self.assertTrue(both.front_camera_streamer.is_streaming)
            # Gear change to Drive leaves rear paused, front unaffected.
            both.update_camera_stream(3)
            self.assertFalse(both.camera_streamer.is_streaming)
            self.assertTrue(both.front_camera_streamer.is_streaming)
            # Gear change to Reverse starts rear without disturbing front.
            both.update_camera_stream(1)
            self.assertTrue(both.camera_streamer.is_streaming)
            self.assertTrue(both.front_camera_streamer.is_streaming)
        finally:
            both.destroy()

    def test_run_carla_and_bridge_shell_syntax_and_help(self):
        script = os.path.join(BRIDGE_DIR, "run_carla_and_bridge.sh")
        syntax = subprocess.run(
            ["bash", "-n", script], capture_output=True, text=True, check=False
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        help_out = subprocess.run(
            ["bash", script, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_out.returncode, 0, help_out.stderr)
        self.assertIn("--enable-camera-stream", help_out.stdout)
        self.assertIn("--enable-front-camera-stream", help_out.stdout)
        self.assertIn("--front-camera-fifo-path=PATH", help_out.stdout)


if __name__ == "__main__":
    unittest.main()
