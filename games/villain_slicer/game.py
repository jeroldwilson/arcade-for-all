"""
game.py — Cyber Warrior: Cartoon Villain Slicer (pygame)

A fast-paced cartoon warrior slicing game designed for middle schoolers,
powered by MetaMotion wrist-tilt and gyroscopic gesture controls.

Features:
- Freeform cyber katana sword slicing with neon plasma trails.
- Cartoon villains with unique movement patterns and split/break mechanics:
    • Gear-Bot: Clockwork minion; bursts with flying cogs, bolts, and sparks.
    • Shadow Imp: Flying bat-gargoyle swooping in sinusoidal wave patterns.
    • Glitch Slime: Squishy blob that splits into 2 mini-slimes on first slice.
    • Rocket Grunt: Fast horizontal lane runner on a sputtering rocket.
    • Shield Trooper: Armored grunt; 1st cut breaks shield, 2nd cut defeats.
    • Spike Drone: Floating hazard mine (avoid slicing!).
    • Dr. Mecha-Pig: Giant boss appearing every milestone requiring 3 cuts.
- Energy Meter & Ultimate Attack: Upward wrist flick triggers screen-clearing Thunder Slash.
- ASTRA Accessible mode: Intent assist with soft-magnetism and dwell strike.
- Gesture HUD live avatar overlay.
"""

import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pygame
from shared.gesture_hud import GestureHUD
from shared.gestures import Gesture
from shared.gestures.bindings import dispatch_bindings, poll_and_signals
from shared.game_experience import (
    GameGoalsPrompt, InactivityMonitor, VisualEffects,
    NebulaBg, StarField, make_glow, FireworksCelebration,
    GameExitAppreciationScreen
)

# ── Color Palette ─────────────────────────────────────────────────────────────
BG_COLOR       = (10, 12, 26)
NEON_CYAN      = (0, 240, 255)
NEON_PINK      = (255, 40, 140)
NEON_YELLOW    = (255, 230, 40)
NEON_GREEN     = (50, 255, 120)
NEON_PURPLE    = (180, 70, 255)
TEXT_WHITE     = (255, 255, 255)
TEXT_DIM       = (160, 175, 200)
ACC_YELLOW     = (255, 230, 80)
ACC_BLUE       = (20, 60, 180)

# ── Enemy Definitions ──────────────────────────────────────────────────────────
ENEMY_TYPES = [
    {"id": "gear_bot",       "name": "Gear-Bot",       "base_r": 42, "speed": 140, "points": 10, "color": (120, 160, 200), "debris": (80, 200, 255)},
    {"id": "shadow_imp",     "name": "Shadow Imp",     "base_r": 36, "speed": 160, "points": 15, "color": (160, 80, 240),  "debris": (220, 100, 255)},
    {"id": "glitch_slime",   "name": "Glitch Slime",   "base_r": 50, "speed": 110, "points": 20, "color": (50, 240, 100),  "debris": (100, 255, 150)},
    {"id": "rocket_grunt",   "name": "Rocket Grunt",   "base_r": 44, "speed": 220, "points": 25, "color": (255, 100, 50),  "debris": (255, 180, 60)},
    {"id": "shield_trooper", "name": "Shield Trooper", "base_r": 54, "speed": 95,  "points": 30, "color": (140, 140, 160), "debris": (200, 210, 230)},
]

@dataclass
class Villain:
    x: float
    y: float
    vx: float
    vy: float
    kind: str
    r: int
    points: int
    color: Tuple[int, int, int]
    debris_color: Tuple[int, int, int]
    hp: int = 1
    max_hp: int = 1
    wave_phase: float = 0.0
    rot: float = 0.0
    rot_spd: float = 0.0
    alive: bool = True
    hazard: bool = False
    is_boss: bool = False
    is_mini: bool = False

@dataclass
class VillainDebris:
    x: float
    y: float
    vx: float
    vy: float
    rot: float
    rot_spd: float
    color: Tuple[int, int, int]
    r: int
    shape: str     # "cog" | "half" | "slime" | "spark"
    life: float = 1.0
    max_life: float = 1.0

@dataclass
class ComicPopup:
    x: float
    y: float
    text: str
    color: Tuple[int, int, int]
    scale: float = 1.0
    life: float = 0.75
    max_life: float = 0.75
    vy: float = -45.0

class VillainSlicerGame:
    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        debug: bool = False,
        mode: str = "standard",
        audio=None,
        username: str = "",
        game_submode: str = "play",
    ):
        self._screen = screen
        self._clock = clock
        self._debug = debug
        self._mode = mode
        self._audio = audio
        self._username = username
        self._game_submode = game_submode
        
        self.hud = GestureHUD(scale=0.3)
        self._gesture_src = None
        
        self._W, self._H = screen.get_size()
        self._sc = min(self._W / 800.0, self._H / 600.0)
        
        # Audio & Game Experience
        self._inactivity = InactivityMonitor(username=username, audio=audio)
        self._effects = VisualEffects()
        self._nebula = NebulaBg()
        self._starfield = StarField(n=80)
        self._celebration: Optional[FireworksCelebration] = None
        self._last_celebrated_score = 0
        
        # Fonts
        if not pygame.font.get_init():
            pygame.font.init()
        self._font_lg = pygame.font.SysFont("Arial", max(28, int(52 * self._sc)), bold=True)
        self._font_md = pygame.font.SysFont("Arial", max(18, int(30 * self._sc)), bold=True)
        self._font_sm = pygame.font.SysFont("Arial", max(12, int(18 * self._sc)), bold=True)
        self._font_comic = pygame.font.SysFont("Arial", max(22, int(42 * self._sc)), bold=True)
        
        # Blade Trail
        self._blade_x = self._W // 2
        self._blade_y = self._H // 2
        self._blade_trail: deque = deque(maxlen=16)
        
        # Game State
        self._score = 0
        self._energy = 0.0          # 0.0 to 100.0 (Ultimate meter)
        self._ultimate_active = False
        self._ultimate_timer = 0.0
        self._combo = 0
        self._combo_timer = 0.0
        self._game_over = False
        self._paused = False
        self._time_left = 60.0      # 60 second wave timer
        self._enemies_sliced = 0
        self._screen_shake = 0.0
        
        # Entities
        self._villains: List[Villain] = []
        self._debris: List[VillainDebris] = []
        self._popups: List[ComicPopup] = []
        self._spawn_timer = 0.0
        self._boss_active = False
        
        # ASTRA Assist
        self._dwell_target: Optional[Villain] = None
        self._dwell_time: float = 0.0

    def run(self, gesture_src) -> str:
        self._gesture_src = gesture_src
        
        # Goals prompt
        goals_prompt = GameGoalsPrompt(self._screen, self._clock, mode=self._mode)
        self._goal = goals_prompt.run(gesture_src)
        if self._goal is None:
            return "home"
            
        self._reset()
        pygame.mouse.set_visible(False)
        if self._audio:
            self._audio.start_background()
            
        while True:
            dt = self._clock.tick(60) / 1000.0
            
            # Update celebration
            if self._celebration is not None:
                if not self._celebration.update(dt):
                    self._celebration = None
                self._handle_events()
            else:
                result = self._handle_events()
                if result:
                    if self._audio: self._audio.stop_background()
                    return result
                    
                if not self._paused and not self._game_over:
                    self._update(dt)
                    
                    # Milestone check
                    current_milestone = self._score // 1000
                    last_milestone = self._last_celebrated_score // 1000
                    if current_milestone > last_milestone and self._score > 0:
                        self._celebration = FireworksCelebration(self._W, self._H, self._username, current_milestone * 1000)
                        self._last_celebrated_score = self._score
                        
            self._draw()
            gs = self._gesture_src.get_state() if getattr(self, "_gesture_src", None) is not None else None
            if gs:
                self.hud.draw(self._screen, gs, self._W - 110, self._H - 110)
            pygame.display.flip()

    def _reset(self):
        self._score = 0
        self._energy = 20.0
        self._combo = 0
        self._combo_timer = 0.0
        self._game_over = False
        self._paused = False
        self._time_left = 75.0 if self._mode == "accessible" else 60.0
        self._enemies_sliced = 0
        self._villains.clear()
        self._debris.clear()
        self._popups.clear()
        self._spawn_timer = 0.5
        self._boss_active = False

    def _handle_events(self) -> Optional[str]:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._game_over:
                        return "home"
                    self._paused = not self._paused
                elif event.key == pygame.K_r:
                    self._reset()
                elif event.key == pygame.K_SPACE:
                    # Keyboard trigger ultimate
                    if self._energy >= 100.0:
                        self._trigger_ultimate()
        return None

    def _update(self, dt: float):
        if self._time_left > 0:
            self._time_left = max(0.0, self._time_left - dt)
            if self._time_left <= 0:
                self._game_over = True
                if self._audio: self._audio.play_game_over()
                
        # Screen shake dampening
        self._screen_shake = max(0.0, self._screen_shake - dt * 15.0)
        
        # Combo timer
        if self._combo_timer > 0:
            self._combo_timer -= dt
            if self._combo_timer <= 0:
                self._combo = 0
                
        # Ultimate timer
        if self._ultimate_active:
            self._ultimate_timer -= dt
            if self._ultimate_timer <= 0:
                self._ultimate_active = False
                
        # Update Blade Position from Sensor / Mouse
        gs = self._gesture_src.get_state() if self._gesture_src else None
        events, sig = poll_and_signals(self._gesture_src, gs)
        self._update_blade(gs, dt, sig)

        # Check Ultimate Trigger via Upward Wrist Flick / Shake
        def _maybe_ult(_ev):
            if self._energy >= 100.0 and not self._ultimate_active:
                self._trigger_ultimate()

        dispatch_bindings(
            events,
            {
                Gesture.FLICK_UP: _maybe_ult,
                Gesture.SHAKE: _maybe_ult,
            },
        )
        if gs and gs.launch and self._energy >= 100.0 and not self._ultimate_active:
            self._trigger_ultimate()
            
        # Spawn Villains
        self._update_spawner(dt)
        
        # Update Villains Physics & Slicing
        self._update_villains(dt)
        
        # Update Debris & Popups
        for d in self._debris:
            d.x += d.vx * dt
            d.y += d.vy * dt
            d.vy += 320.0 * dt   # gravity
            d.rot += d.rot_spd * dt
            d.life -= dt
        self._debris = [d for d in self._debris if d.life > 0]
        
        for p in self._popups:
            p.y += p.vy * dt
            p.life -= dt
        self._popups = [p for p in self._popups if p.life > 0]

    def _update_blade(self, gs, dt: float, sig=None):
        if (
            gs is not None
            and gs.calibrated
            and sig is not None
            and not getattr(gs, "sensor_disconnected", False)
            and (abs(sig.gz) > 7 or abs(sig.gy) > 7)
        ):
            sens = 4.0 if self._mode == "accessible" else 3.3
            dx = -sig.gz * sens * dt * 60.0
            dy = -sig.gy * sens * dt * 60.0
            self._blade_x = max(20, min(self._W - 20, self._blade_x + dx))
            self._blade_y = max(20, min(self._H - 20, self._blade_y + dy))
        else:
            # Mouse fallback
            mx, my = pygame.mouse.get_pos()
            self._blade_x += (mx - self._blade_x) * 0.4
            self._blade_y += (my - self._blade_y) * 0.4
            
        self._blade_trail.append((self._blade_x, self._blade_y, time.time()))

    def _update_spawner(self, dt: float):
        self._spawn_timer -= dt
        if self._spawn_timer <= 0:
            rate = 1.4 if self._mode == "accessible" else 0.95
            self._spawn_timer = random.uniform(rate * 0.7, rate * 1.3)
            self._spawn_enemy()
            
        # Spawn Boss every 300 points if none active
        if self._score > 0 and self._score % 300 < 40 and not self._boss_active and len(self._villains) < 4:
            self._spawn_boss()

    def _spawn_enemy(self, specific_kind=None, x=None, y=None, is_mini=False):
        t = random.choice(ENEMY_TYPES) if not specific_kind else next(e for e in ENEMY_TYPES if e["id"] == specific_kind)
        r = int(t["base_r"] * self._sc * (0.6 if is_mini else 1.0))
        speed = t["speed"] * (0.8 if self._mode == "accessible" else 1.1)
        
        # Spawning trajectories
        side = random.choice(["left", "right", "top"]) if x is None else "custom"
        if side == "left":
            ex = -r
            ey = random.uniform(self._H * 0.35, self._H * 0.8)
            vx = random.uniform(speed * 0.8, speed * 1.2)
            vy = random.uniform(-40, 40)
        elif side == "right":
            ex = self._W + r
            ey = random.uniform(self._H * 0.35, self._H * 0.8)
            vx = -random.uniform(speed * 0.8, speed * 1.2)
            vy = random.uniform(-40, 40)
        elif side == "top":
            ex = random.uniform(self._W * 0.2, self._W * 0.8)
            ey = -r
            vx = random.uniform(-speed * 0.5, speed * 0.5)
            vy = random.uniform(speed * 0.8, speed * 1.3)
        else:
            ex, ey = x, y
            vx = random.uniform(-speed * 0.7, speed * 0.7)
            vy = random.uniform(-speed * 0.5, speed * 0.5)
            
        hp = 2 if t["id"] == "shield_trooper" and not is_mini else 1
        hazard = (random.random() < 0.15 and self._mode != "accessible" and not is_mini)
        
        self._villains.append(Villain(
            x=ex, y=ey, vx=vx, vy=vy,
            kind="spike_drone" if hazard else t["id"],
            r=r, points=t["points"] if not is_mini else t["points"] // 2,
            color=(255, 50, 50) if hazard else t["color"],
            debris_color=t["debris"],
            hp=hp, max_hp=hp,
            wave_phase=random.uniform(0, math.tau),
            rot_spd=random.uniform(-2.0, 2.0),
            hazard=hazard, is_mini=is_mini
        ))

    def _spawn_boss(self):
        self._boss_active = True
        r = int(85 * self._sc)
        self._villains.append(Villain(
            x=-r, y=self._H * 0.4,
            vx=80 * self._sc, vy=0,
            kind="dr_mecha_pig",
            r=r, points=100,
            color=(255, 120, 160),
            debris_color=(255, 200, 80),
            hp=3, max_hp=3,
            rot_spd=0.5,
            is_boss=True
        ))
        self._add_popup(self._W // 2, self._H * 0.3, "BOSS WARNING: DR. MECHA-PORK!", (255, 60, 60), 1.5)

    def _update_villains(self, dt: float):
        bx, by = self._blade_x, self._blade_y
        blade_speed = 0.0
        if len(self._blade_trail) >= 2:
            p1 = self._blade_trail[-1]
            p2 = self._blade_trail[-2]
            blade_speed = math.hypot(p1[0] - p2[0], p1[1] - p2[1]) / max(dt, 0.001)

        hit_extra = 25 if self._mode == "accessible" else 12

        for v in self._villains:
            if not v.alive:
                continue
                
            # Trajectory update
            v.wave_phase += dt * 3.0
            if v.kind == "shadow_imp":
                v.y += math.sin(v.wave_phase) * 80.0 * dt
            elif v.kind == "glitch_slime":
                v.vy += 220.0 * dt  # bouncy gravity
                if v.y > self._H * 0.8:
                    v.vy = -random.uniform(160, 260)
            v.x += v.vx * dt
            v.y += v.vy * dt
            v.rot += v.rot_spd * dt

            # Slicing Collision Check
            dist = math.hypot(bx - v.x, by - v.y)
            is_hit = (dist < v.r + hit_extra and blade_speed > 220.0) or self._ultimate_active

            # ASTRA Dwell Strike Assist
            if self._mode == "accessible" and dist < v.r + 45:
                if self._dwell_target == v:
                    self._dwell_time += dt
                    if self._dwell_time >= 0.4:
                        is_hit = True
                        self._dwell_time = 0.0
                else:
                    self._dwell_target = v
                    self._dwell_time = 0.0

            if is_hit:
                self._slice_villain(v)

        # Cleanup out-of-bounds
        for v in self._villains:
            if v.x < -v.r * 3 or v.x > self._W + v.r * 3 or v.y > self._H + v.r * 3:
                v.alive = False
                if v.is_boss:
                    self._boss_active = False
        self._villains = [v for v in self._villains if v.alive]

    def _slice_villain(self, v: Villain):
        v.hp -= 1
        self._screen_shake = 6.0
        
        # Hazard Check
        if v.hazard:
            v.alive = False
            self._score = max(0, self._score - 30)
            self._add_popup(v.x, v.y, "HAZARD HIT! -30", (255, 60, 60), 1.2)
            if self._audio: self._audio.play_hit()
            return

        if v.hp > 0:
            # Multi-hit feedback (Shield break / Boss damage)
            self._add_popup(v.x, v.y, "SHIELD BROKEN!" if not v.is_boss else f"BOSS HP: {v.hp}!", (255, 220, 60), 1.1)
            self._spawn_debris(v.x, v.y, v.debris_color, count=8)
            if self._audio: self._audio.play_hit()
            return

        # Defeated
        v.alive = False
        self._enemies_sliced += 1
        self._combo += 1
        self._combo_timer = 1.8
        
        # Energy gain
        self._energy = min(100.0, self._energy + 8.0)
        
        # Score calculation
        mult = min(5, 1 + self._combo // 3)
        pts = v.points * mult
        self._score += pts
        
        # Sound & Juice
        if self._audio: self._audio.play_collect()
        self._spawn_debris(v.x, v.y, v.debris_color, count=16)
        
        # Special Mechanics: Slime Split
        if v.kind == "glitch_slime" and not v.is_mini:
            self._spawn_enemy("glitch_slime", v.x - 20, v.y, is_mini=True)
            self._spawn_enemy("glitch_slime", v.x + 20, v.y, is_mini=True)
            self._add_popup(v.x, v.y, "SLIME SPLIT!", (80, 255, 120), 1.1)
        elif self._combo >= 3:
            p_text = random.choice(["POW!", "SLASH!", "CRITICAL!", "SAVAGE!"])
            self._add_popup(v.x, v.y, f"{p_text} +{pts} (x{mult})", NEON_PINK, 1.3)
        else:
            self._add_popup(v.x, v.y, f"+{pts}", TEXT_WHITE, 1.0)
            
        if v.is_boss:
            self._boss_active = False
            self._add_popup(self._W // 2, self._H * 0.4, "BOSS DESTROYED! +100", NEON_YELLOW, 1.8)

    def _trigger_ultimate(self):
        self._ultimate_active = True
        self._ultimate_timer = 1.2
        self._energy = 0.0
        self._screen_shake = 15.0
        self._add_popup(self._W // 2, self._H // 2, "⚡ OMEGA THUNDER SLICE! ⚡", NEON_YELLOW, 2.0)
        if self._audio: self._audio.play_success(self._username)

    def _spawn_debris(self, x: float, y: float, color: Tuple[int, int, int], count: int = 12):
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            spd = random.uniform(100, 320)
            self._debris.append(VillainDebris(
                x=x, y=y,
                vx=math.cos(angle) * spd,
                vy=math.sin(angle) * spd - 60,
                rot=random.uniform(0, 360),
                rot_spd=random.uniform(-10, 10),
                color=color,
                r=random.randint(4, 9),
                shape=random.choice(["cog", "half", "spark"])
            ))

    def _add_popup(self, x: float, y: float, text: str, color: Tuple[int, int, int], scale: float = 1.0):
        self._popups.append(ComicPopup(x=x, y=y, text=text, color=color, scale=scale))

    def _draw(self):
        # Shake offset
        ox = random.uniform(-self._screen_shake, self._screen_shake) if self._screen_shake > 0 else 0
        oy = random.uniform(-self._screen_shake, self._screen_shake) if self._screen_shake > 0 else 0
        
        self._screen.fill(BG_COLOR)
        self._nebula.draw(self._screen)
        self._starfield.draw(self._screen)
        
        # 1. Draw Ultimate Background Flash
        if self._ultimate_active:
            flash_surf = pygame.Surface((self._W, self._H), pygame.SRCALPHA)
            flash_surf.fill((255, 230, 80, 70))
            self._screen.blit(flash_surf, (0, 0))
            
        # 2. Draw Debris
        for d in self._debris:
            frac = d.life / d.max_life
            dr = max(1, int(d.r * frac))
            pygame.draw.circle(self._screen, d.color, (int(d.x + ox), int(d.y + oy)), dr)
            
        # 3. Draw Cartoon Villains
        for v in self._villains:
            self._draw_villain(v, ox, oy)
            
        # 4. Draw Cyber Katana Blade Trail
        self._draw_blade_trail(ox, oy)
        
        # 5. Draw Comic Popups
        for p in self._popups:
            p_surf = self._font_comic.render(p.text, True, p.color)
            if p.scale != 1.0:
                pw, ph = p_surf.get_size()
                p_surf = pygame.transform.smoothscale(p_surf, (int(pw * p.scale), int(ph * p.scale)))
            self._screen.blit(p_surf, p_surf.get_rect(center=(int(p.x + ox), int(p.y + oy))))
            
        # 6. Draw HUD (Score, Timer, Energy Meter)
        self._draw_ui()
        
        # 7. Draw Dwell Indicator in ASTRA mode
        if self._mode == "accessible" and self._dwell_target and self._dwell_time > 0:
            prog = min(1.0, self._dwell_time / 0.4)
            tr = self._dwell_target.r + 14
            pygame.draw.circle(self._screen, ACC_YELLOW, (int(self._dwell_target.x), int(self._dwell_target.y)), tr, 3)
            arc_rect = pygame.Rect(self._dwell_target.x - tr, self._dwell_target.y - tr, tr * 2, tr * 2)
            pygame.draw.arc(self._screen, (255, 80, 80), arc_rect, 0, math.tau * prog, 5)

    def _draw_villain(self, v: Villain, ox: float, oy: float):
        vx, vy = int(v.x + ox), int(v.y + oy)
        
        # Draw Character Body
        if v.kind == "gear_bot":
            # Round robot with cogs
            pygame.draw.circle(self._screen, v.color, (vx, vy), v.r)
            pygame.draw.circle(self._screen, (40, 50, 70), (vx, vy), v.r, 3)
            # Glowing eyes
            pygame.draw.circle(self._screen, NEON_CYAN, (vx - v.r//3, vy - v.r//4), 6)
            pygame.draw.circle(self._screen, NEON_CYAN, (vx + v.r//3, vy - v.r//4), 6)
        elif v.kind == "shadow_imp":
            # Bat wings + pointy ears
            pygame.draw.circle(self._screen, v.color, (vx, vy), v.r)
            pygame.draw.polygon(self._screen, (100, 40, 160), [(vx - v.r, vy), (vx - v.r*2, vy - v.r), (vx - v.r//2, vy + v.r//2)])
            pygame.draw.polygon(self._screen, (100, 40, 160), [(vx + v.r, vy), (vx + v.r*2, vy - v.r), (vx + v.r//2, vy + v.r//2)])
            pygame.draw.circle(self._screen, NEON_YELLOW, (vx - v.r//3, vy - 2), 5)
            pygame.draw.circle(self._screen, NEON_YELLOW, (vx + v.r//3, vy - 2), 5)
        elif v.kind == "glitch_slime":
            # Squishy jelly blob
            pygame.draw.ellipse(self._screen, v.color, (vx - v.r, vy - int(v.r * 0.8), v.r * 2, int(v.r * 1.6)))
            pygame.draw.circle(self._screen, TEXT_WHITE, (vx, vy - 6), 10)
            pygame.draw.circle(self._screen, (10, 50, 20), (vx, vy - 6), 5)
        elif v.kind == "dr_mecha_pig":
            # Giant Boss Robot Pig
            pygame.draw.circle(self._screen, v.color, (vx, vy), v.r)
            pygame.draw.circle(self._screen, (60, 60, 70), (vx, vy), v.r, 5)
            # Snout
            pygame.draw.ellipse(self._screen, (255, 170, 200), (vx - 24, vy - 10, 48, 32))
            pygame.draw.circle(self._screen, (50, 20, 30), (vx - 10, vy + 4), 6)
            pygame.draw.circle(self._screen, (50, 20, 30), (vx + 10, vy + 4), 6)
            # Angry Cyber Monocle
            pygame.draw.circle(self._screen, (255, 30, 30), (vx + 22, vy - 20), 12)
        elif v.hazard:
            # Spike Drone
            pygame.draw.circle(self._screen, (255, 40, 40), (vx, vy), v.r)
            pygame.draw.circle(self._screen, (30, 30, 30), (vx, vy), v.r, 4)
            # Warning skull cross
            pygame.draw.line(self._screen, TEXT_WHITE, (vx - 10, vy - 10), (vx + 10, vy + 10), 3)
            pygame.draw.line(self._screen, TEXT_WHITE, (vx + 10, vy - 10), (vx - 10, vy + 10), 3)
        else:
            # Standard Trooper
            pygame.draw.circle(self._screen, v.color, (vx, vy), v.r)
            pygame.draw.circle(self._screen, (50, 50, 60), (vx, vy), v.r, 3)
            if v.hp > 1:
                # Wooden/Metal Shield Icon
                pygame.draw.rect(self._screen, (190, 130, 60), (vx - v.r//2, vy - v.r//2, v.r, v.r), border_radius=4)
                pygame.draw.rect(self._screen, (240, 220, 100), (vx - v.r//2, vy - v.r//2, v.r, v.r), 2, border_radius=4)

    def _draw_blade_trail(self, ox: float, oy: float):
        if len(self._blade_trail) < 2:
            return
            
        pts = [(int(p[0] + ox), int(p[1] + oy)) for p in self._blade_trail]
        # Multi-layered neon glow line
        pygame.draw.lines(self._screen, (20, 90, 180), False, pts, 12)
        pygame.draw.lines(self._screen, NEON_CYAN, False, pts, 6)
        pygame.draw.lines(self._screen, TEXT_WHITE, False, pts, 2)
        
        # Blade Tip Flare
        bx, by = pts[-1]
        pygame.draw.circle(self._screen, (120, 230, 255), (bx, by), 8)
        pygame.draw.circle(self._screen, TEXT_WHITE, (bx, by), 4)

    def _draw_ui(self):
        # 1. Score
        score_surf = self._font_lg.render(f"SCORE: {self._score}", True, TEXT_WHITE)
        self._screen.blit(score_surf, (24, 20))
        
        # 2. Wave Timer
        t_color = (255, 60, 60) if self._time_left < 10 else NEON_CYAN
        time_surf = self._font_md.render(f"TIME: {int(self._time_left)}s", True, t_color)
        self._screen.blit(time_surf, (self._W // 2 - time_surf.get_width() // 2, 24))
        
        # 3. Ultimate Energy Meter
        bar_w = 200
        bar_h = 16
        bx = self._W - bar_w - 30
        by = 28
        
        # Bar Container
        pygame.draw.rect(self._screen, (20, 25, 40), (bx, by, bar_w, bar_h), border_radius=8)
        fill_w = int(bar_w * (self._energy / 100.0))
        fill_clr = NEON_YELLOW if self._energy >= 100.0 else NEON_PINK
        if fill_w > 0:
            pygame.draw.rect(self._screen, fill_clr, (bx, by, fill_w, bar_h), border_radius=8)
        pygame.draw.rect(self._screen, (80, 120, 180), (bx, by, bar_w, bar_h), 2, border_radius=8)
        
        # Ultimate Ready Text
        lbl = "⚡ FLICK UP: OMEGA SLASH! ⚡" if self._energy >= 100.0 else "ENERGY METER"
        lbl_surf = self._font_sm.render(lbl, True, fill_clr if self._energy >= 100.0 else TEXT_DIM)
        self._screen.blit(lbl_surf, (bx + (bar_w - lbl_surf.get_width()) // 2, by + bar_h + 4))

        # 4. Mode Badge
        mode_lbl = "ASTRA (ASSIST ON)" if self._mode == "accessible" else "VEERA (STANDARD)"
        mb_surf = self._font_sm.render(mode_lbl, True, NEON_GREEN if self._mode == "accessible" else TEXT_DIM)
        self._screen.blit(mb_surf, (24, 68))
        
        # 5. Game Over Overlay
        if self._game_over:
            overlay = pygame.Surface((self._W, self._H), pygame.SRCALPHA)
            overlay.fill((10, 12, 24, 210))
            self._screen.blit(overlay, (0, 0))
            
            go_text = self._font_lg.render("VICTORY! WAVE CLEARED" if self._score > 0 else "TIME UP!", True, NEON_YELLOW)
            self._screen.blit(go_text, go_text.get_rect(center=(self._W // 2, self._H // 2 - 40)))
            
            sc_text = self._font_md.render(f"Final Score: {self._score}  |  Villains Sliced: {self._enemies_sliced}", True, TEXT_WHITE)
            self._screen.blit(sc_text, sc_text.get_rect(center=(self._W // 2, self._H // 2 + 10)))
            
            hint = self._font_sm.render("Press R to Play Again  •  ESC for Menu", True, TEXT_DIM)
            self._screen.blit(hint, hint.get_rect(center=(self._W // 2, self._H // 2 + 60)))
