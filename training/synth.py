"""Synthetic hack-overlay samples: draws mod-menu panels and ESP overlays onto clean screens.

Real hack screenshots are scarce, so this bootstraps the `mod_menu` and `esp_overlay` classes from
clean gameplay / CODM menu images. The model still needs real examples (collect.py) before alerts go live.

    python -m training.synth --base training/dataset/normal_gameplay training/dataset/codm_menu_ui \\
        --out training/dataset --mod 400 --esp 400
"""

from __future__ import annotations

import argparse
import colorsys
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = (448, 224)
SCALE = 2  # draw at 2x, then downsample for anti-aliasing
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]
FONTS = [p for p in FONT_PATHS if Path(p).exists()]

TITLES = ["MOD MENU", "VIP MENU", "PREMIUM", "CHEAT", "MENU", "PRO MOD", "HAX", "MOD", "PANEL", "INJECTOR", "ELITE MOD"]
TABS = ["AIM", "ESP", "VISUAL", "MISC", "WEAPON", "PLAYER", "MEMORY", "SETTINGS", "BR", "MP"]
FEATURES = [
    "Aimbot", "Aim Lock", "Silent Aim", "Auto Fire", "Auto Headshot", "Magic Bullet", "Aim FOV", "Aim Smooth",
    "ESP Box", "ESP Line", "ESP Name", "ESP Distance", "ESP Health", "ESP Skeleton", "Wallhack", "Chams",
    "No Recoil", "No Spread", "Fast Reload", "Rapid Fire", "Infinite Ammo", "Speed Hack", "Fly Hack",
    "High Jump", "No Fog", "Night Vision", "Radar Hack", "Hide Name", "Anti Ban", "Bypass", "Wide View",
    "Fast Scope", "Instant Hit", "Bullet Track", "Target Bone", "Ignore Knocked", "Draw FOV", "Crosshair",
]
FOOTERS = ["Telegram @{}", "by {}", "t.me/{}", "discord.gg/{}", "v{}.{}", "Build {}"]


def font(rng: random.Random, size: int) -> ImageFont.ImageFont:
    if FONTS:
        return ImageFont.truetype(rng.choice(FONTS), size)
    return ImageFont.load_default(size)


def rand_word(rng: random.Random, n: tuple[int, int] = (4, 9)) -> str:
    return "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(rng.randint(*n)))


def hue_color(rng: random.Random, s: tuple[float, float], v: tuple[float, float], a: int = 255) -> tuple[int, int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(rng.random(), rng.uniform(*s), rng.uniform(*v))
    return int(r * 255), int(g * 255), int(b * 255), a


# --- mod menu --------------------------------------------------------------------------------

def draw_switch(d: ImageDraw.ImageDraw, x: int, y: int, h: int, on: bool, accent, rng: random.Random) -> int:
    w = int(h * 1.9)
    off = (90, 90, 90, 255)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=accent if on else off)
    k = h - 6
    kx = x + w - k - 3 if on else x + 3
    d.ellipse([kx, y + 3, kx + k, y + 3 + k], fill=(240, 240, 240, 255))
    return w


def draw_checkbox(d: ImageDraw.ImageDraw, x: int, y: int, h: int, on: bool, accent, rng: random.Random) -> int:
    d.rectangle([x, y, x + h, y + h], outline=(220, 220, 220, 255), width=max(2, h // 8), fill=accent if on else None)
    if on:
        d.line([(x + h * 0.2, y + h * 0.55), (x + h * 0.42, y + h * 0.78), (x + h * 0.82, y + h * 0.25)],
               fill=(255, 255, 255, 255), width=max(2, h // 6))
    return h


def draw_slider(d: ImageDraw.ImageDraw, x: int, y: int, h: int, w: int, accent, f, rng: random.Random) -> None:
    t = rng.random()
    cy = y + h // 2
    d.rectangle([x, cy - 2, x + w, cy + 2], fill=(100, 100, 100, 255))
    d.rectangle([x, cy - 2, x + int(w * t), cy + 2], fill=accent)
    d.ellipse([x + int(w * t) - h // 3, cy - h // 3, x + int(w * t) + h // 3, cy + h // 3], fill=(240, 240, 240, 255))
    d.text((x + w + 8, y), str(int(t * rng.choice([1, 10, 100, 360]))), font=f, fill=(230, 230, 230, 255))


def list_menu(img: Image.Image, rng: random.Random) -> Image.Image:
    """Floating panel: title bar, optional tabs, a list of toggles / checkboxes / sliders."""
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pw, ph = int(W * rng.uniform(0.22, 0.5)), int(H * rng.uniform(0.45, 0.95))
    px, py = rng.randint(0, W - pw), rng.randint(0, H - ph)
    accent = hue_color(rng, (0.6, 1.0), (0.75, 1.0))
    bg = hue_color(rng, (0.0, 0.5), (0.03, 0.22), rng.randint(150, 245))
    radius = rng.choice([0, 6, 12, 20])
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=radius, fill=bg,
                        outline=accent if rng.random() < 0.6 else None, width=rng.randint(2, 4))

    row_h = max(22, int(ph / rng.uniform(7, 12)))
    fsize = int(row_h * rng.uniform(0.5, 0.68))
    f, fb = font(rng, fsize), font(rng, int(fsize * 1.25))
    y = py
    # header
    hh = int(row_h * rng.uniform(1.1, 1.5))
    if rng.random() < 0.85:
        d.rounded_rectangle([px, py, px + pw, py + hh], radius=radius, fill=accent if rng.random() < 0.7 else bg)
        title = rng.choice(TITLES) if rng.random() < 0.8 else rand_word(rng).upper()
        if rng.random() < 0.4:
            title += f" v{rng.randint(1, 9)}.{rng.randint(0, 9)}"
        d.text((px + 12, py + (hh - fb.size) // 2), title, font=fb, fill=(255, 255, 255, 255))
        if rng.random() < 0.6:
            d.text((px + pw - 28, py + (hh - fb.size) // 2), rng.choice(["x", "-", "≡"]), font=fb, fill=(255, 255, 255, 255))
        y += hh + 6
    # tabs
    if rng.random() < 0.5:
        tabs = rng.sample(TABS, rng.randint(2, 4))
        tw = pw // len(tabs)
        sel = rng.randrange(len(tabs))
        for i, t in enumerate(tabs):
            if i == sel:
                d.rectangle([px + i * tw, y, px + (i + 1) * tw, y + row_h], fill=accent)
            d.text((px + i * tw + 8, y + (row_h - fsize) // 2), t, font=f, fill=(255, 255, 255, 255))
        y += row_h + 6
    # feature rows
    style = rng.choice(["switch", "checkbox", "mixed"])
    feats = rng.sample(FEATURES, min(len(FEATURES), 14))
    text_col = (235, 235, 235, 255) if rng.random() < 0.8 else accent
    for name in feats:
        if y + row_h > py + ph - 4:
            break
        if rng.random() < 0.3:
            d.line([(px + 8, y - 3), (px + pw - 8, y - 3)], fill=(255, 255, 255, 40), width=1)
        kind = style if style != "mixed" else rng.choice(["switch", "checkbox", "slider"])
        ch = int(row_h * 0.62)
        cy = y + (row_h - ch) // 2
        if kind == "slider" and pw > 180:
            d.text((px + 12, y), name, font=f, fill=text_col)
            draw_slider(d, px + 12, y + fsize + 2, ch, int(pw * 0.55), accent, f, rng)
            y += int(row_h * 1.5)
            continue
        on = rng.random() < 0.55
        if rng.random() < 0.5:
            draw_checkbox(d, px + 12, cy, ch, on, accent, rng) if kind == "checkbox" else draw_switch(d, px + 12, cy, ch, on, accent, rng)
            d.text((px + 12 + int(ch * 2.3), y + (row_h - fsize) // 2), name, font=f, fill=text_col)
        else:
            d.text((px + 12, y + (row_h - fsize) // 2), name, font=f, fill=text_col)
            cw = int(ch * 1.9) if kind == "switch" else ch
            draw_switch(d, px + pw - 12 - cw, cy, ch, on, accent, rng) if kind == "switch" else draw_checkbox(d, px + pw - 12 - cw, cy, ch, on, accent, rng)
        y += row_h
    if rng.random() < 0.4 and y + fsize < py + ph:
        foot = rng.choice(FOOTERS).format(rand_word(rng), rng.randint(0, 9))
        d.text((px + 12, py + ph - fsize - 8), foot, font=f, fill=(200, 200, 200, 200))
    # many menus leave a floating launcher icon on screen too
    if rng.random() < 0.3:
        r = int(H * rng.uniform(0.04, 0.07))
        cx, cy = rng.randint(r, W - r), rng.randint(r, H - r)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent, outline=(255, 255, 255, 255), width=3)
        d.text((cx - r // 2, cy - r // 2), rng.choice(["M", "V", "H", "★"]), font=font(rng, r), fill=(255, 255, 255, 255))
    return Image.alpha_composite(img.convert("RGBA"), layer)


SECTIONS = ["Visuals", "Aim Control", "Extras", "Skins", "Settings", "System Info", "Player", "Weapons", "Memory", "Misc"]
ITEMS = ["Alias - Queen", "Cipher - Joker", "AK117 - Legendary", "Ghost - Mythic", "DR-H - Epic", "Fennec - Mythic",
         "Price - Classic", "Mara - Legendary", "M4 - Gold", "Kilo 141 - Epic"]
IMGUI_TITLES = ["{} : CODM", "{} | CODM", "{} v{}", "CODM {}", "{} MENU"]


def sidebar_menu(img: Image.Image, rng: random.Random) -> Image.Image:
    """Large dark app-style panel with a sidebar of sections (e.g. 'engine' style cheat UIs)."""
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pw, ph = int(W * rng.uniform(0.4, 0.7)), int(H * rng.uniform(0.55, 0.9))
    px, py = rng.randint(0, W - pw), rng.randint(0, H - ph)
    accent = hue_color(rng, (0.6, 1.0), (0.8, 1.0))
    base = rng.randint(14, 34)
    d.rectangle([px, py, px + pw, py + ph], fill=(base, base, base + 4, rng.randint(225, 250)))
    sw = int(pw * rng.uniform(0.22, 0.32))
    d.rectangle([px, py, px + sw, py + ph], fill=(base - 6 if base > 6 else 0, base - 6 if base > 6 else 0, base, 255))
    f, fs, fb = font(rng, int(ph * 0.035)), font(rng, int(ph * 0.024)), font(rng, int(ph * 0.045))
    # brand
    d.ellipse([px + 14, py + 14, px + 14 + ph // 16, py + 14 + ph // 16], outline=accent, width=3)
    d.text((px + 22 + ph // 16, py + 16), rng.choice(BRANDS) + " " + rng.choice(["ENGINE", "MOD", "PANEL", "MENU"]), font=f, fill=accent)
    # sections
    y, rh = py + int(ph * 0.14), int(ph * rng.uniform(0.09, 0.12))
    sel = rng.randrange(5)
    for i, name in enumerate(rng.sample(SECTIONS, 6)):
        if y + rh > py + ph * 0.82:
            break
        if i == sel:
            d.rectangle([px + 6, y, px + sw - 6, y + rh - 4], fill=(*accent[:3], 70))
            d.rectangle([px + 6, y, px + 10, y + rh - 4], fill=accent)
        d.ellipse([px + 18, y + rh // 4, px + 18 + rh // 3, y + rh // 4 + rh // 3], outline=(170, 170, 170, 255), width=2)
        d.text((px + 30 + rh // 3, y + rh // 6), name, font=fs, fill=(210, 210, 210, 255))
        d.text((px + 30 + rh // 3, y + rh // 2), rand_word(rng, (6, 12)), font=font(rng, int(ph * 0.016)), fill=(110, 110, 110, 255))
        y += rh
    d.ellipse([px + 16, py + ph - 30, px + 26, py + ph - 20], fill=(60, 220, 90, 255))
    d.text((px + 32, py + ph - 34), rng.choice(["SYSTEM READY", "CONNECTED", "INJECTED", "ONLINE"]), font=fs, fill=(60, 220, 90, 255))
    if rng.random() < 0.6:
        d.text((px + 16, py + ph - 64), f"{rng.randint(1, 365)}d {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}", font=fs, fill=accent)
    # content
    cx, cw = px + sw + 18, pw - sw - 36
    d.text((cx, py + 14), rng.choice(SECTIONS).upper(), font=fb, fill=(240, 240, 240, 255))
    d.text((px + pw - 30, py + 14), "x", font=fb, fill=(220, 220, 220, 255))
    y = py + int(ph * 0.16)
    tabs = rng.sample(["Weapons", "Melee", "Operators", "Aim", "ESP", "Misc", "Vehicles"], 3)
    tsel, tw = rng.randrange(3), cw // 3
    for i, t in enumerate(tabs):
        d.rectangle([cx + i * tw, y, cx + (i + 1) * tw - 4, y + rh * 0.8], fill=(*accent[:3], 120) if i == tsel else (base + 14, base + 14, base + 18, 255))
        d.text((cx + i * tw + tw // 4, y + rh * 0.2), t, font=fs, fill=(235, 235, 235, 255))
    y += int(rh * 1.1)
    if rng.random() < 0.6:
        d.rectangle([cx, y, cx + cw, y + rh * 0.75], fill=(base + 8, base + 8, base + 10, 255))
        d.text((cx + 10, y + rh * 0.18), "Search name or ID...", font=fs, fill=(130, 130, 130, 255))
        y += int(rh * 1.0)
    while y + rh < py + ph * (0.78 if rng.random() < 0.6 else 0.95):
        d.text((cx + 10, y + rh * 0.2), rng.choice(ITEMS + FEATURES), font=fs, fill=(230, 230, 230, 255))
        if rng.random() < 0.6:
            d.rectangle([cx + cw - 150, y + 4, cx + cw - 60, y + rh * 0.7], outline=(220, 180, 50, 255), width=2)
        else:
            draw_switch(d, cx + cw - 60, int(y + rh * 0.15), int(rh * 0.55), rng.random() < 0.5, accent, rng)
        y += int(rh * 0.85)
    if y + rh < py + ph:
        d.rectangle([cx, y + 6, cx + cw // 2, y + rh], fill=accent)
        d.text((cx + cw // 8, y + rh * 0.3), rng.choice(["Apply", "Apply locally (trial)", "Enable", "Save"]), font=fs, fill=(20, 20, 20, 255))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def imgui_menu(img: Image.Image, rng: random.Random) -> Image.Image:
    """Dear ImGui-style window: coloured title bar, translucent body, buttons, checkboxes, value sliders."""
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pw, ph = int(W * rng.uniform(0.35, 0.65)), int(H * rng.uniform(0.5, 0.95))
    px, py = rng.randint(0, W - pw), rng.randint(0, H - ph)
    bar = rng.choice([(110, 90, 210), (70, 110, 200), (180, 50, 60), (40, 140, 90), (60, 60, 70)]) + (255,)
    active = rng.choice([(230, 50, 40, 255), bar, (240, 150, 30, 255)])
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=rng.choice([4, 8, 12]),
                        fill=(rng.randint(40, 75), rng.randint(40, 75), rng.randint(50, 85), rng.randint(165, 235)))
    th = int(ph * rng.uniform(0.06, 0.09))
    d.rounded_rectangle([px, py, px + pw, py + th], radius=6, fill=bar)
    f = font(rng, int(th * 0.6))
    title = rng.choice(IMGUI_TITLES).format(rand_word(rng, (3, 6)).upper(), rng.randint(1, 9))
    d.text((px + pw // 2 - len(title) * f.size // 4, py + th * 0.15), title, font=f, fill=(255, 255, 255, 255))
    d.text((px + pw - th, py + th * 0.1), "x", font=f, fill=(255, 255, 255, 255))
    rh = int(ph * rng.uniform(0.07, 0.1))
    fs = font(rng, int(rh * 0.6))
    lw = int(pw * rng.uniform(0.22, 0.3))
    y = py + th + 12
    for name in rng.sample(["Player", "Draw", "Hide", "Aim", "Misc", "ESP", "Weapon"], rng.randint(2, 4)):
        d.rounded_rectangle([px + 10, y, px + 10 + lw, y + rh * 1.4], radius=8, fill=(*bar[:3], 160))
        d.text((px + 22, y + rh * 0.35), name, font=fs, fill=(255, 255, 255, 255))
        y += int(rh * 1.6)
    x0, y = px + lw + 24, py + th + 12
    while y + rh < py + ph - rh:
        kind = rng.choice(["check", "check", "pills", "slider"])
        if kind == "check":
            on = rng.random() < 0.6
            d.rounded_rectangle([x0, y, x0 + rh * 0.8, y + rh * 0.8], radius=4, fill=(120, 120, 130, 220))
            if on:
                d.line([(x0 + rh * 0.15, y + rh * 0.4), (x0 + rh * 0.35, y + rh * 0.62), (x0 + rh * 0.68, y + rh * 0.15)], fill=(255, 255, 255, 255), width=3)
            d.text((x0 + rh, y), "Enable " + rng.choice(FEATURES), font=fs, fill=(255, 255, 255, 255))
        elif kind == "pills":
            d.text((x0, y), rng.choice(["Aim Target:", "Aim Location:", "Aim Trigger:", "Bone:"]), font=fs, fill=(255, 255, 255, 255))
            bx = x0 + int(fs.size * 6)
            for k, lab in enumerate(rng.sample(["Head", "Chest", "Legs", "Both", "AimFire", "AimScope", "Aim FOV"], 3)):
                bw = int(fs.size * (len(lab) * 0.55 + 1))
                if bx + bw > px + pw - 8:
                    break
                d.rounded_rectangle([bx, y, bx + bw, y + rh * 0.85], radius=6, fill=active if k == 0 else (*bar[:3], 170))
                d.text((bx + 6, y + 2), lab, font=fs, fill=(255, 255, 255, 255))
                bx += bw + 6
        else:
            sw_ = int((px + pw - x0) * 0.62)
            d.rounded_rectangle([x0, y, x0 + sw_, y + rh * 0.8], radius=6, fill=(110, 110, 120, 200))
            d.text((x0 + sw_ // 2 - fs.size, y), rng.choice(["1.00", "60", "200.000", "0.50", str(rng.randint(1, 360))]), font=fs, fill=(255, 255, 255, 255))
            d.text((x0 + sw_ + 8, y), rng.choice(["Smooth Aim", "Size Fov", "Distance Aim", "Smooth Lock", "Speed"]), font=fs, fill=(255, 255, 255, 255))
        y += int(rh * 1.1)
    if rng.random() < 0.7:
        d.text((px + 10, py + ph - rh * 1.2), rng.choice(["Device: iPad", "Device: iPhone", "Android 14", "iOS: 18.4.1"]), font=fs, fill=(240, 240, 240, 255))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def mod_menu(img: Image.Image, rng: random.Random) -> Image.Image:
    return rng.choice([list_menu, sidebar_menu, imgui_menu])(img, rng)


# --- ESP -------------------------------------------------------------------------------------

ESP_COLORS = [(255, 40, 40), (40, 255, 60), (255, 230, 40), (40, 230, 255), (255, 255, 255), (255, 60, 255), (255, 140, 0)]


def esp_overlay(img: Image.Image, rng: random.Random) -> Image.Image:
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    col = (*rng.choice(ESP_COLORS), 255)
    alt = (*rng.choice(ESP_COLORS), 255)
    th = rng.randint(2, 5)
    box_style = rng.choice(["rect", "corners", "rect", "filled"])
    line_from = rng.choice([None, "top", "bottom", "center"])
    show_hp, show_text, show_skel = rng.random() < 0.6, rng.random() < 0.75, rng.random() < 0.25
    f = font(rng, int(H * rng.uniform(0.028, 0.045)))
    for _ in range(rng.randint(1, 7)):
        bh = int(H * rng.uniform(0.07, 0.5))
        bw = int(bh * rng.uniform(0.35, 0.55))
        x0 = rng.randint(0, W - bw)
        y0 = rng.randint(int(H * 0.12), max(int(H * 0.12) + 1, H - bh - 4))
        x1, y1 = x0 + bw, y0 + bh
        c = col if rng.random() < 0.75 else alt
        if box_style == "rect":
            d.rectangle([x0, y0, x1, y1], outline=c, width=th)
        elif box_style == "filled":
            d.rectangle([x0, y0, x1, y1], outline=c, width=th, fill=(*c[:3], rng.randint(30, 70)))
        else:
            k = max(6, bw // 4)
            for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
                d.line([(cx, cy), (cx + sx * k, cy)], fill=c, width=th)
                d.line([(cx, cy), (cx, cy + sy * k)], fill=c, width=th)
        if line_from:
            src = {"top": (W // 2, 0), "bottom": (W // 2, H), "center": (W // 2, H // 2)}[line_from]
            dst = ((x0 + x1) // 2, y0 if line_from == "top" else y1 if line_from == "bottom" else (y0 + y1) // 2)
            d.line([src, dst], fill=c, width=max(1, th - 1))
        if show_hp:
            hp = rng.random()
            bx = x0 - th * 3 - 4
            d.rectangle([bx, y0, bx + th * 2, y1], fill=(20, 20, 20, 200))
            hc = (int(255 * (1 - hp)), int(255 * hp), 40, 255)
            d.rectangle([bx, y1 - int(bh * hp), bx + th * 2, y1], fill=hc)
        if show_text:
            label = rng.choice([f"{rng.randint(3, 250)}m", rand_word(rng, (5, 10)), f"[{rng.randint(1, 100)}] {rand_word(rng, (4, 8))}",
                                f"{rand_word(rng, (4, 8))} {rng.randint(3, 250)}m", "BOT", f"HP {rng.randint(1, 100)}"])
            ty = y0 - f.size - 4 if rng.random() < 0.7 else y1 + 2
            d.text((x0, ty), label, font=f, fill=c)
        if show_skel:
            hx, hy = (x0 + x1) // 2, y0 + bh // 10
            neck, hip = (hx, y0 + bh // 5), (hx, y0 + bh // 2)
            d.ellipse([hx - bw // 8, hy - bw // 8, hx + bw // 8, hy + bw // 8], outline=c, width=th)
            for a, b in ((neck, hip), (neck, (x0, y0 + bh // 3)), (neck, (x1, y0 + bh // 3)),
                         (hip, (x0 + bw // 4, y1)), (hip, (x1 - bw // 4, y1))):
                d.line([a, b], fill=c, width=max(1, th - 1))
    if rng.random() < 0.35:
        txt = rng.choice([f"ENEMIES: {rng.randint(1, 12)}", f"Enemy nearby: {rng.randint(1, 6)}", f"Players {rng.randint(1, 20)}", "WARNING"])
        bf = font(rng, int(H * 0.05))
        d.text((W // 2 - bf.size * len(txt) // 4, int(H * 0.08)), txt, font=bf, fill=(255, 60, 60, 255))
    if rng.random() < 0.3:  # FOV circle
        r = int(H * rng.uniform(0.12, 0.35))
        d.ellipse([W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r], outline=(*col[:3], 200), width=max(1, th - 1))
    return Image.alpha_composite(img.convert("RGBA"), layer)


BRANDS = ["CLOUD", "VIP", "HAX", "NEXUS", "STORM", "GHOST", "ZEUS", "KING", "PRO", "SKY", "ALPHA", "VORTEX"]


def subtle_overlay(img: Image.Image, rng: random.Random, in_match: bool) -> Image.Image:
    """Lightweight cheat HUD as seen on real hand cams: small brand watermark, thin FOV circle,
    hairline snap lines and skeletons, small red name tags. Brand and circle stay on lobby screens too."""
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    white = (255, 255, 255, rng.randint(170, 255))
    if rng.random() < 0.75:  # brand watermark, top centre
        brand = rng.choice(BRANDS) if rng.random() < 0.85 else rand_word(rng, (3, 7)).upper()
        bf = font(rng, int(H * rng.uniform(0.03, 0.05)))
        bcol = rng.choice([(235, 40, 50, 255), (255, 70, 90, 255), (255, 220, 40, 255), (60, 220, 255, 255), (255, 255, 255, 255)])
        d.text((W // 2 + int(W * rng.uniform(-0.04, 0.04)) - bf.size * len(brand) // 3, int(H * rng.uniform(0.0, 0.06))), brand, font=bf, fill=bcol)
    if rng.random() < (0.55 if in_match else 0.9):  # FOV circle, sometimes with crosshair and target square
        r = int(H * rng.uniform(0.15, 0.42))
        cx, cy = W // 2 + rng.randint(-W // 40, W // 40), H // 2 + rng.randint(-H // 30, H // 30)
        lw = rng.randint(2, 4)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=white, width=lw)
        if rng.random() < 0.5:
            d.line([(cx - r, cy), (cx + r, cy)], fill=white, width=max(1, lw - 1))
            d.line([(cx, cy - r), (cx, cy + r)], fill=white, width=max(1, lw - 1))
            s = r // 9
            d.rectangle([cx - s, cy - s, cx + s, cy + s], outline=white, width=max(1, lw - 1))
    if in_match:
        tf = font(rng, int(H * rng.uniform(0.022, 0.034)))
        top = (W // 2, int(H * rng.uniform(0.0, 0.05)))
        for _ in range(rng.randint(1, 8)):
            th = int(H * rng.uniform(0.03, 0.22))  # mostly far, small targets
            x, y = rng.randint(int(W * 0.05), int(W * 0.95)), rng.randint(int(H * 0.25), int(H * 0.75))
            if rng.random() < 0.8:
                d.line([top, (x, y - th // 2)], fill=(255, 255, 255, rng.randint(120, 230)), width=rng.randint(1, 2))
            if rng.random() < 0.75:  # small red name tag above the target
                tw, tag_h = int(th * rng.uniform(1.2, 2.5)) + 20, max(10, int(H * 0.028))
                d.rounded_rectangle([x - tw // 2, y - th // 2 - tag_h - 4, x + tw // 2, y - th // 2 - 4], radius=3,
                                    fill=(rng.randint(200, 245), rng.randint(30, 70), rng.randint(40, 80), rng.randint(170, 240)))
                if rng.random() < 0.6:
                    d.text((x - tw // 2 + 3, y - th // 2 - tag_h - 4), rand_word(rng, (4, 8)), font=tf, fill=(255, 255, 255, 230))
            if rng.random() < 0.4:  # hairline skeleton
                hx, hy = x, y - th // 2 + th // 8
                neck, hip = (hx, y - th // 4), (hx, y + th // 8)
                for a, b in ((neck, hip), (neck, (x - th // 5, y)), (neck, (x + th // 5, y)),
                             (hip, (x - th // 6, y + th // 2)), (hip, (x + th // 6, y + th // 2))):
                    d.line([a, b], fill=white, width=rng.randint(1, 2))
                d.ellipse([hx - th // 12, hy - th // 12, hx + th // 12, hy + th // 12], outline=white, width=1)
    return Image.alpha_composite(img.convert("RGBA"), layer)


# --- main ------------------------------------------------------------------------------------

def load_bases(dirs: list[Path]) -> list[Path]:
    return sorted(p for d in dirs for p in d.rglob("*") if p.suffix.lower() in IMAGE_EXT and not p.name.startswith("synth_"))


def render(base: Path, kind: str, rng: random.Random) -> Image.Image:
    img = Image.open(base).convert("RGB").resize((SIZE[0] * SCALE, SIZE[1] * SCALE), Image.BILINEAR)
    in_match = base.parent.name != "codm_menu_ui"
    if kind == "mod_menu":
        out = mod_menu(img, rng)
        if rng.random() < 0.25:  # menu and ESP often show together
            out = subtle_overlay(out.convert("RGB"), rng, in_match) if rng.random() < 0.5 or not in_match else esp_overlay(out.convert("RGB"), rng)
    elif kind == "esp_overlay" and in_match and rng.random() < 0.45:
        out = esp_overlay(img, rng)  # bold boxes: in a match only
    else:
        out = subtle_overlay(img, rng, in_match)
    return out.convert("RGB").resize(SIZE, Image.LANCZOS)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, nargs="+", required=True, help="folders of clean screens to draw on")
    ap.add_argument("--out", type=Path, default=Path("training/dataset"))
    ap.add_argument("--mod", type=int, default=400, help="mod_menu samples")
    ap.add_argument("--esp", type=int, default=400, help="esp_overlay samples")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    bases = load_bases(args.base)
    if not bases:
        raise SystemExit("no base images found")
    # Cheat overlays are mostly seen in a match; the brand watermark and FOV circle stay on lobby screens too.
    match_bases = [b for b in bases if b.parent.name != "codm_menu_ui"] or bases
    rng = random.Random(args.seed)
    for kind, n in (("mod_menu", args.mod), ("esp_overlay", args.esp)):
        out = args.out / kind
        out.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            base = rng.choice(match_bases if kind == "esp_overlay" and rng.random() < 0.75 else bases)
            render(base, kind, rng).save(out / f"synth_{args.seed}_{i:05d}.jpg", quality=rng.randint(70, 95))
        print(f"{n} synthetic {kind} → {out}")


if __name__ == "__main__":
    main()
