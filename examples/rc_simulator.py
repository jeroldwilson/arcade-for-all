"""
rc_simulator.py — Phase 5: Virtual RC Car Dashboard

A visual testing tool to prove the Machine Learning model works
independently of the games. It acts as a "Virtual Remote Control".
"""

import sys
import math
import pygame

from shared.sensor import MetaMotionSensor
from shared.gesture import GestureInterpreter, CONFIG_ACCESSIBLE
from shared.gesture_learner import GestureLearningSystem, PROFILE_ACCESSIBLE

# ── Constants ─────────────────────────────────────────────────────────────────
W, H = 800, 600
FPS = 60
BG = (20, 20, 30)

def draw_arrow(surf, cx, cy, angle_deg, lit):
    """Draws a directional arrow. Lights up bright neon green when active."""
    color = (50, 255, 100) if lit else (60, 60, 80)
    
    # Points for an arrow pointing UP
    pts = [
        (0, -40),
        (30, 0),
        (10, 0),
        (10, 40),
        (-10, 40),
        (-10, 0),
        (-30, 0)
    ]
    
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    
    rotated = []
    for x, y in pts:
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        rotated.append((cx + rx, cy + ry))
        
    pygame.draw.polygon(surf, color, rotated)
    if lit:
        # Add a white glowing border when lit
        pygame.draw.polygon(surf, (255, 255, 255), rotated, 2)

def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Virtual RC Car Dashboard")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 24, bold=True)
    font_sm = pygame.font.SysFont("monospace", 16)

    print("Starting MetaMotion BLE thread...")
    sensor = MetaMotionSensor()
    sensor.start_background()
    
    print("Initializing Interpreter...")
    interpreter = GestureInterpreter(sensor.data_queue, config=CONFIG_ACCESSIBLE, sensor=sensor)
    interpreter.start()
    
    print("Loading AI Model...")
    # NOTE: Be sure to use the SAME username you use when playing the games!
    learner = GestureLearningSystem(username="my_kid", profile=PROFILE_ACCESSIBLE)
    
    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        gs = interpreter.get_state()
        learner.update(gs)
        
        # ── The ML Bridge Logic ──
        # Get the AI's prediction of what the child wants to do
        dx, dy = learner.get_cursor_delta(gs, scale_x=1.0, scale_y=1.0, dt=1.0)
        
        # Map the delta directly to an RC Car command
        active_dir = None
        if math.hypot(dx, dy) > 0.1:
            if abs(dx) > abs(dy):
                active_dir = "RIGHT" if dx > 0 else "LEFT"
            else:
                active_dir = "DOWN" if dy > 0 else "UP"

        # ── Draw the UI ──
        screen.fill(BG)
        cx, cy = W // 2, H // 2
        
        status_text = "READY TO DRIVE!" if learner.model_ready else "NO MODEL FOUND. Play a game in Learn Mode first."
        status_color = (100, 255, 100) if learner.model_ready else (255, 100, 100)
        ts = font.render(status_text, True, status_color)
        screen.blit(ts, ts.get_rect(center=(W//2, 50)))
        
        draw_arrow(screen, cx, cy - 100, 0, active_dir == "UP")
        draw_arrow(screen, cx, cy + 100, 180, active_dir == "DOWN")
        draw_arrow(screen, cx - 100, cy, -90, active_dir == "LEFT")
        draw_arrow(screen, cx + 100, cy, 90, active_dir == "RIGHT")
        
        pygame.draw.circle(screen, (50, 50, 50), (cx, cy), 30)
        if active_dir:
            pygame.draw.circle(screen, (255, 200, 50), (cx, cy), 20)

        pygame.display.flip()

    print("Shutting down...")
    interpreter.stop()
    sensor.stop_background()
    pygame.quit()

if __name__ == "__main__":
    main()
