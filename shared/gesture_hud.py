import pygame
import pygame.gfxdraw
import math
import time
from typing import Optional, Tuple, List, Sequence
from shared.gesture import GestureState


class GestureHUD:
    """
    Renders a live, interactive 3D-perspective Realistic Right-Hand Avatar
    inside a translucent circular glass HUD.

    Dynamically tracks and visualizes:
      • Real-time 3D wrist roll & pitch (from Euler angles, raw accelerometer, or keyboard)
      • Mirror-mode tilt: user tilts left → on-screen hand & arc tilt left (Kinect convention)
      • Dynamic 3D directional lighting (Lambertian + warm subsurface shading + specular)
      • Organic dorsal hand anatomy with smooth subsurface gradients, natural finger splay,
        soft extensor tendons, and curved knuckle creases
      • 3D-projected fingernails with lunula crescents that rotate & foreshorten naturally
      • Dynamic finger flex & splay response to flicks, launches, and slices
      • 3D extruded MetaMotion BLE sensor pod with beveled walls & thumb-side pulsating LED
      • Soft projected drop shadow inside the glass HUD pod

    The sensor is worn on the RIGHT wrist with the green LED on the left (thumb-side)
    edge of the sensor pod, matching the physical MetaMotion band orientation.
    """

    # ── Skin, wristband & sensor color palette ───────────────────────────────
    _SKIN_HIGHLIGHT = (252, 218, 192)   # specular dorsal highlight
    _SKIN_LIGHT = (244, 202, 172)       # lit dorsal skin
    _SKIN_BASE = (234, 186, 154)        # base neutral skin tone
    _SKIN_SHADE = (210, 158, 124)       # shaded slope skin tone
    _SKIN_DEEP_SHADE = (184, 130, 98)   # warm subsurface shadow
    _SKIN_EDGE = (164, 114, 84)         # outer contour line
    _CREASE_COLOR = (188, 136, 104)     # soft knuckle crease tone

    _NAIL_BASE = (252, 224, 212)        # fingernail plate
    _NAIL_LUNULA = (255, 242, 236)      # pale crescent at nail base
    _NAIL_EDGE = (212, 168, 144)        # soft cuticle / nail border

    _BAND_MAIN = (38, 48, 74)           # dark navy elastomer strap
    _BAND_SIDE = (26, 34, 54)           # shaded strap side bevel
    _BAND_ACCENT = (64, 86, 132)        # strap center ridge highlight
    _BAND_EDGE = (18, 24, 40)           # strap outline

    _SENSOR_TOP = (34, 36, 46)          # sensor pod top housing
    _SENSOR_WALL = (22, 24, 32)         # sensor pod extruded side walls
    _SENSOR_EDGE = (82, 86, 104)        # sensor bevel rim
    _SENSOR_FACE = (44, 47, 60)          # recessed sensor top face
    _SENSOR_FACE_BORDER = (62, 66, 82)

    # Normalized directional light vector (top-left-front toward the hand)
    _LIGHT_DIR = (-0.36, -0.44, -0.82)

    # ── Static 3D right-hand geometry (dorsal / back-of-hand view) ───────────
    # Y-axis: negative = toward fingertips, positive = toward forearm
    # X-axis: negative = thumb side (left on screen), positive = pinky side
    # Z-axis: negative = raised toward viewer (dorsal dome), positive = deeper away

    # Forearm & wrist base
    _FOREARM_3D = (
        (-13.8, 36.0, 1.8), (13.8, 36.0, 2.0),
        (15.2, 55.0, 7.2), (8.0, 56.5, 6.8),
        (-8.0, 56.5, 6.8), (-15.2, 55.0, 7.2),
    )
    _FOREARM_HI_3D = (
        (-8.5, 36.0, 0.5), (8.0, 36.0, 0.6),
        (9.0, 55.5, 5.8), (-9.0, 55.5, 5.8),
    )
    _WRIST_3D = (
        (-15.0, 22.0, 1.0), (14.6, 22.0, 1.2),
        (14.0, 38.0, 2.2), (-14.0, 38.0, 2.0),
    )

    # Smooth 16-vertex organic palm perimeter (clockwise from index base)
    _PALM_BASE_3D = (
        (-14.5, -3.2, 0.2),   # index MCP outer
        (-7.0, -4.8, -0.8),   # index-middle web
        (0.5, -4.8, -0.8),    # middle-ring web
        (7.8, -3.8, -0.3),    # ring-pinky web
        (14.6, -1.8, 0.6),    # pinky MCP outer
        (16.2, 4.0, 1.2),     # upper hypothenar edge
        (16.4, 11.5, 1.4),    # mid hypothenar curve
        (15.4, 18.5, 1.4),    # lower hypothenar curve
        (14.2, 24.5, 1.2),    # ulnar wrist junction
        (-14.6, 24.5, 1.0),   # radial wrist junction
        (-16.5, 18.5, 1.2),   # lower thenar base
        (-18.6, 11.0, 1.3),   # mid thenar muscle curve
        (-20.2, 4.2, 1.4),    # thumb CMC prominence
        (-22.2, -2.5, 1.8),   # thumb web outer
        (-17.8, -1.2, 0.8),   # thumb-index purlicue fold
        (-15.5, -2.5, 0.4),   # index base transition
    )

    # Soft inner dorsal dome layers (for smooth organic 3D curvature shading without seams)
    _PALM_MID_DOME_3D = (
        (-12.2, -2.2, -0.8),
        (-3.0, -3.6, -1.4),
        (6.5, -2.8, -1.0),
        (12.5, -0.5, -0.2),
        (13.8, 9.0, 0.2),
        (12.2, 20.5, 0.2),
        (-12.2, 20.5, 0.0),
        (-15.2, 9.5, 0.2),
        (-14.8, 1.5, 0.0),
    )
    _PALM_HIGH_DOME_3D = (
        (-9.5, -1.0, -1.5),
        (-2.2, -2.2, -2.0),
        (5.2, -1.4, -1.6),
        (9.5, 7.5, -1.2),
        (7.5, 17.0, -0.8),
        (-8.5, 17.0, -0.8),
        (-11.2, 7.5, -1.0),
    )
    # Soft thenar (thumb base) muscular pillow
    _THENAR_PILLOW_3D = (
        (-19.2, 3.8, 0.8),
        (-14.0, 0.5, -0.4),
        (-11.8, 9.5, -0.4),
        (-14.8, 17.5, 0.4),
        (-17.8, 11.5, 0.8),
    )

    # Outer palm contour paths for crisp silhouette edges
    _PALM_LEFT_CONTOUR_3D = (
        (-14.6, 24.5, 1.0), (-16.5, 18.5, 1.2),
        (-18.6, 11.0, 1.3), (-20.2, 4.2, 1.4),
    )
    _THUMB_WEB_CONTOUR_3D = (
        (-22.2, -2.5, 1.8), (-17.8, -1.2, 0.8), (-14.5, -3.2, 0.2),
    )
    _PALM_RIGHT_CONTOUR_3D = (
        (14.2, 24.5, 1.2), (15.4, 18.5, 1.4),
        (16.4, 11.5, 1.4), (16.2, 4.0, 1.2), (14.6, -1.8, 0.6),
    )

    # Subtle dorsal extensor tendons (from mid-metacarpal to MCP knuckles)
    _TENDONS_3D = (
        ((-7.8, 14.0, -1.2), (-9.4, 5.0, -1.4), (-10.8, -3.2, -0.4)),
        ((-2.6, 15.5, -1.6), (-2.8, 5.0, -2.0), (-3.0, -4.4, -1.0)),
        ((2.4, 15.0, -1.3), (3.4, 5.0, -1.5), (4.4, -3.6, -0.5)),
        ((6.8, 14.0, -0.6), (9.2, 5.5, -0.5), (11.5, -2.0, 0.4)),
    )

    # MCP knuckle prominence positions & radii: (x, y, z, radius)
    _MCP_KNUCKLES_3D = (
        (-10.8, -3.4, -0.3, 3.4),
        (-3.0, -4.5, -1.0, 3.7),
        (4.4, -3.7, -0.4, 3.4),
        (11.5, -2.1, 0.4, 3.0),
    )

    # Curved wristband geometry (3 facets for cylindrical wrap around wrist)
    _BAND_LEFT_3D = (
        (-16.6, 25.0, 1.5), (-7.0, 24.5, -2.2), (-6.8, 37.5, 0.8), (-15.8, 37.5, 3.8),
    )
    _BAND_CENTER_3D = (
        (-7.0, 24.5, -2.2), (7.0, 24.5, -2.2), (6.8, 37.5, 0.8), (-6.8, 37.5, 0.8),
    )
    _BAND_RIGHT_3D = (
        (7.0, 24.5, -2.2), (16.6, 25.0, 1.5), (15.8, 37.5, 3.8), (6.8, 37.5, 0.8),
    )
    _BAND_RIB_3D = (
        (-16.0, 30.3, 0.8), (-7.0, 29.8, -2.4), (7.0, 29.8, -2.4), (16.0, 30.3, 0.8),
        (15.8, 32.3, 1.4), (6.9, 31.8, -1.8), (-6.9, 31.8, -1.8), (-15.8, 32.3, 1.4),
    )
    _BAND_DOTS_3D = (
        (-12.2, 28.0, -0.5), (-8.5, 27.7, -1.8), (8.5, 27.7, -1.8), (12.2, 28.0, -0.5),
        (-11.8, 34.5, 1.8), (-8.2, 34.3, 0.2), (8.2, 34.3, 0.2), (11.8, 34.5, 1.8),
    )

    # 3D Extruded MetaMotion Sensor Pod
    _SENSOR_BASE_CORNERS = (
        (-11.0, 26.3, -2.2), (11.0, 26.3, -2.2),
        (10.2, 36.7, 0.4), (-10.2, 36.7, 0.4),
    )
    _SENSOR_TOP_CORNERS = (
        (-9.8, 27.1, -7.8), (9.8, 27.1, -7.8),
        (9.1, 35.9, -5.6), (-9.1, 35.9, -5.6),
    )
    _SENSOR_FACE_3D = (
        (-8.2, 28.0, -8.0), (8.2, 28.0, -8.0),
        (7.6, 35.0, -6.0), (-7.6, 35.0, -6.0),
    )

    # Structured finger definitions with natural resting anatomical splay & taper:
    _FINGER_SPECS = (
        {
            "name": "thumb",
            "is_thumb": True,
            "splay_dir": -1.25,
            # Base CMC/MCP → IP → Tip: (x, y, z, radius)
            "joints": (
                (-19.2, 2.2, 0.9, 4.6),
                (-25.8, -8.2, 1.8, 3.85),
                (-31.0, -17.8, 2.9, 3.3),
            ),
            "nail_length": 5.2,
            "nail_width": 2.45,
        },
        {
            "name": "index",
            "is_thumb": False,
            "splay_dir": -0.75,
            # Natural slight radial spread toward left (-X)
            "joints": (
                (-10.8, -3.4, -0.2, 3.75),
                (-11.4, -19.5, 1.2, 3.25),
                (-11.8, -31.5, 2.3, 2.85),
                (-12.0, -40.5, 3.4, 2.45),
            ),
            "nail_length": 5.0,
            "nail_width": 1.95,
        },
        {
            "name": "middle",
            "is_thumb": False,
            "splay_dir": -0.05,
            "joints": (
                (-3.0, -4.5, -1.0, 3.95),
                (-3.1, -22.2, 0.8, 3.4),
                (-3.2, -35.8, 2.2, 2.95),
                (-3.2, -46.0, 3.5, 2.55),
            ),
            "nail_length": 5.4,
            "nail_width": 2.05,
        },
        {
            "name": "ring",
            "is_thumb": False,
            "splay_dir": 0.6,
            # Natural slight ulnar spread toward right (+X)
            "joints": (
                (4.4, -3.7, -0.4, 3.7),
                (5.2, -20.0, 1.1, 3.15),
                (5.7, -32.6, 2.3, 2.75),
                (6.0, -41.5, 3.4, 2.4),
            ),
            "nail_length": 5.0,
            "nail_width": 1.9,
        },
        {
            "name": "pinky",
            "is_thumb": False,
            "splay_dir": 1.2,
            "joints": (
                (11.5, -2.1, 0.4, 3.25),
                (13.0, -15.2, 1.6, 2.75),
                (14.0, -24.8, 2.5, 2.4),
                (14.7, -32.2, 3.4, 2.1),
            ),
            "nail_length": 4.2,
            "nail_width": 1.65,
        },
    )

    # Outer silhouette loop in 3D for projecting the soft drop shadow onto the HUD dome
    _SHADOW_SILHOUETTE_3D = (
        (-14.5, 52.0, 6.0), (-15.5, 24.0, 1.0), (-20.0, 3.0, 1.0),
        (-32.5, -18.5, 3.5), (-27.0, -19.5, 3.5), (-18.0, -3.0, 1.0),
        (-14.0, -41.0, 4.0), (-3.2, -47.0, 4.0), (7.0, -42.5, 4.0),
        (16.0, -33.0, 4.0), (16.5, 4.0, 1.5), (14.5, 24.0, 1.5), (14.5, 52.0, 6.0),
    )

    def __init__(self, image_path: Optional[str] = None, scale: float = 0.3):
        # `image_path` is retained for backward compatibility with existing callers.
        _ = image_path
        self.scale = scale
        scale_ratio = scale / 0.3 if scale > 0 else 1.0
        self._hud_r = max(32, int(round(92 * scale_ratio)))
        self._geom_scale = 1.55 * scale_ratio

        # Smooth interpolation state
        self.current_roll = 0.0       # degrees
        self.current_pitch = 0.0      # degrees
        self.current_offset_x = 0.0   # pixels (flick nudge)
        self.current_offset_y = 0.0   # pixels (flick nudge)
        self.launch_anim = 0.0        # spring lift for flick-up
        self.finger_flex = 0.0        # dynamic extension (-1) / curl (+1)
        self.finger_splay = 0.0       # dynamic finger spread during active gestures

        self.flick_cooldown = 0.0

        # Badge state
        self.active_gesture_text = ""
        self.active_gesture_color = (255, 255, 255)
        self.gesture_timer = 0.0

        if not pygame.font.get_init():
            pygame.font.init()
        try:
            self.font_badge = pygame.font.SysFont("Arial", 15, bold=True)
            self.font_val = pygame.font.SysFont("Arial", 12, bold=True)
        except Exception:
            self.font_badge = pygame.font.Font(None, 18)
            self.font_val = pygame.font.Font(None, 15)

        # Pre-render static glass HUD pod and reusable overlay surfaces
        self._hc = self._hud_r + 6
        self._base_hud_surf = self._build_base_hud_surface()
        self._arc_hud_surf = pygame.Surface(self._base_hud_surf.get_size(), pygame.SRCALPHA)
        self._shadow_surf = pygame.Surface(self._base_hud_surf.get_size(), pygame.SRCALPHA)
        max_glow_r = 9
        self._led_surf_half = max_glow_r * 2 + 4
        self._led_surf = pygame.Surface(
            (self._led_surf_half * 2, self._led_surf_half * 2), pygame.SRCALPHA
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_base_hud_surface(self) -> pygame.Surface:
        """Pre-render the static translucent glass pod, specular glass rim, and crosshair."""
        hud_r = self._hud_r
        hc_x = hc_y = self._hc
        surf = pygame.Surface((hud_r * 2 + 12, hud_r * 2 + 12), pygame.SRCALPHA)

        # Glassmorphic pod: layered circles for depth
        self._aa_circle(surf, (12, 18, 34, 195), hc_x, hc_y, hud_r)
        self._aa_circle(surf, (26, 42, 74, 155), hc_x, hc_y, hud_r - 3)
        self._aa_circle(surf, (38, 62, 104, 85), hc_x, hc_y - int(hud_r * 0.12), int(hud_r * 0.82))

        # Outer rim glow
        try:
            pygame.gfxdraw.aacircle(surf, hc_x, hc_y, hud_r, (85, 160, 245, 220))
            pygame.gfxdraw.aacircle(surf, hc_x, hc_y, hud_r - 1, (60, 125, 210, 145))
        except (ValueError, OverflowError):
            pygame.draw.circle(surf, (85, 160, 245, 220), (hc_x, hc_y), hud_r, 2)

        # Subtle degree tick marks around the inner top bezel
        for deg in range(-60, 61, 15):
            rad = math.radians(deg - 90)
            r_outer = hud_r - 4
            r_inner = hud_r - (10 if deg % 30 == 0 else 7)
            x1 = int(hc_x + math.cos(rad) * r_inner)
            y1 = int(hc_y + math.sin(rad) * r_inner)
            x2 = int(hc_x + math.cos(rad) * r_outer)
            y2 = int(hc_y + math.sin(rad) * r_outer)
            pygame.draw.aaline(surf, (90, 140, 200, 110), (x1, y1), (x2, y2))

        # Fine crosshair
        pygame.draw.line(
            surf, (65, 90, 135, 65),
            (hc_x - hud_r + 14, hc_y), (hc_x + hud_r - 14, hc_y), 1,
        )
        pygame.draw.line(
            surf, (65, 90, 135, 65),
            (hc_x, hc_y - hud_r + 14), (hc_x, hc_y + hud_r - 14), 1,
        )
        return surf

    def _trigger_gesture(self, text: str, color: Tuple[int, int, int], duration: float = 0.55):
        self.active_gesture_text = text
        self.active_gesture_color = color
        self.gesture_timer = duration

    def _rotate_3d(
        self,
        x: float, y: float, z: float,
        roll_rad: float, pitch_rad: float,
    ) -> Tuple[float, float, float]:
        """Rotate point (x,y,z) in 3D by pitch (X-axis) and roll (Z-axis)."""
        cp, sp = math.cos(pitch_rad), math.sin(pitch_rad)
        cr, sr = math.cos(roll_rad), math.sin(roll_rad)

        # 1. Pitch around X-axis
        y1 = y * cp - z * sp
        z1 = y * sp + z * cp
        x1 = x

        # 2. Roll around Z-axis
        x2 = x1 * cr - y1 * sr
        y2 = x1 * sr + y1 * cr
        z2 = z1
        return x2, y2, z2

    def _project_3d(
        self,
        x: float, y: float, z: float,
        roll_rad: float, pitch_rad: float,
        cx: float, cy: float,
        fov: float = 210.0,
    ) -> Tuple[int, int]:
        """Rotate point (x,y,z) in 3D by roll and pitch, then perspective-project to 2D."""
        x2, y2, z2 = self._rotate_3d(x, y, z, roll_rad, pitch_rad)
        depth = fov / max(40.0, fov + z2 + 80.0)
        return int(cx + x2 * depth), int(cy + y2 * depth)

    def _project_3d_with_depth(
        self,
        x: float, y: float, z: float,
        roll_rad: float, pitch_rad: float,
        cx: float, cy: float,
        fov: float = 210.0,
    ) -> Tuple[int, int, float, float]:
        """Rotate & project (x,y,z), returning (proj_x, proj_y, depth_scale, cam_z)."""
        x2, y2, z2 = self._rotate_3d(x, y, z, roll_rad, pitch_rad)
        depth = fov / max(40.0, fov + z2 + 80.0)
        return int(cx + x2 * depth), int(cy + y2 * depth), depth, z2

    def _poly_lighting(
        self,
        poly_3d: Sequence[Tuple[float, float, float]],
        roll_rad: float,
        pitch_rad: float,
    ) -> float:
        """
        Compute normalized directional light intensity [0.0 .. 1.0] for a 3D polygon
        after rotating by (roll_rad, pitch_rad).
        """
        if len(poly_3d) < 3:
            return 0.65
        p0 = self._rotate_3d(*poly_3d[0], roll_rad, pitch_rad)
        p1 = self._rotate_3d(*poly_3d[1], roll_rad, pitch_rad)
        p2 = self._rotate_3d(*poly_3d[2], roll_rad, pitch_rad)

        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]

        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm < 1e-6:
            return 0.65
        nx /= norm
        ny /= norm
        nz /= norm

        # Ensure dorsal normal points toward the viewer (-Z)
        if nz > 0:
            nx, ny, nz = -nx, -ny, -nz

        lx, ly, lz = self._LIGHT_DIR
        dot = max(0.0, min(1.0, nx * lx + ny * ly + nz * lz))
        return dot

    @staticmethod
    def _mix_rgb(
        c1: Tuple[int, int, int],
        c2: Tuple[int, int, int],
        t: float,
    ) -> Tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        return (
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
        )

    def _shade_skin(self, light_dot: float, bias: float = 0.0) -> Tuple[int, int, int]:
        """Map directional light dot product to warm subsurface-shaded skin color."""
        val = max(0.0, min(1.0, light_dot + bias))
        if val < 0.38:
            return self._mix_rgb(self._SKIN_DEEP_SHADE, self._SKIN_SHADE, val / 0.38)
        if val < 0.68:
            return self._mix_rgb(self._SKIN_SHADE, self._SKIN_BASE, (val - 0.38) / 0.30)
        if val < 0.88:
            return self._mix_rgb(self._SKIN_BASE, self._SKIN_LIGHT, (val - 0.68) / 0.20)
        return self._mix_rgb(self._SKIN_LIGHT, self._SKIN_HIGHLIGHT, (val - 0.88) / 0.12)

    def _aa_polygon(self, surface: pygame.Surface, color: Tuple[int, ...], points: List[Tuple[int, int]]):
        """Draw an antialiased filled polygon using gfxdraw."""
        if len(points) < 3:
            return
        try:
            pygame.gfxdraw.filled_polygon(surface, points, color)
            pygame.gfxdraw.aapolygon(surface, points, color)
        except (ValueError, OverflowError):
            pygame.draw.polygon(surface, color[:3], points)

    def _aa_circle(self, surface: pygame.Surface, color: Tuple[int, ...], cx: int, cy: int, r: int):
        """Draw an antialiased filled circle using gfxdraw."""
        if r < 1:
            r = 1
        try:
            pygame.gfxdraw.filled_circle(surface, cx, cy, r, color)
            pygame.gfxdraw.aacircle(surface, cx, cy, r, color)
        except (ValueError, OverflowError):
            pygame.draw.circle(surface, color[:3], (cx, cy), r)

    # ── Main draw ─────────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface, gs: GestureState, x: int, y: int):
        if gs is None:
            return

        dt = 0.016
        if self.flick_cooldown > 0:
            self.flick_cooldown -= dt

        # ── 1. COMPUTE TARGET ORIENTATION ─────────────────────────────────────
        # Mirror mode (Kinect convention):
        #   Physical tilt left  → euler_roll < 0 → target_roll > 0 → screen hand tilts left  ✓
        #   Physical tilt right → euler_roll > 0 → target_roll < 0 → screen hand tilts right ✓
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

        # Keyboard mirror-mode
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            target_roll = 35.0       # left key → hand tilts left on screen
        elif keys[pygame.K_RIGHT]:
            target_roll = -35.0      # right key → hand tilts right on screen
        if keys[pygame.K_UP]:
            target_pitch = -25.0
        elif keys[pygame.K_DOWN]:
            target_pitch = 25.0

        # ── 2. FLICK / GESTURE DETECTION ───────────────────────────────────────
        gx = getattr(gs, 'abs_gx', 0.0)
        gy = getattr(gs, 'abs_gy', 0.0)
        gz = getattr(gs, 'abs_gz', 0.0)
        gyro_mag = math.sqrt(gx * gx + gy * gy + gz * gz)

        if gs.launch or ((keys[pygame.K_SPACE] or gy > 140.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("LAUNCH / FLICK UP!", (255, 230, 80), 0.7)
            self.launch_anim = 1.0
            self.flick_cooldown = 0.4
        elif gs.steer_left or ((gx < -110.0 or gz < -110.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK LEFT", (80, 255, 140), 0.6)
            self.current_offset_x = -38.0
            self.flick_cooldown = 0.35
        elif gs.steer_right or ((gx > 110.0 or gz > 110.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK RIGHT", (80, 255, 140), 0.6)
            self.current_offset_x = 38.0
            self.flick_cooldown = 0.35
        elif gs.steer_down or (gy < -130.0 and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK DOWN", (100, 220, 255), 0.6)
            self.current_offset_y = 30.0
            self.flick_cooldown = 0.35
        elif getattr(gs, 'slice_active', False) and getattr(gs, 'slice_direction', ''):
            if abs(gz) > 100.0 or abs(gy) > 100.0 or abs(gx) > 100.0:
                self._trigger_gesture(f"SLICE {gs.slice_direction.upper()}", (255, 110, 100), 0.45)
        elif abs(target_roll) > 10.0:
            direction = "TILT LEFT" if target_roll > 0 else "TILT RIGHT"
            self._trigger_gesture(f"{direction} {int(abs(target_roll))}°", (140, 215, 255), 0.2)
        elif abs(target_pitch) > 12.0:
            direction = "TILT FORWARD" if target_pitch < 0 else "TILT BACK"
            self._trigger_gesture(direction, (140, 215, 255), 0.2)

        # ── 3. SMOOTH PHYSICS / SPRING INTERPOLATION ──────────────────────────
        self.current_roll += (target_roll - self.current_roll) * 0.35
        self.current_pitch += (target_pitch - self.current_pitch) * 0.35
        self.current_offset_x += (0.0 - self.current_offset_x) * 0.16
        self.current_offset_y += (0.0 - self.current_offset_y) * 0.16
        self.launch_anim += (0.0 - self.launch_anim) * 0.14

        # Secondary organic finger motion: extend & splay on launch/slice/high gyro
        target_flex = -0.85 * self.launch_anim + (0.25 if target_pitch > 12 else 0.0)
        target_splay = min(1.0, self.launch_anim * 0.85 + min(1.0, gyro_mag / 240.0) * 0.4)
        self.finger_flex += (target_flex - self.finger_flex) * 0.25
        self.finger_splay += (target_splay - self.finger_splay) * 0.25

        # Negative sign on roll_rad so positive current_roll ("TILT LEFT") rotates
        # upward-pointing fingers (-Y) counter-clockwise toward the LEFT (-X).
        roll_rad = -math.radians(self.current_roll)
        pitch_rad = math.radians(self.current_pitch - (self.launch_anim * 30.0))

        # ── 4. GLASS HUD BACKGROUND ──────────────────────────────────────────
        hud_r = self._hud_r
        hc_x = hc_y = self._hc
        center_x = x
        center_y = y

        arc_angle = math.radians(self.current_roll)
        if abs(arc_angle) > 0.05:
            self._arc_hud_surf.fill((0, 0, 0, 0))
            self._arc_hud_surf.blit(self._base_hud_surf, (0, 0))
            arc_rect = pygame.Rect(
                hc_x - hud_r + 5, hc_y - hud_r + 5,
                (hud_r - 5) * 2, (hud_r - 5) * 2,
            )
            start_a = math.pi / 2 + min(0.0, arc_angle)
            end_a = math.pi / 2 + max(0.0, arc_angle)
            arc_color = (80, 230, 255, 240) if abs(arc_angle) < 0.6 else (255, 200, 70, 240)
            pygame.draw.arc(
                self._arc_hud_surf, arc_color, arc_rect,
                start_a, end_a, 4,
            )
            screen.blit(self._arc_hud_surf, (center_x - hc_x, center_y - hc_y))
        else:
            screen.blit(self._base_hud_surf, (center_x - hc_x, center_y - hc_y))

        # ── 5. REALISTIC 3D RIGHT-HAND AVATAR ────────────────────────────────
        hx = center_x + self.current_offset_x
        hy = center_y + self.current_offset_y - (self.launch_anim * 40.0)

        sc = self._geom_scale

        def proj(px: float, py: float, pz: float) -> Tuple[int, int]:
            return self._project_3d(px * sc, py * sc, pz * sc, roll_rad, pitch_rad, hx, hy)

        def proj_depth(px: float, py: float, pz: float) -> Tuple[int, int, float, float]:
            return self._project_3d_with_depth(px * sc, py * sc, pz * sc, roll_rad, pitch_rad, hx, hy)

        def proj_poly(poly: Sequence[Tuple[float, float, float]]) -> List[Tuple[int, int]]:
            return [proj(px, py, pz) for px, py, pz in poly]

        # ─── 0. Soft Projected Drop Shadow inside HUD Dome ────────────────
        self._shadow_surf.fill((0, 0, 0, 0))
        sh_ox = hc_x + (hx - center_x) + int(4 * (sc / 1.55))
        sh_oy = hc_y + (hy - center_y) + int(6 * (sc / 1.55))
        shadow_pts = [
            self._project_3d(
                px * sc, py * sc, (pz + 16.0) * sc,
                roll_rad, pitch_rad, sh_ox, sh_oy,
            )
            for px, py, pz in self._SHADOW_SILHOUETTE_3D
        ]
        self._aa_polygon(self._shadow_surf, (6, 10, 20, 60), shadow_pts)
        screen.blit(self._shadow_surf, (center_x - hc_x, center_y - hc_y))

        # Compute base directional lighting across the dorsal hand plane
        dorsal_lit = self._poly_lighting(self._PALM_MID_DOME_3D, roll_rad, pitch_rad)
        # Add subtle roll-dependent directional warmth (tilting toward top-left brightens)
        roll_shade_shift = -math.sin(roll_rad) * 0.08 - math.sin(pitch_rad) * 0.06
        hand_lit = max(0.15, min(0.98, dorsal_lit + roll_shade_shift))

        # ─── 1. Forearm & Wrist (smooth shaded base + dorsal highlight) ───
        self._aa_polygon(screen, self._shade_skin(hand_lit, -0.10), proj_poly(self._FOREARM_3D))
        self._aa_polygon(screen, self._shade_skin(hand_lit, -0.04), proj_poly(self._FOREARM_HI_3D))
        self._aa_polygon(screen, self._shade_skin(hand_lit, -0.05), proj_poly(self._WRIST_3D))

        # ─── 2. Organic Multi-Layer Dorsal Palm & Thumb Pillow ────────────
        self._aa_polygon(screen, self._shade_skin(hand_lit, -0.04), proj_poly(self._PALM_BASE_3D))
        self._aa_polygon(screen, self._shade_skin(hand_lit, 0.01), proj_poly(self._PALM_MID_DOME_3D))
        self._aa_polygon(screen, self._shade_skin(hand_lit, 0.06), proj_poly(self._PALM_HIGH_DOME_3D))
        self._aa_polygon(screen, self._shade_skin(hand_lit, 0.02), proj_poly(self._THENAR_PILLOW_3D))

        # Outer palm contour lines for crisp anatomical definition
        for contour in (
            self._PALM_LEFT_CONTOUR_3D,
            self._THUMB_WEB_CONTOUR_3D,
            self._PALM_RIGHT_CONTOUR_3D,
        ):
            c_pts = proj_poly(contour)
            for i in range(len(c_pts) - 1):
                pygame.draw.aaline(screen, self._SKIN_EDGE, c_pts[i], c_pts[i + 1])

        # ─── 3. Subtle Dorsal Extensor Tendons & MCP Knuckle Mounds ───────
        tendon_hi = self._shade_skin(hand_lit, 0.11)
        tendon_sh = self._shade_skin(hand_lit, -0.03)

        for tendon in self._TENDONS_3D:
            t_pts = proj_poly(tendon)
            t_sh_pts = [proj(px + 0.55, py, pz + 0.15) for px, py, pz in tendon]
            for i in range(len(t_pts) - 1):
                pygame.draw.aaline(screen, tendon_sh, t_sh_pts[i], t_sh_pts[i + 1])
                pygame.draw.aaline(screen, tendon_hi, t_pts[i], t_pts[i + 1])

        # MCP knuckle mounds & soft inter-knuckle contours
        for kx, ky, kz, kr in self._MCP_KNUCKLES_3D:
            kpx, kpy, kdepth, _ = proj_depth(kx, ky, kz)
            rad_px = max(2, int(round(kr * sc * kdepth)))
            self._aa_circle(screen, self._shade_skin(hand_lit, 0.08), kpx, kpy, rad_px)
            c_left = proj(kx - kr * 0.48, ky - 1.0, kz + 0.1)
            c_mid = proj(kx, ky - 1.5, kz)
            c_right = proj(kx + kr * 0.48, ky - 1.0, kz + 0.1)
            pygame.draw.aaline(screen, self._CREASE_COLOR, c_left, c_mid)
            pygame.draw.aaline(screen, self._CREASE_COLOR, c_mid, c_right)

        # ─── 4. Articulated Capsule Fingers & 3D Projected Fingernails ────
        for fspec in self._FINGER_SPECS:
            is_thumb = fspec["is_thumb"]
            splay_dir = fspec["splay_dir"]
            raw_joints = fspec["joints"]

            # Apply dynamic splay & flex to joint 3D coordinates
            joints_3d: List[Tuple[float, float, float, float]] = []
            for j_idx, (jx, jy, jz, jr) in enumerate(raw_joints):
                if j_idx == 0:
                    joints_3d.append((jx, jy, jz, jr))
                else:
                    seg_frac = j_idx / (len(raw_joints) - 1)
                    dx = splay_dir * self.finger_splay * (2.0 * seg_frac)
                    dz = self.finger_flex * (3.0 * (seg_frac ** 1.4))
                    dy = (
                        abs(self.finger_flex) * (1.1 * seg_frac)
                        if self.finger_flex > 0
                        else -self.finger_flex * (0.9 * seg_frac)
                    )
                    joints_3d.append((jx + dx, jy + dy, jz + dz, jr))

            # Draw each phalanx segment as a 3D-lit tapered capsule with soft highlight
            for seg_i in range(len(joints_3d) - 1):
                x0, y0, z0, r0 = joints_3d[seg_i]
                x1, y1, z1, r1 = joints_3d[seg_i + 1]

                dx = x1 - x0
                dy = y1 - y0
                seg_len = math.hypot(dx, dy) or 1.0
                px_n = -dy / seg_len
                py_n = dx / seg_len

                seg_quad_3d = (
                    (x0 - px_n * r0, y0 - py_n * r0, z0 + 0.2),
                    (x0 + px_n * r0, y0 + py_n * r0, z0 + 0.2),
                    (x1 + px_n * r1, y1 + py_n * r1, z1 + 0.15),
                    (x1 - px_n * r1, y1 - py_n * r1, z1 + 0.15),
                )
                seg_bias = 0.02 * seg_i + (0.02 if not is_thumb else -0.01)
                seg_color = self._shade_skin(hand_lit, seg_bias)

                # Proximal joint capsule sphere
                jx0, jy0, jd0, _ = proj_depth(x0, y0, z0)
                self._aa_circle(screen, seg_color, jx0, jy0, max(2, int(round(r0 * sc * jd0))))

                # Tapered segment body
                quad_2d = proj_poly(seg_quad_3d)
                self._aa_polygon(screen, seg_color, quad_2d)

                # Central cylindrical ridge highlight along phalanx
                hi_quad_3d = (
                    (x0 - px_n * r0 * 0.45, y0 - py_n * r0 * 0.45, z0 - 0.25),
                    (x0 + px_n * r0 * 0.45, y0 + py_n * r0 * 0.45, z0 - 0.25),
                    (x1 + px_n * r1 * 0.45, y1 + py_n * r1 * 0.45, z1 - 0.25),
                    (x1 - px_n * r1 * 0.45, y1 - py_n * r1 * 0.45, z1 - 0.25),
                )
                self._aa_polygon(screen, self._shade_skin(hand_lit, seg_bias + 0.06), proj_poly(hi_quad_3d))

                # Antialiased lateral contour edges
                pygame.draw.aaline(screen, self._SKIN_EDGE, quad_2d[0], quad_2d[3])
                pygame.draw.aaline(screen, self._SKIN_EDGE, quad_2d[1], quad_2d[2])

                # Soft double curved skin creases at PIP / DIP joints
                if seg_i > 0:
                    c1_l = proj(x0 - px_n * r0 * 0.62, y0 - py_n * r0 * 0.62 - 0.35, z0 - 0.2)
                    c1_m = proj(x0, y0 - 0.65, z0 - 0.35)
                    c1_r = proj(x0 + px_n * r0 * 0.62, y0 + py_n * r0 * 0.62 - 0.35, z0 - 0.2)
                    c2_l = proj(x0 - px_n * r0 * 0.50, y0 - py_n * r0 * 0.50 + 0.55, z0 - 0.2)
                    c2_m = proj(x0, y0 + 0.8, z0 - 0.35)
                    c2_r = proj(x0 + px_n * r0 * 0.50, y0 + py_n * r0 * 0.50 + 0.55, z0 - 0.2)
                    pygame.draw.aaline(screen, self._CREASE_COLOR, c1_l, c1_m)
                    pygame.draw.aaline(screen, self._CREASE_COLOR, c1_m, c1_r)
                    pygame.draw.aaline(screen, self._SKIN_SHADE, c2_l, c2_m)
                    pygame.draw.aaline(screen, self._SKIN_SHADE, c2_m, c2_r)

            # Rounded fingertip dome
            tx, ty, tz, tr = joints_3d[-1]
            bx, by, bz, _ = joints_3d[-2]
            tpx, tpy, tdepth, _ = proj_depth(tx, ty, tz)
            tip_color = self._shade_skin(hand_lit, 0.07)
            self._aa_circle(screen, tip_color, tpx, tpy, max(2, int(round(tr * sc * tdepth))))

            # 3D Projected Fingernail (rotates and foreshortens naturally with the distal phalanx)
            fdx = tx - bx
            fdy = ty - by
            fdz = tz - bz
            flen = math.hypot(fdx, fdy) or 1.0
            ux, uy, uz = fdx / flen, fdy / flen, fdz / flen
            px_n, py_n = -uy, ux

            nail_len = fspec["nail_length"]
            nail_w = fspec["nail_width"]
            ncx = tx - ux * (nail_len * 0.36)
            ncy = ty - uy * (nail_len * 0.36)
            ncz = tz - uz * (nail_len * 0.36) - 0.55

            hl = nail_len * 0.5
            hw = nail_w
            nail_poly_3d = (
                (ncx - ux * hl * 0.75 - px_n * hw * 0.72, ncy - uy * hl * 0.75 - py_n * hw * 0.72, ncz),
                (ncx - ux * hl - px_n * hw * 0.35, ncy - uy * hl - py_n * hw * 0.35, ncz),
                (ncx - ux * hl + px_n * hw * 0.35, ncy - uy * hl + py_n * hw * 0.35, ncz),
                (ncx - ux * hl * 0.75 + px_n * hw * 0.72, ncy - uy * hl * 0.75 + py_n * hw * 0.72, ncz),
                (ncx + ux * hl * 0.65 + px_n * hw * 0.85, ncy + uy * hl * 0.65 + py_n * hw * 0.85, ncz - 0.1),
                (ncx + ux * hl + px_n * hw * 0.42, ncy + uy * hl + py_n * hw * 0.42, ncz - 0.15),
                (ncx + ux * hl - px_n * hw * 0.42, ncy + uy * hl - py_n * hw * 0.42, ncz - 0.15),
                (ncx + ux * hl * 0.65 - px_n * hw * 0.85, ncy + uy * hl * 0.65 - py_n * hw * 0.85, ncz - 0.1),
            )
            nail_col = self._mix_rgb(self._NAIL_EDGE, self._NAIL_BASE, 0.55 + 0.45 * hand_lit)
            nail_pts_2d = proj_poly(nail_poly_3d)
            self._aa_polygon(screen, nail_col, nail_pts_2d)

            # Pale crescent lunula at the proximal base of the fingernail
            lunula_poly_3d = (
                nail_poly_3d[0],
                nail_poly_3d[1],
                nail_poly_3d[2],
                nail_poly_3d[3],
                (ncx - ux * hl * 0.32 + px_n * hw * 0.45, ncy - uy * hl * 0.32 + py_n * hw * 0.45, ncz - 0.05),
                (ncx - ux * hl * 0.32 - px_n * hw * 0.45, ncy - uy * hl * 0.32 - py_n * hw * 0.45, ncz - 0.05),
            )
            self._aa_polygon(screen, self._NAIL_LUNULA, proj_poly(lunula_poly_3d))

            # Subtle cuticle & nail border outline
            for i in range(len(nail_pts_2d)):
                pygame.draw.aaline(
                    screen, self._NAIL_EDGE,
                    nail_pts_2d[i], nail_pts_2d[(i + 1) % len(nail_pts_2d)],
                )

        # ─── 5. Curved Wristband (3D-shaded facets + center rib) ──────────
        for b_facet, base_col in (
            (self._BAND_LEFT_3D, self._BAND_SIDE),
            (self._BAND_RIGHT_3D, self._BAND_SIDE),
            (self._BAND_CENTER_3D, self._BAND_MAIN),
        ):
            b_lit = self._poly_lighting(b_facet, roll_rad, pitch_rad)
            shaded_band = self._mix_rgb(self._BAND_EDGE, base_col, 0.45 + 0.55 * b_lit)
            b_pts = proj_poly(b_facet)
            self._aa_polygon(screen, shaded_band, b_pts)

        pts_rib = proj_poly(self._BAND_RIB_3D)
        self._aa_polygon(screen, self._BAND_ACCENT, pts_rib)

        for dx, dy, dz in self._BAND_DOTS_3D:
            dp = proj(dx, dy, dz)
            self._aa_circle(screen, self._BAND_ACCENT, dp[0], dp[1], 1)

        band_outline_3d = (
            self._BAND_LEFT_3D[0], self._BAND_CENTER_3D[0], self._BAND_CENTER_3D[1],
            self._BAND_RIGHT_3D[1], self._BAND_RIGHT_3D[2], self._BAND_CENTER_3D[2],
            self._BAND_CENTER_3D[3], self._BAND_LEFT_3D[3],
        )
        band_outline_2d = proj_poly(band_outline_3d)
        for i in range(len(band_outline_2d)):
            pygame.draw.aaline(
                screen, self._BAND_EDGE,
                band_outline_2d[i], band_outline_2d[(i + 1) % len(band_outline_2d)],
            )

        # ─── 6. 3D Extruded MetaMotion Sensor Pod ─────────────────────────
        b_c = self._SENSOR_BASE_CORNERS
        t_c = self._SENSOR_TOP_CORNERS
        side_walls = []
        for i in range(4):
            ni = (i + 1) % 4
            wall_3d = (b_c[i], b_c[ni], t_c[ni], t_c[i])
            avg_z = sum(self._rotate_3d(*pt, roll_rad, pitch_rad)[2] for pt in wall_3d) * 0.25
            side_walls.append((avg_z, wall_3d))

        side_walls.sort(key=lambda item: item[0], reverse=True)
        for _, wall_3d in side_walls:
            w_lit = self._poly_lighting(wall_3d, roll_rad, pitch_rad)
            w_col = self._mix_rgb((14, 15, 20), (54, 58, 74), w_lit)
            w_pts = proj_poly(wall_3d)
            self._aa_polygon(screen, w_col, w_pts)
            for j in range(4):
                pygame.draw.aaline(screen, (45, 48, 60), w_pts[j], w_pts[(j + 1) % 4])

        # Top surface of extruded sensor pod
        top_lit = self._poly_lighting(t_c, roll_rad, pitch_rad)
        top_col = self._mix_rgb(self._SENSOR_WALL, self._SENSOR_TOP, 0.4 + 0.6 * top_lit)
        pts_sensor_top = proj_poly(t_c)
        self._aa_polygon(screen, top_col, pts_sensor_top)
        for i in range(len(pts_sensor_top)):
            pygame.draw.aaline(
                screen, self._SENSOR_EDGE,
                pts_sensor_top[i], pts_sensor_top[(i + 1) % len(pts_sensor_top)],
            )

        # Recessed sensor face + subtle metallic sheen
        pts_face = proj_poly(self._SENSOR_FACE_3D)
        face_col = self._mix_rgb(self._SENSOR_TOP, self._SENSOR_FACE, 0.35 + 0.65 * top_lit)
        self._aa_polygon(screen, face_col, pts_face)
        for i in range(len(pts_face)):
            pygame.draw.aaline(
                screen, self._SENSOR_FACE_BORDER,
                pts_face[i], pts_face[(i + 1) % len(pts_face)],
            )

        # Subtle sensor icon chevron on the pod face
        ch_l = proj(-3.2, 32.7, -7.2)
        ch_m = proj(0.0, 30.1, -7.6)
        ch_r = proj(3.2, 32.7, -7.2)
        pygame.draw.aaline(screen, (85, 95, 120), ch_l, ch_m)
        pygame.draw.aaline(screen, (85, 95, 120), ch_m, ch_r)

        # ─── 7. Glowing MetaMotion LED (left / thumb-side edge of pod) ────
        led_x, led_y, led_depth, _ = proj_depth(-8.6, 31.5, -7.2)
        led_color = (100, 255, 120) if getattr(gs, "calibrated", True) else (255, 160, 40)
        pulse = (math.sin(time.time() * 6.0) + 1.0) * 0.5

        glow_r = max(3, int((6 + pulse * 3) * min(1.25, led_depth * (sc / 1.55))))
        glow_r = min(9, glow_r)
        lc = self._led_surf_half
        self._led_surf.fill((0, 0, 0, 0))
        self._aa_circle(self._led_surf, (*led_color[:3], 30), lc, lc, glow_r + 2)
        self._aa_circle(self._led_surf, (*led_color[:3], 75), lc, lc, glow_r - 1)
        self._aa_circle(self._led_surf, (*led_color[:3], 210), lc, lc, max(2, glow_r - 3))
        bright = tuple(min(255, c + 80) for c in led_color[:3])
        self._aa_circle(self._led_surf, (*bright, 255), lc, lc, 2)

        screen.blit(self._led_surf, (led_x - lc, led_y - lc))

        # ── 6. GESTURE BADGES & ANGLE READOUT ────────────────────────────────
        if self.gesture_timer > 0:
            self.gesture_timer -= dt
            badge_text = self.font_badge.render(self.active_gesture_text, True, self.active_gesture_color)
            bw, bh = badge_text.get_size()

            badge_bg = pygame.Surface((bw + 18, bh + 8), pygame.SRCALPHA)
            badge_bg.fill((15, 20, 32, 235))
            pygame.draw.rect(
                badge_bg, (*self.active_gesture_color, 220),
                (0, 0, bw + 18, bh + 8), 1, border_radius=6,
            )

            bx = center_x - (bw + 18) // 2
            by = center_y - hud_r - bh - 8
            screen.blit(badge_bg, (bx, by))
            screen.blit(badge_text, (bx + 9, by + 4))
        else:
            deg_val = int(self.current_roll)
            deg_str = f"{deg_val:+d}°" if abs(deg_val) > 1 else "READY"
            val_surf = self.font_val.render(deg_str, True, (140, 180, 225))
            screen.blit(val_surf, val_surf.get_rect(center=(center_x, center_y + hud_r - 14)))
