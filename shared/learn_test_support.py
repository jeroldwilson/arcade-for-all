"""
learn_test_support.py — Shared learn/test UI + guided learn helpers.

Keeps game modules lightweight by centralizing:
  - learn/test HUD status rendering
  - validation panel line generation + panel drawing
  - simple guided learn progression utilities
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import pygame


Color = Tuple[int, int, int]


@dataclass
class GuidedLearnFlow:
    """
    Direction-by-direction guided practice tracker.

    Progress is inferred from recorder class-count deltas, so it works with the
    existing GestureLearningSystem without changing learner internals.
    """

    directions: Sequence[str]
    per_direction_target: int = 8
    enabled: bool = True

    def __post_init__(self) -> None:
        self._dirs = tuple(self.directions)
        self._counts: Dict[str, int] = {d: 0 for d in self._dirs}
        self._last_seen: Dict[str, int] = {d: 0 for d in self._dirs}
        self._idx = 0
        self._completed = False

    @property
    def current_direction(self) -> Optional[str]:
        if not self.enabled or self._completed or self._idx >= len(self._dirs):
            return None
        return self._dirs[self._idx]

    @property
    def completed(self) -> bool:
        return self._completed

    def reset(self, enable: Optional[bool] = None) -> None:
        if enable is not None:
            self.enabled = enable
        self._counts = {d: 0 for d in self._dirs}
        self._last_seen = {d: 0 for d in self._dirs}
        self._idx = 0
        self._completed = False

    def sync_baseline(self, class_counts: Dict[str, int]) -> None:
        for d in self._dirs:
            self._last_seen[d] = int(class_counts.get(d, 0))

    def observe_class_counts(self, class_counts: Dict[str, int]) -> None:
        cur = self.current_direction
        for d in self._dirs:
            prev = self._last_seen.get(d, 0)
            now = int(class_counts.get(d, 0))
            delta = max(0, now - prev)
            if cur is not None and d == cur and delta > 0:
                self._counts[d] += delta
            self._last_seen[d] = now

        while cur is not None and self._counts[cur] >= self.per_direction_target:
            self._idx += 1
            if self._idx >= len(self._dirs):
                self._completed = True
                break
            cur = self.current_direction

    def toggle(self) -> bool:
        if self.enabled:
            self.enabled = False
            return self.enabled
        if self._completed:
            self.reset(enable=True)
        else:
            self.enabled = True
        return self.enabled

    def status_text(self) -> str:
        if not self.enabled:
            return "MANUAL LEARN [G=guided]"
        if self._completed:
            return "GUIDED COMPLETE [G=manual]"
        cur = self.current_direction
        if cur is None:
            return "GUIDED"
        return f"GUIDED {cur.upper()} {self._counts[cur]}/{self.per_direction_target} [G=manual]"


def synthetic_target_xy(
    blade_xy: Tuple[float, float],
    direction: str,
    span: float,
) -> Tuple[float, float]:
    bx, by = blade_xy
    if direction == "right":
        return (bx + span, by)
    if direction == "left":
        return (bx - span, by)
    if direction == "up":
        return (bx, by - span)
    if direction == "down":
        return (bx, by + span)
    return (bx + span, by)


def draw_submode_indicator(
    screen: pygame.Surface,
    font_sm: pygame.font.Font,
    font_md: pygame.font.Font,
    w: int,
    h: int,
    game_submode: str,
    sklearn_missing: bool,
    learner,
    guided_text: str = "",
    show_balance_warn: bool = False,
    show_rec_flash: bool = False,
) -> None:
    right = w - 10
    bottom = h - 8
    line_gap = max(14, font_sm.get_height() + 2)

    if game_submode == "learn" and sklearn_missing:
        txt = "LEARN UNAVAILABLE — pip install scikit-learn"
        clr = (255, 80, 60)
    elif game_submode == "learn" and learner is not None:
        n = int(getattr(learner, "total_recordings", 0))
        bal = ""
        if show_balance_warn and hasattr(learner, "class_balance_ok") and not learner.class_balance_ok:
            bal = "  ! imbalanced"
        txt = f"LEARN  {n} rec{bal}  [R=regular T=test]"
        clr = (255, 130, 60)
    elif game_submode == "test" and sklearn_missing:
        txt = "TEST UNAVAILABLE — pip install scikit-learn"
        clr = (255, 80, 60)
    elif game_submode == "test" and learner is not None:
        if bool(getattr(learner, "model_ready", False)):
            txt = "TEST  MODEL READY  [V=validate  R=regular  L=learn]"
            clr = (100, 220, 255)
        else:
            n = int(getattr(learner, "saved_sample_count", 0))
            if n == 0:
                reason = "no data yet — press L"
            elif n < 10:
                reason = f"only {n}/10 samples — learn more"
            else:
                reason = f"{n} samples saved — retraining"
            txt = f"TEST  NO MODEL  ({reason})"
            clr = (255, 140, 100)
    elif game_submode == "play":
        txt = "L=learn  T=test"
        clr = (100, 100, 130)
    else:
        txt = game_submode.upper()
        clr = (180, 180, 220)

    if guided_text:
        g = font_sm.render(guided_text, True, (255, 220, 120))
        screen.blit(g, g.get_rect(right=right, bottom=bottom - line_gap))

    s = font_sm.render(txt, True, clr)
    screen.blit(s, s.get_rect(right=right, bottom=bottom))

    if show_rec_flash and learner is not None and bool(getattr(learner, "rec_flash_active", False)):
        rec_s = font_md.render("● REC", True, (255, 60, 60))
        screen.blit(rec_s, rec_s.get_rect(center=(w // 2, 40)))


def build_validation_lines(
    learner,
    sklearn_missing: bool,
    detail_level: str = "compact",   # "compact" | "detailed"
) -> List[Tuple[str, Color]]:
    lines: List[Tuple[str, Color]] = []
    add = lines.append

    add(("MODEL VALIDATION  [V close]", (100, 180, 255)))
    add(("", (180, 180, 200)))

    if sklearn_missing:
        add(("sklearn not installed", (220, 90, 70)))
        add(("pip install scikit-learn", (180, 100, 80)))
        return lines
    if learner is None:
        add(("No learner.", (200, 100, 100)))
        return lines
    if bool(getattr(learner, "validation_running", False)):
        dots = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
        add((f"Validating{dots}", (220, 210, 80)))
        add(("session-aware CV running...", (110, 110, 140)))
        return lines

    res = getattr(learner, "validation_result", None)
    if res is None:
        add(("Press V to validate.", (140, 140, 170)))
        return lines
    if getattr(res, "error", ""):
        add((f"! {res.error}", (220, 90, 70)))
        return lines

    add((f"Accuracy: {int(res.overall_accuracy * 100)}%", (80, 215, 100)))
    folds = getattr(res, "cv_folds_used", 0)
    if detail_level == "detailed" and folds:
        add((f"{res.n_samples} samples  {res.n_sessions} sessions  {folds} folds", (110, 110, 140)))
    else:
        add((f"{res.n_samples} samples  {res.n_sessions} sessions", (110, 110, 140)))
    add(("", (180, 180, 200)))
    add(("Dir  F1   P   R    n", (110, 110, 150)))
    add(("-" * 28, (50, 50, 75)))

    short = {"right": "R", "left": "L", "up": "U", "down": "D"}
    for d in ("right", "left", "up", "down"):
        if d not in res.per_class:
            continue
        info = res.per_class[d]
        add((
            f"{short[d]:<3} {int(info.get('f1', 0) * 100):>3}% "
            f"{int(info.get('precision', 0) * 100):>3}% "
            f"{int(info.get('recall', 0) * 100):>3}% "
            f"{info.get('support', 0):>3}",
            (185, 185, 210),
        ))

    add(("", (180, 180, 200)))
    add((f"FP rate: {int(res.fp_rate * 100)}%", (140, 140, 170)))
    add((f"Unsure: {int(res.abstain_rate * 100)}%", (140, 140, 170)))

    if detail_level == "detailed":
        lat_ms = float(getattr(res, "latency_ms", 0.0))
        lat_txt = f"{lat_ms:.2f}ms" if lat_ms > 0 else "n/a"
        add((f"Latency: ~{lat_txt}", (140, 140, 170)))

        confusion = getattr(res, "confusion", {}) or {}
        dirs = [d for d in ("right", "left", "up", "down") if d in confusion]
        if dirs:
            add(("", (180, 180, 200)))
            add(("Confusion (true→pred):", (110, 110, 150)))
            short = {"right": "R", "left": "L", "up": "U", "down": "D"}
            hdr = "     " + "  ".join(f"{short[d]:<2}" for d in dirs)
            add((hdr, (100, 130, 170)))
            for true_d in dirs:
                row = f"{short[true_d]:<3}  "
                row += "  ".join(f"{confusion.get(true_d, {}).get(p, 0):<2}" for p in dirs)
                add((row, (185, 185, 210)))

        weakest = getattr(res, "weakest_class", "")
        if weakest and weakest in getattr(res, "per_class", {}):
            wf1 = int(res.per_class.get(weakest, {}).get("f1", 0) * 100)
            if wf1 < 80:
                arrow = {"right": "→", "left": "←", "up": "↑", "down": "↓"}
                add(("", (180, 180, 200)))
                add((f"Tip: practice {arrow.get(weakest, '')} {weakest} (F1={wf1}%)", (255, 210, 70)))

    return lines


def draw_validation_panel(
    screen: pygame.Surface,
    w: int,
    h: int,
    lines: List[Tuple[str, Color]],
    panel_mode: str = "standard",
    detail_level: str = "compact",
    panel_w: Optional[int] = None,
    pad: Optional[int] = None,
    margin: Optional[int] = None,
) -> None:
    base = min(w, h)
    compact = (detail_level != "detailed")

    # Responsive sizing: readable at small res, bounded on large res.
    font_sz = int(max(9, min(12, base * (0.016 if compact else 0.017))))
    f_body = pygame.font.SysFont("monospace", font_sz)
    line_h = max(font_sz + 3, int(font_sz * 1.25))
    pad = int(max(8, min(14, base * 0.02))) if pad is None else pad
    margin = int(max(8, min(16, base * 0.018))) if margin is None else margin

    if panel_w is None:
        frac = 0.32 if compact else 0.36
        if panel_mode == "accessible":
            frac -= 0.02  # less intrusive in assisted mode
        panel_w = int(w * frac)
        panel_w = max(230, min(420, panel_w))

    max_height_frac = 0.38 if compact else 0.50
    if panel_mode == "accessible":
        max_height_frac -= 0.05
    max_panel_h = int(h * max_height_frac)

    # Clamp line count so panel stays unobtrusive.
    max_lines = max(6, (max_panel_h - 2 * pad) // line_h)
    if len(lines) > max_lines:
        trimmed = lines[: max_lines - 1] + [("…", (130, 130, 150))]
    else:
        trimmed = lines

    panel_h = pad * 2 + len(trimmed) * line_h
    px = w - panel_w - margin
    py = h - panel_h - margin

    alpha = 145 if panel_mode == "accessible" else 160
    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((6, 6, 18, alpha))
    screen.blit(panel, (px, py))
    pygame.draw.rect(screen, (60, 100, 170, 180), (px, py, panel_w, panel_h), 1, border_radius=6)

    iy = py + pad
    for text, color in trimmed:
        if text:
            surf = f_body.render(text, True, color)
            screen.blit(surf, (px + pad, iy))
        iy += line_h
