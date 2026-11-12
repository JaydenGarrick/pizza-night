#!/usr/bin/env python3
"""Copy animation clips from one character GLB into another, matching bones by name (channels for bones the target lacks are dropped;
translation / scale tracks are dropped too, so the target keeps its own bone lengths and only takes the rotations).
usage: merge_clips.py --into A.glb --from B.glb --clips Name1,Name2 [--suffix _x] [--all] --out OUT.glb"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_io import read_glb, write_glb, acc_read, acc_append

def opt(flag, default=None):
    a = sys.argv; return a[a.index(flag) + 1] if flag in a else default
dst, binb = read_glb(opt("--into")); src, sbin = read_glb(opt("--from")); suffix = opt("--suffix", "")
names = opt("--clips", "").split(",") if opt("--clips") else [a["name"] for a in src.get("animations", [])]
dnode = {n.get("name"): i for i, n in enumerate(dst["nodes"])}; have = {a["name"] for a in dst.get("animations", [])}
added = 0
for an in src.get("animations", []):
    if an["name"] not in names: continue
    new = {"name": an["name"] + suffix, "channels": [], "samplers": []}; dropped = set(); smap = {}
    for ch in an["channels"]:
        nm = src["nodes"][ch["target"]["node"]].get("name"); path = ch["target"]["path"]
        if nm not in dnode: dropped.add(nm); continue
        if path != "rotation": continue
        si = ch["sampler"]
        if si not in smap:
            s = an["samplers"][si]; ia = src["accessors"][s["input"]]; oa = src["accessors"][s["output"]]
            ti = acc_append(dst, binb, acc_read(src, sbin, s["input"]), ia["componentType"], ia["type"], with_bounds=True)
            to = acc_append(dst, binb, acc_read(src, sbin, s["output"]), oa["componentType"], oa["type"])
            new["samplers"].append({"input": ti, "output": to, "interpolation": s.get("interpolation", "LINEAR")}); smap[si] = len(new["samplers"]) - 1
        new["channels"].append({"sampler": smap[si], "target": {"node": dnode[nm], "path": path}})
    if not new["channels"]: print(f"  {an['name']}: no usable channels, skipped"); continue
    if new["name"] in have: dst["animations"] = [a for a in dst["animations"] if a["name"] != new["name"]]
    dst.setdefault("animations", []).append(new); added += 1
    print(f"  {new['name']}: {len(new['channels'])} rotation channels" + (f", dropped bones: {', '.join(sorted(dropped))}" if dropped else ""))
write_glb(opt("--out"), dst, binb); print(f"merged {added} clips -> {opt('--out')} ({len(dst['animations'])} clips)")
