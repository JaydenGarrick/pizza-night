#!/usr/bin/env python3
"""Regenerate only the generic-building GLBs (public/models/xbox/static/<CELL>__lego.glb) for city cells, leaving the stage files alone.
usage: xbox_relego.py [CELL ...]   (default: every cell with a lego placement in public/levels/XB_CITY/stage.json)"""
import sys, json, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.xbmesh import parse
from xbox.lego import parse_lego
from xbox.lego_mesh import build_lego
ORIENT = json.load(open("intermediate/xbox/lego_orient.json")) if Path("intermediate/xbox/lego_orient.json").exists() else {}   # per-ring +90 fixes (tools/xbox_lego_orient.py)
from PIL import Image
index = json.load(open("intermediate/xbox/pack_index.json")); packs_dir = Path("intermediate/xbox/packs"); static_dir = Path("public/models/xbox/static")
cells = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted({p["mesh"].split(".")[0] for p in json.load(open("public/levels/XB_CITY/stage.json"))["statics"] if p.get("class") == "lego"})
pack_cache = {}
def pack(n):
    if n not in pack_cache: pack_cache[n] = XBPack((packs_dir / f"{n}.pack").read_bytes())
    return pack_cache[n]
tex_where, mesh_where, ifl_where = {}, {}, {}
for pkn in ["CITY", "GAME"] + [k for k in index if k.startswith(("CITY_STRIP", "CITY_EXTRA"))] + cells:
    for nm, t, o, s in index.get(pkn, []):
        if t == 4: tex_where.setdefault(nm.lower(), pkn)
        elif t == 0x11: mesh_where.setdefault(nm.lower(), pkn)
        elif t == 6: ifl_where.setdefault(nm.lower(), pkn)
def load_tex(name):
    if name.lower() not in tex_where and name.lower() in ifl_where:
        ifl = pack(ifl_where[name.lower()]).resource(name.upper(), 6) or pack(ifl_where[name.lower()]).resource(name, 6)
        if ifl:
            first = ifl.decode("latin-1").replace("\r", "\n").split("\n")[0].strip()
            if "." in first: first = first.rsplit(".", 1)[0]
            if first and first.lower() != name.lower(): return load_tex(first)
    pkn = tex_where.get(name.lower())
    if not pkn: return None
    try: return Image.open(io.BytesIO(pack(pkn).resource(name, 4))).convert("RGBA")
    except Exception: return None
def load_ring(name):
    pkn = mesh_where.get(name.lower()); return parse(pack(pkn).resource(name, 0x11)) if pkn else None
tot = 0
for cell in cells:
    ens = pack(cell).resource(cell, 8); L = parse_lego(ens) if ens else None
    if not L: print(cell, "no lego block"); continue
    n = build_lego(cell, L, static_dir / f"{cell}__lego.glb", load_tex, load_ring, orient=ORIENT); tot += n or 0; print(f"{cell}: {n} segments")
print("done", len(cells), "cells", tot, "segments")
