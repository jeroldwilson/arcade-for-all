import pygame
import math
import time
from typing import Optional, Tuple, List
from shared.gesture import GestureState

class GestureHUD:
    """
    Renders a live, interactive 3D-perspective Vector Hand Avatar inside a translucent
    circular glass HUD.
    
    Dynamically tracks and visualizes:
      • Real-time 3D wrist roll & pitch (from Euler angles, raw accelerometer, or keyboard)
      • High-speed Gyro Flicks (Left / Right / Up / Down / Launch)
      • Twist / Spin rotation
      • Live gesture badges & continuous degree readouts
      • Pulsating MetaMotion BLE Sensor LED
    """
    def __init__(self, image_path: Optional[str] = None, scale: float = 0.3):
        self.scale = scale
        
        # Smooth interpolation state
        self.current_roll = 0.0      # degrees
        self.current_pitch = 0.0     # degrees
        self.current_offset_x = 0.0  # pixels
        self.current_offset_y = 0.0  # pixels
        self.launch_anim = 0.0       # spring lift
        
        # Gyro peak tracking for flick detection directly inside HUD
        self.last_gx = 0.0
        self.last_gy = 0.0
        self.last_gz = 0.0
        self.flick_cooldown = 0.0
        
        # Badge state
        self.active_gesture_text = ""
        self.active_gesture_color = (255, 255, 255)
        self.gesture_timer = 0.0

        if not pygame.font.get_init():
            pygame.font.init()
        self.font_badge = pygame.font.SysFont("Arial", 15, bold=True)
        self.font_val = pygame.font.SysFont("Arial", 12, bold=True)

    def _trigger_gesture(self, text: str, color: Tuple[int, int, int], duration: float = 0.55):
        self.active_gesture_text = text
        self.active_gesture_color = color
        self.gesture_timer = duration

    def _project_3d(self, x: float, y: float, z: float, roll_rad: float, pitch_rad: float, cx: float, cy: float, fov: float = 200.0) -> Tuple[int, int]:
        """Rotate point (x, y, z) in 3D by roll and pitch, then perspective project to 2D screen."""
        # 1. Pitch around X axis
        y1 = y * math.cos(pitch_rad) - z * math.sin(pitch_rad)
        z1 = y * math.sin(pitch_rad) + z * math.cos(pitch_rad)
        x1 = x
        
        # 2. Roll around Z axis
        x2 = x1 * math.cos(roll_rad) - y1 * math.sin(roll_rad)
        y2 = x1 * math.sin(roll_rad) + y1 * math.cos(roll_rad)
        z2 = z1
        
        # 3. Perspective projection
        depth = fov / (fov + z2 + 80.0)
        proj_x = cx + x2 * depth
        proj_y = cy + y2 * depth
        return int(proj_x), int(proj_y)

    def draw(self, screen: pygame.Surface, gs: GestureState, x: int, y: int):
        if gs is None:
            return

        dt = 0.016
        if self.flick_cooldown > 0:
            self.flick_cooldown -= dt

        # ── 1. COMPUTE REAL-TIME TARGET ORIENTATION ──
        # Check all available telemetry channels with priority:
        # A) Direct Euler roll/pitch (hardware sensor fusion or Madgwick)
        # B) Raw calibrated gravity accelerometer (raw_ax, abs_ay)
        # C) Paddle velocity / keyboard inputs
        target_roll = 0.0
        target_pitch = 0.0

        if hasattr(gs, 'euler_roll') and abs(gs.euler_roll) > 1.0:
            target_roll = -gs.euler_roll * 0.95
        elif hasattr(gs, 'raw_ax') and abs(gs.raw_ax) > 0.02:
            target_roll = -gs.raw_ax * 75.0
        elif hasattr(gs, 'paddle_velocity') and abs(gs.paddle_velocity) > 0.05:
            target_roll = -gs.paddle_velocity * 45.0

        if hasattr(gs, 'euler_pitch') and abs(gs.euler_pitch) > 1.0:
            target_pitch = gs.euler_pitch * 0.8
        elif hasattr(gs, 'tilt_y') and abs(gs.tilt_y) > 0.05:
            target_pitch = gs.tilt_y * 40.0

        # Also support live keyboard responsiveness
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            target_roll = 35.0
        elif keys[pygame.K_RIGHT]:
            target_roll = -35.0
        if keys[pygame.K_UP]:
            target_pitch = -25.0
        elif keys[pygame.K_DOWN]:
            target_pitch = 25.0

        # ── 2. DETECT FLICKS & TRIGGER GESTURES ──
        gx = getattr(gs, 'abs_gx', 0.0)
        gy = getattr(gs, 'abs_gy', 0.0)
        gz = getattr(gs, 'abs_gz', 0.0)

        # Launch / Flick Up
        if gs.launch or keys[pygame.K_SPACE] or (gy > 140.0 and self.flick_cooldown <= 0):
            self._trigger_gesture("LAUNCH / FLICK UP!", (255, 230, 80), 0.7)
            self.launch_anim = 1.0
            self.flick_cooldown = 0.4
        # Steer / Flick Left
        elif gs.steer_left or keys[pygame.K_LEFT] or ((gx < -110.0 or gz < -110.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK LEFT", (80, 255, 140), 0.6)
            self.current_offset_x = -38.0
            self.flick_cooldown = 0.35
        # Steer / Flick Right
        elif gs.steer_right or keys[pygame.K_RIGHT] or ((gx > 110.0 or gz > 110.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK RIGHT", (80, 255, 140), 0.6)
            self.current_offset_x = 38.0
            self.flick_cooldown = 0.35
        # Steer / Flick Down
        elif gs.steer_down or keys[pygame.K_DOWN] or (gy < -130.0 and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK DOWN", (100, 220, 255), 0.6)
            self.current_offset_y = 30.0
            self.flick_cooldown = 0.35
        # Multi-directional Slices
        elif getattr(gs, 'slice_active', False) and getattr(gs, 'slice_direction', ''):
            if abs(gz) > 100.0 or abs(gy) > 100.0 or abs(gx) > 100.0:
                self._trigger_gesture(f"SLICE {gs.slice_direction.upper()}", (255, 110, 100), 0.45)
        # Continuous Tilt Left/Right badge
        elif abs(target_roll) > 10.0:
            direction = "TILT LEFT" if target_roll > 0 else "TILT RIGHT"
            self._trigger_gesture(f"{direction} {int(abs(target_roll))}°", (140, 215, 255), 0.2)
        # Continuous Tilt Forward/Back
        elif abs(target_pitch) > 12.0:
            direction = "TILT FORWARD" if target_pitch < 0 else "TILT BACK"
            self._trigger_gesture(direction, (140, 215, 255), 0.2)

        # ── 3. SMOOTH PHYSICS & SPRING INTERPOLATION ──
        self.current_roll += (target_roll - self.current_roll) * 0.35
        self.current_pitch += (target_pitch - self.current_pitch) * 0.35
        self.current_offset_x += (0.0 - self.current_offset_x) * 0.16
        self.current_offset_y += (0.0 - self.current_offset_y) * 0.16
        self.launch_anim += (0.0 - self.launch_anim) * 0.14

        roll_rad = math.radians(self.current_roll)
        pitch_rad = math.radians(self.current_pitch - (self.launch_anim * 30.0))

        # ── 4. RENDER GLASS HUD BACKGROUND ──
        hud_r = 92
        center_x = x
        center_y = y

        hud_surf = pygame.Surface((hud_r * 2 + 12, hud_r * 2 + 12), pygame.SRCALPHA)
        hc_x, hc_y = hud_r + 6, hud_r + 6
        
        # Glassmorphic pod with subtle glowing rim
        pygame.draw.circle(hud_surf, (15, 22, 38, 185), (hc_x, hc_y), hud_r)
        pygame.draw.circle(hud_surf, (35, 55, 90, 150), (hc_x, hc_y), hud_r - 2)
        pygame.draw.circle(hud_surf, (80, 150, 235, 210), (hc_x, hc_y), hud_r, 2)
        
        # Real-time animated tilt arc
        arc_rect = pygame.Rect(hc_x - hud_r + 5, hc_y - hud_r + 5, (hud_r - 5) * 2, (hud_r - 5) * 2)
        angle_rad = -roll_rad
        start_a = math.pi/2 - max(0.0, angle_rad)
        end_a = math.pi/2 - min(0.0, angle_rad)
        if abs(angle_rad) > 0.05:
            arc_color = (80, 230, 255, 240) if abs(angle_rad) < 0.6 else (255, 200, 70, 240)
            pygame.draw.arc(hud_surf, arc_color, arc_rect, min(start_a, end_a), max(start_a, end_a), 4)

        # Crosshair ticks
        pygame.draw.line(hud_surf, (60, 80, 120, 100), (hc_x - hud_r + 10, hc_y), (hc_x + hud_r - 10, hc_y), 1)
        pygame.draw.line(hud_surf, (60, 80, 120, 100), (hc_x, hc_y - hud_r + 10), (hc_x, hc_y + hud_r - 10), 1)
        
        screen.blit(hud_surf, (center_x - hc_x, center_y - hc_y))

        # ── 5. RENDER 3D VECTOR HAND AVATAR ──
        hx = center_x + self.current_offset_x
        hy = center_y + self.current_offset_y - (self.launch_anim * 40.0)

        # Scaled Geometry
        wrist_poly_3d = [
            (-16, 28, 0), (16, 28, 0), (14, 52, 10), (-14, 52, 10)
        ]
        band_poly_3d = [
            (-18, 18, -2), (18, 18, -2), (17, 34, 4), (-17, 34, 4)
        ]
        sensor_pod_3d = [
            (-12, 21, -8), (12, 21, -8), (11, 31, -6), (-11, 31, -6)
        ]
        palm_poly_3d = [
            (-18, 18, 0), (18, 18, 0), (17, -15, 2), (-17, -15, 2)
        ]
        fingers_3d = [
            # Thumb
            [(-17, 8, 2), (-27, 0, 4), (-29, -10, 2), (-22, -6, 0)],
            # Index
            [(-15, -15, 2), (-14, -38, 4), (-8, -38, 4), (-9, -15, 2)],
            # Middle
            [(-7, -15, 2), (-6, -44, 5), (0, -44, 5), (0, -15, 2)],
            # Ring
            [(2, -15, 2), (2, -40, 4), (8, -40, 4), (8, -15, 2)],
            # Pinky
            [(10, -15, 2), (11, -32, 3), (16, -32, 3), (16, -15, 2)],
        ]

        def project_poly(poly):
            return [self._project_3d(px * 1.45, py * 1.7, pz * 1.45, roll_rad, pitch_rad, hx, hy) for px, py, pz in poly]

        skin_base = (245, 198, 165)
        skin_shade = (218, 164, 130)
        skin_edge = (175, 125, 92)
        band_color = (45, 145, 230)
        sensor_color = (25, 25, 30)

        # Draw Forearm
        pts_arm = project_poly(wrist_poly_3d)
        pygame.draw.polygon(screen, skin_shade, pts_arm)
        pygame.draw.polygon(screen, skin_edge, pts_arm, 1)

        # Draw Palm
        pts_palm = project_poly(palm_poly_3d)
        pygame.draw.polygon(screen, skin_base, pts_palm)
        pygame.draw.polygon(screen, skin_edge, pts_palm, 1)

        # Draw Fingers
        for finger in fingers_3d:
            pts_f = project_poly(finger)
            pygame.draw.polygon(screen, skin_base, pts_f)
            pygame.draw.polygon(screen, skin_edge, pts_f, 1)

        # Draw Wristband
        pts_band = project_poly(band_poly_3d)
        pygame.draw.polygon(screen, band_color, pts_band)
        pygame.draw.polygon(screen, (20, 70, 130), pts_band, 2)

        # Draw MetaMotion Sensor Pod
        pts_sensor = project_poly(sensor_pod_3d)
        pygame.draw.polygon(screen, sensor_color, pts_sensor)
        pygame.draw.polygon(screen, (90, 90, 105), pts_sensor, 1)

        # Glowing MetaMotion LED
        led_center_3d = self._project_3d(0, 26 * 1.7, -9 * 1.45, roll_rad, pitch_rad, hx, hy)
        led_color = (100, 255, 120) if getattr(gs, "calibrated", True) else (255, 160, 40)
        pulse = (math.sin(time.time() * 6.0) + 1.0) * 0.5
        glow_r = int(3 + pulse * 2)
        
        led_surf = pygame.Surface((glow_r * 4 + 4, glow_r * 4 + 4), pygame.SRCALPHA)
        lc = glow_r * 2 + 2
        pygame.draw.circle(led_surf, (*led_color, 95), (lc, lc), glow_r + 3)
        pygame.draw.circle(led_surf, led_color, (lc, lc), 2)
        screen.blit(led_surf, (led_center_3d[0] - lc, led_center_3d[1] - lc))

        # ── 6. DYNAMIC GESTURE BADGES & ANGLE READOUT ──
        if self.gesture_timer > 0:
            self.gesture_timer -= dt
            badge_text = self.font_badge.render(self.active_gesture_text, True, self.active_gesture_color)
            bw, bh = badge_text.get_size()
            
            badge_bg = pygame.Surface((bw + 18, bh + 8), pygame.SRCALPHA)
            badge_bg.fill((15, 20, 32, 235))
            pygame.draw.rect(badge_bg, (*self.active_gesture_color, 220), (0, 0, bw + 18, bh + 8), 1, border_radius=6)
            
            bx = center_x - (bw + 18) // 2
            by = center_y - hud_r - bh - 8
            screen.blit(badge_bg, (bx, by))
            screen.blit(badge_text, (bx + 9, by + 4))
        else:
            deg_val = int(self.current_roll)
            deg_str = f"{deg_val:+d}°" if abs(deg_val) > 1 else "READY"
            val_surf = self.font_val.render(deg_str, True, (140, 180, 225))
            screen.blit(val_surf, val_surf.get_rect(center=(center_x, center_y + hud_r - 14)))
