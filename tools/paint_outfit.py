#!/usr/bin/env python3
"""Procedurally paint a character texture by body region (uses skin weights to know which texels are which body part).
usage: paint_outfit.py MODEL.glb --out texture.png [--size 1024] [--style street] [--keep head,neck]
Styles are dicts of region -> painter; edit STYLES below or pass --json style.json."""
import sys, io, json, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
out = opt("--out", "outfit.png"); size = int(opt("--size", "1024")); style_name = opt("--style", "street"); keep = set((opt("--keep", "head") or "").split(",")); style_json = opt("--json")
model = Path([a for a in args if a.endswith(".glb")][0])
g = GLBFile(model); j = g.j
joints = j["skins"][0]["joints"]; bone_names = [j["nodes"][n].get("name", str(n)) for n in joints]
REGIONS = ["head", "neck", "torso", "hips", "shoulders", "upper arm", "elbow", "forearm", "hand", "fingers", "thigh", "shin", "foot", "other"]
def region(name):
    n = name.lower()
    for key, lab in [("head", "head"), ("jaw", "head"), ("neck", "neck"), ("spine", "torso"), ("hip", "hips"), ("clavicle", "shoulders"), ("shoulder", "shoulders"), ("upper_arm", "upper arm"), ("elbow", "elbow"), ("lower_arm", "forearm"), ("wrist", "hand"), ("hand", "hand"), ("thumb", "fingers"), ("index", "fingers"), ("middle", "fingers"), ("ring", "fingers"), ("pinky", "fingers"), ("fingers", "fingers"), ("upper_leg", "thigh"), ("lower_leg", "shin"), ("ankle", "foot"), ("foot", "foot"), ("ball", "foot"), ("toe", "foot"), ("root", "hips")]:
        if key in n: return lab
    return "other"
prim = j["meshes"][0]["primitives"][0]
uv = g.accessor(prim["attributes"]["TEXCOORD_0"]).astype(np.float64); idx = g.accessor(prim["indices"]).reshape(-1, 3)
J = g.accessor(prim["attributes"]["JOINTS_0"]); W = g.accessor(prim["attributes"]["WEIGHTS_0"])
mat = j["materials"][prim["material"]]; bct = mat["pbrMetallicRoughness"]["baseColorTexture"]
base = Image.open(io.BytesIO(g.view_bytes(j["images"][j["textures"][bct["index"]]["source"]]["bufferView"]))).convert("RGBA").resize((size, size), Image.LANCZOS)
# region id raster (dilated by a few px so seams don't show the old texture)
rid = Image.new("L", (size, size), 0); d = ImageDraw.Draw(rid)
for tri in idx:
    pts = [((uv[k][0] % 1) * size, (uv[k][1] % 1) * size) for k in tri]
    if max(abs(pts[a][0] - pts[b][0]) for a in range(3) for b in range(3)) > size * 0.8: continue
    dom = int(np.bincount(J[tri].flatten(), weights=W[tri].flatten()).argmax())
    d.polygon(pts, fill=REGIONS.index(region(bone_names[dom])) + 1, outline=REGIONS.index(region(bone_names[dom])) + 1)
rid = rid.filter(ImageFilter.MaxFilter(5))
R = np.asarray(rid)
rng = np.random.default_rng(7)
def noise(scale, amp):
    n = rng.normal(0, 1, (size // scale + 1, size // scale + 1))
    im = Image.fromarray(((n - n.min()) / (n.max() - n.min()) * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
    return (np.asarray(im).astype(np.float32) / 255 - 0.5) * amp
def fabric(color, grain=0.05, weave=None):
    c = np.array(color, np.float32) / 255
    img = np.ones((size, size, 3), np.float32) * c
    img += noise(2, grain)[..., None]; img += noise(16, grain * 0.6)[..., None]
    if weave:  # fine diagonal twill for denim
        yy, xx = np.mgrid[0:size, 0:size]
        img += (((xx + yy) % weave) / weave - 0.5)[..., None] * 0.06
    return np.clip(img, 0, 1)
STYLES = {
  "street": {  # cream button-up, blue jeans, olive sneakers, bare hands
    "neck": fabric((206, 160, 128), 0.03), "shoulders": fabric((235, 228, 210), 0.04), "torso": fabric((235, 228, 210), 0.04),
    "upper arm": fabric((235, 228, 210), 0.04), "elbow": fabric((235, 228, 210), 0.04), "forearm": fabric((235, 228, 210), 0.04),
    "hand": fabric((206, 160, 128), 0.03), "fingers": fabric((206, 160, 128), 0.03),
    "hips": fabric((235, 228, 210), 0.04), "thigh": fabric((88, 118, 160), 0.06, weave=3), "shin": fabric((92, 124, 168), 0.06, weave=3),
    "foot": fabric((150, 142, 86), 0.05), "other": fabric((235, 228, 210), 0.04) },
}
if style_json: STYLES["custom"] = {k: fabric(tuple(v["color"]), v.get("grain", 0.04), v.get("weave")) for k, v in json.load(open(style_json)).items()}; style_name = "custom"
style = STYLES[style_name]
out_img = np.asarray(base).astype(np.float32) / 255
for ri, name in enumerate(REGIONS):
    if name in keep or name not in style: continue
    m = R == ri + 1
    out_img[m, :3] = style[name][m]
# shirt details on the torso front: placket + buttons (positions tuned for SpideyMesh UV layout; skip for other models)
if model.stem == "spideymesh" and "torso" not in keep and style_name == "street":
    tex = Image.fromarray((out_img * 255).astype(np.uint8)); d2 = ImageDraw.Draw(tex)
    s = size / 1024
    x = int(392 * s); d2.line([(x, int(70 * s)), (x, int(470 * s))], fill=(200, 192, 172, 255), width=max(1, int(3 * s)))
    d2.line([(x + int(14 * s), int(70 * s)), (x + int(14 * s), int(470 * s))], fill=(215, 207, 187, 255), width=max(1, int(2 * s)))
    for y in range(int(110 * s), int(470 * s), int(60 * s)): d2.ellipse([x + int(3 * s), y - int(5 * s), x + int(13 * s), y + int(5 * s)], fill=(245, 240, 225, 255), outline=(150, 140, 120, 255))
    # jeans: darker seams down the outer legs and a waistband
    d2.rectangle([int(690 * s), int(640 * s), int(1010 * s), int(660 * s)], fill=(70, 95, 135, 255))
    out_img = np.asarray(tex).astype(np.float32) / 255
Image.fromarray((np.clip(out_img, 0, 1) * 255).astype(np.uint8)).save(out)
print(f"wrote {out} ({size}px) regions painted: {[n for n in REGIONS if n in style and n not in keep]}")
