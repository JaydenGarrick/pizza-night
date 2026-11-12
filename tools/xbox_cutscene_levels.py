#!/usr/bin/env python3
"""Map each Xbox cutscene to the city cell / interior it plays in (by the first camera position vs ENS placement bounds), export missing
interior cells as levels (public/levels/XB_<CELL>) and write public/xbox_cutscenes/levels.json {cutscene: level}.
usage: xbox_cutscene_levels.py [--no-export]"""
import sys, json, subprocess, re
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.ens import parse_ens
index = json.load(open("intermediate/xbox/pack_index.json")); packs_dir = Path("intermediate/xbox/packs")
# cell bounds from ENS placements (D3D coords)
cells = {}
for pk, ents in index.items():
    for n, t, o, s in ents:
        if t != 8: continue
        try: _h, recs = parse_ens(XBPack((packs_dir / f"{pk}.pack").read_bytes()).resource(n, 8))
        except Exception: continue
        T = np.array([r["M"][3, :3] for r in recs], float) if recs else None
        if T is None or len(T) < 3: continue
        T = T[np.linalg.norm(T, axis=1) > 1.0]                       # drop origin-relative records
        if len(T) < 3: continue
        cells[n] = (pk, T.min(0), T.max(0), len(T))
print(len(cells), "cells with placements")
idx = json.load(open("public/xbox_cutscenes/index.json")); levels = {}; need_export = {}
INTERIOR = re.compile(r"^[A-Z]\d{2}I\d{2}$|^X[A-Z]\d{2}$")          # E39I02 (building interior), XG01 (special interior level)
import struct
def glb_bounds(path):
    g = Path(path).read_bytes(); jl = struct.unpack_from("<I", g, 12)[0]; J = json.loads(g[20:20 + jl]); lo = np.full(3, 1e9); hi = np.full(3, -1e9)
    for m in J.get("meshes", []):
        for pr in m["primitives"]:
            a = J["accessors"][pr["attributes"]["POSITION"]]
            if "min" in a: lo = np.minimum(lo, a["min"]); hi = np.maximum(hi, a["max"])
    return lo, hi
_mesh_bounds = {}
def level_bounds(cell):
    """world bbox (D3D coords) of an exported level: the room mesh '<cell>R' when it exists (ENS placement bounds and huge props are
    far too loose), else the union of its statics smaller than 300 m (ground, placeholders and giant barriers excluded)"""
    if cell in _mesh_bounds: return _mesh_bounds[cell]
    st = Path(f"public/levels/XB_{cell}/stage.json")
    if not st.exists() or "interior" not in json.load(open(st)):
        pk = cells[cell][0]; subprocess.run([sys.executable, "-I", "tools/xbox_export_cell.py", cell, "--out", f"public/levels/XB_{cell}"], capture_output=True, text=True)
    if not st.exists(): _mesh_bounds[cell] = None; return None
    lo = np.full(3, 1e9); hi = np.full(3, -1e9); room = None
    for pl in json.load(open(st))["statics"]:
        try: a, b = glb_bounds("." + pl["url"] if pl["url"].startswith("/") else pl["url"])
        except Exception: continue
        if a[0] > 1e8: continue
        a = np.array(a) + pl["pos"]; b = np.array(b) + pl["pos"]
        if pl["url"].lower().endswith(f"__{cell.lower()}r.glb"): room = (a, b); break
        if np.linalg.norm((a + b) / 2) < 4 and (b - a).max() < 10: continue      # origin placeholder
        if "city_ground" in pl["url"].lower() or (b - a).max() > 300: continue
        lo = np.minimum(lo, a); hi = np.maximum(hi, b)
    if room: lo, hi = room
    if lo[0] > 1e8: _mesh_bounds[cell] = None; return None
    lo, hi = np.array([lo[0], lo[1], -hi[2]]), np.array([hi[0], hi[1], -lo[2]])   # three.js -> D3D z
    _mesh_bounds[cell] = (lo, hi); return _mesh_bounds[cell]
def box_dist(p, lo, hi):
    d = np.maximum(np.maximum(lo - p, p - hi), 0); return float(np.linalg.norm(d))
for c in idx["cutscenes"]:
    votes = {}; ncam = 0; outside = 0
    for s in c["shots"]:
        sc = json.load(open(f"public/xbox_cutscenes/{s['name']}/scene.json"))
        if not sc.get("camera"): continue
        ncam += 1; p = sc["camera"]["pos"][len(sc["camera"]["pos"]) // 2]; cam = np.array([p[0], p[1], -p[2]])
        cands = sorted((float(np.prod(hi - lo + 1)), n) for n, (pk, lo, hi, cnt) in cells.items() if INTERIOR.match(n) and np.all(cam >= lo - 40) and np.all(cam <= hi + 40))
        hits = []
        for vol, n in cands:
            b = level_bounds(n)
            if b is None: continue
            d = box_dist(cam, b[0], b[1])
            # inside the room box -> that room; a camera hovering up to 25 m outside a box counts only deep underground (X arenas
            # at y < -100 have no city alternative); at street level the city is the right backdrop
            if d <= 0 or (d <= 25 and cam[1] < -100) or (d <= 8 and re.match(r"^[A-Z]\d{2}I\d{2}$", n)): hits.append((d, float(np.prod(b[1] - b[0] + 1)), n))   # building interiors: cameras sit JUST outside the room mesh (8 m, like the viewer rig); 25 m let a 20 m street shot (Rhino) claim a shop
        hits.sort()
        if hits:
            votes[hits[0][2]] = votes.get(hits[0][2], 0) + 1
            if hits[0][0] > 0: outside += 1            # camera just outside the room mesh: the building's entrance/hallway pieces live in the city cell
    if not ncam: levels[c["name"]] = ["XB_CITY"]; print(f"{c['name']:22s} no camera -> XB_CITY"); continue
    ranked = sorted(votes.items(), key=lambda kv: -kv[1])
    # story sets (X levels) are split into rooms (XF02 bank office, XF03 lobby, XF01 vault corridor...): a shot in one room looks through
    # doorways into the others, so load the whole connected cluster (rooms of the same set within 60 m of each other)
    def box_gap(a, b): d = np.maximum(np.maximum(a[0] - b[1], b[0] - a[1]), 0); return float(np.linalg.norm(d))
    extra = []
    for n, v in list(ranked):
        if not n.startswith("X"): continue
        seen = {n}; stack = [n]
        while stack:
            cur = stack.pop(); b = level_bounds(cur)
            if b is None: continue
            for o in cells:
                if o in seen or o[:2] != cur[:2] or not INTERIOR.match(o): continue
                bo = level_bounds(o)
                if bo is not None and box_gap(b, bo) < 60: seen.add(o); stack.append(o)
        for o in sorted(seen):
            if o not in dict(ranked) and o not in extra: extra.append(o)
    ranked = ranked + [(o, 0) for o in extra]
    def is_interior(n):
        try: return bool(json.load(open(f"public/levels/XB_{n}/stage.json")).get("interior"))
        except Exception: return True
    def grp(n): return n[:3] if re.match(r"^[A-Z]\d{2}I\d{2}$", n) else (n[:2] if n.startswith("X") else n)   # rooms of one building (D27I02/03/04) or one story set (XF01..06) count together
    main_votes = sum(v for n, v in ranked if grp(n) == grp(ranked[0][0])) if ranked else 0
    if ranked and main_votes * 2 >= ncam:                              # at least half the shots sit inside the main level / building
        lv = [f"XB_{n}" for n, v in ranked]                             # every level that any shot sits in (classroom + lab...)
        if sum(v for n, v in ranked) < ncam or not all(is_interior(n) for n, v in ranked) or (outside and ranked[0][0][0] != "X"): lv.append("XB_CITY")   # outside shots / street-level sets / hallways in the city cell
        levels[c["name"]] = lv
        for n, v in ranked: need_export.setdefault(f"XB_{n}", n)
    else: levels[c["name"]] = ["XB_CITY"] + [f"XB_{n}" for n, v in ranked]
    for n, v in ranked: need_export.setdefault(f"XB_{n}", n)
    print(f"{c['name']:22s} {ncam} cams -> {levels[c['name']]}   votes {votes}")
if "--no-export" not in sys.argv:
    for lvl, cell in need_export.items():
        if (Path("public/levels") / lvl / "stage.json").exists(): continue
        print("exporting", lvl); r = subprocess.run([sys.executable, "-I", "tools/xbox_export_cell.py", cell, "--out", f"public/levels/{lvl}"], capture_output=True, text=True)
        print("  ", (r.stdout.strip().splitlines() or ["?"])[-1][:160])
json.dump(levels, open("public/xbox_cutscenes/levels.json", "w"), indent=1); print("wrote levels.json:", len(levels), "cutscenes;", sorted({l for v in levels.values() for l in v}))
