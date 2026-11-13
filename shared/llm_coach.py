"""
shared/llm_coach.py — Optional Local Qwen 2.5 1.5B (Q4_K_M) AI Voice Coach

Provides an OPTIONAL, toggleable AI Coach (`QwenCoach`) that enhances TTS and HUD
messages for a middle-school player without ever overriding or blocking the
built-in standard TTS when disabled or when the local model is not installed.

Supported Local Backends (auto-detected):
  1. `llama_cpp` Python package (`pip install llama-cpp-python`) with a local
     `qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` file in `models/` or `~/.cache/`
  2. Local Ollama server (`http://127.0.0.1:11434`) running `qwen2.5-coder:1.5b`
     or `qwen2.5:1.5b`

Zero-Latency Design (Never blocks 60 FPS Pygame loop):
  - Pre-generates and replenishes a small queue of personalized middle-school
    messages in a background daemon thread across 3 distinct emotional tones:
      • "success"    — varied middle-school appreciation (hype, chill, gamer, epic)
      • "random_miss"— light, zero-sarcasm, playful "oof / oops, Shake it off!"
                        when a player is doing well and just slips up once
      • "motivate"   — warm, encouraging motivational push when the player is
                        hesitating, playing slowly/less enthusiastically, or
                        finding a streak of questions difficult
"""

import json
import logging
import os
import queue
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models"

DEFAULT_GGUF_NAMES = (
    "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
    "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "qwen2.5-coder-1.5b-q4_k_m.gguf",
)

OLLAMA_MODELS = (
    "qwen2.5-coder:1.5b-instruct-q4_K_M",
    "qwen2.5-coder:1.5b",
    "qwen2.5:1.5b",
)


class QwenCoach:
    """
    Optional, toggleable Qwen 2.5 1.5B (Q4_K_M) middle-school game coach.
    If neither `llama-cpp-python` (+ GGUF) nor `ollama` is installed/available,
    `available` is False and the game seamlessly uses its standard built-in TTS.
    """

    def __init__(self, username: str = "Champion", enabled: bool = True, game_type: str = "math"):
        self.username = (username or "Champion").strip() or "Champion"
        self.game_type = (game_type or "math").strip().lower()
        self.backend: Optional[str] = None      # "llama_cpp" | "ollama" | None
        self.model_label: str = "Qwen2.5-Coder-1.5B-Q4_K_M"
        self._llama_model = None
        self._ollama_model: str = ""
        self._gguf_path: Optional[Path] = None
        self._lock = threading.Lock()

        # Pre-warmed message queues per tone so `get_message()` is instant (0 ms)
        self._pools: Dict[str, queue.Queue] = {
            "success": queue.Queue(maxsize=5),
            "random_miss": queue.Queue(maxsize=5),
            "motivate": queue.Queue(maxsize=5),
        }
        self._req_queue: queue.Queue = queue.Queue(maxsize=12)

        self._detect_backend()
        self.enabled: bool = bool(enabled and self.available)

        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="qwen-coach-worker"
        )
        self._worker_thread.start()

        if self.enabled:
            self._schedule_replenish_all()

    @property
    def available(self) -> bool:
        return self.backend is not None

    @property
    def status_label(self) -> str:
        if not self.available:
            return "AI COACH: NOT INSTALLED [Q]"
        return f"AI COACH (Qwen 1.5B): {'ON' if self.enabled else 'OFF'} [Q]"

    def toggle(self) -> Tuple[bool, str]:
        """
        Toggle the optional Qwen LLM coach on/off.
        Returns (is_enabled, status_message).
        """
        if not self.available:
            # Re-check in case user just started Ollama or dropped GGUF in models/
            self._detect_backend()
        if not self.available:
            self.enabled = False
            return (
                False,
                "Qwen 1.5B Q4_K_M not detected (place GGUF in models/ or run ollama) — Using Standard TTS",
            )

        self.enabled = not self.enabled
        if self.enabled:
            self._schedule_replenish_all()
            return True, f"Qwen 2.5 1.5B Coach ENABLED ({self.backend})"
        return False, "Qwen 2.5 1.5B Coach OFF — Using Standard TTS"

    # ── Backend Discovery ─────────────────────────────────────────────────────

    def _detect_backend(self) -> None:
        """Check for local GGUF + llama_cpp first, then local Ollama server."""
        # 1. Check for GGUF file in models/ or env var QWEN_GGUF_PATH
        gguf_candidates = []
        env_path = os.environ.get("QWEN_GGUF_PATH", "").strip()
        if env_path:
            gguf_candidates.append(Path(env_path))
        if MODELS_DIR.exists():
            for name in DEFAULT_GGUF_NAMES:
                gguf_candidates.append(MODELS_DIR / name)
            for p in MODELS_DIR.glob("*.gguf"):
                gguf_candidates.append(p)

        for candidate in gguf_candidates:
            if candidate.exists() and candidate.is_file():
                try:
                    import llama_cpp  # type: ignore
                    self._gguf_path = candidate
                    self.backend = "llama_cpp"
                    self.model_label = candidate.stem
                    logger.info("Detected Qwen GGUF for llama_cpp: %s", candidate)
                    return
                except ImportError:
                    logger.info("Found GGUF %s but llama-cpp-python is not installed.", candidate)

        # 2. Check local Ollama HTTP API (127.0.0.1:11434) with a fast 0.25s timeout
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=0.25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                for pref in OLLAMA_MODELS:
                    for installed in models:
                        if pref.lower() in installed.lower() or "qwen" in installed.lower():
                            self._ollama_model = installed
                            self.backend = "ollama"
                            self.model_label = installed
                            logger.info("Detected Ollama Qwen model: %s", installed)
                            return
        except Exception:
            pass

    # ── Tone Classification & Prompt Construction ─────────────────────────────

    @staticmethod
    def classify_miss_tone(
        streak_before_miss: int,
        consecutive_misses: int,
        response_seconds: float,
    ) -> str:
        """
        Decide whether a miss or slow play needs:
          • 'random_miss' — playful, non-sarcastic 'Oof / Oops!' when the teen
            was doing fine and just had a random slip-up.
          • 'motivate'    — warm, confidence-building motivational push when
            the teen has missed 2+ in a row OR took >12s (low enthusiasm / stuck).
        """
        if consecutive_misses >= 2 or response_seconds >= 12.0:
            return "motivate"
        return "random_miss"

    def get_feedback(
        self,
        tone: str,
        problem_text: str,
        spoken_problem: str,
        correct_answer: int,
        streak: int = 0,
        other_side: str = "right",
        is_algebra: bool = False,
    ) -> Optional[Tuple[str, str, str]]:
        """
        Return `(headline, subtext, spoken_tts)` generated by Qwen 2.5 1.5B if
        enabled & available; otherwise return `None` so the caller uses its
        existing standard TTS templates untouched.
        """
        if not self.enabled or not self.available:
            return None

        # Queue a background replenishment for next time
        self._enqueue_request(tone, problem_text, spoken_problem, correct_answer, streak, other_side, is_algebra)

        pool = self._pools.get(tone)
        if pool is not None:
            try:
                raw_line = pool.get_nowait()
                return self._format_for_hud(
                    raw_line, tone, problem_text, spoken_problem, correct_answer, streak, other_side, is_algebra
                )
            except queue.Empty:
                pass
        return None

    def get_message(self, tone: str, context: str = "") -> Optional[str]:
        """Return a single short AI coaching/celebration line for non-math games."""
        if not self.enabled or not self.available:
            return None
        self._enqueue_request(tone, context or "game", context or "game", 0, 1, "right", False)
        pool = self._pools.get(tone)
        if pool is not None:
            try:
                raw_line = pool.get_nowait()
                raw = re.sub(r"\s+", " ", (raw_line or "").strip()).strip('"\'')
                clean = "".join(ch for ch in raw if ord(ch) < 128).strip()
                if clean:
                    return clean
            except queue.Empty:
                pass
        return None

    def _format_for_hud(
        self,
        llm_sentence: str,
        tone: str,
        problem_text: str,
        spoken_problem: str,
        correct_answer: int,
        streak: int,
        other_side: str,
        is_algebra: bool,
    ) -> Tuple[str, str, str]:
        """Combine the LLM's natural middle-school sentence with the exact math fact."""
        # Sanitize whitespace, quotes, and non-ascii glyphs (prevents tofu □ boxes)
        raw = re.sub(r"\s+", " ", (llm_sentence or "").strip()).strip('"\'')
        clean = "".join(ch for ch in raw if ord(ch) < 128).strip()

        ans_display = f"x = {correct_answer}" if is_algebra else f"{problem_text} = {correct_answer}"
        ans_spoken = f"x is {correct_answer}" if is_algebra else f"{spoken_problem} is {correct_answer}"

        if tone == "success":
            headline = clean[:32].upper() if clean else f"NICE JOB, {self.username.upper()}!"
            subtext = f"{ans_display}  •  Streak x{max(1, streak)}!"
            spoken = f"{clean} {ans_spoken}!" if clean else f"Nice job {self.username}! {ans_spoken}!"
        elif tone == "random_miss":
            # Natural teen variation without forcing a static "OOPS!" or "OOF!" every time
            headline = clean[:32].upper() if clean else "SO CLOSE!"
            subtext = f"Try {other_side.upper()} for {correct_answer}  •  {ans_display}"
            spoken = f"{clean} Move {other_side} for {correct_answer}!" if clean else f"So close {self.username}! Move {other_side} for {correct_answer}!"
        else:  # "motivate"
            headline = clean[:32].upper() if clean else f"YOU'VE GOT THIS, {self.username.upper()}!"
            subtext = f"Aim {other_side.upper()} ({correct_answer})  •  {ans_display}"
            spoken = f"{clean} Aim {other_side} for {correct_answer}!" if clean else f"Keep going {self.username}! Aim {other_side} for {correct_answer}!"

        return headline, subtext, spoken

    # ── Background Worker & LLM Inference ─────────────────────────────────────

    def _schedule_replenish_all(self) -> None:
        for tone in ("success", "random_miss", "motivate"):
            self._enqueue_request(tone, "7 × 8", "7 times 8", 56, 3, "right", False)

    def _enqueue_request(
        self,
        tone: str,
        problem_text: str,
        spoken_problem: str,
        correct_answer: int,
        streak: int,
        other_side: str,
        is_algebra: bool,
    ) -> None:
        try:
            self._req_queue.put_nowait(
                (tone, problem_text, spoken_problem, correct_answer, streak, other_side, is_algebra)
            )
        except queue.Full:
            pass

    def _worker_loop(self) -> None:
        while True:
            item = self._req_queue.get()
            if not self.enabled or not self.available:
                time.sleep(0.1)
                continue

            tone, problem_text, spoken_problem, correct_answer, streak, other_side, is_algebra = item
            pool = self._pools.get(tone)
            if pool is not None and pool.full():
                continue

            prompt = self._build_prompt(tone, streak, is_algebra)
            generated = self._generate_text(prompt)
            if generated and pool is not None:
                try:
                    pool.put_nowait(generated)
                except queue.Full:
                    pass

    def _build_prompt(self, tone: str, streak: int, is_algebra: bool) -> str:
        name = self.username
        gt = self.game_type
        if gt == "math":
            subject = "middle school algebra" if is_algebra else "mental math"
            success_styles = [
                ("gamer hype", "'Pure genius!', 'Unstoppable skills!', 'Direct hit!'"),
                ("chill teammate", "'Smooth solve!', 'Clean math!', 'Too easy for you!'"),
                ("space commander", "'Target locked!', 'Orbit cleared!', 'Precision strike!'"),
                ("supportive buddy", "'Crushed it!', 'You are on fire!', 'Master class!'"),
            ]
            action_desc = f"solving a {subject} problem on a {max(1, streak)} streak"
            tough_desc = f"{name} is finding {subject} tough."
        elif gt == "fruit_ninja":
            success_styles = [
                ("ninja hype", "'Sharp katana!', 'Ninja combo!', 'Fruit slice master!'"),
                ("arcade buddy", "'Clean slice!', 'Super reflexes!', 'Sliced to perfection!'"),
                ("action coach", "'Lightning blade!', 'Epic combo!', 'Unstoppable swing!'"),
            ]
            action_desc = "slicing fruit with fast wrist swings"
            tough_desc = f"{name} is resting during a fruit slicing game."
        elif gt == "bricks":
            success_styles = [
                ("arcade hype", "'Brick smasher!', 'Clean sweep!', 'Unstoppable bounce!'"),
                ("chill teammate", "'Great paddle save!', 'Bricks cleared!', 'Awesome aim!'"),
                ("power coach", "'Direct smash!', 'Super rebound!', 'Total control!'"),
            ]
            action_desc = "smashing bricks and controlling the paddle"
            tough_desc = f"{name} is resting during a brick breaker game."
        else:
            success_styles = [
                ("arcade hype", "'Awesome move!', 'Unstoppable!', 'Great reflex!'"),
                ("supportive buddy", "'Crushed it!', 'You are on fire!', 'Keep rolling!'"),
            ]
            action_desc = f"playing {gt.replace('_', ' ')} with wrist gestures"
            tough_desc = f"{name} is resting during {gt.replace('_', ' ')}."

        if tone == "success":
            style, examples = random.choice(success_styles)
            return (
                f"You are a friendly middle-school game coach talking to {name}. "
                f"Write ONE very short punchy praise (max 4 to 5 words, max 28 characters) for {name} "
                f"{action_desc}. "
                f"Style: {style} (e.g. {examples}). "
                f"No hashtags, no emojis, no quotes."
            )
        elif tone == "random_miss":
            style, examples = random.choice([
                ("casual teammate", "'So close!', 'Almost had it!', 'Right on the edge!'"),
                ("encouraging friend", "'Easy fix!', 'No sweat!', 'You got the next one!'"),
                ("quick reset", "'Quick reset!', 'Brush it off!', 'Back in action!'"),
                ("playful buddy", "'Nice try!', 'Tiny slip!', 'Shake it off!'"),
                ("focus push", "'Just missed it!', 'Right there!', 'Keep the rhythm!'"),
            ])
            return (
                f"You are a friendly middle-school game buddy talking to {name}. "
                f"{name} is playing well but had a minor slip-up. "
                f"Write ONE short, casual, zero-sarcasm phrase (max 4 words). "
                f"Style: {style} (e.g. {examples}). "
                f"Show natural variation; do NOT always say 'Oops' or 'Oof'. "
                f"No sarcasm, no emojis, no quotes."
            )
        else:  # motivate
            style, examples = random.choice([
                ("supportive coach", "'You got this!', 'Take your time!', 'Ready when you are!'"),
                ("positive mentor", "'Stay locked in!', 'Believe in yourself!', 'Your next move rocks!'"),
                ("calm anchor", "'Breathe and focus!', 'Every move counts!', 'Keep pushing!'"),
                ("team ally", "'We got this!', 'Stay confident!', 'Let us keep going!'"),
            ])
            return (
                f"You are a supportive, encouraging middle-school coach talking to {name}. "
                f"{tough_desc} "
                f"Write ONE short encouraging phrase (max 6 words) that builds confidence to make their next move. "
                f"Style: {style} (e.g. {examples}). "
                f"No emojis, no quotes."
            )

    def _generate_text(self, prompt: str) -> Optional[str]:
        with self._lock:
            if self.backend == "llama_cpp" and self._gguf_path is not None:
                try:
                    import llama_cpp  # type: ignore
                    if self._llama_model is None:
                        self._llama_model = llama_cpp.Llama(
                            model_path=str(self._gguf_path),
                            n_ctx=512,
                            n_threads=4,
                            verbose=False,
                        )
                    res = self._llama_model.create_chat_completion(
                        messages=[
                            {"role": "system", "content": "Output only one very short plain-text phrase (max 5 words)."},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=18,
                        temperature=0.7,
                    )
                    txt = res["choices"][0]["message"]["content"].strip()
                    first_line = txt.splitlines()[0].strip().strip('"\'')
                    return re.sub(r"[^\w\s.,!?'\"-]", "", first_line)
                except Exception as exc:
                    logger.debug("llama_cpp generation error: %s", exc)
                    return None

            elif self.backend == "ollama" and self._ollama_model:
                try:
                    payload = json.dumps({
                        "model": self._ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": 18, "temperature": 0.7},
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        "http://127.0.0.1:11434/api/generate",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=2.5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        txt = (data.get("response") or "").strip()
                        if txt:
                            first_line = txt.splitlines()[0].strip().strip('"\'')
                            return re.sub(r"[^\w\s.,!?'\"-]", "", first_line)
                        return None
                except Exception as exc:
                    logger.debug("Ollama generation error: %s", exc)
                    return None
        return None


class VoiceTTS:
    """Non-blocking TTS helper using macOS `say` or Linux `espeak`."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._say_bin = shutil.which("say")
        self._espeak_bin = shutil.which("espeak") or shutil.which("espeak-ng")

    @property
    def available(self) -> bool:
        return bool(self._say_bin or self._espeak_bin)

    def speak(self, text: str, interrupt: bool = False, rate: int = 185) -> None:
        if not self.enabled or not text or not self.available:
            return
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                if not interrupt:
                    return
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None

        def _worker():
            try:
                cmd = []
                if self._say_bin:
                    cmd = [self._say_bin, "-r", str(rate), text]
                elif self._espeak_bin:
                    cmd = [self._espeak_bin, "-s", str(rate), text]
                if cmd:
                    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with self._lock:
                        self._proc = p
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True, name="voice-tts").start()

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc = None
