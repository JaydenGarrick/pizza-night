#!/usr/bin/env python3
"""Export a map's BSP world geometry to public/levels/<Map>/bsp.glb and point stage.json at it.
usage: export_bsp.py MAP.whr [--scale 0.02] [--sky]"""
import sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet
from ue2.bsp import load_bsp, PF_INVISIBLE, PF_PORTAL, PF_FAKEBACKDROP, PF_TWOSIDED, PF_MASKED, PF_TRANSLUCENT
from ue2.gltf import GLB
from ue2.materials import resolve_material, TextureCache
from ue2 import convert as C

args = sys.argv[1:]
scale = float(args[args.index("--scale") + 1]) if "--scale" in args else 0.02
keep_sky = "--sky" in args
map_path = Path([a for a in args if not a.startswith("--") and not a.replace('.', '').isdigit()][0]).resolve(); root = map_path.parents[1]
pset = PackageSet([root]); pkg = pset.open(map_path)
models = sorted(pkg.exports_of_class("Model"), key=lambda e: -e.size)
m = load_bsp(pkg, models[0])
P = C.vec(m["points"]) * scale; V = C.vec(m["vectors"])
glb = GLB(); tc = TextureCache(glb)
groups = {}   # surf material key -> {pos, nrm, uv, idx}
mat_info = {}
skipped = {"invisible": 0, "portal": 0, "sky": 0, "degenerate": 0}
for n in m["nodes"]:
    if n["nverts"] < 3: continue
    s = m["surfs"][n["isurf"]]; pf = s["flags"]
    if pf & PF_INVISIBLE: skipped["invisible"] += 1; continue
    if pf & PF_PORTAL: skipped["portal"] += 1; continue
    if pf & PF_FAKEBACKDROP and not keep_sky: skipped["sky"] += 1; continue
    key = s["material"].full if s["material"] else "None"
    if key not in mat_info:
        diffuse, info = resolve_material(s["material"]) if s["material"] else (None, {"alpha": None, "two_sided": False, "emissive": None, "size": None})
        mat_info[key] = (diffuse, info)
    diffuse, info = mat_info[key]
    g = groups.setdefault(key, {"pos": [], "nrm": [], "uv": [], "idx": [], "two_sided": False, "flags": 0})
    g["flags"] |= pf
    if pf & PF_TWOSIDED: g["two_sided"] = True
    vidx = m["verts"][n["ivert"]:n["ivert"] + n["nverts"]]
    pts = P[vidx]
    base = m["points"][s["pbase"]]; tu = m["vectors"][s["vtu"]]; tv = m["vectors"][s["vtv"]]
    usz, vsz = (info.get("size") or (256, 256))
    rel = m["points"][vidx] - base
    uv = np.stack([rel @ tu / usz, rel @ tv / vsz], axis=1)
    # polygon normal from the node plane (UE), converted; orient winding so the geometric normal agrees
    pn = C.vec(np.array(n["plane"][:3]))
    geo = np.zeros(3)                                   # Newell polygon normal (robust to collinear leading verts)
    for k in range(len(pts)):
        a = pts[k]; b = pts[(k + 1) % len(pts)]
        geo += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
    if np.linalg.norm(geo) < 1e-12: skipped["degenerate"] += 1; continue
    order = list(range(len(pts)))
    if np.dot(geo, pn) < 0: order = order[::-1]
    base_i = len(g["pos"])
    for k in order:
        g["pos"].append(pts[k]); g["nrm"].append(pn); g["uv"].append(uv[k])
    for k in range(1, len(order) - 1):
        g["idx"] += [base_i, base_i + k, base_i + k + 1]
prims = []
for key, g in groups.items():
    diffuse, info = mat_info[key]
    ti = tc.index(diffuse) if diffuse else None
    alpha = "MASK" if g["flags"] & PF_MASKED else ("BLEND" if g["flags"] & PF_TRANSLUCENT else info.get("alpha"))
    mat = glb.material(key, ti, alpha, g["two_sided"] or info.get("two_sided", False), tc.index(info["emissive"]) if info.get("emissive") else None)
    pos = np.array(g["pos"], dtype=np.float32); nrm = np.array(g["nrm"], dtype=np.float32); uv = np.array(g["uv"], dtype=np.float32); idx = np.array(g["idx"], dtype=np.uint32)
    prims.append({"attributes": {"POSITION": glb.accessor(pos, 34962, minmax=True), "NORMAL": glb.accessor(nrm, 34962), "TEXCOORD_0": glb.accessor(uv, 34962)}, "indices": glb.accessor(idx, 34963), "material": mat, "mode": 4})
glb.j["meshes"].append({"name": f"{pkg.name}_bsp", "primitives": prims})
node = glb.node(name="bsp", mesh=0); glb.j["scenes"][0]["nodes"] = [node]
out_dir = Path("public/levels") / pkg.name; out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / "bsp.glb"; size = glb.write(out)
stage_path = out_dir / "stage.json"
if stage_path.exists():
    st = json.loads(stage_path.read_text()); st["bsp"] = f"/public/levels/{pkg.name}/bsp.glb"; stage_path.write_text(json.dumps(st))
tris = sum(len(g["idx"]) // 3 for g in groups.values())
print(f"{pkg.name}: bsp {tris} tris, {len(groups)} materials, skipped {skipped} -> {out} ({size/1e6:.1f} MB)")
