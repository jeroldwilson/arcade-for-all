"""
tests/replay.py — Offline IMU replay harness & fixture generator (roadmap Phase 1).

Usage from Python / tests:
    from tests.replay import replay, replay_full, ensure_fixtures
    events = replay("tests/fixtures/flicks_up.jsonl")

No BLE and no pygame required.
"""

from __future__ import annotations

import math
import queue
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from shared.child_profile import ChildProfile
from shared.gesture import GestureConfig, GestureInterpreter, GestureState
from shared.gestures.types import GestureEvent, Signals
from shared.quat import gravity_from_q, q_from_euler
from shared.recorder import load_samples, write_samples
from shared.sensor import IMUSample

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def replay_full(
    source: Union[str, Path, Iterable[IMUSample]],
    config: Optional[GestureConfig] = None,
    profile: Optional[ChildProfile] = None,
) -> Tuple[List[GestureEvent], List[GestureState], List[Signals]]:
    """Feed samples synchronously through GestureInterpreter without threads."""
    samples = load_samples(source) if isinstance(source, (str, Path)) else list(source)
    cfg = config or GestureConfig(haptics_enabled=False)
    interp = GestureInterpreter(queue.Queue(), config=cfg, sensor=None, profile=profile)
    events: List[GestureEvent] = []
    states: List[GestureState] = []
    signals: List[Signals] = []
    for s in samples:
        interp._process(s)
        events.extend(interp.poll())
        states.append(interp.get_state())
        signals.append(interp.signals())
    return events, states, signals


def replay(
    source: Union[str, Path, Iterable[IMUSample]],
    config: Optional[GestureConfig] = None,
    profile: Optional[ChildProfile] = None,
) -> List[GestureEvent]:
    """Replay a .jsonl file (or sample iterable) and return all emitted GestureEvents."""
    events, _, _ = replay_full(source, config=config, profile=profile)
    return events


# ── Synthetic fixture builders (deterministic, 100 Hz) ────────────────────────

def _make_sample(t: float, roll_deg: float = 0.0, pitch_deg: float = 0.0, yaw_deg: float = 0.0,
                 gx: float = 0.0, gy: float = 0.0, gz: float = 0.0,
                 lin_ax: float = 0.0, lin_ay: float = 0.0, lin_az: float = 0.0) -> IMUSample:
    q = q_from_euler(roll_deg, pitch_deg, yaw_deg)
    gx_grav, gy_grav, gz_grav = gravity_from_q(q)
    return IMUSample(
        timestamp=round(t, 6),
        ax=gx_grav + lin_ax,
        ay=gy_grav + lin_ay,
        az=gz_grav + lin_az,
        gx=gx, gy=gy, gz=gz,
        hw_heading=yaw_deg % 360.0,
        hw_pitch=pitch_deg,
        hw_roll=roll_deg,
        hw_fusion_valid=True,
        hw_qw=q[0], hw_qx=q[1], hw_qy=q[2], hw_qz=q[3],
    )


def build_rest_samples(duration_s: float = 2.5, fs: float = 100.0) -> List[IMUSample]:
    n = int(duration_s * fs)
    out = []
    for i in range(n):
        t = i / fs
        # Tiny physiological micro-tremor (±0.3°, ±2°/s)
        wobble = 0.25 * math.sin(2 * math.pi * 1.5 * t)
        out.append(_make_sample(t, roll_deg=wobble, pitch_deg=-0.5 * wobble,
                                gx=1.5 * math.cos(2 * math.pi * 1.5 * t)))
    return out


def build_tremor_samples(duration_s: float = 2.5, fs: float = 100.0) -> List[IMUSample]:
    """8 Hz tremor (±2° angle, ±15°/s gyro) around neutral."""
    n = int(duration_s * fs)
    out = []
    for i in range(n):
        t = i / fs
        s8 = math.sin(2 * math.pi * 8.0 * t)
        c8 = math.cos(2 * math.pi * 8.0 * t)
        out.append(_make_sample(t, roll_deg=2.0 * s8, pitch_deg=2.0 * c8,
                                gx=15.0 * c8, gy=-15.0 * s8))
    return out


def build_tilt_left_right_samples(fs: float = 100.0) -> List[IMUSample]:
    """1.1 s rest → 0.8 s right tilt (pitch=-22° → ax>0) → 0.4 s rest → 0.8 s left tilt."""
    out: List[IMUSample] = []
    for i in range(int(3.1 * fs)):
        t = i / fs
        if t < 1.1:
            pitch = 0.0
        elif t < 1.9:
            pitch = -22.0   # gravity shifts onto +x (right tilt)
        elif t < 2.3:
            pitch = 0.0
        else:
            pitch = +22.0   # gravity shifts onto -x (left tilt)
        out.append(_make_sample(t, pitch_deg=pitch))
    return out


def build_flicks_up_samples(fs: float = 100.0) -> List[IMUSample]:
    """1.1 s rest → upward flick (gy=-260°/s at 1.3 s) → downward jerk (gy=+260°/s at 2.1 s)."""
    out: List[IMUSample] = []
    for i in range(int(2.6 * fs)):
        t = i / fs
        gy = 0.0
        if 1.30 <= t < 1.38:
            gy = -260.0     # upward flick (FLICK_UP_GY_SIGN = -1)
        elif 2.10 <= t < 2.18:
            gy = +260.0     # downward jerk — must NOT launch
        out.append(_make_sample(t, gy=gy))
    return out


def build_slices_samples(fs: float = 100.0) -> List[IMUSample]:
    """1.1 s rest → right slice (gz=+240) at 1.3 s → up slice (gy=-240) at 1.8 s."""
    out: List[IMUSample] = []
    for i in range(int(2.3 * fs)):
        t = i / fs
        gy = gz = 0.0
        if 1.30 <= t < 1.40:
            gz = 240.0
        elif 1.80 <= t < 1.90:
            gy = -240.0
        out.append(_make_sample(t, gy=gy, gz=gz))
    return out


def build_spasm_samples(fs: float = 100.0) -> List[IMUSample]:
    """1.1 s rest → 40 ms sudden jerky spasm at 1.4 s (high gyro + high linear jerk)."""
    out: List[IMUSample] = []
    for i in range(int(2.2 * fs)):
        t = i / fs
        gx = gy = lin_ax = 0.0
        if 1.40 <= t < 1.44:
            gy = -250.0
            gx = 180.0
            lin_ax = 1.6 if int((t - 1.40) * fs) % 2 == 0 else -1.6
        out.append(_make_sample(t, gx=gx, gy=gy, lin_ax=lin_ax))
    return out


def build_hold_samples(direction: str = "right", fs: float = 100.0) -> List[IMUSample]:
    """1.1 s rest → 0.85 s sustained tilt in `direction` ('right' or 'left') → 0.4 s rest."""
    sign = -1.0 if direction == "right" else 1.0  # pitch_deg < 0 gives ax > 0 (right)
    out: List[IMUSample] = []
    for i in range(int(2.4 * fs)):
        t = i / fs
        pitch = sign * 20.0 if 1.15 <= t < 2.00 else 0.0
        out.append(_make_sample(t, pitch_deg=pitch))
    return out


def ensure_fixtures(directory: Path = FIXTURES_DIR) -> Path:
    """Create standard .jsonl replay fixtures on disk if missing."""
    directory.mkdir(parents=True, exist_ok=True)
    builders = {
        "rest.jsonl": build_rest_samples,
        "tremor.jsonl": build_tremor_samples,
        "tilt_left_right.jsonl": build_tilt_left_right_samples,
        "flicks_up.jsonl": build_flicks_up_samples,
        "slices.jsonl": build_slices_samples,
        "spasm.jsonl": build_spasm_samples,
        "hold_right.jsonl": lambda: build_hold_samples("right"),
        "hold_left.jsonl": lambda: build_hold_samples("left"),
    }
    for name, fn in builders.items():
        path = directory / name
        if not path.exists():
            write_samples(path, fn(), relative_time=False)
    return directory

