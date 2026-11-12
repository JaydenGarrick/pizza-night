#!/usr/bin/env python3
"""Export a UE2 skeletal mesh (+ textures + animations) to GLB.

usage: export_character.py <package.ukx> [--mesh NAME] [--anim NAME|none] [--out file.glb]
                           [--scale 0.02] [--clips a,b,c] [--textures-dir DIR] [--conj auto|none|all|nonroot|root]
"""
import sys, re, json
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet, ObjRef
from ue2.props import object_props
from ue2.skelmesh import load_skelmesh
from ue2.anim import load_anim
from ue2.texture import load_texture
from ue2.gltf import GLB
from ue2 import convert as C

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args:
        i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
mesh_name = opt("--mesh"); anim_name = opt("--anim"); out = opt("--out"); scale = float(opt("--scale", "0.02"))
clips = opt("--clips"); texdir = opt("--textures-dir"); conj_mode = opt("--conj", "all")
pkg_path = Path(args[0]).resolve()
root = pkg_path.parents[1]
pset = PackageSet([root])
pkg = pset.open(pkg_path)

# ---------------------------------------------------------------- pick objects
skel_exports = pkg.exports_of_class("SkeletalMesh")
if mesh_name:
    skel_exports = [e for e in skel_exports if e.name.lower() == mesh_name.lower()]
if not skel_exports:
    sys.exit("no SkeletalMesh found")
mesh_exp = skel_exports[0]
mesh = load_skelmesh(pkg, mesh_exp)
anim = None
if anim_name != "none":
    anim_exports = pkg.exports_of_class("MeshAnimation")
    if anim_name:
        anim_exports = [e for e in anim_exports if e.name.lower() == anim_name.lower()]
    elif mesh["animation"]:
        a_pkg, a_exp = mesh["animation"].resolve()
        if a_exp: anim_exports = [a_exp]; pkg_anim = a_pkg
    if anim_exports:
        anim = load_anim(pkg, anim_exports[0])
print(f"mesh {mesh_exp.name}: {len(mesh['bones'])} bones, {len(mesh['points'])} points, {len(mesh['wedges'])} wedges, {len(mesh['triangles'])} tris")
if anim: print(f"anim {anim['name']}: {len(anim['sequences'])} sequences, {len(anim['bones'])} bones")

# ---------------------------------------------------------------- materials
def resolve_material(ref, depth=0):
    """Follow Shader/Combiner/FinalBlend etc. to a base Texture. Returns (diffuse_export_tuple, info dict)."""
    info = {"alpha": None, "two_sided": False, "emissive": None}
    seen = 0
    while ref and seen < 8:
        seen += 1
        p, e = ref.resolve()
        if not e:
            return None, info
        cls = e.cls.lower()
        if cls == "texture":
            props, _, _ = object_props(p, e)
            if props.get("bMasked"): info["alpha"] = "MASK"
            elif props.get("bAlphaTexture"): info["alpha"] = "BLEND"
            return (p, e), info
        props, _, _ = object_props(p, e)
        if cls == "shader":
            if props.get("TwoSided"): info["two_sided"] = True
            op = props.get("OutputBlending", 0)
            if op in (1, 2, 3, 4) and props.get("Opacity"): info["alpha"] = "BLEND"
            si = props.get("SelfIllumination")
            if isinstance(si, ObjRef) and si:
                pp, ee = si.resolve()
                if ee and ee.cls.lower() == "texture": info["emissive"] = (pp, ee)
            ref = props.get("Diffuse")
        elif cls in ("combiner",):
            ref = props.get("Material1") or props.get("Material2")
        elif cls in ("finalblend", "texmodifier", "texpanner", "texscaler", "texrotator", "texoscillator", "texcoordsource", "texenvmap", "materialswitch", "materialsequence"):
            if cls == "finalblend":
                if props.get("TwoSided"): info["two_sided"] = True
                if props.get("AlphaTest"): info["alpha"] = "MASK"
                elif props.get("FrameBufferBlending", 0) not in (0,): info["alpha"] = "BLEND"
            ref = props.get("Material") or props.get("Materials")
            if hasattr(ref, "objs"): ref = ref.objs()[0]
        elif cls in ("vertexcolor", "constantcolor", "fadecolor", "cubemap"):
            return None, info
        else:
            ref = props.get("Diffuse") or props.get("Material")
    return None, info

glb = GLB()
tex_cache = {}
def texture_index(pe):
    p, e = pe
    key = (p.name, e.name)
    if key not in tex_cache:
        img, props = load_texture(p, e)
        if texdir:
            Path(texdir).mkdir(parents=True, exist_ok=True); img.save(Path(texdir) / f"{p.name}.{e.name}.png")
        tex_cache[key] = glb.image_png(img, f"{p.name}.{e.name}")
    return tex_cache[key]

mat_indices = []
for mi, (polyflags, texidx) in enumerate(mesh["materials"]):
    ref = mesh["textures"][texidx] if texidx < len(mesh["textures"]) else None
    diffuse, info = resolve_material(ref)
    name = ref.full if ref else f"mat{mi}"
    ti = texture_index(diffuse) if diffuse else None
    ei = texture_index(info["emissive"]) if info["emissive"] else None
    mat_indices.append(glb.material(name, ti, info["alpha"], info["two_sided"], ei))
    print(f"  material[{mi}] {name} -> {'tex ' + diffuse[1].name if diffuse else 'no texture'} alpha={info['alpha']}")
if not mat_indices:
    mat_indices.append(glb.material("default"))

# ---------------------------------------------------------------- skeleton (with convention detection)
bones = mesh["bones"]
nb = len(bones)
ue_pos = np.array([b["pos"] for b in bones]); ue_quat = np.array([b["quat"] for b in bones])
points = mesh["points"].astype(np.float64)

# per-bone dominant vertex centroid (in UE space) for convention check
infl = np.array(mesh["influences"], dtype=np.float64)  # weight, point, bone
dom = {}
for w, pi, bi in infl:
    if w >= 0.6: dom.setdefault(int(bi), []).append(points[int(pi)])

def skeleton_world(conj_flags):
    lt = [C.vec(ue_pos[i]) for i in range(nb)]
    lq = [C.quat(ue_quat[i], conj=conj_flags[i]) for i in range(nb)]
    return C.world_matrices(bones, lt, lq), lt, lq

def score(conj_flags):
    W, _, _ = skeleton_world(conj_flags)
    err = 0; n = 0
    for bi, pts in dom.items():
        if len(pts) < 4: continue
        c = C.vec(np.mean(pts, axis=0))
        err += np.linalg.norm(W[bi][:3, 3] - c); n += 1
    return err / max(n, 1)

modes = {"none": [False] * nb, "all": [True] * nb, "nonroot": [i != 0 for i in range(nb)], "root": [i == 0 for i in range(nb)]}
if conj_mode == "auto":
    scores = {k: score(v) for k, v in modes.items()}
    conj_mode = min(scores, key=scores.get)
    print("  quaternion convention scores (lower=better):", {k: round(v, 2) for k, v in scores.items()}, "->", conj_mode)
conj_flags = modes[conj_mode]
W, local_t, local_q = skeleton_world(conj_flags)

# root transform (UE: actor = RotOrigin * (point - MeshOrigin) * MeshScale), then unit scale
ms = np.array(mesh["mesh_scale"]); mo = np.array(mesh["mesh_origin"]); ro = mesh["rot_origin"]
yaw = ro[1] / 65536.0 * 2 * np.pi; pitch = ro[0] / 65536.0 * 2 * np.pi; roll = ro[2] / 65536.0 * 2 * np.pi
# UE rotator -> rotation matrix (UE space): yaw about Z, pitch about Y, roll about X ; R = Yaw*Pitch*Roll
def rotm_ue(pitch, yaw, roll):
    cy, sy = np.cos(yaw), np.sin(yaw); cp, sp = np.cos(pitch), np.sin(pitch); cr, sr = np.cos(roll), np.sin(roll)
    Ry = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]); Rp = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]]); Rr = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return Ry @ Rp @ Rr
R_ue = rotm_ue(pitch, yaw, roll)
# full UE-space root: p' = R_ue @ ((p - mo) * ms)   => in glTF: M R_ue M^T applied after conversion
R_g = C.M @ R_ue @ C.M.T
root_mat = np.eye(4); root_mat[:3, :3] = R_g * scale
root_mat[:3, 3] = (R_g @ C.vec(-mo * ms)) * scale
if not np.allclose(ms, ms[0]): print("WARNING: non-uniform MeshScale", ms)
K = scale * ms[0]; tA = (R_g @ C.vec(-mo * ms)) * scale; qA = C.quat_from_mat(R_g)
# bake: all local translations *= K; root bone rotated by R_g and offset by tA; recompute world matrices
local_t = [np.asarray(t) * K for t in local_t]
local_t[0] = R_g @ local_t[0] + tA
local_q = [np.asarray(q) for q in local_q]
local_q[0] = C.quat_mul(qA, local_q[0])
W = C.world_matrices(bones, local_t, local_q)
root_mat = np.eye(4)

# ---------------------------------------------------------------- geometry
wedges = mesh["wedges"]; tris = mesh["triangles"]
nw = len(wedges)
w_point = np.array([w[0] for w in wedges]); uv = np.array([[w[1], w[2]] for w in wedges], dtype=np.float32)
pos = ((R_g @ C.vec(points[w_point]).T).T * K + tA).astype(np.float32)
# triangles: reverse winding to compensate handedness flip
idx = np.array([[t[0], t[2], t[1]] for t in tris], dtype=np.uint32)
mat_of_tri = np.array([t[3] for t in tris])
# smooth normals (per point, then per wedge)
pn = np.zeros((len(points), 3))
P = (R_g @ C.vec(points).T).T * K + tA
for a, b, c in idx:
    pa, pb, pc = P[w_point[a]], P[w_point[b]], P[w_point[c]]
    n = np.cross(pb - pa, pc - pa)
    for k in (a, b, c): pn[w_point[k]] += n
ln = np.linalg.norm(pn, axis=1, keepdims=True); pn = pn / np.where(ln == 0, 1, ln)
nrm = pn[w_point].astype(np.float32)
# facing check: average of normal · (centroid - center)
cen = P.mean(0); face_c = (P[w_point[idx[:, 0]]] + P[w_point[idx[:, 1]]] + P[w_point[idx[:, 2]]]) / 3
fn = np.cross(P[w_point[idx[:, 1]]] - P[w_point[idx[:, 0]]], P[w_point[idx[:, 2]]] - P[w_point[idx[:, 0]]])
outward = np.mean(np.sign(np.einsum("ij,ij->i", fn, face_c - cen)))
if outward < 0:
    print("  winding looked inward; flipping"); idx = idx[:, [0, 2, 1]]; nrm = -nrm
# skin weights per point -> 4 influences
jw = {}
for w, pi, bi in infl:
    jw.setdefault(int(pi), []).append((float(w), int(bi)))
J = np.zeros((nw, 4), dtype=np.uint16); Wt = np.zeros((nw, 4), dtype=np.float32)
for wi in range(nw):
    lst = sorted(jw.get(int(w_point[wi]), [(1.0, 0)]), reverse=True)[:4]
    s = sum(w for w, _ in lst) or 1.0
    for k, (w, b) in enumerate(lst): J[wi, k] = b; Wt[wi, k] = w / s

# ---------------------------------------------------------------- nodes
root_node = glb.node(name=f"{mesh_exp.name}_root", matrix=[float(x) for x in root_mat.T.flatten()])
bone_nodes = []
for i, b in enumerate(bones):
    bone_nodes.append(glb.node(name=b["name"].split(":")[-1], translation=[float(x) for x in local_t[i]], rotation=[float(x) for x in local_q[i]]))
for i, b in enumerate(bones):
    if i == 0: continue
    glb.j["nodes"][bone_nodes[b["parent"]]].setdefault("children", []).append(bone_nodes[i])
# inverse bind matrices (bone world -> mesh space); skeleton root attached under root_node
ibm = np.array([np.linalg.inv(W[i]).T.flatten() for i in range(nb)], dtype=np.float32)
skin = {"joints": bone_nodes, "inverseBindMatrices": glb.accessor(ibm), "skeleton": bone_nodes[0], "name": mesh_exp.name}
glb.j["skins"].append(skin)
prims = []
pos_acc = glb.accessor(pos, 34962, minmax=True); nrm_acc = glb.accessor(nrm, 34962); uv_acc = glb.accessor(uv, 34962)
j_acc = glb.accessor(J, 34962); w_acc = glb.accessor(Wt, 34962)
for mi in sorted(set(mat_of_tri.tolist())):
    sel = idx[mat_of_tri == mi].flatten()
    prims.append({"attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc, "TEXCOORD_0": uv_acc, "JOINTS_0": j_acc, "WEIGHTS_0": w_acc},
                  "indices": glb.accessor(sel.astype(np.uint32), 34963), "material": mat_indices[mi] if mi < len(mat_indices) else mat_indices[0], "mode": 4})
glb.j["meshes"].append({"name": mesh_exp.name, "primitives": prims})
mesh_node = glb.node(name=mesh_exp.name, mesh=0, skin=0)
glb.j["nodes"][root_node]["children"] = [bone_nodes[0], mesh_node]
glb.j["scenes"][0]["nodes"] = [root_node]

# ---------------------------------------------------------------- animations
if anim:
    bone_by_name = {b["name"].lower(): i for i, b in enumerate(bones)}
    track_to_node = []
    for (bn, fl, par) in anim["bones"]:
        track_to_node.append(bone_nodes[bone_by_name[bn.lower()]] if bn.lower() in bone_by_name else None)
    want = set(c.lower() for c in clips.split(",")) if clips else None
    exported = 0
    for seq, mc in zip(anim["sequences"], anim["moves"]):
        if want and seq["name"].lower() not in want: continue
        rate = seq["rate"] or 30.0
        nf = max(seq["num_frames"], 1)
        tscale = (nf / mc["track_time"]) if mc["track_time"] > 0 else 1.0
        a = {"name": seq["name"], "channels": [], "samplers": []}
        for ti, tr in enumerate(mc["tracks"]):
            node = track_to_node[ti] if ti < len(track_to_node) else None
            if node is None or (not tr["quat"] and not tr["pos"]): continue
            times = np.array(tr["time"], dtype=np.float32) * tscale / rate if tr["time"] else np.array([0.0], dtype=np.float32)
            conj = conj_flags[bone_by_name[anim["bones"][ti][0].lower()]]
            if tr["quat"]:
                q = C.quat(np.array(tr["quat"]), conj=conj)
                if bone_by_name[anim["bones"][ti][0].lower()] == 0: q = np.array([C.quat_mul(qA, qq) for qq in q])
                q = q.astype(np.float32)
                if len(q) == 1: tq = np.array([0.0], dtype=np.float32)
                else: tq = times[:len(q)] if len(times) >= len(q) else np.linspace(0, (nf - 1) / rate, len(q), dtype=np.float32)
                # ensure shortest-path continuity
                for k in range(1, len(q)):
                    if np.dot(q[k], q[k - 1]) < 0: q[k] = -q[k]
                a["samplers"].append({"input": glb.accessor(tq, minmax=True), "output": glb.accessor(q), "interpolation": "LINEAR"})
                a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": node, "path": "rotation"}})
            if tr["pos"]:
                p = C.vec(np.array(tr["pos"])) * K
                if bone_by_name[anim["bones"][ti][0].lower()] == 0: p = (R_g @ p.T).T + tA
                p = p.astype(np.float32)
                if len(p) == 1: tp = np.array([0.0], dtype=np.float32)
                else: tp = times[:len(p)] if len(times) >= len(p) else np.linspace(0, (nf - 1) / rate, len(p), dtype=np.float32)
                a["samplers"].append({"input": glb.accessor(tp, minmax=True), "output": glb.accessor(p), "interpolation": "LINEAR"})
                a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": node, "path": "translation"}})
        if a["channels"]:
            a["extras"] = {"frames": seq["num_frames"], "rate": rate, "duration": (nf - 1) / rate,
                           "notifies": [{"t": round(t, 4), "fn": fn, "obj": repr(o) if o else None} for t, fn, o in seq["notifies"]]}
            glb.j["animations"].append(a); exported += 1
    print(f"  exported {exported} animation clips")

glb.j["asset"]["extras"] = {"source": f"{pkg.name}.{mesh_exp.name}", "mesh_scale": [float(x) for x in ms], "mesh_origin": [float(x) for x in mo], "rot_origin": list(ro), "unit_scale": scale, "conj": conj_mode}
out = out or f"{mesh_exp.name}.glb"
size = glb.write(out)
print(f"wrote {out} ({size/1e6:.2f} MB)")
