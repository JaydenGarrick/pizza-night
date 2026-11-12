#!/usr/bin/env python3
"""Recolor the Male02 civilian body texture to: off-white shirt (tie removed), blue jeans, olive sneakers.
usage: recolor_male02.py [--shirt r,g,b] [--jeans r,g,b] [--shoes r,g,b] [--out intermediate/retex/male02_street.png]"""
import sys, colorsys
import numpy as np
from PIL import Image
args = sys.argv[1:]
def opt(flag, default):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
col = lambda s: np.array([float(x) for x in s.split(",")])
shirt_c = col(opt("--shirt", "0.93,0.89,0.78")); jeans_c = col(opt("--jeans", "0.38,0.49,0.66")); shoes_c = col(opt("--shoes", "0.60,0.57,0.35")); out_path = opt("--out", "intermediate/retex/male02_street.png")
src = Image.open("intermediate/textures/GenericMaleTextures.MaleBodyVersion02a.png").convert("RGBA")
a = np.asarray(src).astype(np.float32) / 255; rgb = a[..., :3].copy(); H, Wd = rgb.shape[:2]
hsv = np.stack(np.vectorize(colorsys.rgb_to_hsv)(rgb[..., 0], rgb[..., 1], rgb[..., 2]), -1)
hue, sat, val = hsv[..., 0] * 360, hsv[..., 1].copy(), hsv[..., 2].copy()
yy, xx = np.mgrid[0:H, 0:Wd]; rng = np.random.default_rng(3); grain = rng.normal(0, 0.02, (H, Wd)); out = rgb.copy()
tie = (xx < 165) & (hue > 90) & (hue < 180) & (sat > 0.3)
for y in range(H):
    for x in np.where(tie[y])[0]:
        l = x
        while l >= 0 and tie[y, l]: l -= 1
        r = x
        while r < Wd and tie[y, r]: r += 1
        px = rgb[y, l] if (l >= 0 and (r >= Wd or (x - l) <= (r - x))) else rgb[y, r]
        out[y, x] = px; val[y, x] = colorsys.rgb_to_hsv(*px)[2]; sat[y, x] = 0.05
shirt = ((xx < 139) | ((xx < 183) & (yy > 34))) & (sat < 0.3) & (val > 0.2)   # the sleeve column runs to x=183 (arm UVs sample 128..182); the trousers start right of it
out[shirt] = np.clip(shirt_c * (val[shirt] / float(val[shirt].mean()))[:, None] + grain[shirt][:, None], 0, 1)
shoe = (xx >= 139) & (xx <= 182) & (yy <= 34) & (sat > 0.12)
out[shoe] = np.clip(shoes_c * (0.45 + 1.1 * val[shoe])[:, None], 0, 1)
pants = ((xx >= 183) & ~shoe & ~((yy <= 34) & (xx <= 182))) | ((xx > 182) & (yy <= 34))
out[pants] = np.clip(jeans_c * (0.5 + 0.9 * val[pants])[:, None] + (((xx + yy) % 3) / 3 - 0.5)[pants][:, None] * 0.05 + grain[pants][:, None] * 1.5, 0, 1)
a[..., :3] = out
Image.fromarray((a * 255).astype(np.uint8)).resize((1024, 512), Image.LANCZOS).save(out_path); print("wrote", out_path)
