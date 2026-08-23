"""
game_experience.py — Shared logic for enhanced gameplay experience:
- Inactivity tracking & Wake Up sequence (haptics, LEDs, screen messages)
- Auto Pause/Resume
- Goal configuration prompt (Score, Time, Endless)
- Fireworks & Particle effects
"""

import time
import random
import pygame

# ── Inactivity & Auto-Pause ───────────────────────────────────────────────────

class InactivityMonitor:
    def __init__(self, username: str, sensor=None):
        self.username = username or "Player"
        self.sensor = sensor
        self.last_motion_time = time.time()
        self.last_pulse_time = 0.0
        self.is_paused = False
        self.message = ""
        self.message_color = (255, 255, 255)
        
        self.inactivity_threshold = 5.0  # seconds before wake-up sequence
        self.pause_threshold = 15.0      # seconds before auto-pause
        
        self.font = pygame.font.SysFont("Helvetica", 48, bold=True)
        self.small_font = pygame.font.SysFont("Helvetica", 32)
        
        self.woke_up = False

    def update(self, is_moving: bool, is_manually_paused: bool = False) -> str:
        """Returns 'PAUSE', 'RESUME', or None based on state changes."""
        now = time.time()
        
        if is_manually_paused:
            self.last_motion_time = now # Prevent triggering immediately after unpause
            self.message = ""
            return None
            
        if is_moving:
            self.last_motion_time = now
            if self.is_paused:
                self.is_paused = False
                self.message = ""
                if self.sensor:
                    self.sensor.set_ambient_light(on=False) # Turn off LED on resume
                return "RESUME"
            
            if self.woke_up:
                self.woke_up = False
                self.message = ""
                if self.sensor:
                    self.sensor.set_ambient_light(on=False)
            
            return None
        
        inactive_dur = now - self.last_motion_time
        
        if inactive_dur > self.pause_threshold:
            if not self.is_paused:
                self.is_paused = True
                self.message = "PAUSED - MAKE A MOVE TO RESUME"
                if self.sensor:
                    self.sensor.set_ambient_light(on=False) # No solid red
                return "PAUSE"
                
        elif inactive_dur > self.inactivity_threshold and not self.is_paused:
            self.woke_up = True
            # Pulse every 2 seconds
            if now - self.last_pulse_time > 2.0:
                self.last_pulse_time = now
                if self.sensor:
                    self.sensor.vibrate(0.3)
                    color = random.choice([0, 1, 2])
                    self.sensor.set_ambient_light(on=True, color=color, blink=True)
                
                messages = [
                    f"Come on {self.username}, you can do it!",
                    f"Keep going {self.username}!",
                    f"Wake up {self.username}, time to play!",
                    "Don't give up!",
                    "Make a move!"
                ]
                self.message = random.choice(messages)
                self.message_color = (random.randint(150,255), random.randint(150,255), random.randint(150,255))
                
        return None

    def draw(self, screen: pygame.Surface):
        if not self.message:
            return
            
        surf = self.font.render(self.message, True, self.message_color)
        rect = surf.get_rect(center=(screen.get_width()//2, screen.get_height()//2))
        
        # Draw backdrop
        bg = pygame.Surface((rect.width + 40, rect.height + 40), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        screen.blit(bg, (rect.x - 20, rect.y - 20))
        screen.blit(surf, rect)

# ── Game Goals Prompt ─────────────────────────────────────────────────────────

class GameGoal:
    def __init__(self, target_score: int = 0, target_time_sec: int = 0):
        self.target_score = target_score
        self.target_time_sec = target_time_sec
        self.indefinite = (target_score == 0 and target_time_sec == 0)
        self.start_time = 0.0

    def start(self):
        self.start_time = time.time()
        
    def check_met(self, current_score: int) -> bool:
        if self.indefinite:
            return False
        if self.target_score > 0 and current_score >= self.target_score:
            return True
        if self.target_time_sec > 0 and (time.time() - self.start_time) >= self.target_time_sec:
            return True
        return False

class GameGoalsPrompt:
    def __init__(self, screen, clock):
        self.screen = screen
        self.clock = clock
        self.font_large = pygame.font.SysFont("Helvetica", 64, bold=True)
        self.font = pygame.font.SysFont("Helvetica", 36)
        self.options = [
            ("Score Target: 20", GameGoal(target_score=20)),
            ("Score Target: 50", GameGoal(target_score=50)),
            ("Time Limit: 2 Min", GameGoal(target_time_sec=120)),
            ("Time Limit: 5 Min", GameGoal(target_time_sec=300)),
            ("Endless Play", GameGoal())
        ]
        self.selected_idx = 0
        
    def run(self) -> GameGoal:
        running = True
        W, H = self.screen.get_size()
        
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return GameGoal() # Endless default
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        self.selected_idx = (self.selected_idx - 1) % len(self.options)
                    elif event.key == pygame.K_DOWN:
                        self.selected_idx = (self.selected_idx + 1) % len(self.options)
                    elif event.key == pygame.K_RETURN:
                        return self.options[self.selected_idx][1]
                        
            self.screen.fill((20, 20, 30))
            
            title = self.font_large.render("Select Game Goal", True, (255, 255, 255))
            self.screen.blit(title, title.get_rect(center=(W//2, H//4)))
            
            start_y = H//2 - 50
            for i, (text, goal) in enumerate(self.options):
                color = (0, 255, 100) if i == self.selected_idx else (150, 150, 150)
                prefix = "▶ " if i == self.selected_idx else "  "
                surf = self.font.render(prefix + text, True, color)
                rect = surf.get_rect(center=(W//2, start_y + i*50))
                self.screen.blit(surf, rect)
                
            pygame.display.flip()
            self.clock.tick(60)

# ── Visual Effects ────────────────────────────────────────────────────────────

class Particle:
    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.vx = random.uniform(-200, 200)
        self.vy = random.uniform(-400, 100)
        self.color = color
        self.life = 1.0
        self.max_life = random.uniform(0.5, 1.5)
        
    def update(self, dt):
        self.vy += 400 * dt # gravity
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        
    def draw(self, screen):
        if self.life > 0:
            alpha = max(0, min(255, int((self.life / self.max_life) * 255)))
            surf = pygame.Surface((6, 6), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*self.color, alpha), (3, 3), 3)
            screen.blit(surf, (int(self.x)-3, int(self.y)-3))

class VisualEffects:
    def __init__(self, sensor=None):
        self.particles: List[Particle] = []
        self.sensor = sensor
        
    def trigger_point_gain(self, x, y):
        color = (random.randint(150,255), random.randint(150,255), 50)
        for _ in range(15):
            self.particles.append(Particle(x, y, color))
            
    def trigger_fireworks(self, x, y):
        if self.sensor:
            self.sensor.vibrate(0.5)
            color = random.choice([0, 1, 2])
            self.sensor.set_ambient_light(on=True, color=color, blink=True)
            
        color = (random.randint(100,255), random.randint(100,255), random.randint(100,255))
        for _ in range(60):
            self.particles.append(Particle(x, y, color))
            
    def trigger_pause(self):
        pass
        
    def trigger_resume(self):
        if self.sensor:
            self.sensor.vibrate(0.2)
            
    def update(self, dt):
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        
    def draw(self, screen):
        for p in self.particles:
            p.draw(screen)
