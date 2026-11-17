"""
dual_sensor.py — Optional dual-sensor hub (wrist required + upper arm optional).

Manages a primary wrist `MetaMotionSensor` and an optional secondary upper-arm
`MetaMotionSensor` (subscribed to `StreamChannel.QUAT` only to keep BLE
bandwidth lightweight). If `upper_arm_mac` is None, fails to connect, or
disconnects mid-session, `DualSensorHub` gracefully falls back to single-sensor
wrist-only mode.
"""

from __future__ import annotations

import logging
import queue
import time
from typing import Callable, Optional, Tuple

from shared.sensor import IMUSample, MetaMotionSensor, StreamChannel

logger = logging.getLogger(__name__)


class DualSensorHub:
    """Drop-in sensor wrapper supporting 1 (wrist) or 2 (wrist + upper arm) sensors."""

    def __init__(
        self,
        wrist_mac: Optional[str] = None,
        upper_arm_mac: Optional[str] = None,
        scan_timeout: float = 10.0,
        sf_profile: str = "full",
        subscriptions: Optional[StreamChannel] = None,
        sensor_factory: Callable[..., MetaMotionSensor] = MetaMotionSensor,
    ):
        self.wrist_mac = wrist_mac
        self.upper_arm_mac = upper_arm_mac
        self.sf_profile = sf_profile

        self.wrist = sensor_factory(
            scan_timeout=scan_timeout,
            sf_profile=sf_profile,
            subscriptions=subscriptions,
        )
        self.upper_arm: Optional[MetaMotionSensor] = (
            sensor_factory(
                scan_timeout=scan_timeout,
                sf_profile="lean",
                subscriptions=StreamChannel.QUAT,
            )
            if upper_arm_mac
            else None
        )
        self._last_upper_sample: Optional[IMUSample] = None
        self._last_upper_rx_t: float = 0.0

    @property
    def data_queue(self) -> queue.Queue:
        return self.wrist.data_queue

    @property
    def dual_sensor_active(self) -> bool:
        return self.upper_arm is not None and self.upper_arm.is_connected()

    @property
    def cal_state(self) -> Tuple[int, int, int]:
        return self.wrist.cal_state

    @property
    def mag_cal_state(self) -> int:
        return self.wrist.mag_cal_state

    def is_connected(self) -> bool:
        return self.wrist.is_connected()

    def start_background(self, address: Optional[str] = None) -> None:
        wrist_addr = address or self.wrist_mac
        self.wrist.start_background(address=wrist_addr)

        if self.upper_arm is not None and self.upper_arm_mac:
            try:
                self.upper_arm.start_background(address=self.upper_arm_mac)
                logger.info("DualSensorHub: upper-arm sensor connected (%s)", self.upper_arm_mac)
            except Exception as exc:
                logger.warning(
                    "DualSensorHub: upper-arm sensor (%s) failed (%s) — falling back to single-sensor mode",
                    self.upper_arm_mac, exc,
                )
                self.upper_arm = None

    def stop_background(self) -> None:
        self.wrist.stop_background()
        if self.upper_arm is not None:
            try:
                self.upper_arm.stop_background()
            except Exception:
                pass

    def set_subscriptions(self, channels: StreamChannel) -> None:
        self.wrist.set_subscriptions(channels)
        # Upper arm always stays on lightweight QUAT-only stream
        if self.upper_arm is not None and self.upper_arm.is_connected():
            self.upper_arm.set_subscriptions(StreamChannel.QUAT)

    def set_sample_callback(self, cb: Callable[[IMUSample], None]) -> None:
        self.wrist.set_sample_callback(cb)

    def vibrate(self, duration: float = 0.15) -> None:
        self.wrist.vibrate(duration)

    def set_ambient_light(self, on: bool = True, color: int = 0, blink: bool = False) -> None:
        self.wrist.set_ambient_light(on=on, color=color, blink=blink)

    def save_calibration_to_nvm(self) -> None:
        self.wrist.save_calibration_to_nvm()
        if self.upper_arm is not None and self.upper_arm.is_connected():
            self.upper_arm.save_calibration_to_nvm()

    def get_latest_upper_sample(self, max_age_s: float = 0.35) -> Optional[IMUSample]:
        """Drain upper-arm queue and return the newest sample, or None if unavailable/stale."""
        if self.upper_arm is None or not self.upper_arm.is_connected():
            return None

        q = self.upper_arm.data_queue
        newest: Optional[IMUSample] = None
        while True:
            try:
                newest = q.get_nowait()
            except queue.Empty:
                break

        now = time.monotonic()
        if newest is not None:
            self._last_upper_sample = newest
            self._last_upper_rx_t = now

        if self._last_upper_sample is not None and (now - self._last_upper_rx_t) <= max_age_s:
            return self._last_upper_sample
        return None
