#!/usr/bin/env python3
"""Recolour the Joe's Pizza (F48 / F48I01) textures from red to F&F navy: every saturated red pixel (hue 345..18 deg) becomes navy with
the original shading kept.  usage: ff_recolor.py [--navy r,g,b] [--list a,b,c]  -> intermediate/ff/<name>_ff.png + a before/after sheet."""
import sys, numpy as np
from pathlib import Path
from PIL import Image, ImageDraw
args = sys.argv[1:]
def opt(f, d):
    if f in args: i = args.index(f); v = args[i + 1]; del args[i:i + 2]; return v
    return d
NAVY = np.array([float(v) for v in opt("--navy", "28,78,142").split(",")]) / 255.0          # from the F&F crest (16,80,144) lifted a touch for the game's pre-lit look
DEFAULT = "f48_i01awn,f48_i01win,f48_i01door,f48i01_countertrm,f48i01_chair,f48i01_sign,f48i01_win,f48i01_table,f48i01_fridge,f48i01_counter,f48i01_wall,f48i01_doors,f48i01_cabinet,f48i01_register,f48i01_ceiling,f48i01_oven,f48i01_brikwite"
names = opt("--list", DEFAULT).split(",")
src_dir = Path("intermediate/ff")
def hsv(rgb):
    mx = rgb.max(-1); mn = rgb.min(-1); d = mx - mn
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0.0); val = mx
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]; dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, ((g - b) / dd) % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) * 60.0
    h = np.where(d < 1e-6, 0.0, h); return h, sat, val
tiles = []; report = []
for n in names:
    p = src_dir / f"{n}.png"
    if not p.exists(): report.append((n, "missing")); continue
    im = Image.open(p).convert("RGBA"); a = np.asarray(im).astype(np.float32) / 255.0; rgb = a[..., :3].copy()
    h, s, v = hsv(rgb)
    red = ((h >= 345) | (h <= 18)) & (s > 0.42) & (v > 0.12)
    frac = float(red.mean())
    if frac > 0:
        vref = float(np.percentile(v[red], 75)); shade = np.clip(v / vref, 0.25, 1.35)[..., None]
        rgb[red] = np.clip(NAVY * shade[red], 0, 1)
    out = a.copy(); out[..., :3] = rgb; Image.fromarray((out * 255).astype(np.uint8)).save(src_dir / f"{n}_ff.png")
    report.append((n, f"{frac*100:.1f}% red"))
    w, hgt = im.size; sc = min(150 / w, 150 / hgt, 3); sz = (max(1, int(w * sc)), max(1, int(hgt * sc)))
    bef = im.resize(sz, Image.NEAREST); aft = Image.fromarray((out * 255).astype(np.uint8)).resize(sz, Image.NEAREST)
    t = Image.new("RGBA", (320, 180), (40, 40, 44, 255)); t.alpha_composite(bef, (5 + (150 - sz[0]) // 2, 5 + (150 - sz[1]) // 2)); t.alpha_composite(aft, (165 + (150 - sz[0]) // 2, 5 + (150 - sz[1]) // 2))
    ImageDraw.Draw(t).text((6, 164), f"{n} {frac*100:.0f}%", fill=(255, 255, 0, 255)); tiles.append(t)
cols = 4; rows = (len(tiles) + cols - 1) // cols; sheet = Image.new("RGBA", (320 * cols, 180 * rows), (0, 0, 0, 255))
for i, t in enumerate(tiles): sheet.paste(t, ((i % cols) * 320, (i // cols) * 180))
sheet.save("shots/ff_recolor_sheet.png")
for r in report: print(f"  {r[0]:22s} {r[1]}")
print("sheet -> shots/ff_recolor_sheet.png")
