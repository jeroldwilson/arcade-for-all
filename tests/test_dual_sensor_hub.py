"""
Unit tests for Phase 4: DualSensorHub + Twin-Sensor startup prompt & blink/vibrate assignment.
No second physical sensor required.
"""

import queue
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import main as app_main
from shared.dual_sensor import DualSensorHub
from shared.sensor import IMUSample, StreamChannel


class _FakeSensor:
    def __init__(self, scan_timeout=10.0, sf_profile="full", subscriptions=None, fail_connect=False):
        self.scan_timeout = scan_timeout
        self.sf_profile = sf_profile
        self.subscriptions = subscriptions
        self.data_queue = queue.Queue()
        self._connected = False
        self._fail_connect = fail_connect
        self.calls = []

    def start_background(self, address=None):
        self.calls.append(("start", address))
        if self._fail_connect:
            raise RuntimeError("BLE connect failed")
        self._connected = True

    def stop_background(self):
        self.calls.append(("stop",))
        self._connected = False

    def is_connected(self):
        return self._connected

    def set_subscriptions(self, channels):
        self.subscriptions = channels
        self.calls.append(("sub", channels))

    def set_ambient_light(self, on=True, color=0, blink=False):
        self.calls.append(("led", on, color, blink))

    def vibrate(self, duration=0.15):
        self.calls.append(("vibrate", duration))

    @property
    def cal_state(self):
        return (3, 3, 0)

    @property
    def mag_cal_state(self):
        return 0


class TestDualSensorHub(unittest.TestCase):
    def test_twin_mode_pairs_samples_and_keeps_upper_arm_quat_only(self):
        created = []

        def factory(**kwargs):
            s = _FakeSensor(**kwargs)
            created.append(s)
            return s

        hub = DualSensorHub(
            wrist_mac="WRIST_MAC",
            upper_arm_mac="UPPER_MAC",
            sensor_factory=factory,
        )
        hub.start_background()
        self.assertTrue(hub.is_connected())
        self.assertTrue(hub.dual_sensor_active)
        self.assertEqual(created[1].subscriptions, StreamChannel.QUAT)

        # Updating wrist subscriptions keeps upper arm on QUAT-only
        hub.set_subscriptions(StreamChannel.GYRO)
        self.assertEqual(created[0].subscriptions, StreamChannel.GYRO)
        self.assertEqual(created[1].subscriptions, StreamChannel.QUAT)

        # Push upper-arm samples and drain latest
        s1 = IMUSample(timestamp=time.monotonic(), hw_fusion_valid=True, hw_qw=1.0)
        s2 = IMUSample(timestamp=time.monotonic(), hw_fusion_valid=True, hw_qw=0.707, hw_qx=0.707)
        created[1].data_queue.put(s1)
        created[1].data_queue.put(s2)
        latest = hub.get_latest_upper_sample()
        self.assertIs(latest, s2)

        # Mid-session upper-arm disconnect falls back gracefully
        created[1]._connected = False
        self.assertFalse(hub.dual_sensor_active)
        self.assertIsNone(hub.get_latest_upper_sample())

    def test_upper_arm_connect_failure_falls_back_to_single_sensor(self):
        idx = {"n": 0}

        def factory(**kwargs):
            idx["n"] += 1
            return _FakeSensor(fail_connect=(idx["n"] == 2), **kwargs)

        hub = DualSensorHub(
            wrist_mac="WRIST_MAC",
            upper_arm_mac="BAD_UPPER_MAC",
            sensor_factory=factory,
        )
        hub.start_background()
        self.assertTrue(hub.is_connected())
        self.assertFalse(hub.dual_sensor_active)
        self.assertIsNone(hub.get_latest_upper_sample())


class TestTwinSensorStartupPrompt(unittest.TestCase):
    def test_enter_defaults_to_single_sensor(self):
        devices = [
            ("MetaMotion S", "AA:BB:CC:00:00:01", -55),
            ("MetaMotion S", "AA:BB:CC:00:00:02", -62),
        ]
        # First "" selects Single mode; second "" selects device [1]
        with patch("builtins.input", side_effect=["", ""]):
            wrist, upper = app_main._prompt_sensor_setup(devices)
        self.assertEqual(wrist, "AA:BB:CC:00:00:01")
        self.assertIsNone(upper)

    def test_twin_mode_blinks_vibrates_and_assigns_positions(self):
        devices = [
            ("MetaMotion S #1", "AA:BB:CC:00:00:01", -55),
            ("MetaMotion S #2", "AA:BB:CC:00:00:02", -62),
        ]
        created = []

        def factory(**kwargs):
            s = _FakeSensor(**kwargs)
            created.append(s)
            return s

        # "2" = Twin mode; then "2" = first board is Upper Arm; "1" = second board is Wrist
        with patch("builtins.input", side_effect=["2", "2", "1"]):
            wrist, upper = app_main._prompt_sensor_setup(devices, sensor_factory=factory)

        self.assertEqual(wrist, "AA:BB:CC:00:00:02")
        self.assertEqual(upper, "AA:BB:CC:00:00:01")
        # Both sensors were pinged with blink + vibrate and then stopped
        for s in created:
            self.assertIn(("led", True, 2, True), s.calls)
            self.assertIn(("vibrate", 0.35), s.calls)
            self.assertIn(("stop",), s.calls)


if __name__ == "__main__":
    unittest.main()
