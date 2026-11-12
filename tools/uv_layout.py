#!/usr/bin/env python3
"""Render a character's UV layout over its texture and a body-region map (which texture areas belong to which bones).
usage: uv_layout.py MODEL.glb [--size 2048] [--out intermediate/uv]"""
import sys, io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile

args = sys.argv[1:]
size = int(args[args.index("--size") + 1]) if "--size" in args else 2048
outdir = Path(args[args.index("--out") + 1]) if "--out" in args else Path("intermediate/uv")
model = Path([a for a in args if a.endswith(".glb")][0]); outdir.mkdir(parents=True, exist_ok=True)
g = GLBFile(model); j = g.j
joints = j["skins"][0]["joints"] if j.get("skins") else []
bone_names = [j["nodes"][n].get("name", str(n)) for n in joints]
def region(name):
    n = name.lower()
    for key, lab in [("head", "head"), ("neck", "neck"), ("jaw", "head"), ("spine", "torso"), ("hip", "hips"), ("clavicle", "shoulders"), ("shoulder", "shoulders"), ("upper_arm", "upper arm"), ("elbow", "elbow"), ("lower_arm", "forearm"), ("wrist", "hand"), ("hand", "hand"), ("thumb", "fingers"), ("index", "fingers"), ("middle", "fingers"), ("ring", "fingers"), ("pinky", "fingers"), ("fingers", "fingers"), ("upper_leg", "thigh"), ("lower_leg", "shin"), ("ankle", "foot"), ("foot", "foot"), ("ball", "foot"), ("toe", "foot"), ("root", "hips")]:
        if key in n: return lab
    return "other"
palette = {"head": (255, 90, 90), "neck": (255, 160, 60), "torso": (255, 230, 60), "hips": (150, 220, 60), "shoulders": (60, 220, 140), "upper arm": (60, 200, 220), "elbow": (60, 140, 255), "forearm": (120, 90, 255), "hand": (200, 80, 255), "fingers": (255, 80, 200), "thigh": (170, 120, 60), "shin": (120, 170, 120), "foot": (200, 200, 200), "other": (90, 90, 90)}
for mi, mesh in enumerate(j["meshes"]):
    for pi, p in enumerate(mesh["primitives"]):
        uv = g.accessor(p["attributes"]["TEXCOORD_0"]).astype(np.float64); idx = g.accessor(p["indices"]).reshape(-1, 3)
        J = g.accessor(p["attributes"]["JOINTS_0"]) if "JOINTS_0" in p["attributes"] else None
        W = g.accessor(p["attributes"]["WEIGHTS_0"]) if "WEIGHTS_0" in p["attributes"] else None
        # base texture
        base = None
        mat = j["materials"][p["material"]] if "material" in p else {}
        bct = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if bct is not None:
            im = j["images"][j["textures"][bct["index"]]["source"]]; base = Image.open(io.BytesIO(g.view_bytes(im["bufferView"]))).convert("RGBA").resize((size, size), Image.NEAREST)
        wire = (base.copy() if base else Image.new("RGBA", (size, size), (30, 30, 30, 255)))
        d = ImageDraw.Draw(wire)
        regions = Image.new("RGBA", (size, size), (0, 0, 0, 255)); dr = ImageDraw.Draw(regions)
        def px(u, v): return (u % 1.0) * size, (v % 1.0) * size
        for tri in idx:
            pts = [px(*uv[k]) for k in tri]
            if max(abs(pts[a][0] - pts[b][0]) for a in range(3) for b in range(3)) > size * 0.8: continue  # wrapped tri
            d.polygon(pts, outline=(0, 255, 120, 255))
            if J is not None:
                dom = int(np.bincount(J[tri].flatten(), weights=W[tri].flatten()).argmax())
                dr.polygon(pts, fill=palette[region(bone_names[dom])])
        # legend
        y = 8
        for lab, col in palette.items():
            dr.rectangle([8, y, 48, y + 22], fill=col); dr.text((56, y + 4), lab, fill=(255, 255, 255))
            y += 28
        tag = f"{model.stem}_m{mi}p{pi}" if len(j["meshes"]) > 1 or len(mesh["primitives"]) > 1 else model.stem
        wire.save(outdir / f"{tag}_uv.png"); Image.blend(regions, wire, 0.35).save(outdir / f"{tag}_regions.png")
        if base: base.save(outdir / f"{tag}_texture.png")
        print(f"{tag}: {len(idx)} tris -> {outdir}/{tag}_uv.png, _regions.png" + (", _texture.png" if base else ""))
