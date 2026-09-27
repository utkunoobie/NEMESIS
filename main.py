# ─────────────────────────────────────────────────────────────────────────
#  NEMESIS // AssaultCube Toolkit (Enhanced Fast Fire)
#  - ENTITIES list updates in place (no more flicker)
#  - Minimap math re-derived from scratch (correct rotation)
#  - NEMESIS badge top-right of screen
#  - Stealth Mode embeds minimap in main window
# ─────────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import messagebox
import time
import ctypes
import math
import os
import struct
import tempfile
import traceback

try:
    import pymem
    import pymem.process
except ImportError:
    pymem = None


# ───────────────────────────── palette ─────────────────────────────
BG       = "#08090d"
SURFACE  = "#10131a"
SURFACE2 = "#151923"
SURFACE3 = "#1b202c"
BORDER   = "#282e3b"
TEXT     = "#eef2ff"
MUTED    = "#8d96aa"
FAINT    = "#515a6d"
ACCENT   = "#9b7bff"
ACCENT2  = "#6c5ce7"
SUCCESS  = "#5ee6a8"
ERROR    = "#ff6577"
WARNING  = "#ffc66d"


# ───────────────────────────── helpers ─────────────────────────────
def interpolate_color(hex1, hex2, factor):
    factor = max(0.0, min(1.0, factor))
    r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
    r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def create_nemesis_icon(path, size=64):
    cx = cy = size / 2.0
    r = size * 0.44
    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            dx = abs(x - cx + 0.5)
            dy = abs(y - cy + 0.5)
            if dx + dy <= r:
                t = 1.0 - (dx + dy) / r
                rr = int(0x6c + (0xc4 - 0x6c) * t)
                gg = int(0x5c + (0xb5 - 0x5c) * t)
                bb = int(0xe7 + (0xff - 0xe7) * t)
                row.append((bb, gg, rr, 255))
            else:
                row.append((0, 0, 0, 0))
        pixels.append(row)

    pixel_data = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            b, g, r_, a = pixels[y][x]
            pixel_data += bytes([b, g, r_, a])

    mask_row = ((size + 31) // 32) * 4
    mask = b'\x00' * (mask_row * size)

    bih = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                      len(pixel_data) + len(mask), 0, 0, 0, 0)
    image_data = bih + bytes(pixel_data) + mask
    image_size = len(image_data)

    icondir = struct.pack('<HHH', 0, 1, 1)
    icondirentry = struct.pack('<BBBBHHII',
        size if size < 256 else 0,
        size if size < 256 else 0,
        0, 0, 1, 32, image_size, 22)

    with open(path, 'wb') as f:
        f.write(icondir + icondirentry + image_data)


# ─────────────────────── minimap projection (correct math) ───────────────────────
MINIMAP_YAW_SIGN = 1        # try 1 or -1
MINIMAP_YAW_OFFSET = 0      # try 0, 90, -90, 180


def _project_entity(dx, dy, yaw_deg, scale):
    alpha = math.radians(MINIMAP_YAW_SIGN * yaw_deg + MINIMAP_YAW_OFFSET)
    sin_a = math.sin(alpha)
    cos_a = math.cos(alpha)
    sx = (dx * sin_a - dy * cos_a) * scale
    sy = -(dx * cos_a + dy * sin_a) * scale
    return sx, sy


# ─────────────────────────── memory bridge ───────────────────────────
class GameMemory:
    def __init__(self):
        self.pm = None
        self.client = None
        self.base = None
        self.local_player_ptr = None
        self.entity_list_ptr = None
        self.player_count_ptr = None
        self.fov_ptr = None

    def attach(self):
        if pymem is None:
            return False
        try:
            self.pm = pymem.Pymem("ac_client.exe")
            self.client = pymem.process.module_from_name(
                self.pm.process_handle, "ac_client.exe")
            self.base = self.client.lpBaseOfDll
            self.local_player_ptr = self.base + 0x0017E0A8
            self.entity_list_ptr = self.base + 0x18AC04
            self.player_count_ptr = self.base + 0x18AC0C
            self.fov_ptr = self.base + 0x18A7CC
            return True
        except Exception as e:
            print(f"Attach error: {e}")
            return False

    def get_player(self):
        try:
            return self.pm.read_int(self.local_player_ptr)
        except Exception:
            return None

    def get_player_count(self):
        try:
            return self.pm.read_int(self.player_count_ptr)
        except Exception:
            return 0

    def read_health(self):
        p = self.get_player()
        if p:
            try:
                return self.pm.read_int(p + 0xEC)
            except Exception:
                return 0
        return 0

    def read_armor(self):
        p = self.get_player()
        if p:
            try:
                return self.pm.read_int(p + 0xF0)
            except Exception:
                return 0
        return 0

    def write_health(self, value):
        p = self.get_player()
        if p:
            self.pm.write_int(p + 0xEC, value)
            return True
        return False

    def write_armor(self, value):
        p = self.get_player()
        if p:
            self.pm.write_int(p + 0xF0, value)
            return True
        return False

    def write_grenade(self, value):
        p = self.get_player()
        if p:
            self.pm.write_int(p + 0x144, value)
            return True
        return False

    def set_all_ammo(self, value):
        p = self.get_player()
        if p:
            for off in [0x140, 0x138, 0x13C, 0x134, 0x12C]:
                self.pm.write_int(p + off, value)
            return True
        return False

    def set_fast_fire(self, enable=True):
        p = self.get_player()
        if not p:
            return False
        if enable:
            for off in [0x160, 0x164, 0x158, 0x170, 0x174, 0x178, 0x180]:
                try:
                    self.pm.write_int(p + off, 0)
                except Exception:
                    pass
        return True

    def get_player_pos(self, player_ptr):
        try:
            return (self.pm.read_float(player_ptr + 0x2C),
                    self.pm.read_float(player_ptr + 0x30))
        except Exception:
            return None

    def read_pos_xyz(self):
        p = self.get_player()
        if p:
            try:
                x = self.pm.read_float(p + 0x2C)
                y = self.pm.read_float(p + 0x30)
                z = self.pm.read_float(p + 0x28)
                return (x, y, z)
            except Exception:
                return None
        return None

    def write_pos(self, x=None, y=None, z=None):
        p = self.get_player()
        if not p:
            return False
        try:
            if x is not None:
                self.pm.write_float(p + 0x2C, float(x))
            if y is not None:
                self.pm.write_float(p + 0x30, float(y))
            if z is not None:
                self.pm.write_float(p + 0x28, float(z))
            return True
        except Exception:
            return False

    def get_player_yaw(self):
        p = self.get_player()
        if p:
            try:
                return self.pm.read_float(p + 0x34) % 360.0
            except Exception:
                return 0.0
        return 0.0

    def get_player_team(self, player_ptr):
        try:
            return self.pm.read_int(player_ptr + 0x30C)
        except Exception:
            return 0

    def get_entities(self):
        entities = []
        try:
            count = self.pm.read_int(self.player_count_ptr)
            ent_list = self.pm.read_int(self.entity_list_ptr)
            if not ent_list or count <= 1:
                return entities
            local = self.get_player()
            for i in range(1, count):
                ent_ptr = self.pm.read_int(ent_list + (i * 4))
                if ent_ptr and ent_ptr != local:
                    hp = self.pm.read_int(ent_ptr + 0xEC)
                    if hp > 0:
                        pos = self.get_player_pos(ent_ptr)
                        team = self.get_player_team(ent_ptr)
                        if pos:
                            entities.append({
                                "index": i,
                                "ptr": ent_ptr,
                                "pos": pos,
                                "hp": hp,
                                "team": team,
                            })
        except Exception:
            pass
        return entities

    def get_entities_extended(self):
        entities = []
        try:
            count = self.pm.read_int(self.player_count_ptr)
            ent_list = self.pm.read_int(self.entity_list_ptr)
            local = self.get_player()
            local_xyz = self.read_pos_xyz()

            if not ent_list or count <= 1:
                return entities

            for i in range(1, count):
                ent_ptr = self.pm.read_int(ent_list + (i * 4))
                if not ent_ptr or ent_ptr == local:
                    continue
                hp = self.pm.read_int(ent_ptr + 0xEC)
                if hp <= 0:
                    continue
                try:
                    ex = self.pm.read_float(ent_ptr + 0x2C)
                    ey = self.pm.read_float(ent_ptr + 0x30)
                    ez = self.pm.read_float(ent_ptr + 0x28)
                except Exception:
                    continue
                team = self.get_player_team(ent_ptr)

                dist = None
                if local_xyz:
                    lx, ly, lz = local_xyz
                    dist = math.sqrt((ex - lx) ** 2 + (ey - ly) ** 2 +
                                     (ez - lz) ** 2)

                entities.append({
                    "index": i,
                    "ptr": ent_ptr,
                    "pos": (ex, ey),
                    "xyz": (ex, ey, ez),
                    "hp": hp,
                    "team": team,
                    "dist": dist,
                })
        except Exception:
            pass

        entities.sort(key=lambda e: e["index"])
        return entities


# ─────────────────────────── minimap drawing ───────────────────────────
def draw_minimap(canvas, size, scale, local_pos, local_team, entities, yaw):
    c = canvas
    c.delete("all")
    cx = cy = size / 2
    radius = (size / 2) - 5

    c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                  fill="#0d1117", outline=BORDER, width=2)
    c.create_oval(cx - radius + 6, cy - radius + 6,
                  cx + radius - 6, cy + radius - 6,
                  outline="#1a2030", width=1)
    c.create_line(cx, cy - radius + 8, cx, cy + radius - 8, fill="#1a2030")
    c.create_line(cx - radius + 8, cy, cx + radius - 8, cy, fill="#1a2030")

    if not local_pos:
        c.create_text(cx, cy, text="NO SIGNAL", fill=FAINT,
                      font=("Segoe UI Semibold", 9))
        return

    lx, ly = local_pos
    for ent in entities:
        ex, ey = ent["pos"]
        dx = ex - lx
        dy = ey - ly
        sx, sy = _project_entity(dx, dy, yaw, scale)
        px = cx + sx
        py = cy + sy

        dist = math.hypot(px - cx, py - cy)
        if dist > radius - 8:
            a = math.atan2(py - cy, px - cx)
            px = cx + (radius - 8) * math.cos(a)
            py = cy + (radius - 8) * math.sin(a)

        color = "#4ba3ff" if ent["team"] == local_team else "#ff4b4b"
        c.create_oval(px - 4, py - 4, px + 4, py + 4,
                      fill=color, outline="#ffffff", width=1)

    c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                  fill=SUCCESS, outline="#ffffff", width=1)
    c.create_line(cx, cy, cx, cy - 14, fill=SUCCESS, width=2)


class MinimapOverlay:
    def __init__(self):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.size = 190
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.size}x{self.size}+22+{sh - self.size - 110}")
        self.bg_color = "#000001"
        self.root.configure(bg=self.bg_color)
        self.root.wm_attributes("-transparentcolor", self.bg_color)
        self.canvas = tk.Canvas(self.root, bg=self.bg_color,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.scale = 1.85
        self._make_click_through()

    def _make_click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                return
            GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception as e:
            print(f"Minimap click-through error: {e}")

    def update_map(self, local_pos, local_team, entities, yaw=0.0):
        draw_minimap(self.canvas, self.size, self.scale,
                     local_pos, local_team, entities, yaw)

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


class EmbeddedMinimap:
    def __init__(self, parent, size=220):
        self.size = size
        self.scale = 1.85
        self.frame = tk.Frame(parent, bg=BORDER)
        self.canvas = tk.Canvas(self.frame, width=size, height=size,
                                bg="#0d1117", highlightthickness=0, bd=0)
        self.canvas.pack(padx=1, pady=1)

    def update_map(self, local_pos, local_team, entities, yaw=0.0):
        draw_minimap(self.canvas, self.size, self.scale,
                     local_pos, local_team, entities, yaw)


# ─────────────────────────── badge overlay ───────────────────────────
class BadgeOverlay:
    WIDTH  = 128
    HEIGHT = 30
    BG_COLOR = "#000001"

    def __init__(self):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        sw = self.root.winfo_screenwidth()
        x = sw - self.WIDTH - 18
        y = 18
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.root.configure(bg=self.BG_COLOR)
        self.root.wm_attributes("-transparentcolor", self.BG_COLOR)
        self.canvas = tk.Canvas(self.root, bg=self.BG_COLOR,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._make_click_through()
        self._draw()

    def _make_click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                return
            GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception as e:
            print(f"Badge click-through error: {e}")

    def _draw(self):
        c = self.canvas
        c.delete("all")
        r = self.HEIGHT // 2
        c.create_oval(0, 0, self.HEIGHT, self.HEIGHT,
                      fill="#0a0c12", outline=BORDER, width=1)
        c.create_oval(self.WIDTH - self.HEIGHT, 0, self.WIDTH, self.HEIGHT,
                      fill="#0a0c12", outline=BORDER, width=1)
        c.create_rectangle(r, 0, self.WIDTH - r, self.HEIGHT,
                           fill="#0a0c12", outline="")
        c.create_line(r, 0, self.WIDTH - r, 0, fill=BORDER)
        c.create_line(r, self.HEIGHT - 1, self.WIDTH - r, self.HEIGHT - 1,
                      fill=BORDER)
        c.create_line(0, r, 0, self.HEIGHT - r, fill=BORDER)
        c.create_line(self.WIDTH - 1, r, self.WIDTH - 1, self.HEIGHT - r,
                      fill=BORDER)
        c.create_text(20, self.HEIGHT / 2, text="◆", fill=ACCENT,
                      font=("Segoe UI", 14, "bold"))
        c.create_text(34, self.HEIGHT / 2 + 1, text="NEMESIS", anchor="w",
                      fill=TEXT, font=("Segoe UI Semibold", 9))
        c.create_text(self.WIDTH - 14, self.HEIGHT / 2, text="●",
                      fill=SUCCESS, font=("Segoe UI", 7))

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ─────────────────────────── HUD overlay ───────────────────────────
class HUDOverlay:
    WIDTH    = 272
    HEIGHT   = 400
    OFFSET_X = 18
    OFFSET_Y = 130
    BG_COLOR = "#000001"

    def __init__(self):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(
            f"{self.WIDTH}x{self.HEIGHT}+{self.OFFSET_X}+{self.OFFSET_Y}")
        self.root.configure(bg=self.BG_COLOR)
        self.root.wm_attributes("-transparentcolor", self.BG_COLOR)
        self.canvas = tk.Canvas(self.root, bg=self.BG_COLOR,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.active_features = []
        self._make_click_through()
        self.redraw()

    def _make_click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                return
            GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception as e:
            print(f"HUD click-through error: {e}")

    def add_feature(self, name):
        if name not in self.active_features:
            self.active_features.append(name)
            self.redraw()

    def remove_feature(self, name):
        if name in self.active_features:
            self.active_features.remove(name)
            self.redraw()

    @staticmethod
    def _rounded_rect(canvas, x1, y1, x2, y2, r,
                      fill="", outline="", width=1):
        canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r,
                          start=90, extent=90, fill=fill, outline=fill)
        canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r,
                          start=0, extent=90, fill=fill, outline=fill)
        canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2,
                          start=180, extent=90, fill=fill, outline=fill)
        canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2,
                          start=270, extent=90, fill=fill, outline=fill)
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2,
                                fill=fill, outline=fill)
        canvas.create_rectangle(x1, y1 + r, x2, y2 - r,
                                fill=fill, outline=fill)
        if outline:
            canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
            canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
            canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width)
            canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width)

    def redraw(self):
        c = self.canvas
        c.delete("all")
        c.create_text(12, 18, text="ACTIVE MODULES", anchor="w",
                      fill=MUTED, font=("Segoe UI Semibold", 8))
        c.create_line(12, 32, self.WIDTH - 12, 32, fill=BORDER)

        if not self.active_features:
            c.create_text(self.WIDTH / 2, 60, text="no modules enabled",
                          fill=FAINT, font=("Segoe UI", 8))
            return

        y = 42
        for feat in self.active_features:
            self._rounded_rect(c, 8, y, self.WIDTH - 8, y + 30, 7,
                               fill="#0a0c12", outline=BORDER, width=1)
            c.create_rectangle(8, y + 6, 12, y + 24, fill=ACCENT, outline="")
            c.create_text(22, y + 15, text=feat.upper(), anchor="w",
                          fill=TEXT, font=("Segoe UI Semibold", 9))
            c.create_text(self.WIDTH - 22, y + 15, text="ON", anchor="e",
                          fill=SUCCESS, font=("Segoe UI Semibold", 8))
            y += 36

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ─────────────────────────── widgets ───────────────────────────
class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, bg, hover, fg="#ffffff",
                 width=110, height=38, radius=12, **kwargs):
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else SURFACE
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kwargs)
        self.command = command
        self.normal = bg
        self.hover = hover
        self.fg = fg
        self.radius = radius
        self.w = width
        self.h = height
        self.text = text
        self._draw(self.normal, self.fg)
        self.bind("<Enter>", lambda e: self._draw(self.hover, self.fg))
        self.bind("<Leave>", lambda e: self._draw(self.normal, self.fg))
        self.bind("<Button-1>", lambda e: self.command())

    def set_colors(self, normal, hover, fg):
        self.normal, self.hover, self.fg = normal, hover, fg
        self._draw(self.normal, self.fg)

    def _draw(self, color, fg_color=None):
        if fg_color is None:
            fg_color = self.fg
        self.delete("all")
        r = self.radius
        self.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                        fill=color, outline=color)
        self.create_arc(self.w - 2 * r, 0, self.w, 2 * r, start=0, extent=90,
                        fill=color, outline=color)
        self.create_arc(0, self.h - 2 * r, 2 * r, self.h, start=180, extent=90,
                        fill=color, outline=color)
        self.create_arc(self.w - 2 * r, self.h - 2 * r, self.w, self.h,
                        start=270, extent=90, fill=color, outline=color)
        self.create_rectangle(r, 0, self.w - r, self.h,
                              fill=color, outline=color)
        self.create_rectangle(0, r, self.w, self.h - r,
                              fill=color, outline=color)
        self.create_text(self.w / 2, self.h / 2, text=self.text,
                         fill=fg_color, font=("Segoe UI Semibold", 9))


class RoundedTab(tk.Canvas):
    def __init__(self, parent, text, command, width=80, height=36, radius=11):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text = text
        self.command = command
        self.w, self.h, self.r = width, height, radius
        self.active = False
        self.hovering = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda e: self.command())
        self.redraw()

    def _on_enter(self, _):
        self.hovering = True
        self.redraw()

    def _on_leave(self, _):
        self.hovering = False
        self.redraw()

    def set_active(self, state):
        self.active = state
        self.redraw()

    def redraw(self):
        self.delete("all")
        if self.active:
            fill, fg = ACCENT2, "#ffffff"
        elif self.hovering:
            fill, fg = SURFACE3, TEXT
        else:
            fill, fg = SURFACE2, MUTED

        r, w, h = self.r, self.w, self.h
        self.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                        fill=fill, outline=fill)
        self.create_arc(w - 2 * r, 0, w, 2 * r, start=0, extent=90,
                        fill=fill, outline=fill)
        self.create_arc(0, h - 2 * r, 2 * r, h, start=180, extent=90,
                        fill=fill, outline=fill)
        self.create_arc(w - 2 * r, h - 2 * r, w, h, start=270, extent=90,
                        fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h - r, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg,
                         font=("Segoe UI Semibold", 8))


# ─────────────────────── entity row (updates in place) ───────────────────────
class EntityRow:
    def __init__(self, parent, ent, tp_callback):
        self.ent = ent
        self.tp_callback = tp_callback

        self.frame = tk.Frame(parent, bg=SURFACE2,
                              highlightthickness=1, highlightbackground=BORDER)
        self.frame.pack(fill="x", padx=6, pady=3)

        left = tk.Frame(self.frame, bg=SURFACE2)
        left.pack(side="left", fill="both", expand=True,
                  padx=(10, 6), pady=8)

        top = tk.Frame(left, bg=SURFACE2)
        top.pack(fill="x")
        self.lbl_name = tk.Label(top, text=f"PLAYER #{ent['index']}",
                                 font=("Segoe UI Semibold", 9),
                                 bg=SURFACE2, fg=TEXT)
        self.lbl_name.pack(side="left")
        self.lbl_hp = tk.Label(top, text=f"HP {ent['hp']}",
                               font=("Consolas", 9, "bold"),
                               bg=SURFACE2, fg=ERROR)
        self.lbl_hp.pack(side="left", padx=10)
        self.lbl_team = tk.Label(top, text=f"T{ent['team']}",
                                 font=("Consolas", 9, "bold"),
                                 bg=SURFACE2, fg=SUCCESS)
        self.lbl_team.pack(side="left")

        dist_text = f"{ent['dist']:.1f}m" if ent.get("dist") is not None else "--"
        self.lbl_dist = tk.Label(top, text=dist_text,
                                 font=("Consolas", 9),
                                 bg=SURFACE2, fg=ACCENT)
        self.lbl_dist.pack(side="right")

        bottom = tk.Frame(left, bg=SURFACE2)
        bottom.pack(fill="x", pady=(2, 0))
        ex, ey, ez = ent["xyz"]
        self.lbl_xyz = tk.Label(bottom,
                                text=f"X {ex:.1f}   Y {ey:.1f}   Z {ez:.1f}",
                                font=("Consolas", 8),
                                bg=SURFACE2, fg=MUTED)
        self.lbl_xyz.pack(side="left")

        RoundedButton(self.frame, "TP",
                      lambda: self.tp_callback(self.ent),
                      ACCENT2, ACCENT, fg="#ffffff",
                      width=46, height=30, radius=9).pack(
                          side="right", padx=8, pady=8)

    def update(self, ent):
        self.ent = ent
        self.lbl_hp.config(text=f"HP {ent['hp']}")
        self.lbl_team.config(text=f"T{ent['team']}")
        if ent.get("dist") is not None:
            self.lbl_dist.config(text=f"{ent['dist']:.1f}m")
        else:
            self.lbl_dist.config(text="--")
        ex, ey, ez = ent["xyz"]
        self.lbl_xyz.config(text=f"X {ex:.1f}   Y {ey:.1f}   Z {ez:.1f}")

    def destroy(self):
        try:
            self.frame.destroy()
        except Exception:
            pass


# ─────────────────────────── main app ───────────────────────────
class NemesisApp:
    W, H = 480, 860

    def __init__(self, root):
        self.root = root
        self._intro_alive = True
        self.gm = None
        self.hud = None
        self.minimap = None
        self.badge = None
        self.embedded_map = None
        self._drag_x = 0
        self._drag_y = 0
        self.saved_health = 100
        self.saved_armor = 100
        self.toggle_widgets = {}
        self.tab_frames = {}
        self.tab_buttons = {}
        self.current_tab = "STATS"
        self._entity_rows = []
        self._ent_tick = 0

        try:
            self._init_window()
            self.show_intro()
        except Exception as e:
            traceback.print_exc()
            try:
                messagebox.showerror("NEMESIS startup failed", str(e))
            except Exception:
                pass

    def _init_window(self):
        r = self.root
        r.title("NEMESIS // AssaultCube")
        r.configure(bg=BG)
        r.overrideredirect(True)
        r.protocol("WM_DELETE_WINDOW", self.on_close)

        sw = r.winfo_screenwidth()
        sh = r.winfo_screenheight()
        x = max(0, (sw - self.W) // 2)
        y = max(0, (sh - self.H) // 2)
        r.geometry(f"{self.W}x{self.H}+{x}+{y}")
        r.update_idletasks()

        try:
            path = os.path.join(tempfile.gettempdir(), "nemesis_ac_icon.ico")
            create_nemesis_icon(path, 64)
            r.iconbitmap(path)
        except Exception as e:
            print(f"Icon error: {e}")

        try:
            hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
            if hwnd:
                CreateRoundRectRgn = ctypes.windll.gdi32.CreateRoundRectRgn
                CreateRoundRectRgn.restype = ctypes.c_void_p
                CreateRoundRectRgn.argtypes = [ctypes.c_int, ctypes.c_int,
                                               ctypes.c_int, ctypes.c_int,
                                               ctypes.c_int, ctypes.c_int]
                SetWindowRgn = ctypes.windll.user32.SetWindowRgn
                SetWindowRgn.restype = ctypes.c_int
                SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_bool]
                rgn = CreateRoundRectRgn(0, 0, self.W + 1, self.H + 1, 28, 28)
                if rgn:
                    SetWindowRgn(hwnd, rgn, True)
        except Exception as e:
            print(f"Rounding error: {e}")

        try:
            hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
            if hwnd:
                pref = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

        try:
            self._show_in_taskbar()
        except Exception as e:
            print(f"Taskbar error: {e}")

        try:
            r.attributes("-topmost", True)
        except Exception:
            pass
        try:
            r.deiconify()
            r.lift()
        except Exception:
            pass

        self.shell = tk.Frame(r, bg=BG)
        self.shell.pack(fill="both", expand=True, padx=1, pady=1)

    def _show_in_taskbar(self):
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        if not hwnd:
            return
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style &= ~WS_EX_TOOLWINDOW
        style |= WS_EX_APPWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def make_titlebar(self, parent, title, subtitle):
        bar = tk.Frame(parent, bg=BG, height=62)
        bar.pack(fill="x", padx=18, pady=(14, 0))
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=BG)
        left.pack(side="left", fill="y")
        tk.Label(left, text="◆", font=("Segoe UI", 18, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left", padx=(0, 9))
        textbox = tk.Frame(left, bg=BG)
        textbox.pack(side="left", fill="y")
        tk.Label(textbox, text=title, font=("Segoe UI Semibold", 14),
                 bg=BG, fg=TEXT).pack(anchor="w", pady=(7, 0))
        tk.Label(textbox, text=subtitle, font=("Segoe UI", 8),
                 bg=BG, fg=MUTED).pack(anchor="w")

        close = tk.Label(bar, text="×", font=("Segoe UI", 18),
                         bg=BG, fg=MUTED, cursor="hand2")
        close.pack(side="right", padx=4)
        close.bind("<Enter>", lambda e: close.config(fg=ERROR))
        close.bind("<Leave>", lambda e: close.config(fg=MUTED))
        close.bind("<Button-1>", lambda e: self.on_close())

        mini = tk.Label(bar, text="—", font=("Segoe UI", 14, "bold"),
                        bg=BG, fg=MUTED, cursor="hand2")
        mini.pack(side="right", padx=4, pady=(0, 4))
        mini.bind("<Enter>", lambda e: mini.config(fg=ACCENT))
        mini.bind("<Leave>", lambda e: mini.config(fg=MUTED))
        mini.bind("<Button-1>", lambda e: self.minimize())

        for widget in (bar, left, textbox):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)
        return bar

    def minimize(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 6)
        except Exception as e:
            print(f"Minimize failed: {e}")

    def start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def do_drag(self, event):
        x = self.root.winfo_pointerx() - self._drag_x
        y = self.root.winfo_pointery() - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def show_intro(self):
        self.intro_frame = tk.Frame(self.shell, bg=BG)
        self.intro_frame.pack(fill="both", expand=True)

        self.lbl_logo = tk.Label(self.intro_frame, text="◆",
                                 font=("Segoe UI", 52, "bold"),
                                 bg=BG, fg=ACCENT)
        self.lbl_logo.place(relx=.5, rely=.39, anchor="center")
        self.lbl_title = tk.Label(self.intro_frame, text="NEMESIS",
                                  font=("Segoe UI Semibold", 30),
                                  bg=BG, fg=TEXT)
        self.lbl_title.place(relx=.5, rely=.52, anchor="center")
        self.lbl_sub = tk.Label(self.intro_frame, text="ASSAULTCUBE TOOLKIT",
                                font=("Segoe UI", 9), bg=BG, fg=MUTED)
        self.lbl_sub.place(relx=.5, rely=.59, anchor="center")

        self.root.after(1200, lambda: self.fade_out_intro_text(0))
        self.root.after(3500, self._force_connect_screen)

    def fade_out_intro_text(self, step):
        if not self._intro_alive:
            return
        total_steps = 20
        try:
            if step <= total_steps:
                f = step / total_steps
                self.lbl_logo.config(fg=interpolate_color(ACCENT, BG, f))
                self.lbl_title.config(fg=interpolate_color(TEXT, BG, f))
                self.lbl_sub.config(fg=interpolate_color(MUTED, BG, f))
                self.root.after(20, lambda: self.fade_out_intro_text(step + 1))
            else:
                self._intro_alive = False
                try:
                    self.intro_frame.destroy()
                except Exception:
                    pass
                self.build_connect_screen()
        except tk.TclError:
            pass

    def _force_connect_screen(self):
        if self._intro_alive:
            self._intro_alive = False
            try:
                self.intro_frame.destroy()
            except Exception:
                pass
            self.build_connect_screen()

    def build_connect_screen(self):
        if hasattr(self, "attach_frame") and self.attach_frame.winfo_exists():
            return
        self.attach_frame = tk.Frame(self.shell, bg=BG)
        self.attach_frame.pack(fill="both", expand=True)

        self.make_titlebar(self.attach_frame, "NEMESIS", "ASSAULTCUBE TOOLKIT")

        body = tk.Frame(self.attach_frame, bg=BG)
        body.pack(fill="both", expand=True, padx=28)

        hero_outer = tk.Frame(body, bg=BORDER)
        hero_outer.pack(fill="x", pady=(22, 12))
        hero = tk.Frame(hero_outer, bg=SURFACE)
        hero.pack(fill="both", expand=True, padx=1, pady=1)

        self.lbl_hero_t = tk.Label(hero, text="READY TO CONNECT",
                                   font=("Segoe UI Semibold", 18),
                                   bg=SURFACE, fg=SURFACE)
        self.lbl_hero_t.pack(anchor="w", padx=22, pady=(22, 3))
        self.lbl_hero_s = tk.Label(
            hero, text="Connect to the running AssaultCube client.",
            font=("Segoe UI", 9), bg=SURFACE, fg=SURFACE)
        self.lbl_hero_s.pack(anchor="w", padx=22, pady=(0, 20))

        self.btn_connect = RoundedButton(
            hero, "CONNECT", self.attach_to_game,
            SURFACE, SURFACE, fg=SURFACE, width=150, height=42, radius=12)
        self.btn_connect.pack(anchor="w", padx=22, pady=(0, 22))

        status = tk.Frame(body, bg=SURFACE2)
        status.pack(fill="x", pady=8)
        self.status_dot = tk.Label(status, text="●", font=("Segoe UI", 11),
                                   bg=SURFACE2, fg=SURFACE2)
        self.status_dot.pack(side="left", padx=(16, 7), pady=15)
        self.status_label = tk.Label(status, text="Waiting for game...",
                                     font=("Segoe UI", 9),
                                     bg=SURFACE2, fg=SURFACE2)
        self.status_label.pack(side="left")

        self.lbl_footer = tk.Label(body,
                                   text="WINDOWS 10 / 11  •  DARK UI  •  v3",
                                   font=("Segoe UI", 8), bg=BG, fg=BG)
        self.lbl_footer.pack(side="bottom", pady=18)

        if pymem is None:
            self.status_label.config(text="pymem module missing", fg=ERROR)
            self.status_dot.config(fg=ERROR)

        self.fade_in_connect_text(0)

    def fade_in_connect_text(self, step):
        if not hasattr(self, "lbl_hero_t"):
            return
        total_steps = 20
        try:
            if step <= total_steps:
                f = step / total_steps
                self.lbl_hero_t.config(fg=interpolate_color(SURFACE, TEXT, f))
                self.lbl_hero_s.config(fg=interpolate_color(SURFACE, MUTED, f))
                self.btn_connect.set_colors(
                    interpolate_color(SURFACE, ACCENT2, f),
                    interpolate_color(SURFACE, ACCENT, f),
                    interpolate_color(SURFACE, "#ffffff", f))
                self.status_dot.config(fg=interpolate_color(SURFACE2, WARNING, f))
                self.status_label.config(fg=interpolate_color(SURFACE2, MUTED, f))
                self.lbl_footer.config(fg=interpolate_color(BG, FAINT, f))
                self.root.after(20, lambda: self.fade_in_connect_text(step + 1))
        except tk.TclError:
            pass

    def attach_to_game(self):
        if pymem is None:
            messagebox.showerror("Missing module",
                                 "pymem is not installed.\n\npip install pymem")
            return
        self.status_label.config(text="SEARCHING...", fg=WARNING)
        self.status_dot.config(fg=WARNING)
        self.root.update()

        gm = GameMemory()
        if gm.attach():
            self.gm = gm
            self.status_label.config(text="CONNECTED", fg=SUCCESS)
            self.status_dot.config(fg=SUCCESS)
            self.root.after(350, self.show_hack_interface)
        else:
            self.status_label.config(text="GAME NOT FOUND", fg=ERROR)
            self.status_dot.config(fg=ERROR)
            messagebox.showerror("Connection failed",
                                 "AssaultCube was not found.")

    def show_hack_interface(self):
        try:
            self.attach_frame.destroy()
        except Exception:
            pass
        self.hud = HUDOverlay()
        self.minimap = MinimapOverlay()
        self.badge = BadgeOverlay()

        self.main_frame = tk.Frame(self.shell, bg=BG)
        self.main_frame.pack(fill="both", expand=True)
        self.make_titlebar(self.main_frame, "NEMESIS", "LIVE SESSION")

        session = tk.Frame(self.main_frame, bg=SURFACE2)
        session.pack(fill="x", padx=18, pady=(2, 10))
        tk.Label(session, text="●  CONNECTED",
                 font=("Segoe UI Semibold", 8),
                 bg=SURFACE2, fg=SUCCESS).pack(side="left", padx=13, pady=8)
        tk.Label(session, text="AC_CLIENT.EXE", font=("Consolas", 8),
                 bg=SURFACE2, fg=MUTED).pack(side="right", padx=13)

        tabbar = tk.Frame(self.main_frame, bg=BG)
        tabbar.pack(fill="x", padx=18, pady=(0, 10))
        for name in ("STATS", "PLAYER", "ENTITIES", "MODULES", "LOG"):
            btn = RoundedTab(tabbar, name,
                             lambda n=name: self.switch_tab(n),
                             width=80, height=36, radius=11)
            btn.pack(side="left", padx=2)
            self.tab_buttons[name] = btn

        self.content = tk.Frame(self.main_frame, bg=BG)
        self.content.pack(fill="both", expand=True, padx=18)

        for name in ("STATS", "PLAYER", "ENTITIES", "MODULES", "LOG"):
            self.tab_frames[name] = tk.Frame(self.content, bg=BG)

        self._build_stats_tab(self.tab_frames["STATS"])
        self._build_player_tab(self.tab_frames["PLAYER"])
        self._build_entities_tab(self.tab_frames["ENTITIES"])
        self._build_modules_tab(self.tab_frames["MODULES"])
        self._build_log_tab(self.tab_frames["LOG"])

        footer = tk.Frame(self.main_frame, bg=BG)
        footer.pack(fill="x", padx=18, pady=(2, 10))
        self.status_label = tk.Label(footer, text="●  READY",
                                     font=("Segoe UI Semibold", 8),
                                     bg=BG, fg=SUCCESS)
        self.status_label.pack(side="left")
        tk.Label(footer, text="NEMESIS // ONLINE",
                 font=("Consolas", 7), bg=BG, fg=FAINT).pack(side="right")

        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        self.switch_tab("STATS")
        self.set_toggle_state("minimap_var", True)
        self.log("Session initialized")
        self.update_loop()

    def _on_mousewheel(self, event):
        if self.current_tab != "ENTITIES":
            return
        try:
            self._ent_canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

    def switch_tab(self, name):
        self.current_tab = name
        for n, frame in self.tab_frames.items():
            if n == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for n, btn in self.tab_buttons.items():
            btn.set_active(n == name)
        if name == "ENTITIES":
            self.rebuild_entity_list()

    # ── STATS tab ──
    def _build_stats_tab(self, parent):
        card = self._card(parent)
        header = tk.Frame(card, bg=SURFACE)
        header.pack(fill="x", padx=15, pady=(10, 6))
        tk.Label(header, text="LIVE STATS",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(side="left")
        RoundedButton(header, "RESET STATS", self.reset_stats,
                      ERROR, "#e0485c", width=100, height=24,
                      radius=6).pack(side="right")

        row = tk.Frame(card, bg=SURFACE)
        row.pack(fill="x", padx=15, pady=(0, 12))

        hp_box = tk.Frame(row, bg=SURFACE2, highlightthickness=1,
                          highlightbackground=BORDER)
        hp_box.pack(side="left", fill="x", expand=True, padx=(0, 5))
        tk.Label(hp_box, text="HEALTH", font=("Segoe UI", 7),
                 bg=SURFACE2, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 0))
        self.lbl_live_hp = tk.Label(hp_box, text="100",
                                    font=("Consolas", 14, "bold"),
                                    bg=SURFACE2, fg=ERROR)
        self.lbl_live_hp.pack(anchor="w", padx=10, pady=(0, 8))

        ar_box = tk.Frame(row, bg=SURFACE2, highlightthickness=1,
                          highlightbackground=BORDER)
        ar_box.pack(side="right", fill="x", expand=True, padx=(5, 0))
        tk.Label(ar_box, text="ARMOR", font=("Segoe UI", 7),
                 bg=SURFACE2, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 0))
        self.lbl_live_armor = tk.Label(ar_box, text="100",
                                       font=("Consolas", 14, "bold"),
                                       bg=SURFACE2, fg=WARNING)
        self.lbl_live_armor.pack(anchor="w", padx=10, pady=(0, 8))

        pos_card = self._card(parent)
        pos_header = tk.Frame(pos_card, bg=SURFACE)
        pos_header.pack(fill="x", padx=15, pady=(10, 4))
        tk.Label(pos_header, text="POSITION",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(side="left")
        self.lbl_team = tk.Label(pos_header, text="TEAM  0",
                                 font=("Consolas", 10, "bold"),
                                 bg=SURFACE, fg=SUCCESS)
        self.lbl_team.pack(side="right")

        prow = tk.Frame(pos_card, bg=SURFACE)
        prow.pack(fill="x", padx=15, pady=(0, 14))
        self.lbl_pos_x = tk.Label(prow, text="X  0.0",
                                  font=("Consolas", 11, "bold"),
                                  bg=SURFACE, fg=ACCENT)
        self.lbl_pos_x.pack(side="left")
        self.lbl_pos_y = tk.Label(prow, text="Y  0.0",
                                  font=("Consolas", 11, "bold"),
                                  bg=SURFACE, fg=ACCENT)
        self.lbl_pos_y.pack(side="left", padx=14)
        self.lbl_pos_z = tk.Label(prow, text="Z  0.0",
                                  font=("Consolas", 11, "bold"),
                                  bg=SURFACE, fg=ACCENT)
        self.lbl_pos_z.pack(side="left")

        tp_card = self._card(parent)
        tk.Label(tp_card, text="TELEPORT",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=15, pady=(10, 6))

        xyz_row = tk.Frame(tp_card, bg=SURFACE)
        xyz_row.pack(fill="x", padx=15, pady=(0, 8))
        self.tp_x = self._axis_entry(xyz_row, "X", first=True)
        self.tp_y = self._axis_entry(xyz_row, "Y", first=False)
        self.tp_z = self._axis_entry(xyz_row, "Z", first=False)

        tp_btns = tk.Frame(tp_card, bg=SURFACE)
        tp_btns.pack(fill="x", padx=15, pady=(0, 14))
        RoundedButton(tp_btns, "GET CURRENT", self.tp_get_current,
                      SURFACE2, SURFACE3, fg=ACCENT,
                      width=120, height=32, radius=10).pack(
                          side="left", padx=(0, 6))
        RoundedButton(tp_btns, "TELEPORT", self.tp_apply,
                      ACCENT2, ACCENT, fg="#ffffff",
                      width=120, height=32, radius=10).pack(side="left")

        self._embedded_card = tk.Frame(parent, bg=BORDER)
        embed_inner = tk.Frame(self._embedded_card, bg=SURFACE)
        embed_inner.pack(padx=1, pady=1, fill="both", expand=True)
        tk.Label(embed_inner, text="MINIMAP",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=15, pady=(10, 6))
        self.embedded_map = EmbeddedMinimap(embed_inner, size=220)
        self.embedded_map.frame.pack(padx=15, pady=(0, 14), anchor="center")

    def _build_player_tab(self, parent):
        card = self._card(parent)
        tk.Label(card, text="PLAYER VALUES",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=15, pady=(10, 4))
        self.health_entry = self._entry_row(card, "HEALTH", self.apply_health)
        self.armor_entry = self._entry_row(card, "ARMOR", self.apply_armor)
        self.grenade_entry = self._entry_row(card, "GRENADE", self.apply_grenade)

        ammo_card = self._card(parent)
        tk.Label(ammo_card, text="QUICK AMMO",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=15, pady=(10, 6))
        arow = tk.Frame(ammo_card, bg=SURFACE)
        arow.pack(fill="x", padx=15, pady=(0, 14))
        for label, val in (("20", 20), ("100", 100), ("999", 999)):
            RoundedButton(arow, label, lambda v=val: self.apply_ammo(v),
                          SURFACE2, ACCENT2, fg=ACCENT,
                          width=92, height=36, radius=10).pack(
                              side="left", padx=(0, 8))

    def _axis_entry(self, parent, label, first=False):
        frame = tk.Frame(parent, bg=SURFACE)
        pad = (0, 5) if first else (5, 0)
        frame.pack(side="left", fill="x", expand=True, padx=pad)
        tk.Label(frame, text=label, font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w")
        entry = tk.Entry(frame, bg=SURFACE3, fg=TEXT,
                         insertbackground=ACCENT, selectbackground=ACCENT2,
                         relief="flat", bd=0, font=("Consolas", 9),
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT, justify="center")
        entry.pack(fill="x", ipady=4, pady=(2, 0))
        return entry

    def _entry_row(self, parent, label, command):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", padx=14, pady=3)
        tk.Label(row, text=label, width=12, anchor="w",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=TEXT).pack(side="left")
        entry = tk.Entry(row, width=10, bg=SURFACE3, fg=TEXT,
                         insertbackground=ACCENT, selectbackground=ACCENT2,
                         relief="flat", bd=0, font=("Consolas", 9),
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        entry.pack(side="left", padx=8, ipady=4)
        RoundedButton(row, "APPLY", command, ACCENT2, ACCENT,
                      width=74, height=28, radius=8).pack(side="right")
        return entry

    # ── ENTITIES tab ──
    def _build_entities_tab(self, parent):
        header = tk.Frame(parent, bg=SURFACE2)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="PLAYERS", font=("Segoe UI Semibold", 9),
                 bg=SURFACE2, fg=MUTED).pack(side="left", padx=13, pady=8)
        self.lbl_player_count = tk.Label(header, text="0",
                                         font=("Consolas", 11, "bold"),
                                         bg=SURFACE2, fg=ACCENT)
        self.lbl_player_count.pack(side="right", padx=13)
        tk.Label(header, text="COUNT", font=("Segoe UI Semibold", 8),
                 bg=SURFACE2, fg=MUTED).pack(side="right")

        outer = tk.Frame(parent, bg=SURFACE)
        outer.pack(fill="both", expand=True)

        self._ent_canvas = tk.Canvas(outer, bg=SURFACE, highlightthickness=0,
                                     bd=0)
        scrollbar = tk.Scrollbar(outer, orient="vertical",
                                 command=self._ent_canvas.yview)
        self._ent_inner = tk.Frame(self._ent_canvas, bg=SURFACE)

        self._ent_inner.bind(
            "<Configure>",
            lambda e: self._ent_canvas.configure(
                scrollregion=self._ent_canvas.bbox("all")))

        self._ent_window = self._ent_canvas.create_window(
            (0, 0), window=self._ent_inner, anchor="nw")

        self._ent_canvas.configure(yscrollcommand=scrollbar.set)
        self._ent_canvas.pack(side="left", fill="both", expand=True)
        # Beyaz çizgi/scroll çubuğu kaldırıldı

        self._ent_canvas.bind(
            "<Configure>",
            lambda e: self._ent_canvas.itemconfig(
                self._ent_window, width=e.width))

        btn_row = tk.Frame(parent, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        RoundedButton(btn_row, "REFRESH", self.rebuild_entity_list,
                      SURFACE2, SURFACE3, fg=ACCENT,
                      width=100, height=28, radius=8).pack(side="left")

    def rebuild_entity_list(self):
        if not hasattr(self, "_ent_inner"):
            return
        for row in self._entity_rows:
            row.destroy()
        self._entity_rows = []

        for w in self._ent_inner.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        if not self.gm:
            tk.Label(self._ent_inner, text="not connected",
                     font=("Segoe UI", 9), bg=SURFACE, fg=FAINT).pack(
                         anchor="w", padx=14, pady=14)
            self.lbl_player_count.config(text="0")
            return

        total = self.gm.get_player_count()
        self.lbl_player_count.config(text=str(total))

        entities = self.gm.get_entities_extended()
        if not entities:
            tk.Label(self._ent_inner, text="no other players",
                     font=("Segoe UI", 9), bg=SURFACE, fg=FAINT).pack(
                         anchor="w", padx=14, pady=14)
            return

        for ent in entities:
            self._entity_rows.append(EntityRow(self._ent_inner, ent,
                                               self.tp_to_entity))

    def update_entity_list(self):
        if not hasattr(self, "_ent_inner"):
            return
        if not self.gm:
            return

        total = self.gm.get_player_count()
        self.lbl_player_count.config(text=str(total))

        entities = self.gm.get_entities_extended()

        if len(entities) != len(self._entity_rows):
            self.rebuild_entity_list()
            return

        for row, ent in zip(self._entity_rows, entities):
            try:
                row.update(ent)
            except Exception:
                pass

    def tp_to_entity(self, ent):
        if not self.gm:
            self.set_status("Not connected", ERROR)
            return
        x, y, z = ent["xyz"]
        if self.gm.write_pos(x, y, z):
            self.set_status(f"Teleported to Player #{ent['index']}")
            self.log(f"TP → Player #{ent['index']} "
                     f"({x:.1f}, {y:.1f}, {z:.1f})", ok=True)
        else:
            self.set_status("Teleport failed", ERROR)
            self.log("Teleport failed", error=True)

    # ── MODULES tab ──
    def _build_modules_tab(self, parent):
        card = self._card(parent)
        tk.Label(card, text="FEATURES",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=15, pady=(10, 4))

        self.create_toggle(card, "God Mode (HP + Armor)", "god_mode_var",
                           self.toggle_god_mode, "God Mode")
        self.create_toggle(card, "Unlimited Ammo", "unlimited_ammo_var",
                           self.toggle_unlimited_ammo, "Unlimited Ammo")
        self.create_toggle(card, "Unlimited Grenade", "unlimited_grenade_var",
                           self.toggle_unlimited_grenade, "Unlimited Grenade")
        self.create_toggle(card, "Fast Fire", "fast_fire_var",
                           self.toggle_fast_fire, "Fast Fire")
        self.create_toggle(card, "Minimap Overlay", "minimap_var",
                           self.toggle_minimap, "Minimap")
        self.create_toggle(card, "Stealth Mode", "stealth_mode_var",
                           self.toggle_stealth_mode, "Stealth")

        note = tk.Frame(parent, bg=SURFACE2)
        note.pack(fill="x", pady=(12, 0))
        tk.Label(note, text=("Stealth hides the overlays and embeds the "
                             "minimap inside this window."),
                 font=("Segoe UI", 8), bg=SURFACE2, fg=MUTED,
                 wraplength=380, justify="left").pack(
                     anchor="w", padx=14, pady=12)

    def create_toggle(self, parent, text, var_name, command, hud_name):
        var = tk.BooleanVar(value=False)
        row = tk.Frame(parent, bg=SURFACE, height=34)
        row.pack(fill="x", padx=14, pady=2)
        row.pack_propagate(False)

        label = tk.Label(row, text=text, font=("Segoe UI", 9),
                         bg=SURFACE, fg=TEXT)
        label.pack(side="left")

        switch = tk.Canvas(row, width=42, height=22, bg=SURFACE,
                           highlightthickness=0, bd=0, cursor="hand2")
        switch.pack(side="right")

        animating = [False]
        current_x = [3]

        def draw(knob_x, is_on):
            switch.delete("all")
            track = ACCENT if is_on else "#2a303d"
            knob = "#ffffff"
            switch.create_arc(0, 0, 22, 22, start=90, extent=180,
                              fill=track, outline=track)
            switch.create_arc(20, 0, 42, 22, start=270, extent=180,
                              fill=track, outline=track)
            switch.create_rectangle(11, 0, 31, 22, fill=track, outline=track)
            switch.create_oval(knob_x, 3, knob_x + 16, 19,
                               fill=knob, outline=knob)

        def animate_toggle(target_x, is_on):
            if animating[0]:
                return
            animating[0] = True

            def step():
                dx = target_x - current_x[0]
                if abs(dx) <= 1:
                    current_x[0] = target_x
                    draw(current_x[0], is_on)
                    animating[0] = False
                else:
                    current_x[0] += dx * 0.35
                    draw(current_x[0], is_on)
                    self.root.after(12, step)

            step()

        def toggle(event=None):
            new_val = not var.get()
            var.set(new_val)
            animate_toggle(23 if new_val else 3, new_val)
            if self.hud and hud_name != "Stealth":
                if new_val:
                    self.hud.add_feature(hud_name)
                else:
                    self.hud.remove_feature(hud_name)
            command()

        switch.bind("<Button-1>", toggle)
        label.bind("<Button-1>", toggle)
        draw(3, False)
        setattr(self, var_name, var)
        self.toggle_widgets[var_name] = {"animate": animate_toggle,
                                         "hud_name": hud_name}

    def set_toggle_state(self, var_name, state):
        if var_name not in self.toggle_widgets:
            return
        data = self.toggle_widgets[var_name]
        var = getattr(self, var_name)
        if var.get() == state:
            return
        var.set(state)
        data["animate"](23 if state else 3, state)
        if self.hud and data["hud_name"] != "Stealth":
            if state:
                self.hud.add_feature(data["hud_name"])
            else:
                self.hud.remove_feature(data["hud_name"])

    def _build_log_tab(self, parent):
        card_outer = tk.Frame(parent, bg=BORDER)
        card_outer.pack(fill="both", expand=True)
        card = tk.Frame(card_outer, bg=SURFACE)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(card, bg=SURFACE)
        header.pack(fill="x", padx=13, pady=(10, 4))
        tk.Label(header, text="ACTIVITY",
                 font=("Segoe UI Semibold", 9),
                 bg=SURFACE, fg=MUTED).pack(side="left")
        tk.Label(header, text="● LIVE",
                 font=("Segoe UI Semibold", 7),
                 bg=SURFACE, fg=SUCCESS).pack(side="right")

        box = tk.Frame(card, bg="#0b0e14")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(
            box, bg="#0b0e14", fg="#aeb7c9", insertbackground=ACCENT,
            selectbackground=ACCENT2, relief="flat", bd=0,
            highlightthickness=0, font=("Cascadia Mono", 8),
            wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text.tag_config("normal", foreground="#aeb7c9")
        self.log_text.tag_config("error", foreground=ERROR)
        self.log_text.tag_config("ok", foreground=SUCCESS)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=BORDER)
        outer.pack(fill="x", pady=4)
        card = tk.Frame(outer, bg=SURFACE)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        return card

    def set_status(self, text, color=SUCCESS):
        if hasattr(self, "status_label"):
            self.status_label.config(text=f"●  {text.upper()}", fg=color)

    def log(self, text, error=False, ok=False):
        if not hasattr(self, "log_text"):
            return
        tag = "error" if error else ("ok" if ok else "normal")
        ts = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}] {text}\n", tag)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def reset_stats(self):
        if not self.gm:
            return
        self.gm.write_health(100)
        self.gm.write_armor(100)
        self.set_status("Stats reset to 100")
        self.log("Stats reset to 100", ok=True)

    def tp_get_current(self):
        if not self.gm:
            return
        pos = self.gm.read_pos_xyz()
        if pos:
            self.tp_x.delete(0, "end")
            self.tp_x.insert(0, f"{pos[0]:.2f}")
            self.tp_y.delete(0, "end")
            self.tp_y.insert(0, f"{pos[1]:.2f}")
            self.tp_z.delete(0, "end")
            self.tp_z.insert(0, f"{pos[2]:.2f}")

    def tp_apply(self):
        if not self.gm:
            return
        try:
            x = float(self.tp_x.get())
            y = float(self.tp_y.get())
            z = float(self.tp_z.get())
            if self.gm.write_pos(x, y, z):
                self.set_status("Teleported successfully")
                self.log(f"TP applied: {x}, {y}, {z}", ok=True)
        except ValueError:
            self.set_status("Invalid coordinates", ERROR)

    def apply_health(self):
        if not self.gm: return
        try:
            val = int(self.health_entry.get())
            self.gm.write_health(val)
            self.log(f"Health set to {val}", ok=True)
        except ValueError: pass

    def apply_armor(self):
        if not self.gm: return
        try:
            val = int(self.armor_entry.get())
            self.gm.write_armor(val)
            self.log(f"Armor set to {val}", ok=True)
        except ValueError: pass

    def apply_grenade(self):
        if not self.gm: return
        try:
            val = int(self.grenade_entry.get())
            self.gm.write_grenade(val)
            self.log(f"Grenades set to {val}", ok=True)
        except ValueError: pass

    def apply_ammo(self, val):
        if self.gm and self.gm.set_all_ammo(val):
            self.log(f"Ammo set to {val}", ok=True)

    def toggle_god_mode(self):
        self.log(f"God Mode: {self.god_mode_var.get()}")

    def toggle_unlimited_ammo(self):
        self.log(f"Unlimited Ammo: {self.unlimited_ammo_var.get()}")

    def toggle_unlimited_grenade(self):
        self.log(f"Unlimited Grenade: {self.unlimited_grenade_var.get()}")

    def toggle_fast_fire(self):
        if self.gm:
            self.gm.set_fast_fire(self.fast_fire_var.get())
            self.log(f"Fast Fire: {self.fast_fire_var.get()}")

    def toggle_minimap(self):
        enabled = self.minimap_var.get()
        if self.minimap and hasattr(self.minimap, "root"):
            if enabled and not self.stealth_mode_var.get():
                self.minimap.root.deiconify()
            else:
                self.minimap.root.withdraw()

    def toggle_stealth_mode(self):
        is_stealth = self.stealth_mode_var.get()
        if is_stealth:
            if self.hud: self.hud.root.withdraw()
            if self.badge: self.badge.root.withdraw()
            if self.minimap: self.minimap.root.withdraw()
            self._embedded_card.pack(fill="x", pady=6)
        else:
            if self.hud: self.hud.root.deiconify()
            if self.badge: self.badge.root.deiconify()
            if self.minimap and self.minimap_var.get():
                self.minimap.root.deiconify()
            self._embedded_card.pack_forget()

    def update_loop(self):
        if not self.gm:
            return

        if hasattr(self, "god_mode_var") and self.god_mode_var.get():
            self.gm.write_health(999)
            self.gm.write_armor(999)

        if hasattr(self, "unlimited_ammo_var") and self.unlimited_ammo_var.get():
            self.gm.set_all_ammo(999)

        if hasattr(self, "unlimited_grenade_var") and self.unlimited_grenade_var.get():
            self.gm.write_grenade(99)

        if hasattr(self, "fast_fire_var") and self.fast_fire_var.get():
            self.gm.set_fast_fire(True)

        hp = self.gm.read_health()
        ar = self.gm.read_armor()
        if hasattr(self, "lbl_live_hp"): self.lbl_live_hp.config(text=str(hp))
        if hasattr(self, "lbl_live_armor"): self.lbl_live_armor.config(text=str(ar))

        pos = self.gm.read_pos_xyz()
        if pos and hasattr(self, "lbl_pos_x"):
            self.lbl_pos_x.config(text=f"X  {pos[0]:.1f}")
            self.lbl_pos_y.config(text=f"Y  {pos[1]:.1f}")
            self.lbl_pos_z.config(text=f"Z  {pos[2]:.1f}")

        self._ent_tick += 1
        if self._ent_tick % 3 == 0:
            if self.current_tab == "ENTITIES":
                self.update_entity_list()

            local_pos = (pos[0], pos[1]) if pos else None
            p_ptr = self.gm.get_player()
            local_team = self.gm.get_player_team(p_ptr) if p_ptr else 0
            yaw = self.gm.get_player_yaw()
            entities = self.gm.get_entities()

            if self.minimap:
                self.minimap.update_map(local_pos, local_team, entities, yaw)
            if self.embedded_map:
                self.embedded_map.update_map(local_pos, local_team, entities, yaw)

        self.root.after(20, self.update_loop)

    def on_close(self):
        try:
            if self.hud: self.hud.destroy()
            if self.minimap: self.minimap.destroy()
            if self.badge: self.badge.destroy()
            self.root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = NemesisApp(root)
    root.mainloop()
