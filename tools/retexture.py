#!/usr/bin/env python3
"""Swap textures inside an exported character GLB (no Blender).

usage: retexture.py MODEL.glb --list
       retexture.py MODEL.glb --set <imageName>=<new.png> [--set ...] --out NEW.glb [--emissive <imageName>=<png>] [--color r,g,b]
imageName is the name shown by --list (e.g. SpideyTextures.Spidey512). The PNG can be any size.
"""
import sys, io, json, struct
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile

args = sys.argv[1:]
sets = []; emis = []; color = None; out = None
i = 0; pos = []
while i < len(args):
    a = args[i]
    if a == "--set": sets.append(args[i + 1]); i += 2
    elif a == "--emissive": emis.append(args[i + 1]); i += 2
    elif a == "--out": out = args[i + 1]; i += 2
    elif a == "--color": color = [float(x) for x in args[i + 1].split(",")]; i += 2
    elif a == "--list": pos.append(a); i += 1
    else: pos.append(a); i += 1
model = [p for p in pos if p != "--list"][0]
g = GLBFile(model); j = g.j
images = j.get("images", [])
if "--list" in pos:
    print(f"{model}: {len(images)} images, {len(j.get('materials', []))} materials")
    for k, im in enumerate(images):
        bv = j["bufferViews"][im["bufferView"]]
        pil = Image.open(io.BytesIO(g.view_bytes(im["bufferView"])))
        users = [m.get("name") for m in j.get("materials", []) if any(t.get("index") is not None and j["textures"][t["index"]]["source"] == k for t in [m.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}), m.get("emissiveTexture", {})])]
        print(f"  [{k}] {im.get('name', '?'):40} {pil.size[0]}x{pil.size[1]}  used by {users}")
    sys.exit(0)
if not out: sys.exit("--out required")

# rebuild the binary buffer: copy every bufferView, replacing image views where requested
by_name = {im.get("name"): k for k, im in enumerate(images)}
replace = {}
for s in sets:
    name, path = s.split("=", 1)
    k = by_name.get(name)
    if k is None:
        k = next((i for i, im in enumerate(images) if (im.get("name") or "").lower().endswith(name.lower())), None)
    if k is None: sys.exit(f"image '{name}' not found; use --list")
    img = Image.open(path).convert("RGBA"); buf = io.BytesIO(); img.save(buf, format="PNG"); replace[images[k]["bufferView"]] = buf.getvalue()
newbin = bytearray(); newviews = []
for vi, bv in enumerate(j["bufferViews"]):
    data = replace.get(vi, g.view_bytes(vi))
    while len(newbin) % 4: newbin.append(0)
    nv = dict(bv); nv["byteOffset"] = len(newbin); nv["byteLength"] = len(data); nv.pop("buffer", None); nv["buffer"] = 0
    newviews.append(nv); newbin += data
j["bufferViews"] = newviews; j["buffers"] = [{"byteLength": len(newbin)}]
# optional: add/replace emissive textures and tint
for e in emis:
    name, path = e.split("=", 1)
    img = Image.open(path).convert("RGBA"); buf = io.BytesIO(); img.save(buf, format="PNG"); data = buf.getvalue()
    while len(newbin) % 4: newbin.append(0)
    j["bufferViews"].append({"buffer": 0, "byteOffset": len(newbin), "byteLength": len(data)}); newbin += data
    j.setdefault("images", []).append({"bufferView": len(j["bufferViews"]) - 1, "mimeType": "image/png", "name": f"emissive_{Path(path).stem}"})
    j.setdefault("textures", []).append({"source": len(j["images"]) - 1, "sampler": 0})
    for m in j["materials"]:
        if (m.get("name") or "").lower().endswith(name.lower()) or name == "*":
            m["emissiveTexture"] = {"index": len(j["textures"]) - 1}; m["emissiveFactor"] = [1, 1, 1]
if color:
    for m in j["materials"]: m.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = [color[0], color[1], color[2], 1.0]
j["buffers"] = [{"byteLength": len(newbin)}]
js = json.dumps(j, separators=(",", ":")).encode()
while len(js) % 4: js += b" "
while len(newbin) % 4: newbin.append(0)
with open(out, "wb") as f:
    f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(newbin)))
    f.write(struct.pack("<I4s", len(js), b"JSON")); f.write(js)
    f.write(struct.pack("<I4s", len(newbin), b"BIN\0")); f.write(newbin)
print(f"wrote {out} ({len(replace)} textures replaced)")
