from __future__ import annotations

from functools import lru_cache, wraps
from collections import OrderedDict
import ctypes
import os
import math
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import font as tkfont, ttk
from PIL import Image, ImageChops, ImageDraw, ImageTk

FONT_FAMILIES = {"body": "Noto Sans SC", "heading": "Noto Sans SC Medium",
                 "english": "Segoe UI Variable Text", "display": "Segoe UI Variable Display Semib"}
_PRIVATE_FONT_PATHS = []
_FONT_ROOT = None
_FONT_CACHE = {}


def load_bundled_fonts():
    """Register the included rounded face for this process, without system installation."""
    if os.name != "nt" or _PRIVATE_FONT_PATHS:
        return
    font_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets/fonts/ChillRoundF.ttf"
    if not font_path.is_file():
        return
    add_font = ctypes.windll.gdi32.AddFontResourceExW
    add_font.argtypes = (ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
    add_font.restype = ctypes.c_int
    if add_font(str(font_path), 0x10, None):
        _PRIVATE_FONT_PATHS.append(str(font_path))


def configure_fonts(window):
    global _FONT_ROOT, _FONT_CACHE
    _FONT_ROOT, _FONT_CACHE = window, {}
    available = set(tkfont.families(window))
    for role, names in {
        "body": ("Noto Sans SC", "Microsoft YaHei UI", "Segoe UI Variable Text", "ChillRoundF"),
        "heading": ("Noto Sans SC Medium", "Noto Sans SC", "Segoe UI Variable Text Semibold", "Microsoft YaHei UI"),
        "english": ("Segoe UI Variable Text", "Segoe UI", "Arial"),
        "display": ("Segoe UI Variable Display Semib", "Segoe UI Semibold", "Segoe UI"),
    }.items():
        FONT_FAMILIES[role] = next((n for n in names if n in available), FONT_FAMILIES[role])
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        tkfont.nametofont(name, root=window).configure(family=FONT_FAMILIES["body"], size=10)


def ui_font(size=10, emphasis=False):
    return shared_font("heading" if emphasis else "body", size)


def english_font(size=10, emphasis=False):
    return shared_font("display" if emphasis else "english", size)


def shared_font(role, size):
    key = (role, size)
    if _FONT_ROOT is None:
        return (FONT_FAMILIES[role], size, "normal")
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = tkfont.Font(root=_FONT_ROOT, family=FONT_FAMILIES[role], size=size,
                                     weight="bold" if role in ("heading", "display") else "normal")
    return _FONT_CACHE[key]


def cached_page(key):
    """Keep a constructed navigation page until its underlying data changes."""
    def decorate(method):
        @wraps(method)
        def show(self, *args, **kwargs):
            if not args and not kwargs and self._restore_page(key):
                return
            result = method(self, *args, **kwargs)
            self._remember_page(key)
            return result
        return show
    return decorate


class ScrollablePanel(tk.Frame):
    def __init__(self, parent, background):
        super().__init__(parent, bg=background)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._resize_job = None
        self._scroll_job = None
        self._layout = None
        self._target_offset = 0.0
        self.canvas = tk.Canvas(self, bg=background, bd=0, highlightthickness=0, yscrollincrement=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content = SceneFrame(self.canvas, self._root().colors) if background == self._root().colors["bg"] else tk.Frame(self.canvas, bg=background)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._schedule_resize)
        self.content.bind("<Configure>", self._schedule_resize, add="+")
        self.bind("<Destroy>", self._dispose, add="+")

    def _schedule_resize(self, event=None):
        if self._resize_job is None:
            self._resize_job = self.after_idle(self._resize)

    def _resize(self, event=None):
        self._resize_job = None
        height, required = self.canvas.winfo_height(), self.content.winfo_reqheight()
        width = self.canvas.winfo_width()
        layout = (width, height, required)
        if self._layout == layout:
            return
        self._layout = layout
        self.canvas.itemconfigure(self.item, width=width, height=max(height, required))
        self.canvas.configure(scrollregion=(0, 0, width, max(height, required)))
        if required > height:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()
            self.canvas.yview_moveto(0)

    def scroll_by(self, pixels):
        origin = self._target_offset if self._scroll_job else self.canvas.canvasy(0)
        self.scroll_to(origin + pixels)

    def scroll_to(self, offset):
        total = max(self.canvas.winfo_height(), self.content.winfo_reqheight())
        maximum = max(0, total - self.canvas.winfo_height())
        self._target_offset = max(0.0, min(float(offset), maximum))
        if self._scroll_job:
            self.after_cancel(self._scroll_job)
        origin, started = self.canvas.canvasy(0), time.perf_counter()

        def step():
            progress = min(1.0, (time.perf_counter() - started) / .14)
            eased = 1 - (1 - progress) ** 3
            position = origin + (self._target_offset - origin) * eased
            self.canvas.yview_moveto(position / max(1, total))
            self._scroll_job = self.after(16, step) if progress < 1 else None

        step()

    def _dispose(self, event):
        if event.widget is self:
            for job in (self._resize_job, self._scroll_job):
                if job:
                    self.after_cancel(job)


class ToolTip:
    """Small delayed label for compact icon-only controls."""
    def __init__(self, widget, text, *, background="#303030", foreground="#f4f4f4"):
        self.widget, self.text = widget, text
        self.background, self.foreground = background, foreground
        self.timer = None
        self.popup = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        self.timer = self.widget.after(420, self._show)

    def _show(self):
        self.timer = None
        if not self.widget.winfo_exists():
            return
        self.popup = tk.Toplevel(self.widget)
        self.popup.wm_overrideredirect(True)
        self.popup.attributes("-topmost", True)
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() + max(0, (self.widget.winfo_height() - 26) // 2)
        self.popup.geometry(f"+{x}+{y}")
        tk.Label(self.popup, text=self.text, bg=self.background, fg=self.foreground,
                 font=ui_font(9), padx=9, pady=5, bd=0).pack()

    def _hide(self, _event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None

THEMES = {
    "codex": {"bg": "#28333a", "surface": "#2e3c43", "surface_alt": "#3a4b51",
              "sidebar": "#263239", "sidebar_hover": "#354b50", "glass_tint": "#3a4b51",
              "glass_border": "#728d90", "glass_highlight": "#839d9f", "window_alpha": 1.0,
              "scene_start": "#2b414a", "scene_end": "#2c3543",
              "text": "#edf3f0", "muted": "#b0c3c1", "border": "#465e63",
              "blue": "#acdbc9", "blue_light": "#3a514e", "green": "#acdbc9",
              "green_light": "#30483f", "amber": "#e0b676", "amber_light": "#473a2b",
              "red": "#f08b8b", "danger_bg": "#4b3030", "hero_start": "#53736e",
              "hero_end": "#354750", "button_start": "#456e64", "button_end": "#365e58"},
    "mint": {"bg": "#f3f6f4", "surface": "#ffffff", "surface_alt": "#f0f5f2",
             "text": "#233a36", "muted": "#566b63", "border": "#dce7e1",
             "blue": "#4a8577", "blue_light": "#e0eee7", "green": "#619e86",
             "green_light": "#e2f1e8", "amber": "#bb895a", "amber_light": "#f7eee4",
             "red": "#b65d60", "danger_bg": "#fcebec", "hero_start": "#e8eee0",
             "hero_end": "#c9e0dd", "button_start": "#407564", "button_end": "#326456",
             "scene_start": "#edf4f1", "scene_end": "#edf1f7"},
    "rose": {"bg": "#f8f3f0", "surface": "#fffdfb", "surface_alt": "#f6efeb",
             "text": "#453c3c", "muted": "#776466", "border": "#ecdeda",
             "blue": "#a36b79", "blue_light": "#f0dfe4", "green": "#a87779",
             "green_light": "#f4e3e5", "amber": "#b58b5d", "amber_light": "#f8efe1",
             "red": "#b34f5f", "danger_bg": "#fbe6e9", "hero_start": "#f5e9d9",
             "hero_end": "#ecd0d9", "button_start": "#935c6b", "button_end": "#804c5b",
             "scene_start": "#f7efee", "scene_end": "#f4edf4"},
}


def palette(name: str) -> dict:
    colors = dict(THEMES.get(name, THEMES["codex"]))
    colors.setdefault("sidebar", colors["surface"])
    colors.setdefault("sidebar_hover", colors["blue_light"])
    colors.setdefault("glass_tint", colors["surface_alt"])
    colors.setdefault("glass_border", colors["border"])
    colors.setdefault("glass_highlight", colors["border"])
    colors.setdefault("window_alpha", 1.0)
    colors.setdefault("scene_start", colors["bg"])
    colors.setdefault("scene_end", colors["bg"])
    colors.update(navy=colors["surface"], navy_hover=colors["blue_light"], gold_text="#ffffff",
                  gold_hover=colors["button_start"], sidebar_text=colors["text"], sidebar_muted=colors["muted"])
    return colors


def enable_dark_titlebar(window):
    if os.name != "nt":
        return
    try:
        window.update_idletasks()
        child = window.winfo_id()
        handle = ctypes.windll.user32.GetParent(child) or child
        enabled = ctypes.c_int(1)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        if result != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 19, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except (AttributeError, OSError):
        pass


def rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def mix_color(start, end, amount):
    return "#" + "".join(f"{round(a + (b - a) * amount):02x}" for a, b in zip(rgb(start), rgb(end)))


@lru_cache(maxsize=48)
def gradient_image(width: int, height: int, start: str, end: str, radius: int = 26,
                   landscape: bool = False) -> Image.Image:
    scale = 2
    w, h = max(2, width) * scale, max(2, height) * scale
    strip = Image.new("RGBA", (1, h))
    a, b = rgb(start), rgb(end)
    strip.putdata([tuple(round(c + (d - c) * y / max(1, h - 1)) for c, d in zip(a, b)) + (255,)
                   for y in range(h)])
    image = strip.resize((w, h), Image.Resampling.NEAREST)
    mask = Image.new("L", (w, h))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius * scale, fill=255)
    image.putalpha(mask)
    return image.resize((max(2, width), max(2, height)), Image.Resampling.LANCZOS)


def surface_photo(widget, width, height, start, end, radius, *, landscape=False, border=None, highlight=None):
    """Reuse actual Tk images as well as bitmaps; bound the cache per window."""
    root = widget._root()
    if not hasattr(root, "_surface_photos"):
        root._surface_photos = OrderedDict()
        root._surface_bytes = 0
    key = (width, height, start, end, radius, landscape, border, highlight)
    cache = root._surface_photos
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    image = gradient_image(width, height, start, end, radius, landscape).copy()
    draw = ImageDraw.Draw(image)
    if border:
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, outline=border, width=1)
    if highlight and width >= 80:
        draw.line((30, 1, min(width - 30, 150), 1), fill=highlight, width=1)
    photo = ImageTk.PhotoImage(image, master=root)
    cache[key] = photo
    root._surface_bytes += width * height * 4
    while len(cache) > 64 or root._surface_bytes > 24 * 1024 * 1024:
        oldest, _photo = cache.popitem(last=False)
        root._surface_bytes -= oldest[0] * oldest[1] * 4
    return photo


class DeferredCanvas(tk.Canvas):
    """Merge layout notifications and cancel queued work when a page closes."""
    def schedule_paint(self, event=None):
        if getattr(self, "_paint_job", None) is None:
            self._paint_job = self.after_idle(self._flush_paint)

    def _flush_paint(self):
        self._paint_job = None
        self.paint()

    def _cancel_paint(self, event):
        if event.widget is self:
            for name in ("_paint_job", "_hover_job"):
                job = getattr(self, name, None)
                if job:
                    self.after_cancel(job)
                    setattr(self, name, None)


@lru_cache(maxsize=4)
def scene_image(width, height, start, end):
    """An application-owned ambient background, never a desktop screenshot."""
    if start == end:
        return Image.new("RGBA", (width, height), rgb(start) + (255,))
    w, h = max(2, width // 8), max(2, height // 8)
    image = Image.new("RGBA", (w, h))
    a, b = rgb(start), rgb(end)
    dark = sum(a) < 400
    # Direct color interpolation creates clean ambient gradients without blur.
    lights = ((.82, .12, (57, 108, 111) if dark else (195, 227, 218), .30),
              (.12, .72, (63, 72, 105) if dark else (212, 210, 233), .18),
              (.90, .95, (56, 90, 93) if dark else (228, 214, 208), .20))
    pixels = []
    for y in range(h):
        ny = y / max(1, h - 1)
        for x in range(w):
            nx = x / max(1, w - 1)
            t = .35 * nx + .65 * ny
            color = [c + (d - c) * t for c, d in zip(a, b)]
            for cx, cy, tint, strength in lights:
                amount = math.exp(-((nx - cx) ** 2 / .22 + (ny - cy) ** 2 / .32)) * strength
                color = [c + (d - c) * amount for c, d in zip(color, tint)]
            pixels.append(tuple(round(c) for c in color) + (255,))
    image.putdata(pixels)
    return image.resize((width, height), Image.Resampling.BILINEAR)


@lru_cache(maxsize=48)
def transparent_gradient(width, height, start, end, alpha_start=32, alpha_end=8, radius=18, border=None):
    layer = gradient_image(width, height, start, end, radius).copy()
    opacity = Image.new("L", (1, height))
    opacity.putdata([round(alpha_start + (alpha_end - alpha_start) * y / max(1, height - 1)) for y in range(height)])
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), opacity.resize((width, height))))
    if border:
        ImageDraw.Draw(layer).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, outline=rgb(border) + (38,), width=1)
    return layer


def scene_patch(widget, width, height, colors, material=False):
    root = widget._root()
    rw, rh = max(2, root.winfo_width()), max(2, root.winfo_height())
    start, end = colors["scene_start"], colors["scene_end"]
    if not colors.get("glass", True):
        start = end = colors["bg"]
    background = scene_image(rw, rh, start, end)
    x = max(0, widget.winfo_rootx() - root.winfo_rootx())
    y = max(0, widget.winfo_rooty() - root.winfo_rooty())
    image = background.crop((x, y, x + width, y + height))
    if material and colors.get("glass", True):
        owner = widget.master
        while owner is not None and not isinstance(owner, RoundedCard):
            owner = getattr(owner, "master", None)
        if owner is not None:
            cw, ch = max(2, owner.winfo_width()), max(2, owner.winfo_height())
            overlay = transparent_gradient(cw, ch, colors["surface_alt"], colors["hero_end"], border=colors["glass_border"])
            ox = widget.winfo_rootx() - owner.winfo_rootx()
            oy = widget.winfo_rooty() - owner.winfo_rooty()
            image = Image.alpha_composite(image, overlay.crop((ox, oy, ox + width, oy + height)))
    return image


class SceneFrame(DeferredCanvas):
    """Shared gradient crops line up across nested containers like clear panes."""
    def __init__(self, parent, colors, *, material=False, **kwargs):
        kwargs.setdefault("width", 0)
        kwargs.setdefault("height", 0)
        super().__init__(parent, bg=colors["surface" if material else "bg"], bd=0,
                         highlightthickness=0, **kwargs)
        self.colors, self.material = colors, material
        self._scene_key = None
        self.background_item = self.create_image(0, 0, anchor="nw")
        self.bind("<Configure>", self.schedule_paint)
        self.bind("<Destroy>", self._cancel_paint, add="+")

    def paint(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        root = self._root()
        key = (w, h, self.winfo_rootx(), self.winfo_rooty(), root.winfo_width(), root.winfo_height())
        if key == self._scene_key:
            return
        self._scene_key = key
        image = scene_patch(self, w, h, self.colors, material=self.material)
        self.photo = ImageTk.PhotoImage(image, master=root)
        self.itemconfigure(self.background_item, image=self.photo)
        # Native label backgrounds match their spot on the shared gradient.
        for child in self.winfo_children():
            if isinstance(child, tk.Label):
                px = min(w - 1, max(0, child.winfo_x() + child.winfo_width() // 2))
                py = min(h - 1, max(0, child.winfo_y() + child.winfo_height() // 2))
                color = image.getpixel((px, py))[:3]
                child.configure(bg="#" + "".join(f"{part:02x}" for part in color))


class SceneLabel(DeferredCanvas):
    """Draw text directly over the shared scene without a solid label rectangle."""
    def __init__(self, parent, colors, *, text, foreground, font, material=False,
                 anchor="center", justify="center", wraplength=0, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), bd=0, highlightthickness=0, **kwargs)
        self.colors, self.material, self.text_anchor = colors, material, anchor
        self._paint_key = None
        self.background_item = self.create_image(0, 0, anchor="nw")
        self.text_item = self.create_text(2, 2, anchor="nw", text=text, fill=foreground,
                                         font=font, justify=justify, width=wraplength)
        self._measure()
        self.bind("<Configure>", self.schedule_paint)
        self.bind("<Destroy>", self._cancel_paint, add="+")

    def _measure(self):
        bounds = self.bbox(self.text_item)
        width, height = (bounds[2] - bounds[0], bounds[3] - bounds[1]) if bounds else (1, 1)
        super().configure(width=width + 4, height=height + 4)

    def configure(self, cnf=None, **kwargs):
        if hasattr(self, "text_item"):
            text_fields = {}
            for name in ("text", "font", "justify"):
                if name in kwargs:
                    text_fields[name] = kwargs.pop(name)
            if "fg" in kwargs:
                text_fields["fill"] = kwargs.pop("fg")
            if text_fields:
                self.itemconfigure(self.text_item, **text_fields)
                self._measure()
                self._paint_key = None
                self.schedule_paint()
        return super().configure(cnf, **kwargs)

    config = configure

    def paint(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        key = (w, h, self.winfo_rootx(), self.winfo_rooty(), self._root().winfo_width(), self._root().winfo_height())
        if key == self._paint_key:
            return
        self._paint_key = key
        image = scene_patch(self, w, h, self.colors, material=self.material)
        self.photo = ImageTk.PhotoImage(image, master=self._root())
        self.itemconfigure(self.background_item, image=self.photo)
        bounds = self.bbox(self.text_item)
        if bounds:
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            x = 2 if "w" in self.text_anchor else w - width - 2 if "e" in self.text_anchor else (w - width) / 2
            y = 2 if "n" in self.text_anchor else h - height - 2 if "s" in self.text_anchor else (h - height) / 2
            self.coords(self.text_item, x, y)


def app_icon(size: int = 256) -> Image.Image:
    image = gradient_image(1024, 1024, "#a5c8ac", "#629b96", 235).copy()
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((245, 273, 775, 744), radius=70, outline="#f6fff8", width=29)
    draw.line((510, 317, 510, 699), fill="#f6fff8", width=23)
    draw.line((310, 405, 433, 405), fill="#f6fff8", width=22)
    draw.line((310, 493, 433, 493), fill="#f6fff8", width=22)
    draw.line((589, 405, 709, 405), fill="#f6fff8", width=22)
    draw.line((589, 493, 709, 493), fill="#f6fff8", width=22)
    draw.ellipse((682, 215, 826, 359), fill="#ecd6a4")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def line_icon(kind: str, color: str, size: int = 24) -> ImageTk.PhotoImage:
    image = Image.new("RGBA", (96, 96))
    d = ImageDraw.Draw(image)
    options = dict(fill=color, width=6)
    if kind == "home":
        d.line([(15, 44), (48, 17), (81, 44)], **options)
        d.rounded_rectangle((25, 40, 71, 80), radius=7, outline=color, width=6)
    elif kind == "words":
        d.rounded_rectangle((18, 17, 78, 81), radius=10, outline=color, width=6)
        d.line((48, 23, 48, 74), **options)
        d.line((26, 36, 39, 36), **options)
        d.line((56, 36, 69, 36), **options)
    elif kind == "essays":
        d.rounded_rectangle((20, 17, 70, 81), radius=9, outline=color, width=6)
        d.line((30, 33, 60, 33), **options)
        d.line((30, 47, 54, 47), **options)
        d.line((51, 73, 79, 45), fill=color, width=9)
    elif kind == "progress":
        for x, y in ((22, 56), (43, 39), (64, 20)):
            d.rounded_rectangle((x, y, x + 10, 79), radius=4, fill=color)
    elif kind == "settings":
        for y, knob in ((26, 61), (49, 34), (72, 58)):
            d.line((18, y, 79, y), **options)
            d.ellipse((knob - 9, y - 9, knob + 9, y + 9), fill=color)
    elif kind == "add":
        d.rounded_rectangle((17, 17, 79, 79), radius=18, outline=color, width=6)
        d.line((48, 31, 48, 65), **options)
        d.line((31, 48, 65, 48), **options)
    elif kind == "sound":
        d.polygon([(20, 37), (36, 37), (52, 23), (52, 73), (36, 59), (20, 59)], fill=color)
        d.arc((42, 26, 77, 71), -60, 60, fill=color, width=6)
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS))


class GradientRoundedButton(DeferredCanvas):
    def __init__(self, parent, *, text, command=None, width=170, height=48,
                 start="#83b59d", end="#61978f", foreground="#ffffff", font=None, **kwargs):
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"),
                         bd=0, highlightthickness=0, cursor="hand2", takefocus=1, **kwargs)
        self.label, self.command, self.state = text, command, "normal"
        self.start, self.end, self.foreground, self.font = start, end, foreground, font
        self.hover = False
        self._hover_level = 0.0
        self._hover_job = None
        self._paint_key = None
        self._button_surfaces = OrderedDict()
        self.background_item = self.create_image(0, 0, anchor="nw")
        self.text_item = self.create_text(0, 0, text=text, fill=foreground, font=font)
        self.focus_item = self.create_rectangle(0, 0, 0, 0, outline=foreground, dash=(2, 3), state="hidden")
        self.bind("<Configure>", self.schedule_paint)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<FocusIn>", self.schedule_paint)
        self.bind("<FocusOut>", self.schedule_paint)
        self.bind("<Destroy>", self._cancel_paint, add="+")

    def _press(self, event):
        if self.state != "disabled":
            self.focus_set()
            self.itemconfigure(self.text_item, fill=self.foreground)

    def _release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            return self.invoke()

    def _hover(self, value):
        self.hover = value
        if self._hover_job:
            self.after_cancel(self._hover_job)
        origin, target, started = self._hover_level, float(value), time.perf_counter()

        def step():
            progress = min(1.0, (time.perf_counter() - started) / .09)
            self._hover_level = origin + (target - origin) * (1 - (1 - progress) ** 2)
            self.schedule_paint()
            self._hover_job = self.after(16, step) if progress < 1 else None

        step()

    def configure(self, cnf=None, **kwargs):
        for key in ("text", "command", "state"):
            if key in kwargs:
                setattr(self, "label" if key == "text" else key, kwargs.pop(key))
        result = super().configure(cnf, **kwargs)
        if hasattr(self, "label"):
            super().configure(takefocus=self.state != "disabled", cursor="arrow" if self.state == "disabled" else "hand2")
            self.schedule_paint()
        return result

    config = configure

    def invoke(self):
        if self.state != "disabled" and self.command:
            self.command()
        return "break"

    def paint(self):
        w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        if w <= 2 or h <= 2:
            return
        level = round(self._hover_level * 8) / 8
        start = "#" + "".join(f"{round(a + (b - a) * level):02x}" for a, b in zip(rgb(self.start), rgb(self.end)))
        end = self.end
        if self.state == "disabled":
            start = end = self.end
        position = (self.winfo_rootx(), self.winfo_rooty(), self._root().winfo_width(), self._root().winfo_height())
        strength = getattr(self, "_selection_strength", 0.0 if self.foreground == getattr(self._root(), "colors", {}).get("text") else 1.0)
        key = (w, h, start, end, self.label, self.state, position, strength, self.focus_get() is self)
        if self._paint_key == key:
            return
        self._paint_key = key
        scene = self.master
        while scene and not isinstance(scene, SceneFrame):
            scene = getattr(scene, "master", None)
        colors = getattr(self._root(), "colors", {})
        if scene and colors.get("glass") and colors["scene_start"] != colors["scene_end"]:
            background_key = (w, h, start, end, position, strength)
            if background_key not in self._button_surfaces:
                image = scene_patch(self, w, h, colors, material=scene.material)
                navigation = getattr(self, "_is_navigation", False)
                overlay = transparent_gradient(w, h, start, end,
                                               round(12 + 70 * strength) if navigation else round(45 + 185 * strength),
                                               round(4 + 38 * strength) if navigation else round(18 + 182 * strength),
                                               min(12, h // 2), None if navigation else colors["glass_border"])
                image = Image.alpha_composite(image, overlay)
                self._button_surfaces[background_key] = ImageTk.PhotoImage(image, master=self._root())
                while len(self._button_surfaces) > 6:
                    self._button_surfaces.popitem(last=False)
            self.photo = self._button_surfaces[background_key]
        else:
            self.photo = surface_photo(self, w, h, start, end, min(12, h // 2))
        self.itemconfigure(self.background_item, image=self.photo)
        self.coords(self.text_item, w / 2, h / 2)
        self.itemconfigure(self.text_item, text=self.label, width=w - 24,
                           fill="#989898" if self.state == "disabled" else self.foreground)
        self.coords(self.focus_item, 9, 6, w - 9, h - 6)
        self.itemconfigure(self.focus_item, state="normal" if key[-1] else "hidden")


class NavigationButton(GradientRoundedButton):
    """Keep sidebar controls aligned with the ambient background."""
    def __init__(self, parent, colors, *, text, icon, command):
        self.colors, self.icon, self.selected = colors, icon, False
        self._is_navigation = True
        self._selection_strength = 0.0
        super().__init__(parent, text=text, command=command, width=200, height=50,
                         start=colors["surface_alt"], end=colors["blue_light"],
                         foreground=colors["muted"], font=ui_font(11))
        self.icon_item = self.create_image(14, 25, image=icon, anchor="w")
        self.marker_item = self.create_rectangle(2, 14, 4, 36, fill=colors["blue"], outline="", state="hidden")

    def configure(self, cnf=None, **kwargs):
        if "selected" in kwargs:
            self.selected = kwargs.pop("selected")
            self._selection_strength = .65 if self.selected else 0.0
            self.foreground = self.colors["text"] if self.selected else self.colors["muted"]
        return super().configure(cnf, **kwargs)

    config = configure

    def paint(self):
        super().paint()
        if hasattr(self, "icon_item"):
            h, w = self.winfo_height(), self.winfo_width()
            self.coords(self.text_item, 48, h / 2)
            self.itemconfigure(self.text_item, anchor="w", width=max(1, w - 60))
            self.coords(self.icon_item, 14, h / 2)
            self.coords(self.marker_item, 2, 14, 4, max(14, h - 14))
            self.itemconfigure(self.marker_item, state="normal" if self.selected else "hidden")


class RoundedCard(DeferredCanvas):
    def __init__(self, parent, colors, *, padding=24, minheight=0, tint=None):
        super().__init__(parent, bg=parent.cget("bg"), bd=0, highlightthickness=0, height=minheight)
        self.colors, self.padding, self.minimum = colors, padding, minheight
        self.tint = tint or colors["glass_tint"]
        self._paint_size = None
        self.content = SceneFrame(self, colors, material=True)
        self.window_item = self.create_window(padding, padding, window=self.content, anchor="nw")
        self.background_item = self.create_image(0, 0, anchor="nw")
        self.tag_lower(self.background_item)
        self.bind("<Configure>", self.schedule_paint)
        self.content.bind("<Configure>", self.schedule_paint, add="+")
        self.bind("<Destroy>", self._cancel_paint, add="+")

    def paint(self, event=None):
        w = max(2, self.winfo_width())
        if w <= 2:
            return
        h = max(self.minimum, self.content.winfo_reqheight() + self.padding * 2)
        if int(float(self.cget("height"))) != h:
            self.configure(height=h)
        key = (w, h, self.winfo_rootx(), self.winfo_rooty(), self._root().winfo_width(), self._root().winfo_height())
        if self._paint_size == key:
            return
        self._paint_size = key
        self.itemconfigure(self.window_item, width=max(1, w - self.padding * 2))
        if self.colors.get("glass", True) and self.colors["scene_start"] != self.colors["scene_end"]:
            base = scene_patch(self, w, h, self.colors)
            overlay = transparent_gradient(w, h, self.colors["surface_alt"], self.colors["hero_end"], border=self.colors["glass_border"])
            image = Image.alpha_composite(base, overlay)
            self.photo = ImageTk.PhotoImage(image, master=self._root())
        else:
            self.photo = surface_photo(self, w, h, self.colors["surface"], self.tint, 18,
                                       border=self.colors["glass_border"], highlight=self.colors["glass_highlight"])
        self.itemconfigure(self.background_item, image=self.photo)


class WordCanvas(DeferredCanvas):
    def __init__(self, parent, colors, *, title, subtitle="", caption="", height=260,
                 display_font=None, body_font=None, landscape=False):
        super().__init__(parent, bg=parent.cget("bg"), height=height, bd=0, highlightthickness=0)
        self.colors, self.title, self.subtitle, self.caption = colors, title, subtitle, caption
        self.display_font, self.body_font, self.landscape = display_font, body_font, landscape
        self._paint_key = None
        self._background_size = None
        self.background_item = self.create_image(0, 0, anchor="nw")
        self.caption_item = self.create_text(0, 0, anchor="nw", fill=colors["muted"], font=body_font)
        self.title_item = self.create_text(0, 0, anchor="w", fill=colors["text"])
        self.subtitle_item = self.create_text(0, 0, anchor="w", fill=colors["muted"], font=body_font)
        self.bind("<Configure>", self.schedule_paint)
        self.bind("<Destroy>", self._cancel_paint, add="+")

    def paint(self, event=None):
        w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        if w <= 2 or h <= 2:
            return
        position = (self.winfo_rootx(), self.winfo_rooty(), self._root().winfo_width(), self._root().winfo_height())
        key = (w, h, self.title, self.subtitle, self.caption, self.display_font, self.body_font, position)
        if self._paint_key == key:
            return
        self._paint_key = key
        if self._background_size != (w, h, position):
            self._background_size = (w, h, position)
            if self.colors.get("glass", True):
                base = scene_patch(self, w, h, self.colors)
                overlay = transparent_gradient(w, h, self.colors["hero_start"], self.colors["hero_end"], 60, 14, 20, self.colors["glass_border"])
                self.photo = ImageTk.PhotoImage(Image.alpha_composite(base, overlay), master=self._root())
            else:
                self.photo = surface_photo(self, w, h, self.colors["hero_start"], self.colors["hero_end"], 20,
                                           border=self.colors["glass_border"])
            self.itemconfigure(self.background_item, image=self.photo)
        self.coords(self.caption_item, 32, 28)
        self.itemconfigure(self.caption_item, text=self.caption)
        display = self.display_font or english_font(28, True)
        if isinstance(display, tkfont.Font):
            actual = display.actual()
            face = [actual["family"], actual["size"], actual["weight"]]
        else:
            face = list(display)
        # Fit long collocations above the pronunciation without clipping or overlap.
        title_item = self.title_item
        self.coords(title_item, 32, h * .43)
        self.itemconfigure(title_item, text=self.title, width=max(1, w - 64), font=tuple(face))
        available_height = h * .53 - 46
        while face[1] > 13:
            bounds = self.bbox(title_item)
            if bounds and bounds[3] - bounds[1] <= available_height:
                break
            face[1] -= 1
            self.itemconfigure(title_item, font=tuple(face))
        self.coords(self.subtitle_item, 34, h * .80)
        self.itemconfigure(self.subtitle_item, text=self.subtitle, width=max(1, w - 68))


class SegmentedChoice(SceneFrame):
    """Visible single-choice options with native focus and arrow-key support."""
    def __init__(self, parent, colors, *, options, value=None, variable=None, command=None):
        super().__init__(parent, colors, material=True)
        self.colors, self.command = colors, command
        self.variable = variable if variable is not None else tk.StringVar(self, value=str(value))
        self.buttons = []
        self._selection_job = None
        self._initialized = False
        for index, (key, title) in enumerate(options):
            self.columnconfigure(index, weight=1, uniform="choices")
            button = GradientRoundedButton(self, text=title, font=ui_font(10),
                                           width=ui_font(10).measure(title) + 44, height=44,
                                           command=lambda k=str(key): self.select(k))
            button.grid(row=0, column=index, sticky="ew", padx=1)
            button.bind("<Left>", lambda e, i=index: self._move(i, -1))
            button.bind("<Right>", lambda e, i=index: self._move(i, 1))
            button.bind("<Return>", lambda e, k=str(key): self._activate(k))
            self.buttons.append((str(key), button))
        self._trace = self.variable.trace_add("write", self._refresh)
        self.bind("<Destroy>", self._dispose, add="+")
        self._refresh()

    def _activate(self, key):
        self.select(key)
        return "break"

    def _move(self, index, direction):
        key, button = self.buttons[(index + direction) % len(self.buttons)]
        button.focus_set()
        self.select(key)
        return "break"

    def select(self, key):
        previous = self.variable.get()
        if previous == key:
            return
        self.variable.set(key)
        if self.command and self.command(key) is False and self.winfo_exists():
            self.variable.set(previous)

    def _refresh(self, *args):
        if self._selection_job:
            self.after_cancel(self._selection_job)
            self._selection_job = None
        targets = []
        for key, button in self.buttons:
            selected = key == self.variable.get()
            target = (self.colors["button_start"] if selected else self.colors["surface_alt"],
                      self.colors["button_end"] if selected else self.colors["blue_light"],
                      "#ffffff" if selected else self.colors["text"], float(selected))
            origin = (button.start, button.end, button.foreground, getattr(button, "_selection_strength", float(selected)))
            targets.append((button, origin, target))
        started = time.perf_counter()
        animate = self._initialized
        self._initialized = True
        def step():
            progress = min(1.0, (time.perf_counter() - started) / .16) if animate else 1.0
            amount = 1 - (1 - progress) ** 3
            for button, origin, target in targets:
                button.start, button.end, button.foreground = [mix_color(a, b, amount) for a, b in zip(origin[:3], target[:3])]
                button._selection_strength = round((origin[3] + (target[3] - origin[3]) * amount) * 8) / 8
                button.itemconfigure(button.focus_item, outline=button.foreground)
                button.schedule_paint()
            self._selection_job = self.after(16, step) if progress < 1 else None
        step()

    def _dispose(self, event):
        if event.widget is self:
            if self._selection_job:
                self.after_cancel(self._selection_job)
            self.variable.trace_remove("write", self._trace)
