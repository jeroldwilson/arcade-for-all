"""
sensor.py — MetaMotion BLE sensor interface

Scans for a MetaWear/MetaMotion device, connects via BLE, streams
accelerometer + gyroscope data, and places parsed readings into a
thread-safe queue consumed by the gesture module.

Supported hardware: MetaMotion S / R / RL / C (any MbientLab device
that exposes the standard MetaWear sensor pipeline).

BLE stack used: bleak (cross-platform, no libmetawear native lib needed).
The metawear Python SDK wraps bleak internally when libmetawear is present,
but this module uses a lightweight bleak-only approach so it runs on any
platform without native library compilation.
"""

import asyncio
import struct
import threading
import queue
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable

from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

logger = logging.getLogger(__name__)

# ── MetaWear BLE UUIDs ────────────────────────────────────────────────────────
# These are fixed across all MbientLab hardware revisions.
METAWEAR_SERVICE_UUID      = "326a9000-85cb-9195-d9dd-464cfbbae75a"
METAWEAR_COMMAND_CHAR_UUID = "326a9001-85cb-9195-d9dd-464cfbbae75a"
METAWEAR_NOTIFY_CHAR_UUID  = "326a9006-85cb-9195-d9dd-464cfbbae75a"

# ── MetaWear command bytes ────────────────────────────────────────────────────
# Register values from MetaWear C# SDK + stream_acc_gyro_bmi160.py example.
# SDK call order: set_connection_params → write_config → subscribe → enable_sampling → start
_MODULE_ACCELEROMETER = 0x03
_MODULE_GYROSCOPE     = 0x13

# Settings module (0x11) — request tighter BLE connection interval (7.5 ms)
# Mirrors: mbl_mw_settings_set_connection_parameters(board, 7.5, 7.5, 0, 6000)
# Format: [module, reg=0x09, min_lo, min_hi, max_lo, max_hi, lat_lo, lat_hi, to_lo, to_hi]
# 7.5 ms / 1.25 ms = 6 → 0x0006 LE16;  6000 ms / 10 ms = 600 → 0x0258 LE16
_CMD_CONN_PARAMS = bytes([0x11, 0x09, 0x06, 0x00, 0x06, 0x00, 0x00, 0x00, 0x58, 0x02])

# Accelerometer (BMI160/BMI270) registers confirmed from accelerometer_bosch_register.h:
#   POWER_MODE=0x01, DATA_INTERRUPT_ENABLE=0x02, DATA_CONFIG=0x03, DATA_INTERRUPT=0x04
#
# SDK start sequence (stream_acc_gyro_bmi160.py):
#   1. mbl_mw_acc_write_acceleration_config  → [module, DATA_CONFIG,            odr, range]
#   2. mbl_mw_datasignal_subscribe(acc, ...) → [module, DATA_INTERRUPT,          0x01]
#   3. mbl_mw_acc_enable_acceleration_sampling → [module, DATA_INTERRUPT_ENABLE, 0x01, 0x00]
#   4. mbl_mw_acc_start                      → [module, POWER_MODE,              0x01]
#
# odr_bw 0x28 = Normal bandwidth (bits[7:4]=2) | 100 Hz (bits[3:0]=8)
# AccBoschRange enum: 0=±2G, 1=±4G, 2=±8G, 3=±16G  →  0x01 = ±4 g (matches _ACC_SCALE)
_CMD_ACC_CONFIG     = bytes([_MODULE_ACCELEROMETER, 0x03, 0x28, 0x01])
# datasignal_subscribe: routes acc DATA_INTERRUPT notifications to GATT notify char
_CMD_ACC_DATA_SUB   = bytes([_MODULE_ACCELEROMETER, 0x04, 0x01])
# datasignal_unsubscribe
_CMD_ACC_DATA_UNSUB = bytes([_MODULE_ACCELEROMETER, 0x04, 0x00])
# enable_acceleration_sampling
_CMD_ACC_SUBSCRIBE  = bytes([_MODULE_ACCELEROMETER, 0x02, 0x01, 0x00])
# acc_start (power on)
_CMD_ACC_START      = bytes([_MODULE_ACCELEROMETER, 0x01, 0x01])
# acc_stop (power off)
_CMD_ACC_STOP       = bytes([_MODULE_ACCELEROMETER, 0x01, 0x00])
# disable_acceleration_sampling
_CMD_ACC_UNSUB      = bytes([_MODULE_ACCELEROMETER, 0x02, 0x00, 0x01])

# Gyroscope BMI160 registers confirmed from gyro_bosch_register.h:
#   POWER_MODE=0x01, DATA_INTERRUPT_ENABLE=0x02, CONFIG=0x03, DATA=0x05
#   (BMI270 note: DATA=0x04 — if no data arrives, try replacing 0x05 with 0x04)
#
# SDK start sequence:
#   1. mbl_mw_gyro_bmi160_write_config            → [module, CONFIG,                  odr, range]
#   2. mbl_mw_datasignal_subscribe(gyro, ...)     → [module, DATA,                    0x01]
#   3. mbl_mw_gyro_bmi160_enable_rotation_sampling→ [module, DATA_INTERRUPT_ENABLE,   0x01, 0x00]
#   4. mbl_mw_gyro_bmi160_start                   → [module, POWER_MODE,              0x01]
#
# odr_bw 0x28 = Normal | 100 Hz; range 0x02 = ±500 °/s
_CMD_GYRO_CONFIG    = bytes([_MODULE_GYROSCOPE, 0x03, 0x28, 0x02])
# datasignal_subscribe for BMI160 gyro (DATA register = 0x05)
_CMD_GYRO_DATA_SUB   = bytes([_MODULE_GYROSCOPE, 0x05, 0x01])
# datasignal_unsubscribe
_CMD_GYRO_DATA_UNSUB = bytes([_MODULE_GYROSCOPE, 0x05, 0x00])
# enable_rotation_sampling
_CMD_GYRO_SUBSCRIBE = bytes([_MODULE_GYROSCOPE, 0x02, 0x01, 0x00])
# gyro_start (power on)
_CMD_GYRO_START     = bytes([_MODULE_GYROSCOPE, 0x01, 0x01])
# gyro_stop (power off)
_CMD_GYRO_STOP      = bytes([_MODULE_GYROSCOPE, 0x01, 0x00])
# disable_rotation_sampling
_CMD_GYRO_UNSUB     = bytes([_MODULE_GYROSCOPE, 0x02, 0x00, 0x01])

# LED module registers: PLAY=0x01, STOP=0x02, CONFIG=0x03
# CONFIG format: [module, CONFIG, channel, 0x02, high, low,
#                 rise_lo, rise_hi, high_lo, high_hi, fall_lo, fall_hi,
#                 period_lo, period_hi, delay_lo, delay_hi, repeat]  — 17 bytes total
_MODULE_LED         = 0x02
_CMD_LED_GREEN      = bytes([
    _MODULE_LED, 0x03, 0x00, 0x02,  # module, CONFIG=0x03, channel GREEN=0, fixed 0x02
    0x1f, 0x1f,                      # high_intensity=31, low_intensity=31 (solid)
    0x00, 0x00,                      # rise_time = 0 ms
    0xe8, 0x03,                      # high_time  = 1000 ms
    0x00, 0x00,                      # fall_time  = 0 ms
    0xe8, 0x03,                      # period     = 1000 ms  (100 % duty = solid on)
    0x00, 0x00,                      # delay      = 0 ms
    0xff,                            # repeat     = indefinitely
])
_CMD_LED_PLAY       = bytes([_MODULE_LED, 0x01, 0x01])    # PLAY=0x01, manual mode
_CMD_LED_STOP       = bytes([_MODULE_LED, 0x02, 0x01])    # STOP=0x02, clear=1

# Haptic / buzzer module (0x08)
# [module=0x08, register=0x01, duty_cycle_byte, width_ms_lo, width_ms_hi]
# duty_cycle_byte = round(percent / 100 * 248)  →  100 % = 0xF8
# 500 ms = 0x01F4  →  lo=0xF4, hi=0x01
_MODULE_HAPTIC      = 0x08
_CMD_HAPTIC_BUZZ    = bytes([_MODULE_HAPTIC, 0x01, 0xF8, 0xF4, 0x01])

# Sensor Fusion module (0x19) — Bosch Kalman Filter NDOF mode (acc+gyro+BMM150 mag)
#
# Confirmed register map (from MetaWear-CppAPI sensor_fusion_register.h):
#   0x01 ENABLE            0x02 MODE              0x03 OUTPUT_ENABLE
#   0x04 CORRECTED_ACC     0x05 CORRECTED_GYRO    0x06 CORRECTED_MAG
#   0x07 QUATERNION        0x08 EULER_ANGLES       0x09 GRAVITY_VECTOR
#   0x0A LINEAR_ACC        0x0B CALIBRATION_STATE  0x0C ACC_CAL_DATA
#   0x0D GYRO_CAL_DATA     0x0E MAG_CAL_DATA
#
# Streaming start sequence:
#   0. Pre-config acc+gyro:  [0x03, 0x03, odr, range]  [0x13, 0x03, odr, range]  (config only — no start)
#   1. Probe module:         [0x19, 0x80] → [0x19, 0x80, impl, rev, ...]  confirms SF present
#   2. Write config (NDOF):  [0x19, 0x02, 0x01, 0x31]  nibble-packed: low=acc_range, high=gyro_range+1
#   3. Subscribe Euler:      [0x19, 0x08, 0x01] → periodic [0x19, 0x08, <4×float32>]
#   4. Subscribe cal state:  [0x19, 0x0B, 0x01] → periodic [0x19, 0x0B, <uint8 0-3>]
#   5. Start fusion:         [0x19, 0x01, 0x01]
#
# One-shot reads (response at reg = cmd & 0x7F):
#   [0x19, 0x8B] → [0x19, 0x0B, cal_state_byte]
_MODULE_SENSOR_FUSION  = 0x19
# Write config: [module, MODE_reg=0x02, mode_byte=0x01 (NDOF), config_byte]
# config_byte nibble format confirmed from MetaWear-SDK-Cpp:
#   lower nibble = acc_range_enum  (0=±2G, 1=±4G, 2=±8G, 3=±16G)
#   upper nibble = gyro_range_enum+1  (1=±2000dps, 2=±1000dps, 3=±500dps, 4=±250dps)
# The original 0x0A used wrong packing (acc|gyro<<2) which is why it disconnected.
# 0x31 = acc=±4G (lower=1), gyro=±500dps (upper=3, enum=2, written as 3=enum+1)
_CMD_SF_MODE           = bytes([_MODULE_SENSOR_FUSION, 0x02, 0x01, 0x31])  # NDOF, acc±4G, gyro±500dps
_CMD_SF_EULER_EN       = bytes([_MODULE_SENSOR_FUSION, 0x08, 0x01])  # subscribe EULER_ANGLES (0x08)
_CMD_SF_CAL_EN         = bytes([_MODULE_SENSOR_FUSION, 0x0B, 0x01])  # subscribe CALIBRATION_STATE (0x0B)
_CMD_SF_START          = bytes([_MODULE_SENSOR_FUSION, 0x01, 0x01])  # start fusion
_CMD_SF_EULER_DIS      = bytes([_MODULE_SENSOR_FUSION, 0x08, 0x00])  # unsubscribe Euler
_CMD_SF_CAL_DIS        = bytes([_MODULE_SENSOR_FUSION, 0x0B, 0x00])  # unsubscribe cal state
_CMD_SF_STOP           = bytes([_MODULE_SENSOR_FUSION, 0x01, 0x00])  # stop fusion
_CMD_SF_CORR_ACC_EN    = bytes([_MODULE_SENSOR_FUSION, 0x04, 0x01])  # subscribe CORRECTED_ACC
_CMD_SF_CORR_GYRO_EN   = bytes([_MODULE_SENSOR_FUSION, 0x05, 0x01])  # subscribe CORRECTED_GYRO
_CMD_SF_CORR_ACC_DIS   = bytes([_MODULE_SENSOR_FUSION, 0x04, 0x00])
_CMD_SF_CORR_GYRO_DIS  = bytes([_MODULE_SENSOR_FUSION, 0x05, 0x00])
_CMD_SF_PROBE          = bytes([_MODULE_SENSOR_FUSION, 0x80])        # module info probe
_CMD_SF_READ_CAL_STATE = bytes([_MODULE_SENSOR_FUSION, 0x8B])        # one-shot cal state read (0x80|0x0B)
_CMD_SF_READ_CAL_DATA  = bytes([_MODULE_SENSOR_FUSION, 0x8C])        # one-shot acc cal data read (0x80|0x0C)

# Scale factors (raw int16 → physical units)
# BMI160 at ±4 g  → 1 LSB = 4/32768 g ≈ 0.0001221 g
_ACC_SCALE  = 4.0 / 32768.0
# BMI160 at ±500 °/s → 1 LSB = 500/32768 °/s ≈ 0.01526 °/s
_GYRO_SCALE = 500.0 / 32768.0


@dataclass
class IMUSample:
    """One fused IMU sample delivered to consumers."""
    timestamp: float = field(default_factory=time.monotonic)
    # Accelerometer (g)
    ax: float = 0.0
    ay: float = 0.0
    az: float = 0.0
    # Gyroscope (°/s)
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0
    # Bosch Kalman Filter hardware fusion outputs (module 0x19, NDOF mode)
    hw_heading: float = 0.0       # compass heading 0-360° (drift-free yaw)
    hw_pitch: float = 0.0         # pitch -90 to +90°
    hw_roll: float = 0.0          # roll -180 to +180°
    hw_fusion_valid: bool = False  # True once hardware fusion data is arriving


class MetaMotionSensor:
    """
    Async wrapper around a single MetaMotion device.

    Usage (async context):
        sensor = MetaMotionSensor()
        address = await sensor.scan()          # find first device
        await sensor.connect(address)
        await sensor.start_streaming()
        # sensor.data_queue now receives IMUSample objects
        ...
        await sensor.stop_streaming()
        await sensor.disconnect()

    Usage (threaded context — called from sync code):
        sensor = MetaMotionSensor()
        sensor.start_background(address=None)  # scans + connects in background thread
        # read from sensor.data_queue (thread-safe queue.Queue)
        sensor.stop_background()
    """

    def __init__(self, scan_timeout: float = 10.0):
        self.scan_timeout   = scan_timeout
        self.data_queue: queue.Queue[IMUSample] = queue.Queue(maxsize=256)
        self._client: Optional[BleakClient] = None
        self._connected     = False
        self._streaming     = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._last_acc      = (0.0, 0.0, 0.0)
        self._last_gyro     = (0.0, 0.0, 0.0)
        self._on_sample_cb: Optional[Callable[[IMUSample], None]] = None
        self._notify_count  = 0
        self._sample_count  = 0
        self._device_name: str = ""
        # Event set when the first notification is received (created on BLE loop)
        self._notify_event: Optional[asyncio.Event] = None
        # Counters for module-specific notifications
        self._acc_notify_count = 0
        self._gyro_notify_count = 0
        # BMM150 magnetometer calibration state (0 = uncalibrated, 3 = fully calibrated)
        self._mag_cal_state: int = 0
        self._pending_cal_data: bytes = b''
        # Bosch Kalman Filter hardware fusion state
        self._last_euler: tuple = (0.0, 0.0, 0.0, 0.0)  # (heading, pitch, roll, yaw)
        self._hw_fusion_valid: bool = False
        self._sf_notify_count: int = 0
        self._using_sf: bool = False  # True when streaming via module 0x19 instead of raw 0x03/0x13
        self._address: Optional[str] = None  # stored in connect() for reconnect-after-SF-disconnect

    # ── Public sync API (for use from game / main thread) ─────────────────────

    def start_background(self, address: Optional[str] = None) -> None:
        """Spin up a daemon thread running the async BLE event loop."""
        self._thread = threading.Thread(
            target=self._run_loop, args=(address,), daemon=True, name="ble-sensor"
        )
        self._thread.start()
        # Wait until connected (or failed) before returning
        deadline = time.monotonic() + self.scan_timeout + 5
        while not self._connected and time.monotonic() < deadline:
            time.sleep(0.1)
            if self._thread and not self._thread.is_alive():
                raise RuntimeError("BLE thread died — check logs for details.")

    def stop_background(self) -> None:
        """Signal the BLE thread to stop cleanly."""
        if self._loop and self._loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._teardown(), self._loop)
            try:
                fut.result(timeout=5)  # wait so the loop doesn't close mid-teardown
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)

    def is_connected(self) -> bool:
        return self._connected

    def set_sample_callback(self, cb: Callable[[IMUSample], None]) -> None:
        """Optional callback invoked on every sample (runs in BLE thread)."""
        self._on_sample_cb = cb

    @property
    def mag_cal_state(self) -> int:
        """BMM150 magnetometer calibration state: 0 = offline, 3 = fully calibrated."""
        return self._mag_cal_state

    def poll_mag_cal_state(self) -> None:
        """Request current mag calibration state; self.mag_cal_state updates on next notification."""
        if not self._loop or not self._client or not self._connected:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._async_write(_CMD_SF_READ_CAL_STATE), self._loop
            )
        except Exception as e:
            print(f"[sensor] poll_mag_cal_state failed: {e}")

    def save_calibration_to_nvm(self) -> None:
        """Read current sensor-fusion calibration offsets and persist them to NVM flash."""
        if not self._loop or not self._client or not self._connected:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._async_save_calibration(), self._loop)
        except Exception as e:
            print(f"[sensor] save_calibration_to_nvm scheduling failed: {e}")

    # Convenience sync wrappers that schedule async BLE writes on the BLE loop.
    def set_ambient_light(self, on: bool = True) -> None:
        """Turn the device LED on (solid green) or off. Safe to call from main thread.

        This schedules an async write on the BLE event loop; it returns
        immediately and does not block for the write to complete.
        """
        if not self._loop or not self._client or not self._connected:
            print("[sensor] set_ambient_light: sensor not connected yet (skipping)")
            return
        try:
            asyncio.run_coroutine_threadsafe(self._async_set_led(on), self._loop)
        except Exception as e:
            print(f"[sensor] set_ambient_light scheduling failed: {e}")

    def vibrate(self, duration: float = 0.15) -> None:
        """Trigger a short haptic buzz (duration in seconds)."""
        if not self._loop or not self._client or not self._connected:
            print("[sensor] vibrate: sensor not connected yet (skipping)")
            return
        try:
            asyncio.run_coroutine_threadsafe(self._async_vibrate(duration), self._loop)
        except Exception as e:
            print(f"[sensor] vibrate scheduling failed: {e}")

    # ── Internal async machinery ───────────────────────────────────────────────

    def _run_loop(self, address: Optional[str]) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main(address))
        except Exception as exc:
            logger.error("BLE event loop error: %s", exc)
        finally:
            self._loop.close()

    async def _main(self, address: Optional[str]) -> None:
        if address is None:
            address = await self.scan()
        # Create the notification event in the BLE event loop so connect()
        # can await it to confirm CCCD notifications are actually arriving.
        self._notify_event = asyncio.Event()
        if address is None:
            logger.error("No MetaMotion device found.")
            return
        await self.connect(address)
        if not self._connected:
            return
        await self.start_streaming()
        # Keep the loop alive until cancelled
        try:
            while self._streaming:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        await self._teardown()

    async def _teardown(self) -> None:
        if self._streaming:
            await self.stop_streaming()
        if self._connected:
            await self.disconnect()

    # ── BLE operations ─────────────────────────────────────────────────────────

    async def scan(self) -> Optional[str]:
        """Scan for the first MetaWear/MetaMotion device and return its address."""
        logger.info("Scanning for MetaMotion device (%.0fs)…", self.scan_timeout)
        print(f"[sensor] Scanning for BLE devices ({self.scan_timeout:.0f}s)…")

        # NOTE: on macOS, Core Bluetooth assigns a per-host UUID instead of
        # the real MAC address.  bleak uses that UUID to connect correctly.
        devices = await BleakScanner.discover(timeout=self.scan_timeout)

        # Name-based match
        for d in devices:
            name = d.name or ""
            if any(k in name for k in ("MetaWear", "MetaMotion", "MWC", "MMS")):
                self._device_name = name
                print(f"[sensor] MetaWear detected: '{name}'  [{d.address}]")
                return d.address

        # UUID-based fallback
        for d in devices:
            uuids = [str(u).lower() for u in (d.metadata.get("uuids") or [])]
            if METAWEAR_SERVICE_UUID.lower() in uuids:
                self._device_name = d.name or d.address
                print(f"[sensor] MetaWear detected (by UUID): '{d.name}'  [{d.address}]")
                return d.address

        logger.warning("No MetaMotion device found in scan.")
        print("[sensor] No MetaWear/MetaMotion device found.")
        return None

    async def connect(self, address: str) -> None:
        """Connect via BLE and enable notifications."""
        logger.info("Connecting to %s…", address)
        print(f"[sensor] Connecting to {address}…")
        self._address = address
        self._client = BleakClient(address)
        try:
            await self._client.connect()
        except BleakError as e:
            logger.error("Connection failed: %s", e)
            print(f"[sensor] Connection failed: {e}")
            return

        await asyncio.sleep(0.5)  # let connection fully stabilize before CCCD write
        self._connected = True
        logger.info("Connected.")
        print(f"[sensor] *** CONNECTED  name='{self._device_name}'  addr={address} ***")

        # Enumerate GATT services so we can verify the expected UUIDs are present
        print("[sensor] GATT services on device:")
        has_cmd_char    = False
        has_notify_char = False
        for svc in self._client.services:
            print(f"  service  {svc.uuid}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"    char   {ch.uuid}  [{props}]")
                if ch.uuid.lower() == METAWEAR_COMMAND_CHAR_UUID.lower():
                    has_cmd_char = True
                if ch.uuid.lower() == METAWEAR_NOTIFY_CHAR_UUID.lower():
                    has_notify_char = True
        if has_cmd_char and has_notify_char:
            print("[sensor] ✓ MetaWear command + notify characteristics confirmed")
        else:
            print(f"[sensor] ✗ Expected chars missing — cmd={has_cmd_char} notify={has_notify_char}")
            print(f"[sensor]   expected cmd    = {METAWEAR_COMMAND_CHAR_UUID}")
            print(f"[sensor]   expected notify = {METAWEAR_NOTIFY_CHAR_UUID}")

        # Register notification handler for all data coming back from the device
        try:
            await self._client.start_notify(
                METAWEAR_NOTIFY_CHAR_UUID, self._notification_handler
            )
            print("[sensor] Notification handler registered")
        except Exception as e:
            print(f"[sensor] start_notify FAILED: {e}")
            self._connected = False
            return

        await asyncio.sleep(0.1)

        # Diagnostic: send switch-module info request [0x01, 0x80] — the firmware
        # always responds with a notification, so this tells us whether the CCCD
        # subscription is actually delivering packets.  Wait for the first
        # notification via the event (created in the BLE loop) rather than a
        # blind sleep + counter check.
        write = self._client.write_gatt_char
        try:
            # ensure we have an event to wait on
            if self._notify_event is None:
                self._notify_event = asyncio.Event()
            await write(METAWEAR_COMMAND_CHAR_UUID, bytes([0x01, 0x80]), response=True)
            print("[sensor] Sent module-info probe — waiting for notification…")
            try:
                await asyncio.wait_for(self._notify_event.wait(), timeout=0.8)
            except asyncio.TimeoutError:
                if self._notify_count == 0:
                    print("[sensor] *** No notification received — CCCD subscription may not be active ***")
                    print("[sensor]   (haptic works = write OK; no notification = read-back broken)")
                else:
                    print(f"[sensor] ✓ Notifications confirmed ({self._notify_count} received so far)")
            else:
                print(f"[sensor] ✓ Notifications confirmed ({self._notify_count} received so far)")
        except Exception as e:
            print(f"[sensor] Module-info probe failed: {e}")

        # Request tighter BLE connection interval (mirrors SDK's mbl_mw_settings_set_connection_parameters)
        # The device asks the host for 7.5 ms intervals; give the stack 1.5 s to negotiate.
        try:
            await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_CONN_PARAMS, response=True)
            print("[sensor] Connection parameters requested (7.5 ms interval)")
        except Exception as e:
            print(f"[sensor] Connection params command failed (non-fatal): {e}")
        await asyncio.sleep(1.5)

        # Confirm connection with LED (solid green) + one haptic buzz
        try:
            await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_STOP,  response=True)
            await asyncio.sleep(0.05)
            await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_GREEN, response=True)
            await asyncio.sleep(0.05)
            await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_PLAY,  response=True)
            print("[sensor] LED → solid green")
        except Exception as e:
            print(f"[sensor] LED command failed: {e}")
        try:
            await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_HAPTIC_BUZZ, response=True)
            print("[sensor] Haptic buzz sent")
        except Exception as e:
            print(f"[sensor] Haptic command failed: {e}")

    async def disconnect(self) -> None:
        if self._client and self._connected:
            try:
                await self._client.stop_notify(METAWEAR_NOTIFY_CHAR_UUID)
            except Exception:
                pass  # already unsubscribed (e.g. double-teardown race or BLE drop)
            await self._client.disconnect()
            self._connected = False
            logger.info("Disconnected.")
            print("[sensor] Disconnected.")

    async def start_streaming(self) -> None:
        """
        Start sensor data streaming.

        Preferred path: Bosch Kalman Filter sensor fusion (module 0x19, NDOF mode).
        The SF module controls acc/gyro/mag internally — raw modules 0x03/0x13 must
        NOT be started at the same time or the firmware disconnects.
        Fallback: raw acc/gyro (modules 0x03/0x13) when SF is unavailable.
        """
        if not self._connected or not self._client:
            return

        async def _send(label: str, payload: bytes, with_response: bool = True) -> bool:
            # Look up self._client at call time so reconnect mid-sequence is handled.
            if not self._client:
                print(f"[sensor]   FAILED {label}: no client")
                return False
            try:
                await self._client.write_gatt_char(
                    METAWEAR_COMMAND_CHAR_UUID, payload, response=with_response
                )
                print(f"[sensor]   sent {label}  {payload.hex()}  response={with_response}")
                return True
            except Exception as e:
                print(f"[sensor]   FAILED {label}: {e}")
                return False

        # ── 1. Probe SF module ─────────────────────────────────────────────────
        print("[sensor] Probing sensor fusion module 0x19…")
        count_before = self._notify_count
        probe_ok = await _send("SF_PROBE", _CMD_SF_PROBE)
        await asyncio.sleep(0.35)
        sf_available = probe_ok and (self._notify_count > count_before)
        print(f"[sensor] SF probe: {'available ✓' if sf_available else 'not available — using raw acc/gyro'}")

        # ── 2a. Sensor Fusion path ─────────────────────────────────────────────
        if sf_available:
            print("[sensor] Starting sensor fusion (NDOF — acc±4G gyro±500dps, config=0x31)…")
            # Pre-configure acc + gyro hardware modules BEFORE sending SF MODE.
            # The Bosch SF module picks up these config values when it starts.
            # We send CONFIG only — no subscribe/start so firmware stays quiescent.
            for label, payload in [
                ("ACC_CONFIG",  _CMD_ACC_CONFIG),
                ("GYRO_CONFIG", _CMD_GYRO_CONFIG),
            ]:
                await _send(label, payload)
                await asyncio.sleep(0.12)

            for label, payload, delay in [
                ("SF_MODE",         _CMD_SF_MODE,         0.35),  # 3-byte NDOF mode only
                ("SF_CORR_ACC_EN",  _CMD_SF_CORR_ACC_EN,  0.15),  # corrected acc  (0x04)
                ("SF_CORR_GYRO_EN", _CMD_SF_CORR_GYRO_EN, 0.15),  # corrected gyro (0x05)
                ("SF_EULER_EN",     _CMD_SF_EULER_EN,      0.15),  # euler angles   (0x08)
                ("SF_CAL_EN",       _CMD_SF_CAL_EN,        0.15),  # cal state      (0x0B)
                ("SF_START",        _CMD_SF_START,         0.50),  # start fusion
            ]:
                ok = await _send(label, payload)
                await asyncio.sleep(delay)
                if not ok and label == "SF_MODE":
                    print("[sensor] SF_MODE failed — aborting SF path, falling back to raw")
                    sf_available = False
                    # If firmware disconnected us, reconnect before raw fallback
                    if not self._connected and self._address:
                        print("[sensor] Device disconnected — reconnecting for raw fallback…")
                        await asyncio.sleep(1.5)
                        try:
                            self._client = BleakClient(self._address)
                            await self._client.connect()
                            await asyncio.sleep(0.5)
                            self._connected = True
                            await self._client.start_notify(
                                METAWEAR_NOTIFY_CHAR_UUID, self._notification_handler
                            )
                            print("[sensor] ✓ Reconnected — proceeding with raw acc/gyro")
                        except Exception as re_exc:
                            print(f"[sensor] Reconnect failed: {re_exc}")
                            return
                    break

        if sf_available:
            self._streaming = True
            self._using_sf  = True
            logger.info("Streaming started (sensor fusion).")
            print(f"[sensor] SF streaming started — waiting for corrected acc data…")
            for _ in range(20):        # up to 4 s
                await asyncio.sleep(0.2)
                if self._acc_notify_count > 0:
                    print(f"[sensor] ✓ SF data flowing — acc={self._acc_notify_count} "
                          f"euler={self._sf_notify_count} cal={self._mag_cal_state}")
                    return
            print(f"[sensor] No SF data after 4s (acc={self._acc_notify_count}) — falling back to raw")
            # Clean up failed SF attempt
            for p in [_CMD_SF_CORR_ACC_DIS, _CMD_SF_CORR_GYRO_DIS,
                      _CMD_SF_EULER_DIS, _CMD_SF_CAL_DIS, _CMD_SF_STOP]:
                try: await self._client.write_gatt_char(METAWEAR_COMMAND_CHAR_UUID, p, response=False)
                except Exception: pass
            self._using_sf = False
            await asyncio.sleep(0.3)

        # ── 2b. Raw acc/gyro fallback ──────────────────────────────────────────
        print("[sensor] Starting raw acc/gyro streaming…")
        for label, payload in [
            ("ACC_CONFIG",    _CMD_ACC_CONFIG),
            ("GYRO_CONFIG",   _CMD_GYRO_CONFIG),
            ("ACC_DATA_SUB",  _CMD_ACC_DATA_SUB),
            ("GYRO_DATA_SUB", _CMD_GYRO_DATA_SUB),
            ("ACC_SUBSCRIBE", _CMD_ACC_SUBSCRIBE),
            ("GYRO_SUBSCRIBE",_CMD_GYRO_SUBSCRIBE),
            ("ACC_START",     _CMD_ACC_START),
            ("GYRO_START",    _CMD_GYRO_START),
        ]:
            await _send(label, payload)
            await asyncio.sleep(0.12)
        await asyncio.sleep(0.25)
        self._streaming = True
        logger.info("Streaming started (raw acc/gyro).")

        for _ in range(14):   # up to 2 s
            await asyncio.sleep(0.15)
            if self._acc_notify_count > 0 or self._gyro_notify_count > 0:
                print(f"[sensor] ✓ Raw IMU data flowing — acc={self._acc_notify_count} gyro={self._gyro_notify_count}")
                return

        print("[sensor] No raw notifications — retrying without response…")
        for payload in [_CMD_ACC_CONFIG, _CMD_GYRO_CONFIG,
                        _CMD_ACC_DATA_SUB, _CMD_GYRO_DATA_SUB,
                        _CMD_ACC_SUBSCRIBE, _CMD_GYRO_SUBSCRIBE,
                        _CMD_ACC_START, _CMD_GYRO_START]:
            try:
                await self._client.write_gatt_char(METAWEAR_COMMAND_CHAR_UUID, payload, response=False)
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await asyncio.sleep(1.0)
        print(f"[sensor] After retry: acc={self._acc_notify_count} gyro={self._gyro_notify_count}")

    async def stop_streaming(self) -> None:
        if not self._connected or not self._client:
            return
        cmd = self._client.write_gatt_char
        if self._using_sf:
            for payload in [
                _CMD_SF_CORR_ACC_DIS, _CMD_SF_CORR_GYRO_DIS,
                _CMD_SF_EULER_DIS, _CMD_SF_CAL_DIS, _CMD_SF_STOP,
            ]:
                try:
                    await cmd(METAWEAR_COMMAND_CHAR_UUID, payload, response=False)
                except Exception:
                    pass
        else:
            for payload in [
                _CMD_ACC_STOP,  _CMD_ACC_UNSUB,  _CMD_ACC_DATA_UNSUB,
                _CMD_GYRO_STOP, _CMD_GYRO_UNSUB, _CMD_GYRO_DATA_UNSUB,
            ]:
                try:
                    await cmd(METAWEAR_COMMAND_CHAR_UUID, payload, response=False)
                except Exception:
                    pass
        # Turn off LED
        try:
            await cmd(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_STOP, response=False)
        except Exception:
            pass
        self._streaming = False
        logger.info("Streaming stopped.")

    # --- Async helpers used by sync wrappers --------------------------------
    async def _async_set_led(self, on: bool = True) -> None:
        """Async helper to set the LED solid green (on=True) or stop patterns (on=False)."""
        if not self._client or not self._connected:
            return
        try:
            write = self._client.write_gatt_char
            if on:
                # Stop, write green pattern, play
                await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_STOP,  response=True)
                await asyncio.sleep(0.02)
                await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_GREEN, response=True)
                await asyncio.sleep(0.02)
                await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_PLAY,  response=True)
                print("[sensor] LED cmd (async) → solid green")
            else:
                await write(METAWEAR_COMMAND_CHAR_UUID, _CMD_LED_STOP,  response=True)
                print("[sensor] LED cmd (async) → stopped")
        except Exception as e:
            print(f"[sensor] _async_set_led failed: {e}")

    async def _async_vibrate(self, duration: float = 0.15) -> None:
        """Async helper to trigger haptic buzz for duration seconds."""
        if not self._client or not self._connected:
            return
        try:
            ms = max(1, int(duration * 1000))
            lo = ms & 0xFF
            hi = (ms >> 8) & 0xFF
            payload = bytes([_MODULE_HAPTIC, 0x01, 0xF8, lo, hi])
            await self._client.write_gatt_char(METAWEAR_COMMAND_CHAR_UUID, payload, response=True)
            print("[sensor] Haptic (async) buzz sent")
        except Exception as e:
            print(f"[sensor] _async_vibrate failed: {e}")

    async def _async_write(self, payload: bytes) -> None:
        """Fire-and-forget GATT write (used for read-trigger commands)."""
        if not self._client or not self._connected:
            return
        try:
            await self._client.write_gatt_char(
                METAWEAR_COMMAND_CHAR_UUID, payload, response=True
            )
        except Exception as e:
            print(f"[sensor] write failed ({payload.hex()}): {e}")

    async def _async_save_calibration(self) -> None:
        """Read current sensor-fusion cal data via BLE, then write it back to NVM."""
        if not self._client or not self._connected:
            return
        try:
            self._pending_cal_data = b''
            await self._client.write_gatt_char(
                METAWEAR_COMMAND_CHAR_UUID, _CMD_SF_READ_CAL_DATA, response=True
            )
            # Wait up to 500 ms for the notification containing the cal bytes
            for _ in range(10):
                await asyncio.sleep(0.05)
                if self._pending_cal_data:
                    break
            if self._pending_cal_data:
                nvm_cmd = bytes([_MODULE_SENSOR_FUSION, 0x0C]) + self._pending_cal_data
                await self._client.write_gatt_char(
                    METAWEAR_COMMAND_CHAR_UUID, nvm_cmd, response=True
                )
                print(f"[sensor] Calibration saved to NVM ({len(self._pending_cal_data)} bytes)")
            else:
                print("[sensor] No calibration data received — NVM save skipped")
        except Exception as e:
            print(f"[sensor] _async_save_calibration failed: {e}")

    # ── Notification parsing ───────────────────────────────────────────────────

    def _notification_handler(self, _sender, data: bytearray) -> None:
        """
        Called by bleak in the BLE event loop for every incoming notification.

        MetaWear firmware notification format:
          byte[0] = module id
          byte[1] = register id / opcode
          byte[2..] = payload (varies by module)
        """
        if len(data) < 2:
            return

        self._notify_count += 1
        # Print first 20 notifications + any SF module notification (always log SF)
        is_sf = (len(data) >= 2 and data[0] == _MODULE_SENSOR_FUSION)
        if self._notify_count <= 20 or self._notify_count % 100 == 0 or is_sf:
            print(f"[sensor] notification #{self._notify_count}  module=0x{data[0]:02x} reg=0x{data[1]:02x}  len={len(data)}  raw={data[:8].hex()}")

        # signal the first notification to any waiter
        try:
            if self._notify_event is not None and not self._notify_event.is_set():
                # We're already executing inside the BLE event loop; setting the
                # event here is safe and will resume awaiting coroutines.
                self._notify_event.set()
        except Exception:
            pass

        module = data[0]
        reg    = data[1]
        # Track module-specific notifications for diagnostics / retries
        if module == _MODULE_ACCELEROMETER and reg == 0x04:
            self._acc_notify_count += 1
            self._parse_acc(data[2:])
        elif module == _MODULE_GYROSCOPE and reg == 0x05:
            self._gyro_notify_count += 1
            self._parse_gyro(data[2:])
        elif module == _MODULE_SENSOR_FUSION and reg == 0x04:   # CORRECTED_ACC
            self._acc_notify_count += 1
            self._parse_sf_corrected_acc(data[2:])
        elif module == _MODULE_SENSOR_FUSION and reg == 0x05:   # CORRECTED_GYRO
            self._gyro_notify_count += 1
            self._parse_sf_corrected_gyro(data[2:])
        elif module == _MODULE_SENSOR_FUSION and reg == 0x08:   # EULER_ANGLES
            self._sf_notify_count += 1
            self._parse_sf_euler(data[2:])
        elif module == _MODULE_SENSOR_FUSION and reg == 0x0B:   # CALIBRATION_STATE
            self._parse_cal_state(data[2:])
        elif module == _MODULE_SENSOR_FUSION and reg == 0x0C:   # ACC_CAL_DATA (NVM read response)
            self._parse_cal_data(data[2:])
        else:
            # Other notifications (module-info, etc.) are logged above.
            pass

    def _parse_acc(self, payload: bytearray) -> None:
        """Parse 6-byte little-endian int16 x/y/z accelerometer payload."""
        if len(payload) < 6:
            return
        x, y, z = struct.unpack_from("<hhh", payload)
        self._last_acc = (x * _ACC_SCALE, y * _ACC_SCALE, z * _ACC_SCALE)
        self._emit_sample()

    def _parse_gyro(self, payload: bytearray) -> None:
        """Parse 6-byte little-endian int16 x/y/z gyroscope payload."""
        if len(payload) < 6:
            return
        x, y, z = struct.unpack_from("<hhh", payload)
        self._last_gyro = (x * _GYRO_SCALE, y * _GYRO_SCALE, z * _GYRO_SCALE)
        self._emit_sample()

    def _parse_sf_corrected_acc(self, payload: bytearray) -> None:
        """Parse SF CORRECTED_ACC: MblMwCorrectedCartesianFloat = 3×float32 + uint8 accuracy."""
        if len(payload) < 12:
            return
        x, y, z = struct.unpack_from('<fff', payload[:12])
        # Firmware outputs in g (same scale as raw acc ±4g range).
        # Sanity-check: if magnitude >> 4 it's likely m/s² — convert to g.
        mag_sq = x*x + y*y + z*z
        if mag_sq > 16.0:
            x /= 9.80665; y /= 9.80665; z /= 9.80665
        self._last_acc = (x, y, z)
        self._emit_sample()

    def _parse_sf_corrected_gyro(self, payload: bytearray) -> None:
        """Parse SF CORRECTED_GYRO: MblMwCorrectedCartesianFloat = 3×float32 + uint8 accuracy."""
        if len(payload) < 12:
            return
        gx, gy, gz = struct.unpack_from('<fff', payload[:12])
        self._last_gyro = (gx, gy, gz)
        self._emit_sample()

    def _parse_sf_euler(self, payload: bytearray) -> None:
        """Parse MblMwEulerAngles: 4×float32 [heading, pitch, roll, yaw] from Bosch KF."""
        if len(payload) < 12:
            return
        heading, pitch, roll = struct.unpack_from('<fff', payload[:12])
        self._last_euler = (heading, pitch, roll, heading)
        self._hw_fusion_valid = True
        if self._sf_notify_count <= 5 or self._sf_notify_count % 500 == 0:
            print(f"[sensor] SF euler #{self._sf_notify_count}  "
                  f"heading={heading:.1f}° pitch={pitch:.1f}° roll={roll:.1f}°")

    def _parse_cal_state(self, payload: bytearray) -> None:
        """Parse [accel_cal, gyro_cal, mag_cal, sys_cal] sensor-fusion calibration state."""
        if len(payload) < 3:
            return
        accel_cal = int(payload[0]) & 0x03
        gyro_cal  = int(payload[1]) & 0x03
        mag_cal   = int(payload[2]) & 0x03
        old = self._mag_cal_state
        self._mag_cal_state = mag_cal
        if mag_cal != old:
            print(f"[sensor] Mag cal: {old}→{mag_cal}  (accel={accel_cal} gyro={gyro_cal})")

    def _parse_cal_data(self, payload: bytearray) -> None:
        """Store raw calibration offset bytes received after a read-data request."""
        self._pending_cal_data = bytes(payload)
        print(f"[sensor] Cal data received ({len(payload)} bytes)")

    def _emit_sample(self) -> None:
        ax, ay, az = self._last_acc
        gx, gy, gz = self._last_gyro
        hw_heading, hw_pitch, hw_roll, _ = self._last_euler
        sample = IMUSample(
            timestamp=time.monotonic(),
            ax=ax, ay=ay, az=az,
            gx=gx, gy=gy, gz=gz,
            hw_heading=hw_heading,
            hw_pitch=hw_pitch,
            hw_roll=hw_roll,
            hw_fusion_valid=self._hw_fusion_valid,
        )
        self._sample_count += 1
        if self._sample_count % 50 == 1:
            print(f"[sensor] sample #{self._sample_count}  acc=({ax:+.3f},{ay:+.3f},{az:+.3f})g  gyro=({gx:+.1f},{gy:+.1f},{gz:+.1f})°/s")

        # Non-blocking put — drop oldest if queue is full
        try:
            self.data_queue.put_nowait(sample)
        except queue.Full:
            try:
                self.data_queue.get_nowait()
                self.data_queue.put_nowait(sample)
            except queue.Empty:
                pass

        if self._on_sample_cb:
            try:
                self._on_sample_cb(sample)
            except Exception:
                pass


# ── Demo / standalone test ────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sensor = MetaMotionSensor(scan_timeout=12)
    print("Starting sensor…  (Ctrl-C to quit)")

    def print_sample(s: IMUSample):
        print(
            f"  acc  x={s.ax:+.3f}  y={s.ay:+.3f}  z={s.az:+.3f} g"
            f"   gyro  x={s.gx:+6.1f}  y={s.gy:+6.1f}  z={s.gz:+6.1f} °/s"
        )

    sensor.set_sample_callback(print_sample)

    try:
        sensor.start_background()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        sensor.stop_background()
