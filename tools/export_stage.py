#!/usr/bin/env python3
"""Export a map's static-mesh actors: unique meshes -> public/models/static/*.glb, placements -> public/levels/<Map>/stage.json
usage: export_stage.py MAP.whr [--scale 0.02] [--limit N]"""
import sys, json, math
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet, ObjRef
from ue2.props import object_props
from ue2.staticmesh import load_staticmesh
from ue2.gltf import GLB
from ue2.materials import resolve_material, TextureCache
from ue2 import convert as C

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
scale = float(opt("--scale", "0.02")); limit = int(opt("--limit", "0"))
map_path = Path(args[0]).resolve(); root = map_path.parents[1]
pset = PackageSet([root]); pkg = pset.open(map_path)
out_models = Path("public/models/static"); out_models.mkdir(parents=True, exist_ok=True)
out_level = Path("public/levels") / pkg.name; out_level.mkdir(parents=True, exist_ok=True)

def export_static(p, e, dst):
    m = load_staticmesh(p, e)
    glb = GLB(); tc = TextureCache(glb)
    P = C.vec(m["positions"].astype(np.float64)) * scale
    N = C.vec(m["normals"].astype(np.float64))
    uv = m["uvs"][0] if m["uvs"] else np.zeros((len(P), 2), dtype=np.float32)
    pos_acc = glb.accessor(P.astype(np.float32), 34962, minmax=True); nrm_acc = glb.accessor(N.astype(np.float32), 34962); uv_acc = glb.accessor(uv.astype(np.float32), 34962)
    idx = m["indices"]
    prims = []
    for si, (f4, first, fv, lv, fe, nfaces) in enumerate(m["sections"]):
        sel = idx[first:first + nfaces * 3].reshape(-1, 3)[:, [0, 2, 1]].flatten()   # handedness flip -> reverse winding
        if len(sel) == 0: continue
        ref = m["materials"][si] if si < len(m["materials"]) else None
        diffuse, info = resolve_material(ref) if ref else (None, {"alpha": None, "two_sided": False, "emissive": None})
        ti = tc.index(diffuse) if diffuse else None
        mat = glb.material(ref.full if ref else f"mat{si}", ti, info["alpha"], info["two_sided"], tc.index(info["emissive"]) if info.get("emissive") else None)
        prims.append({"attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc, "TEXCOORD_0": uv_acc}, "indices": glb.accessor(sel.astype(np.uint32), 34963), "material": mat, "mode": 4})
    glb.j["meshes"].append({"name": e.name, "primitives": prims})
    n = glb.node(name=e.name, mesh=0); glb.j["scenes"][0]["nodes"] = [n]
    glb.write(dst)
    return len(P), len(idx) // 3

def rot_quat(rot):
    """UE rotator (pitch, yaw, roll in 65536 units) -> glTF quaternion [x,y,z,w]."""
    p, y, rl = [v / 65536.0 * 2 * math.pi for v in rot]
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(rl), math.cos(rl)
    fwd = np.array([cp * cy, cp * sy, sp]); right = np.array([sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp]); up = np.array([-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp])
    R_ue = np.stack([fwd, right, up], axis=1)
    R = C.M @ R_ue @ C.M.T
    # matrix -> quaternion
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1) * 2; w = 0.25 * s; x = (R[2, 1] - R[1, 2]) / s; yq = (R[0, 2] - R[2, 0]) / s; z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; w = (R[2, 1] - R[1, 2]) / s; x = 0.25 * s; yq = (R[0, 1] + R[1, 0]) / s; z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; w = (R[0, 2] - R[2, 0]) / s; x = (R[0, 1] + R[1, 0]) / s; yq = 0.25 * s; z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; w = (R[1, 0] - R[0, 1]) / s; x = (R[0, 2] + R[2, 0]) / s; yq = (R[1, 2] + R[2, 1]) / s; z = 0.25 * s
    return [float(x), float(yq), float(z), float(w)]

placements = []; meshes = {}; skipped = 0
for e in pkg.exports:
    if e.cls in ("Class", "Package", "Model", "Polys", "Brush", "StaticMesh"): continue
    try:
        props, _, _ = object_props(pkg, e)
    except Exception:
        continue
    sm = props.get("StaticMesh"); loc = props.get("Location")
    if not isinstance(sm, ObjRef) or not sm or loc is None: continue
    if props.get("bHidden") or props.get("DrawType", 2) not in (2, 7, 8) and "DrawType" in props: skipped += 1; continue
    p, me = sm.resolve()
    if not me: skipped += 1; continue
    key = f"{p.name}.{me.name}"
    if key not in meshes:
        dst = out_models / f"{p.name}__{me.name}.glb"
        if not dst.exists():
            try: export_static(p, me, dst)
            except Exception as ex: print(f"  ERR {key}: {type(ex).__name__}: {ex}"); meshes[key] = None; continue
        meshes[key] = f"/public/models/static/{dst.name}"
        if limit and len(meshes) >= limit: break
    if meshes[key] is None: continue
    ds = props.get("DrawScale", 1.0); d3 = props.get("DrawScale3D", (1.0, 1.0, 1.0))
    s = C.vec([d3[0] * ds, d3[1] * ds, d3[2] * ds]); s = [abs(float(v)) for v in s]
    placements.append({"actor": e.name, "class": e.cls, "mesh": key, "url": meshes[key], "tag": props.get("Tag"),
                       "pos": [float(v) for v in C.vec(loc) * scale], "quat": rot_quat(props.get("Rotation", (0, 0, 0))), "scale": s})
stage = {"map": pkg.name, "unit_scale": scale, "statics": placements, "bsp": None}
(out_level / "stage.json").write_text(json.dumps(stage))
print(f"{pkg.name}: {len(placements)} placements, {len([m for m in meshes.values() if m])} unique meshes exported, skipped {skipped} -> {out_level/'stage.json'}")
