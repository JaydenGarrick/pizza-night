#!/usr/bin/env python3
"""Bulk up a skinned character: push vertices along their normals by an amount per bone region (weighted by skin weights), in bind space.
usage: bulk_mesh.py MODEL.glb --out OUT.glb [--inflate 'regex=metres' ...]   default: a stockier torso, shoulders and arms
e.g. --inflate 'spine_0[23]=0.04' --inflate '(upper_arm|shoulder)=0.03'"""
import sys, re
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_io import read_glb, write_glb, acc_read, acc_write_inplace

args = sys.argv[1:]; src = args[0]; out = args[args.index("--out") + 1]
rules = [a for i, a in enumerate(args) if i > 0 and args[i - 1] == "--inflate"]
if not rules: rules = ["^spine_01$=0.02", "^spine_0[234]$=0.04", "^neck=0.012", "_shoulder$=0.035", "_clavicle$=0.03", "_upper_arm$=0.03", "_lower_arm$=0.022", "_hand$=0.008", "^hip$=0.02", "_upper_leg$=0.018", "_lower_leg$=0.01"]
rules = [(re.compile(r.rsplit("=", 1)[0]), float(r.rsplit("=", 1)[1])) for r in rules]
j, binb = read_glb(src); names = [n.get("name", "") for n in j["nodes"]]
def amount(bone_name):
    for rx, v in rules:
        if rx.search(bone_name): return v
    return 0.0
total = 0
for node in j["nodes"]:
    if node.get("mesh") is None or node.get("skin") is None: continue
    joints = j["skins"][node["skin"]]["joints"]; per_joint = np.array([amount(names[ji]) for ji in joints], dtype=np.float32)
    for prim in j["meshes"][node["mesh"]]["primitives"]:
        at = prim["attributes"]
        if "JOINTS_0" not in at or "NORMAL" not in at: continue
        pos = acc_read(j, binb, at["POSITION"]).astype(np.float32); nrm = acc_read(j, binb, at["NORMAL"]).astype(np.float32)
        jn = acc_read(j, binb, at["JOINTS_0"]).astype(np.int64); wt = acc_read(j, binb, at["WEIGHTS_0"]).astype(np.float32)
        push = (per_joint[jn] * wt).sum(axis=1)                      # metres per vertex, blended by skin weight
        nl = np.linalg.norm(nrm, axis=1, keepdims=True); nl[nl == 0] = 1
        pos += nrm / nl * push[:, None]; acc_write_inplace(j, binb, at["POSITION"], pos); total += int((push > 0).sum())
write_glb(out, j, binb); print(f"bulked {total} vertices -> {out}")
