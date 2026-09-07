import tkinter as tk
from tkinter import messagebox, scrolledtext
import pymem
import pymem.process
import time
import ctypes
import math

def interpolate_color(hex1, hex2, factor):
    """İki hex renk arasında yumuşak geçiş hesabı yapar."""
    r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
    r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
    
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


class GameMemory:
    def __init__(self):
        self.pm = None
        self.client = None
        self.base = None
        self.local_player_ptr = None
        self.entity_list_ptr = None
        self.player_count_ptr = None

    def attach(self):
        try:
            self.pm = pymem.Pymem("ac_client.exe")
            self.client = pymem.process.module_from_name(self.pm.process_handle, "ac_client.exe")
            self.base = self.client.lpBaseOfDll
            self.local_player_ptr = self.base + 0x0017E0A8
            self.entity_list_ptr = self.base + 0x18AC04
            self.player_count_ptr = self.base + 0x18AC0C
            return True
        except Exception as e:
            print(f"Attach hatası: {e}")
            return False

    def get_player(self):
        try:
            return self.pm.read_int(self.local_player_ptr)
        except:
            return None

    def read_health(self):
        player = self.get_player()
        if player:
            try:
                return self.pm.read_int(player + 0xEC)
            except:
                return 0
        return 0

    def read_armor(self):
        player = self.get_player()
        if player:
            try:
                return self.pm.read_int(player + 0xF0)
            except:
                return 0
        return 0

    def write_health(self, value):
        player = self.get_player()
        if player:
            self.pm.write_int(player + 0xEC, value)
            return True
        return False

    def write_armor(self, value):
        player = self.get_player()
        if player:
            self.pm.write_int(player + 0xF0, value)
            return True
        return False

    def write_grenade(self, value):
        player = self.get_player()
        if player:
            self.pm.write_int(player + 0x144, value)
            return True
        return False

    def set_all_ammo(self, value):
        player = self.get_player()
        if player:
            ammo_offsets = [0x140, 0x138, 0x13C, 0x134, 0x12C]
            for off in ammo_offsets:
                self.pm.write_int(player + off, value)
            return True
        return False

    def set_fast_fire(self, enable):
        player = self.get_player()
        if not player:
            return False
        value = 0 if enable else 1
        for off in [0x164, 0x160, 0x158]:
            self.pm.write_int(player + off, value)
        return True

    def get_player_pos(self, player_ptr):
        try:
            x = self.pm.read_float(player_ptr + 0x2C)
            y = self.pm.read_float(player_ptr + 0x30)
            return x, y
        except:
            return None

    def get_player_yaw(self):
        player = self.get_player()
        if player:
            try:
                raw_yaw = self.pm.read_float(player + 0x34)
                return raw_yaw % 360.0
            except:
                return 0.0
        return 0.0

    def get_player_team(self, player_ptr):
        try:
            return self.pm.read_int(player_ptr + 0x30C)
        except:
            return 0

    def get_entities(self):
        entities = []
        try:
            count = self.pm.read_int(self.player_count_ptr)
            ent_list = self.pm.read_int(self.entity_list_ptr)
            if not ent_list or count <= 1:
                return entities

            for i in range(1, count):
                ent_ptr = self.pm.read_int(ent_list + (i * 4))
                if ent_ptr:
                    hp = self.pm.read_int(ent_ptr + 0xEC)
                    if hp > 0:
                        pos = self.get_player_pos(ent_ptr)
                        team = self.get_player_team(ent_ptr)
                        if pos:
                            entities.append({"ptr": ent_ptr, "pos": pos, "team": team})
        except:
            pass
        return entities


class MinimapOverlay:
    """Ekranın sol tarafında oyuncunun bakış açısına göre dönen radar penceresi."""
    def __init__(self):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        self.size = 180
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{self.size}x{self.size}+20+{screen_h - self.size - 100}")

        self.bg_color = "#000001"
        self.root.configure(bg=self.bg_color)
        self.root.wm_attributes("-transparentcolor", self.bg_color)

        self.canvas = tk.Canvas(self.root, bg=self.bg_color, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.scale = 1.8
        self._make_click_through()

    def _make_click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as e:
            print(f"Minimap click-through hatası: {e}")

    def update_map(self, local_pos, local_team, entities, yaw=0.0):
        self.canvas.delete("all")
        
        center_x = self.size / 2
        center_y = self.size / 2
        radius = (self.size / 2) - 4

        # Arkaplan Dairesi
        self.canvas.create_oval(
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius,
            fill="#0d1117", outline="#282e3b", width=2
        )

        if not local_pos:
            return

        lx, ly = local_pos
        rad = math.radians(yaw)

        # Pusula Çizgisi (Kuzey Yönü)
        nx = radius * math.sin(rad)
        ny = radius * math.cos(rad)
        self.canvas.create_line(center_x, center_y, center_x + nx, center_y - ny, fill="#282e3b", width=1)

        # Diğer Oyuncuları Bakış Açısına Göre Döndür
        for ent in entities:
            ex, ey = ent["pos"]
            
            dx = ex - lx
            dy = ey - ly

            # Rotasyon Matrisi
            rot_x = dx * math.cos(rad) - dy * math.sin(rad)
            rot_y = dx * math.sin(rad) + dy * math.cos(rad)

            px = center_x + (rot_x * self.scale)
            py = center_y - (rot_y * self.scale)

            # Sınır Kontrolü
            dist = math.sqrt((px - center_x)**2 + (py - center_y)**2)
            if dist > radius - 6:
                angle = math.atan2(py - center_y, px - center_x)
                px = center_x + (radius - 6) * math.cos(angle)
                py = center_y + (radius - 6) * math.sin(angle)

            color = "#4ba3ff" if ent["team"] == local_team else "#ff4b4b"
            self.canvas.create_oval(px - 4, py - 4, px + 4, py + 4, fill=color, outline="#ffffff", width=1)

        # Yerel Oyuncu
        self.canvas.create_oval(center_x - 5, center_y - 5, center_x + 5, center_y + 5, fill="#5ee6a8", outline="#ffffff", width=1)
        self.canvas.create_line(center_x, center_y, center_x, center_y - 14, fill="#5ee6a8", width=2)

    def destroy(self):
        try:
            self.root.destroy()
        except:
            pass


class HUDOverlay:
    """Ekranın sol üst köşesine aktif hileleri çizen transparan overlay."""
    def __init__(self):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry("360x480+15+15")
        
        self.bg_color = "#000001"
        self.root.configure(bg=self.bg_color)
        self.root.wm_attributes("-transparentcolor", self.bg_color)

        self.canvas = tk.Canvas(self.root, bg=self.bg_color, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.active_features = []
        self._make_click_through()

    def _make_click_through(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as e:
            print(f"Click-through hatası: {e}")

    def add_feature(self, name):
        if name not in self.active_features:
            self.active_features.append(name)
            self.redraw()

    def remove_feature(self, name):
        if name in self.active_features:
            self.active_features.remove(name)
            self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        if not self.active_features:
            return

        y = 12
        item_height = 48
        padding = 10
        
        for feat in self.active_features:
            text_str = f"● {feat.upper()}"
            box_width = 260
            
            self.canvas.create_rectangle(
                5, y, 5 + box_width, y + item_height,
                fill="#000000", outline="#282e3b", width=1, stipple="gray25"
            )
            self.canvas.create_rectangle(
                5, y, 11, y + item_height,
                fill="#9b7bff", outline=""
            )
            self.canvas.create_text(
                24, y + (item_height / 2),
                text=text_str, anchor="w",
                fill="#5ee6a8", font=("Consolas", 14, "bold")
            )
            y += item_height + padding

    def destroy(self):
        try:
            self.root.destroy()
        except:
            pass


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, bg, hover, fg="#ffffff", width=110, height=38, radius=12, **kwargs):
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else "#10131a"
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, bd=0, **kwargs)
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

    def _draw(self, color, fg_color=None):
        if fg_color is None:
            fg_color = self.fg
        self.delete("all")
        r = self.radius
        self.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=color, outline=color)
        self.create_arc(self.w-2*r, 0, self.w, 2*r, start=0, extent=90, fill=color, outline=color)
        self.create_arc(0, self.h-2*r, 2*r, self.h, start=180, extent=90, fill=color, outline=color)
        self.create_arc(self.w-2*r, self.h-2*r, self.w, self.h, start=270, extent=90, fill=color, outline=color)
        self.create_rectangle(r, 0, self.w-r, self.h, fill=color, outline=color)
        self.create_rectangle(0, r, self.w, self.h-r, fill=color, outline=color)
        self.create_text(self.w/2, self.h/2, text=self.text,
                         fill=fg_color, font=("Segoe UI Semibold", 9))


class HackApp:
    def __init__(self, root):
        self.root = root

        self.W, self.H = 470, 850
        self.root.title("NEMESIS // AssaultCube")
        self.root.geometry(f"{self.W}x{self.H}")
        self.root.minsize(self.W, self.H)
        self.root.maxsize(self.W, self.H)
        self.root.configure(bg="#08090d")
        self.root.attributes("-topmost", True)
        
        self.root.overrideredirect(True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.update_idletasks()
        self.apply_windows_rounding()

        self.bg = "#08090d"
        self.surface = "#10131a"
        self.surface2 = "#151923"
        self.surface3 = "#1b202c"
        self.border = "#282e3b"
        self.text = "#eef2ff"
        self.muted = "#8d96aa"
        self.accent = "#9b7bff"
        self.accent2 = "#6c5ce7"
        self.success = "#5ee6a8"
        self.error = "#ff6577"
        self.warning = "#ffc66d"

        self.gm = None
        self.hud = None
        self.minimap = None
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        self.saved_health = 100
        self.saved_armor = 100

        self.toggle_widgets = {}

        self.show_intro()

    def apply_windows_rounding(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            preference = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference), ctypes.sizeof(preference)
            )

            CreateRoundRectRgn = ctypes.windll.gdi32.CreateRoundRectRgn
            SetWindowRgn = ctypes.windll.user32.SetWindowRgn
            region = CreateRoundRectRgn(0, 0, self.W + 1, self.H + 1, 28, 28)
            SetWindowRgn(hwnd, region, True)
        except Exception:
            pass

    def center(self):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = (sw - self.W) // 2
        y = (sh - self.H) // 2
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def make_titlebar(self, parent, title, subtitle=None):
        bar = tk.Frame(parent, bg=self.bg, height=62)
        bar.pack(fill="x", padx=18, pady=(14, 0))
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=self.bg)
        left.pack(side="left", fill="y")

        tk.Label(left, text="◆", font=("Segoe UI", 18, "bold"),
                 bg=self.bg, fg=self.accent).pack(side="left", padx=(0, 9))

        textbox = tk.Frame(left, bg=self.bg)
        textbox.pack(side="left", fill="y")
        tk.Label(textbox, text=title, font=("Segoe UI Semibold", 14),
                 bg=self.bg, fg=self.text).pack(anchor="w", pady=(7, 0))
        if subtitle:
            tk.Label(textbox, text=subtitle, font=("Segoe UI", 8),
                     bg=self.bg, fg=self.muted).pack(anchor="w")

        close = tk.Label(bar, text="×", font=("Segoe UI", 18),
                         bg=self.bg, fg=self.muted, cursor="hand2")
        close.pack(side="right", padx=4)
        close.bind("<Enter>", lambda e: close.config(fg=self.error))
        close.bind("<Leave>", lambda e: close.config(fg=self.muted))
        close.bind("<Button-1>", lambda e: self.on_close())

        for widget in (bar, left, textbox):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        return bar

    def start_drag(self, event):
        self._drag_offset_x = event.x
        self._drag_offset_y = event.y

    def do_drag(self, event):
        x = self.root.winfo_pointerx() - self._drag_offset_x
        y = self.root.winfo_pointery() - self._drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def card(self, parent, padx=18, pady=12):
        outer = tk.Frame(parent, bg=self.border)
        outer.pack(fill="x", padx=padx, pady=pady)
        inner = tk.Frame(outer, bg=self.surface)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return inner

    def show_intro(self):
        self.center()

        self.intro_frame = tk.Frame(self.root, bg=self.bg)
        self.intro_frame.pack(fill="both", expand=True)

        self.lbl_logo = tk.Label(self.intro_frame, text="◆", font=("Segoe UI", 52, "bold"),
                                 bg=self.bg, fg=self.accent)
        self.lbl_logo.place(relx=.5, rely=.39, anchor="center")

        self.lbl_title = tk.Label(self.intro_frame, text="NEMESIS", font=("Segoe UI Semibold", 30),
                                  bg=self.bg, fg=self.text)
        self.lbl_title.place(relx=.5, rely=.52, anchor="center")

        self.lbl_sub = tk.Label(self.intro_frame, text="ASSAULTCUBE TOOLKIT", font=("Segoe UI", 9),
                                bg=self.bg, fg=self.muted)
        self.lbl_sub.place(relx=.5, rely=.59, anchor="center")

        self.root.after(1200, lambda: self.fade_out_intro_text(0))

    def fade_out_intro_text(self, step):
        total_steps = 20
        if step <= total_steps:
            factor = step / total_steps
            c_logo = interpolate_color(self.accent, self.bg, factor)
            c_title = interpolate_color(self.text, self.bg, factor)
            c_sub = interpolate_color(self.muted, self.bg, factor)

            self.lbl_logo.config(fg=c_logo)
            self.lbl_title.config(fg=c_title)
            self.lbl_sub.config(fg=c_sub)

            self.root.after(20, lambda: self.fade_out_intro_text(step + 1))
        else:
            self.intro_frame.destroy()
            self.create_attach_screen_fade_in()

    def create_attach_screen_fade_in(self):
        self.attach_frame = tk.Frame(self.root, bg=self.bg)
        self.attach_frame.pack(fill="both", expand=True)

        self.make_titlebar(self.attach_frame, "NEMESIS", "ASSAULTCUBE TOOLKIT")

        body = tk.Frame(self.attach_frame, bg=self.bg)
        body.pack(fill="both", expand=True, padx=28)

        hero = tk.Frame(body, bg=self.surface)
        hero.pack(fill="x", pady=(22, 12))

        self.lbl_hero_t = tk.Label(hero, text="READY TO CONNECT", font=("Segoe UI Semibold", 18),
                                   bg=self.surface, fg=self.surface)
        self.lbl_hero_t.pack(anchor="w", padx=22, pady=(22, 3))

        self.lbl_hero_s = tk.Label(hero, text="Connect to the running AssaultCube client.",
                                   font=("Segoe UI", 9), bg=self.surface, fg=self.surface)
        self.lbl_hero_s.pack(anchor="w", padx=22, pady=(0, 20))

        self.btn_connect = RoundedButton(hero, "CONNECT", self.attach_to_game,
                                         self.surface, self.surface, fg=self.surface, width=150, height=42)
        self.btn_connect.pack(anchor="w", padx=22, pady=(0, 22))

        status_card = tk.Frame(body, bg=self.surface2)
        status_card.pack(fill="x", pady=8)

        self.status_dot = tk.Label(status_card, text="●", font=("Segoe UI", 11),
                                    bg=self.surface2, fg=self.surface2)
        self.status_dot.pack(side="left", padx=(16, 7), pady=15)

        self.status_label = tk.Label(status_card, text="Waiting for game...",
                                      font=("Segoe UI", 9), bg=self.surface2, fg=self.surface2)
        self.status_label.pack(side="left")

        self.lbl_footer = tk.Label(body, text="WINDOWS 10 / 11  •  DARK UI  •  v2",
                                   font=("Segoe UI", 8), bg=self.bg, fg=self.bg)
        self.lbl_footer.pack(side="bottom", pady=18)

        self.fade_in_connect_text(0)

    def fade_in_connect_text(self, step):
        total_steps = 20
        if step <= total_steps:
            factor = step / total_steps

            c_hero_t = interpolate_color(self.surface, self.text, factor)
            c_hero_s = interpolate_color(self.surface, self.muted, factor)
            c_btn_bg = interpolate_color(self.surface, self.accent2, factor)
            c_btn_hover = interpolate_color(self.surface, self.accent, factor)
            c_btn_fg = interpolate_color(self.surface, "#ffffff", factor)
            c_dot = interpolate_color(self.surface2, self.warning, factor)
            c_status = interpolate_color(self.surface2, self.muted, factor)
            c_footer = interpolate_color(self.bg, "#515a6d", factor)

            self.lbl_hero_t.config(fg=c_hero_t)
            self.lbl_hero_s.config(fg=c_hero_s)
            
            self.btn_connect.normal = c_btn_bg
            self.btn_connect.hover = c_btn_hover
            self.btn_connect.fg = c_btn_fg
            self.btn_connect._draw(c_btn_bg, c_btn_fg)

            self.status_dot.config(fg=c_dot)
            self.status_label.config(fg=c_status)
            self.lbl_footer.config(fg=c_footer)

            self.root.after(20, lambda: self.fade_in_connect_text(step + 1))

    def show_hack_interface(self):
        self.attach_frame.destroy()

        self.hud = HUDOverlay()
        self.minimap = MinimapOverlay()

        self.main_frame = tk.Frame(self.root, bg=self.bg)
        self.main_frame.pack(fill="both", expand=True)

        self.make_titlebar(self.main_frame, "NEMESIS", "LIVE SESSION")

        session = tk.Frame(self.main_frame, bg=self.surface2)
        session.pack(fill="x", padx=18, pady=(2, 6))
        tk.Label(session, text="●  CONNECTED", font=("Segoe UI Semibold", 8),
                 bg=self.surface2, fg=self.success).pack(side="left", padx=13, pady=8)
        tk.Label(session, text="AC_CLIENT.EXE", font=("Consolas", 8),
                 bg=self.surface2, fg=self.muted).pack(side="right", padx=13)

        content = tk.Frame(self.main_frame, bg=self.bg)
        content.pack(fill="both", expand=True, padx=18)

        # STATS KARTI
        stats_card = self.card(content, padx=0, pady=4)
        
        stats_header = tk.Frame(stats_card, bg=self.surface)
        stats_header.pack(fill="x", padx=15, pady=(8, 4))
        tk.Label(stats_header, text="LIVE STATS", font=("Segoe UI Semibold", 9),
                 bg=self.surface, fg=self.muted).pack(side="left")

        btn_reset = RoundedButton(stats_header, "RESET STATS", self.reset_stats,
                                  self.error, "#e0485c", width=100, height=24, radius=6)
        btn_reset.pack(side="right")

        stats_row = tk.Frame(stats_card, bg=self.surface)
        stats_row.pack(fill="x", padx=15, pady=(0, 10))

        hp_box = tk.Frame(stats_row, bg=self.surface2, highlightthickness=1, highlightbackground=self.border)
        hp_box.pack(side="left", fill="x", expand=True, padx=(0, 5))
        tk.Label(hp_box, text="HEALTH", font=("Segoe UI", 7), bg=self.surface2, fg=self.muted).pack(anchor="w", padx=10, pady=(6, 0))
        self.lbl_live_hp = tk.Label(hp_box, text="100", font=("Consolas", 14, "bold"), bg=self.surface2, fg=self.error)
        self.lbl_live_hp.pack(anchor="w", padx=10, pady=(0, 6))

        arm_box = tk.Frame(stats_row, bg=self.surface2, highlightthickness=1, highlightbackground=self.border)
        arm_box.pack(side="right", fill="x", expand=True, padx=(5, 0))
        tk.Label(arm_box, text="ARMOR", font=("Segoe UI", 7), bg=self.surface2, fg=self.muted).pack(anchor="w", padx=10, pady=(6, 0))
        self.lbl_live_armor = tk.Label(arm_box, text="100", font=("Consolas", 14, "bold"), bg=self.surface2, fg=self.warning)
        self.lbl_live_armor.pack(anchor="w", padx=10, pady=(0, 6))

        # PLAYER VALUES
        values = self.card(content, padx=0, pady=4)
        tk.Label(values, text="PLAYER VALUES", font=("Segoe UI Semibold", 9),
                 bg=self.surface, fg=self.muted).pack(anchor="w", padx=15, pady=(8, 3))

        self.create_entry_row(values, "HEALTH", "health_entry", self.apply_health)
        self.create_entry_row(values, "ARMOR", "armor_entry", self.apply_armor)
        self.create_entry_row(values, "GRENADE", "grenade_entry", self.apply_grenade)

        # FEATURES
        features = self.card(content, padx=0, pady=4)
        tk.Label(features, text="FEATURES", font=("Segoe UI Semibold", 9),
                 bg=self.surface, fg=self.muted).pack(anchor="w", padx=15, pady=(8, 3))

        self.create_toggle(features, "God Mode (HP + Armor)", "god_mode_var", self.toggle_god_mode, "God Mode")
        self.create_toggle(features, "Unlimited Ammo", "unlimited_ammo_var", self.toggle_unlimited_ammo, "Unlimited Ammo")
        self.create_toggle(features, "Unlimited Grenade", "unlimited_grenade_var", self.toggle_unlimited_grenade, "Unlimited Grenade")
        self.create_toggle(features, "Fast Fire", "fast_fire_var", self.toggle_fast_fire, "Fast Fire")
        self.create_toggle(features, "Minimap Overlay", "minimap_var", self.toggle_minimap, "Minimap")
        self.set_toggle_state("minimap_var", True)

        # ACTIVITY LOG
        log_card = self.card(content, padx=0, pady=4)
        header = tk.Frame(log_card, bg=self.surface)
        header.pack(fill="x", padx=13, pady=(8, 2))
        tk.Label(header, text="ACTIVITY", font=("Segoe UI Semibold", 9),
                 bg=self.surface, fg=self.muted).pack(side="left")
        tk.Label(header, text="LIVE", font=("Segoe UI Semibold", 7),
                 bg=self.surface, fg=self.success).pack(side="right")

        self.log_text = scrolledtext.ScrolledText(
            log_card, height=4, bg="#0b0e14", fg="#aeb7c9",
            insertbackground=self.accent, selectbackground=self.accent2,
            relief="flat", bd=0, highlightthickness=0,
            font=("Cascadia Mono", 8), wrap=tk.WORD, state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        footer = tk.Frame(self.main_frame, bg=self.bg)
        footer.pack(fill="x", padx=18, pady=(2, 10))

        self.status_label = tk.Label(footer, text="●  READY",
                                      font=("Segoe UI Semibold", 8),
                                      bg=self.bg, fg=self.success)
        self.status_label.pack(side="left")

        tk.Label(footer, text="NEMESIS // ONLINE",
                 font=("Consolas", 7), bg=self.bg, fg="#515a6d").pack(side="right")

        self.log("Session initialized")
        self.update_loop()

    def create_entry_row(self, parent, label_text, attr_name, command):
        row = tk.Frame(parent, bg=self.surface)
        row.pack(fill="x", padx=14, pady=3)

        tk.Label(row, text=label_text, width=12, anchor="w",
                 font=("Segoe UI Semibold", 9), bg=self.surface, fg=self.text).pack(side="left")

        entry = tk.Entry(
            row, width=10, bg=self.surface3, fg=self.text,
            insertbackground=self.accent, selectbackground=self.accent2,
            relief="flat", bd=0, font=("Consolas", 9),
            highlightthickness=1, highlightbackground=self.border,
            highlightcolor=self.accent
        )
        entry.pack(side="left", padx=8, ipady=4)

        btn = RoundedButton(row, "APPLY", command,
                            self.accent2, self.accent,
                            width=74, height=28, radius=8)
        btn.pack(side="right")

        setattr(self, attr_name, entry)

    def set_toggle_state(self, var_name, state):
        if var_name in self.toggle_widgets:
            widget_data = self.toggle_widgets[var_name]
            var = getattr(self, var_name)
            if var.get() != state:
                var.set(state)
                target_x = 23 if state else 3
                widget_data["animate"](target_x, state)
                if self.hud:
                    if state:
                        self.hud.add_feature(widget_data["hud_name"])
                    else:
                        self.hud.remove_feature(widget_data["hud_name"])

    def create_toggle(self, parent, text, var_name, command, hud_name):
        var = tk.BooleanVar(value=False)

        row = tk.Frame(parent, bg=self.surface, height=34)
        row.pack(fill="x", padx=14, pady=2)
        row.pack_propagate(False)

        label = tk.Label(row, text=text, font=("Segoe UI", 9),
                         bg=self.surface, fg=self.text)
        label.pack(side="left")

        switch = tk.Canvas(row, width=42, height=22, bg=self.surface,
                           highlightthickness=0, bd=0, cursor="hand2")
        switch.pack(side="right")

        animating = [False]
        current_x = [3]

        def draw(knob_x, is_on):
            switch.delete("all")
            track = self.accent if is_on else "#2a303d"
            knob = "#ffffff"
            
            switch.create_arc(0, 0, 22, 22, start=90, extent=180, fill=track, outline=track)
            switch.create_arc(20, 0, 42, 22, start=270, extent=180, fill=track, outline=track)
            switch.create_rectangle(11, 0, 31, 22, fill=track, outline=track)
            switch.create_oval(knob_x, 3, knob_x + 16, 19, fill=knob, outline=knob)

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
            target = 23 if new_val else 3
            animate_toggle(target, new_val)
            
            if self.hud:
                if new_val:
                    self.hud.add_feature(hud_name)
                else:
                    self.hud.remove_feature(hud_name)

            command()

        switch.bind("<Button-1>", toggle)
        label.bind("<Button-1>", toggle)
        draw(3, False)

        setattr(self, var_name, var)
        self.toggle_widgets[var_name] = {
            "animate": animate_toggle,
            "hud_name": hud_name
        }

    def reset_stats(self):
        if self.god_mode_var.get():
            self.set_toggle_state("god_mode_var", False)

        if self.gm:
            self.gm.write_health(100)
            self.gm.write_armor(0)
            self.gm.write_grenade(0)
            self.gm.set_all_ammo(20)
            self.set_status("Stats Reset (HP:100, Arm:0, Gren:0, Ammo:20)")
            self.log("Reset Stats → HP: 100, Armor: 0, Grenades: 0, Ammo: 20")
        else:
            self.set_status("Player not found", self.error)

    def log(self, message, error=False):
        if hasattr(self, "log_text"):
            timestamp = time.strftime("%H:%M:%S")
            self.log_text.config(state="normal")
            tag = "error" if error else "normal"
            self.log_text.insert(tk.END, f"[{timestamp}]  {message}\n", tag)
            self.log_text.tag_config("normal", foreground="#aeb7c9")
            self.log_text.tag_config("error", foreground=self.error)
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")

    def set_status(self, text, color=None):
        if hasattr(self, "status_label"):
            self.status_label.config(text=f"●  {text}", fg=color or self.success)

    def attach_to_game(self):
        self.status_label.config(text="●  SEARCHING...", fg=self.warning)
        if hasattr(self, "status_dot"):
            self.status_dot.config(fg=self.warning)
        self.root.update()

        temp_gm = GameMemory()
        if temp_gm.attach():
            self.gm = temp_gm
            self.status_label.config(text="●  CONNECTED", fg=self.success)
            self.status_dot.config(fg=self.success)
            self.root.after(350, self.show_hack_interface)
        else:
            self.status_label.config(text="●  GAME NOT FOUND", fg=self.error)
            self.status_dot.config(fg=self.error)
            messagebox.showerror("Connection failed",
                                 "AssaultCube was not found.\nOpen the game and try again.")

    def apply_health(self):
        try:
            val = int(self.health_entry.get())
            if self.gm and self.gm.write_health(val):
                self.set_status(f"Health set to {val}")
                self.log(f"Health → {val}")
            else:
                self.set_status("Player not found", self.error)
                self.log("Player not found", True)
        except ValueError:
            messagebox.showerror("Invalid value", "Enter a valid number.")
            self.log("Invalid health value", True)

    def apply_armor(self):
        try:
            val = int(self.armor_entry.get())
            if self.gm and self.gm.write_armor(val):
                self.set_status(f"Armor set to {val}")
                self.log(f"Armor → {val}")
            else:
                self.set_status("Player not found", self.error)
                self.log("Player not found", True)
        except ValueError:
            messagebox.showerror("Invalid value", "Enter a valid number.")
            self.log("Invalid armor value", True)

    def apply_grenade(self):
        try:
            val = int(self.grenade_entry.get())
            if self.gm and self.gm.write_grenade(val):
                self.set_status(f"Grenades set to {val}")
                self.log(f"Grenades → {val}")
            else:
                self.set_status("Player not found", self.error)
                self.log("Player not found", True)
        except ValueError:
            messagebox.showerror("Invalid value", "Enter a valid number.")
            self.log("Invalid grenade value", True)

    def toggle_god_mode(self):
        active = self.god_mode_var.get()
        if self.gm:
            if active:
                self.saved_health = self.gm.read_health()
                self.saved_armor = self.gm.read_armor()
            else:
                self.gm.write_health(self.saved_health)
                self.gm.write_armor(self.saved_armor)

        self.set_status("God Mode ON" if active else "God Mode OFF",
                        self.success if active else self.muted)
        self.log(f"God Mode {'enabled' if active else 'disabled'}")

    def toggle_unlimited_ammo(self):
        active = self.unlimited_ammo_var.get()
        self.set_status("Unlimited ammo ON" if active else "Unlimited ammo OFF",
                        self.success if active else self.muted)
        self.log(f"Unlimited ammo {'enabled' if active else 'disabled'}")

    def toggle_fast_fire(self):
        if self.gm:
            if self.gm.set_fast_fire(self.fast_fire_var.get()):
                active = self.fast_fire_var.get()
                self.set_status("Fast fire ON" if active else "Fast fire OFF",
                                self.success if active else self.muted)
                self.log(f"Fast fire {'enabled' if active else 'disabled'}")
            else:
                self.set_status("Fast fire failed", self.error)
                self.log("Fast fire could not be applied", True)

    def toggle_unlimited_grenade(self):
        active = self.unlimited_grenade_var.get()
        self.set_status("Unlimited grenade ON" if active else "Unlimited grenade OFF",
                        self.success if active else self.muted)
        self.log(f"Unlimited grenade {'enabled' if active else 'disabled'}")

    def toggle_minimap(self):
        if not self.minimap or not hasattr(self.minimap, "root"):
            return
        
        active = self.minimap_var.get()
        if active:
            self.minimap.root.deiconify()
            self.set_status("Minimap ON", self.success)
            self.log("Minimap enabled")
        else:
            self.minimap.root.withdraw()
            self.set_status("Minimap OFF", self.muted)
            self.log("Minimap disabled")

    def update_loop(self):
        if self.hud and hasattr(self.hud, "root") and self.hud.root.winfo_exists():
            self.hud.root.attributes("-topmost", True)

        if self.minimap and hasattr(self.minimap, "root") and self.minimap.root.winfo_exists():
            self.minimap.root.attributes("-topmost", True)

        if not self.gm:
            return

        player = self.gm.get_player()
        if player:
            local_pos = self.gm.get_player_pos(player)
            local_team = self.gm.get_player_team(player)
            entities = self.gm.get_entities()

            if self.minimap and hasattr(self, "minimap_var") and self.minimap_var.get():
                yaw = self.gm.get_player_yaw()
                self.minimap.update_map(local_pos, local_team, entities, yaw)

            if self.god_mode_var.get():
                if hasattr(self, "lbl_live_hp"):
                    self.lbl_live_hp.config(text="INF")
                if hasattr(self, "lbl_live_armor"):
                    self.lbl_live_armor.config(text="INF")
                self.gm.pm.write_int(player + 0xEC, 999)
                self.gm.pm.write_int(player + 0xF0, 999)
            else:
                hp = self.gm.read_health()
                armor = self.gm.read_armor()
                if hasattr(self, "lbl_live_hp"):
                    self.lbl_live_hp.config(text=str(hp))
                if hasattr(self, "lbl_live_armor"):
                    self.lbl_live_armor.config(text=str(armor))

            if self.unlimited_ammo_var.get():
                for off in [0x140, 0x138, 0x13C, 0x134, 0x12C, 0x130]:
                    self.gm.pm.write_int(player + off, 999)

            if self.unlimited_grenade_var.get():
                self.gm.pm.write_int(player + 0x144, 999)

            if self.fast_fire_var.get():
                for off in [0x164, 0x160, 0x158]:
                    current = self.gm.pm.read_int(player + off)
                    if current != 0:
                        self.gm.pm.write_int(player + off, 0)

        self.root.after(100, self.update_loop)

    def on_close(self):
        if self.gm:
            if hasattr(self, "fast_fire_var") and self.fast_fire_var.get():
                self.gm.set_fast_fire(False)
        if self.hud:
            self.hud.destroy()
        if self.minimap:
            self.minimap.destroy()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = HackApp(root)
    root.mainloop()
