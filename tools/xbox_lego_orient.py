#!/usr/bin/env python3
"""Decide each generic-building ring's footprint orientation from the game's own low-detail city mesh (CITY S_CITYLOD: every building as a
box with a roof).  The lego records give a centre, a w x d unit ring and a yaw, but about a third of the non-square rings render 90 deg
off (the AC62 alley ring sits on the sidewalk; cutscene cameras end up inside buildings) and no record field predicts which, while the
LOD mesh always shows the real footprint.  For every non-square ring: sample its footprint as placed and rotated +90, score = fraction of
samples under an LOD roof minus fraction on the road/sidewalk mesh (public/pizza/roads.json), pick the better when the margin is clear.
Writes intermediate/xbox/lego_orient.json {cell: {record_index: dyaw_deg}} for tools/xbox/lego_mesh.py and xbox_fix_fireescapes.py.
Also fixes the yaw sign: the records' yaw is a left-handed rotation, so after the D3D->glTF z flip it must be applied negated (odd-angle
blocks like A03 at 27 deg only fit the LOD that way)."""
import sys, json, math, collections
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from glbtools import read_glb
from xbpack import XBPack
from xbox.lego import parse_lego
from xbox.lego_mesh import ring_axes
j, b = read_glb("public/models/xbox/static/CITY__s_citylod.glb")
def acc(i):
    a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]; ct = {5126: "f4", 5121: "u1", 5123: "u2", 5125: "u4"}[a["componentType"]]; k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    return np.frombuffer(bytes(b), dtype=ct, count=a["count"] * k, offset=bv.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(a["count"], k)
P = []; T = []; base = 0
for m in j["meshes"]:
    for pr in m["primitives"]:
        p = acc(pr["attributes"]["POSITION"]).astype(float); i = acc(pr["indices"]).astype(int).reshape(-1, 3); P.append(p); T.append(i + base); base += len(p)
P = np.concatenate(P); T = np.concatenate(T); tri = P[T]; n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
roofs = tri[(np.abs(n[:, 1]) > 0.7) & (tri[:, :, 1].min(1) > 2.5)]   # horizontal faces above ground = roofs / setbacks (the LOD's winding is inverted: normals point down)
G = 16.0; grid = collections.defaultdict(list)
for k, t in enumerate(roofs):
    for gx in range(int(math.floor(t[:, 0].min() / G)), int(math.floor(t[:, 0].max() / G)) + 1):
        for gz in range(int(math.floor(t[:, 2].min() / G)), int(math.floor(t[:, 2].max() / G)) + 1): grid[(gx, gz)].append(k)
def under_roof(x, z, ytop=0.0):
    """a LOD roof over (x, z) at least as high as the ring's top - 8 m: a lower neighbour's roof must not count for a tall ring"""
    for k in grid.get((int(math.floor(x / G)), int(math.floor(z / G))), ()):
        t = roofs[k]
        if t[:, 1].max() < ytop - 8: continue
        (x1, z1), (x2, z2), (x3, z3) = t[:, [0, 2]]
        d1 = (x - x2) * (z1 - z2) - (x1 - x2) * (z - z2); d2 = (x - x3) * (z2 - z3) - (x2 - x3) * (z - z3); d3 = (x - x1) * (z3 - z1) - (x3 - x1) * (z - z1)
        if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)): return True
    return False
rd = json.load(open("public/pizza/roads.json")); cs = rd["cs"] if not isinstance(rd["cs"], list) else rd["cs"][0]; roads = set(map(tuple, rd["cells"]))
on_road = lambda x, z: (int(math.floor(x / cs)), int(math.floor(z / cs))) in roads
def samples(rec, dyaw):
    cx, _, cz = rec["pos"]; w, d = rec["w"], rec["d"]; ax, az = ring_axes(rec["yaw"] + dyaw); pts = []
    for lx in np.arange(-w / 2 + 1, w / 2, 2.0):
        for lz in np.arange(-d / 2 + 1, d / 2, 2.0): pts.append((cx + ax[0] * lx + az[0] * lz, -cz + ax[1] * lx + az[1] * lz))
    return pts
def score(rec, dyaw):
    pts = samples(rec, dyaw); r = sum(under_roof(x, z, rec["pos"][1] + rec["h"]) for x, z in pts) / len(pts); s = sum(on_road(x, z) for x, z in pts) / len(pts); return r - s, r, s
def diff_score(rec):
    """compare only the parts of the two footprints that differ (the w-d strips): roof fraction and road fraction of A-only vs B-only samples"""
    A = samples(rec, 0); B = samples(rec, 90); keyA = {(round(x, 1), round(z, 1)) for x, z in A}; keyB = {(round(x, 1), round(z, 1)) for x, z in B}
    cx, cz = rec["pos"][0], -rec["pos"][2]; ax0, az0 = ring_axes(rec["yaw"]); ax1, az1 = ring_axes(rec["yaw"] + 90); w, d = rec["w"], rec["d"]
    def inside(x, z, ax, az): lx = (x - cx) * ax[0] + (z - cz) * ax[1]; lz = (x - cx) * az[0] + (z - cz) * az[1]; return abs(lx) <= w / 2 and abs(lz) <= d / 2
    Aonly = [(x, z) for x, z in A if not inside(x, z, ax1, az1)]; Bonly = [(x, z) for x, z in B if not inside(x, z, ax0, az0)]
    if not Aonly or not Bonly: return 0.0, 0.0
    yt = rec["pos"][1] + rec["h"]; ra = sum(under_roof(x, z, yt) for x, z in Aonly) / len(Aonly); rb = sum(under_roof(x, z, yt) for x, z in Bonly) / len(Bonly)
    sa = sum(on_road(x, z) for x, z in Aonly) / len(Aonly); sb = sum(on_road(x, z) for x, z in Bonly) / len(Bonly)
    return (rb - ra), (sa - sb)        # positive = +90 is better under roofs / less on road
cells = sorted({p["mesh"].split(".")[0] for p in json.load(open("public/levels/XB_CITY/stage.json"))["statics"] if p.get("class") == "lego"})
out = {}; stat = collections.Counter(); margins = []
for cell in cells:
    ens = XBPack((Path("intermediate/xbox/packs") / f"{cell}.pack").read_bytes()).resource(cell, 8); L = parse_lego(ens) if ens else None
    if not L: continue
    for i, r in enumerate(L["records"]):
        if not r["lego"] or not r["h"] or r["w"] == r["d"] or r["yaw"] > 360: continue
        droof, droad = diff_score(r); m = droof + droad; margins.append(round(m, 1))
        if m > 0.3: out.setdefault(cell, {})[str(i)] = 90; stat["rotated +90"] += 1
        elif m < -0.3: stat["kept"] += 1
        else: stat["tie (kept)"] += 1
        if cell == "H77" and i == 224: print("AC62 ring (H77 #224): roof gain", round(droof, 2), "road gain", round(droad, 2), "->", "+90" if m > 0.3 else "kept")
print("non-square rings:", dict(stat)); print("margin histogram:", sorted(collections.Counter(round(m, 1) for m in margins).items()))
Path("intermediate/xbox/lego_orient.json").write_text(json.dumps(out, indent=0)); print("wrote intermediate/xbox/lego_orient.json for", len(out), "cells")
