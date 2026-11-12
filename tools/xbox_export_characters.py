#!/usr/bin/env python3
"""Export every skinned (stride-32) XBMESH found in character/story packs to public/models/xbox/characters/."""
import sys, json, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.xbmesh import parse
index = json.load(open("intermediate/xbox/pack_index.json"))
out = Path("public/models/xbox/characters"); out.mkdir(parents=True, exist_ok=True)
seen = set(); done = 0; skipped = 0
for pack, ents in sorted(index.items()):
    if pack[0] in "ABCDEFGHIJKXZ" and len(pack) <= 6 and not pack.startswith("CITY"): continue   # city cells
    meshes = [n for n, t, o, s in ents if t == 0x11]
    if not meshes: continue
    pk = XBPack((Path("intermediate/xbox/packs") / f"{pack}.pack").read_bytes())
    for mn in meshes:
        key = mn.lower()
        if key in seen: continue
        try: m = parse(pk.resource(mn, 0x11))
        except Exception as ex: skipped += 1; continue
        if not m["sections"] or not any(s["stride"] == 32 for s in m["sections"][0]["subs"]): continue
        seen.add(key)
        r = subprocess.run([sys.executable, "-I", "tools/xbox_export_mesh.py", pack, mn, "--out", str(out / f"{key}.glb")], capture_output=True, text=True)
        if r.returncode == 0: done += 1; print(r.stdout.strip())
        else: skipped += 1; print("ERR", pack, mn, r.stderr.strip().splitlines()[-1][:120])
print(f"exported {done} skinned meshes, skipped {skipped}")
