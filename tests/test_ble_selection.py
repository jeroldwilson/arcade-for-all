import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main as app_main
from shared.sensor import METAWEAR_SERVICE_UUID, MetaMotionSensor


class TestBLESelection(unittest.TestCase):
    def test_discover_devices_filters_and_sorts_by_rssi(self):
        fake_results = {
            "addr1": (
                SimpleNamespace(name="MetaMotion S", address="AA:BB:CC:11:22:33", metadata={}),
                SimpleNamespace(local_name=None, service_uuids=[], rssi=-75),
            ),
            "addr2": (
                SimpleNamespace(name="Other Device", address="11:22:33:44:55:66", metadata={}),
                SimpleNamespace(local_name=None, service_uuids=[], rssi=-40),
            ),
            "addr3": (
                SimpleNamespace(name=None, address="DD:EE:FF:44:55:66", metadata={}),
                SimpleNamespace(
                    local_name="MetaWear",
                    service_uuids=[METAWEAR_SERVICE_UUID],
                    rssi=-55,
                ),
            ),
        }

        with patch("shared.sensor.BleakScanner.discover", new=AsyncMock(return_value=fake_results)):
            devices = asyncio.run(MetaMotionSensor.discover_devices(timeout=1.0))

        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0], ("MetaWear", "DD:EE:FF:44:55:66", -55))
        self.assertEqual(devices[1], ("MetaMotion S", "AA:BB:CC:11:22:33", -75))

    def test_single_device_auto_connects_without_prompt(self):
        devices = [("MetaMotion S", "AA:BB:CC:11:22:33", -60)]
        with patch("builtins.input", side_effect=AssertionError("input() should not be called")):
            selected = app_main._prompt_device_selection(devices)
        self.assertEqual(selected, "AA:BB:CC:11:22:33")

    def test_multiple_devices_prompts_user_and_validates(self):
        devices = [
            ("MetaWear", "AA:BB:CC:11:22:33", -55),
            ("MetaMotion S", "DD:EE:FF:44:55:66", -70),
        ]
        with patch("builtins.input", side_effect=["9", "abc", "2"]):
            selected = app_main._prompt_device_selection(devices)
        self.assertEqual(selected, "DD:EE:FF:44:55:66")

    def test_multiple_devices_default_selects_first(self):
        devices = [
            ("MetaWear", "AA:BB:CC:11:22:33", -55),
            ("MetaMotion S", "DD:EE:FF:44:55:66", -70),
        ]
        with patch("builtins.input", side_effect=[""]):
            selected = app_main._prompt_device_selection(devices)
        self.assertEqual(selected, "AA:BB:CC:11:22:33")


if __name__ == "__main__":
    unittest.main()
