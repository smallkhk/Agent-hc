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


def mod_menu(img: Image.Image, rng: random.Random) -> Image.Image:
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


# --- main ------------------------------------------------------------------------------------

def load_bases(dirs: list[Path]) -> list[Path]:
    return sorted(p for d in dirs for p in d.rglob("*") if p.suffix.lower() in IMAGE_EXT and not p.name.startswith("synth_"))


def render(base: Path, kind: str, rng: random.Random) -> Image.Image:
    img = Image.open(base).convert("RGB").resize((SIZE[0] * SCALE, SIZE[1] * SCALE), Image.BILINEAR)
    out = mod_menu(img, rng) if kind == "mod_menu" else esp_overlay(img, rng)
    if kind == "mod_menu" and rng.random() < 0.25:  # menu and ESP often show together
        out = esp_overlay(out.convert("RGB"), rng)
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
    # ESP only shows in a match, so it is drawn on gameplay only (when the bases are split by class)
    esp_bases = [b for b in bases if b.parent.name == "normal_gameplay"] or bases
    rng = random.Random(args.seed)
    for kind, n in (("mod_menu", args.mod), ("esp_overlay", args.esp)):
        pool = esp_bases if kind == "esp_overlay" else bases
        out = args.out / kind
        out.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            base = rng.choice(pool)
            render(base, kind, rng).save(out / f"synth_{args.seed}_{i:05d}.jpg", quality=rng.randint(70, 95))
        print(f"{n} synthetic {kind} → {out}")


if __name__ == "__main__":
    main()
