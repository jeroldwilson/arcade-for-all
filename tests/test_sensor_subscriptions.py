"""
Unit tests for Phase 1: subscription-based BLE streaming & hardware cal state in shared/sensor.py.
"""

import asyncio
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.sensor import (
    METAWEAR_COMMAND_CHAR_UUID,
    MetaMotionSensor,
    StreamChannel,
    _CMD_SF_CORR_ACC_DIS,
    _CMD_SF_CORR_ACC_EN,
    _CMD_SF_CORR_GYRO_DIS,
    _CMD_SF_CORR_GYRO_EN,
    _CMD_SF_LIN_ACC_DIS,
    _CMD_SF_LIN_ACC_EN,
    _CMD_SF_OUTPUT_DISABLE,
    _CMD_SF_QUAT_DIS,
    _CMD_SF_QUAT_EN,
    _CMD_SF_READ_CAL_DATA,
    _CMD_SF_READ_GYRO_CAL_DATA,
    _MODULE_SENSOR_FUSION,
    _build_sf_output_enable_cmd,
)


class TestStreamChannelMasks(unittest.TestCase):
    def test_output_enable_mask_combinations(self):
        # QUAT only -> bit 3 (0x08)
        self.assertEqual(
            _build_sf_output_enable_cmd(StreamChannel.QUAT),
            bytes([_MODULE_SENSOR_FUSION, 0x03, 0x08, 0x00]),
        )
        # GYRO only -> bit 1 (0x02)
        self.assertEqual(
            _build_sf_output_enable_cmd(StreamChannel.GYRO),
            bytes([_MODULE_SENSOR_FUSION, 0x03, 0x02, 0x00]),
        )
        # QUAT | LIN_ACC -> 0x08 | 0x40 = 0x48
        self.assertEqual(
            _build_sf_output_enable_cmd(StreamChannel.QUAT | StreamChannel.LIN_ACC),
            bytes([_MODULE_SENSOR_FUSION, 0x03, 0x48, 0x00]),
        )
        # DEFAULT_FULL -> ACC(0x01) | GYRO(0x02) | QUAT(0x08) = 0x0B
        self.assertEqual(
            _build_sf_output_enable_cmd(StreamChannel.DEFAULT_FULL),
            bytes([_MODULE_SENSOR_FUSION, 0x03, 0x0B, 0x00]),
        )


class TestSensorSubscriptionAndParsing(unittest.TestCase):
    def test_dynamic_sf_subscription_commands(self):
        sensor = MetaMotionSensor(subscriptions=StreamChannel.DEFAULT_FULL)
        mock_client = MagicMock()
        mock_client.write_gatt_char = AsyncMock()
        sensor._client = mock_client
        sensor._connected = True
        sensor._using_sf = True

        target = StreamChannel.QUAT | StreamChannel.LIN_ACC
        asyncio.run(sensor._async_apply_subscriptions(target))

        written = [call.args[1] for call in mock_client.write_gatt_char.call_args_list]
        self.assertEqual(written[0], _CMD_SF_OUTPUT_DISABLE)
        self.assertIn(_CMD_SF_CORR_ACC_DIS, written)
        self.assertIn(_CMD_SF_CORR_GYRO_DIS, written)
        self.assertIn(_CMD_SF_QUAT_EN, written)
        self.assertIn(_CMD_SF_LIN_ACC_EN, written)
        self.assertEqual(written[-1], _build_sf_output_enable_cmd(target))
        self.assertEqual(sensor._active_subscriptions, target)

    def test_gyro_only_emission_does_not_starve(self):
        sensor = MetaMotionSensor(subscriptions=StreamChannel.GYRO)
        # Simulate that acc had previously arrived before switching to GYRO-only
        sensor._acc_notify_count = 10
        payload = struct.pack("<fff", 12.5, -45.0, 88.0)
        sensor._notification_handler(None, bytearray([_MODULE_SENSOR_FUSION, 0x05]) + payload)
        self.assertEqual(sensor.data_queue.qsize(), 1)
        sample = sensor.data_queue.get_nowait()
        self.assertAlmostEqual(sample.gx, 12.5, places=4)
        self.assertAlmostEqual(sample.gy, -45.0, places=4)
        self.assertAlmostEqual(sample.gz, 88.0, places=4)

    def test_lin_acc_and_cal_state_parsing(self):
        sensor = MetaMotionSensor(subscriptions=StreamChannel.QUAT | StreamChannel.LIN_ACC)
        # Cal state: acc=2, gyro=3, mag=1
        sensor._notification_handler(None, bytearray([_MODULE_SENSOR_FUSION, 0x0B, 2, 3, 1, 0]))
        self.assertEqual(sensor.cal_state, (2, 3, 1))
        self.assertEqual(sensor.accel_cal_state, 2)
        self.assertEqual(sensor.gyro_cal_state, 3)
        self.assertEqual(sensor.mag_cal_state, 1)

        # Linear acc packet (0x0A) + quat packet (0x07) to emit
        lin_payload = struct.pack("<fff", 0.15, -0.25, 0.05)
        sensor._notification_handler(None, bytearray([_MODULE_SENSOR_FUSION, 0x0A]) + lin_payload)
        quat_payload = struct.pack("<ffff", 1.0, 0.0, 0.0, 0.0)
        sensor._notification_handler(None, bytearray([_MODULE_SENSOR_FUSION, 0x07]) + quat_payload)

        sample = sensor.data_queue.get_nowait()
        self.assertTrue(sample.hw_lin_acc_valid)
        self.assertAlmostEqual(sample.lin_ax, 0.15, places=5)
        self.assertAlmostEqual(sample.lin_ay, -0.25, places=5)
        self.assertAlmostEqual(sample.lin_az, 0.05, places=5)

    def test_save_calibration_to_nvm_reads_and_writes_acc_and_gyro(self):
        sensor = MetaMotionSensor()
        sensor._connected = True
        mock_client = MagicMock()

        async def fake_write(uuid, payload, response=True):
            if payload == _CMD_SF_READ_CAL_DATA:
                sensor._notification_handler(None, bytearray([_MODULE_SENSOR_FUSION, 0x0C, 1, 2, 3, 4]))
            elif payload == _CMD_SF_READ_GYRO_CAL_DATA:
                sensor._notification_handler(None, bytearray([_MODULE_SENSOR_FUSION, 0x0D, 5, 6, 7, 8]))

        mock_client.write_gatt_char = AsyncMock(side_effect=fake_write)
        sensor._client = mock_client

        asyncio.run(sensor._async_save_calibration())
        written = [c.args[1] for c in mock_client.write_gatt_char.call_args_list]
        self.assertIn(bytes([_MODULE_SENSOR_FUSION, 0x0C, 1, 2, 3, 4]), written)
        self.assertIn(bytes([_MODULE_SENSOR_FUSION, 0x0D, 5, 6, 7, 8]), written)

    def test_set_sf_mode_toggles_imuplus_and_ndof_bytes(self):
        sensor = MetaMotionSensor(sf_mode="imuplus")
        sensor._connected = True
        sensor._using_sf = True
        mock_client = MagicMock()
        mock_client.write_gatt_char = AsyncMock()
        sensor._client = mock_client

        asyncio.run(sensor._async_set_sf_mode("ndof"))
        written_ndof = [c.args[1] for c in mock_client.write_gatt_char.call_args_list]
        self.assertIn(bytes([_MODULE_SENSOR_FUSION, 0x02, 0x01, 0x31]), written_ndof)

        mock_client.write_gatt_char.reset_mock()
        asyncio.run(sensor._async_set_sf_mode("imuplus"))
        written_imu = [c.args[1] for c in mock_client.write_gatt_char.call_args_list]
        self.assertIn(bytes([_MODULE_SENSOR_FUSION, 0x02, 0x02, 0x31]), written_imu)


if __name__ == "__main__":
    unittest.main()
