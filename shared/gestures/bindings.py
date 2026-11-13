"""
gestures/bindings.py — Game binding dispatch, gesture legends & compatibility adapter
(roadmap §6.3 & Phase 6).
"""

from __future__ import annotations

import inspect
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from shared.gestures.types import Gesture, GestureEvent, Signals

# Gesture legends displayed on the Home screen for each game (Phase 6)
GAME_GESTURE_LEGENDS: Dict[str, str] = {
    "bricks":         "Gestures: Tilt L/R → Paddle  |  Flick Up / Hold Up → Launch  |  Twist → Spin",
    "snake":          "Gestures: Tilt or Flick/Hold 4-Way → Turn Snake",
    "fruit_ninja":    "Gestures: Orientation Pointer → Move Blade  |  Slice / Flick / Hold → Cut",
    "villain_slicer": "Gestures: Orientation Pointer → Move Katana  |  Flick Up / Hold Up → Ultimate",
    "math_choice":    "Gestures: Tilt or Flick/Hold L/R → Pick Answer",
    "youtube_tv":     "Gestures: Flick/Hold L/R → Channel  |  Hold/Flick Up → Play/Pause",
    "scratch_pad":    "Gestures: Tilt → Aim Brush  |  Flick Up / Hold → Clear Canvas",
    "magic_wand":     "Gestures: Tilt → Move Wand  |  Flick Up / Hold → Cast Spell",
    "calibration":    "Gestures: Live 4-Panel IMU & Quaternion Visualizer",
}


def poll_and_signals(gesture_src, gs=None) -> Tuple[List[GestureEvent], Signals]:
    """Read (events, signals) from `gesture_src`, with fallback for test mocks that only have `get_state()`."""
    events: List[GestureEvent] = []
    if gesture_src is not None and hasattr(gesture_src, "poll"):
        events = list(gesture_src.poll())

    if gesture_src is not None and hasattr(gesture_src, "signals"):
        sig = gesture_src.signals()
    elif gs is not None:
        tx = float(getattr(gs, "tilt_x", getattr(gs, "paddle_velocity", 0.0)) or 0.0)
        ty = float(getattr(gs, "tilt_y", 0.0) or 0.0)
        sig = Signals(
            tilt_x=tx,
            tilt_y=ty,
            pointer_x=0.5 * (1.0 + tx),
            pointer_y=0.5 * (1.0 + ty),
            roll=float(getattr(gs, "rel_roll", getattr(gs, "euler_roll", 0.0)) or 0.0),
            pitch=float(getattr(gs, "rel_pitch", getattr(gs, "euler_pitch", 0.0)) or 0.0),
            hold_progress=float(getattr(gs, "hold_progress", 0.0) or 0.0),
            hold_direction=str(getattr(gs, "hold_direction", "") or ""),
            calibrated=bool(getattr(gs, "calibrated", True)),
        )
    else:
        sig = Signals()

    # Synthesize events when a test mock only populates GestureState booleans
    if not events and gs is not None:
        if getattr(gs, "launch", False):
            events.append(GestureEvent(Gesture.FLICK_UP, detector="compat"))
        if getattr(gs, "steer_left", False):
            events.append(GestureEvent(Gesture.FLICK_LEFT, detector="compat"))
        if getattr(gs, "steer_right", False):
            events.append(GestureEvent(Gesture.FLICK_RIGHT, detector="compat"))
        if getattr(gs, "steer_up", False):
            events.append(GestureEvent(Gesture.FLICK_UP, detector="compat"))
        if getattr(gs, "steer_down", False):
            events.append(GestureEvent(Gesture.FLICK_DOWN, detector="compat"))
        if getattr(gs, "slice_active", False):
            events.append(GestureEvent(
                Gesture.SLICE,
                direction=str(getattr(gs, "slice_direction", "") or ""),
                detector="compat",
            ))

    return events, sig


def dispatch_bindings(
    events: Iterable[GestureEvent],
    bindings: Dict[Gesture, Callable],
) -> List[GestureEvent]:
    """Invoke bound handlers for each matching GestureEvent; return handled events."""
    handled: List[GestureEvent] = []
    for ev in events:
        fn = bindings.get(ev.gesture)
        if fn is None:
            continue
        try:
            params = inspect.signature(fn).parameters
            if len(params) == 0:
                fn()
            else:
                fn(ev)
        except TypeError:
            fn()
        handled.append(ev)
    return handled
