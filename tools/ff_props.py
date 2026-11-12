#!/usr/bin/env python3
"""F&F-branded delivery props: the navy delivery bag -> public/models/xbox/props/itm_pizzabag_ff.glb, and the 'props' remap (bag + both
pizza boxes, which tools/ff_box.py builds) is added to every public/ff/skin_*.json.  Run ff_box.py first, then this, then copy skin_v1 -> default."""
import sys, json
from pathlib import Path
sys.path.insert(0, "tools")
from glbtools import read_glb, write_glb, swap_image
FF = Path("intermediate/ff"); PR = Path("public/models/xbox/props"); SK = Path("public/ff")
bag_png = open(FF / "itm_pizzabag_ff.png", "rb").read()
j, b = read_glb(PR / "itm_pizzabag.glb"); n = swap_image(j, b, "itm_pizzabag", bag_png); write_glb(PR / "itm_pizzabag_ff.glb", j, b); print("itm_pizzabag.glb -> itm_pizzabag_ff.glb", n, "image(s)")
props = {f"/public/models/xbox/props/{s}.glb": f"/public/models/xbox/props/{s}_ff.glb" for s in ("itm_pizzaboxflat", "itm_pizzabox", "itm_pizzabag")}
for s in ("itm_pizzaboxflat", "itm_pizzabox"): assert (PR / f"{s}_ff.glb").exists(), f"{s}_ff.glb missing: run tools/ff_box.py first"
for sk in sorted(SK.glob("skin_*.json")):
    d = json.load(open(sk)); d["props"] = props; json.dump(d, open(sk, "w"), indent=1)
print("props added to", [s.name for s in SK.glob('skin_*.json')])
