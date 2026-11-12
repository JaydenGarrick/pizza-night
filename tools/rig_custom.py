#!/usr/bin/env python3
"""Bind a custom (static) GLB model to an exported SM2 character skeleton so it plays all the original clips.
No Blender needed. Weights: inverse-distance to the nearest deform bones (good enough to preview; refine in Blender later).

usage: rig_custom.py --skeleton public/models/characters/spideymesh.glb --custom my_model.glb --out public/models/characters/custom_hero.glb
       [--fit height|none] [--bones 2] [--keep-materials]
"""
import sys, re, json, io
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile
from ue2.gltf import GLB

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
skel_path = opt("--skeleton"); custom_path = opt("--custom"); out_path = opt("--out", "custom_rigged.glb"); fit = opt("--fit", "height"); nb = int(opt("--bones", "2"))
HELPER = re.compile(r"(_RF$|CONT|CONTROL|auto_sca|twist|conn|breather|RootParent|_ball|_toe|jaw|fingers|thumb|index|middle|ring|pinky|pivot|^trajectory$|^root$)", re.I)   # Xbox rigs: the '* pivot' nodes are aim helpers, not deform bones

sk = GLBFile(skel_path); cu = GLBFile(custom_path)
skin = sk.j["skins"][0]; joints = skin["joints"]; nodes = sk.j["nodes"]
W = sk.node_world()
bone_world = [W[j] for j in joints]; bone_names = [nodes[j].get("name", str(j)) for j in joints]
children = {j: [c for c in nodes[j].get("children", []) if c in joints] for j in joints}
# bone segments head->tail (tail = mean of children heads, or head + small offset along parent direction)
segs = []
for bi, j in enumerate(joints):
    head = bone_world[bi][:3, 3]
    ch = children[j]
    if ch: tail = np.mean([W[c][:3, 3] for c in ch], axis=0)
    else: tail = head + (head - bone_world[joints.index(next(p for p in joints if j in children[p]))][:3, 3]) * 0.5 if any(j in children[p] for p in joints) else head + np.array([0, 0.05, 0])
    segs.append((head, tail))
deform = [i for i, n in enumerate(bone_names) if not HELPER.search(n)]
print(f"skeleton: {len(joints)} bones, {len(deform)} used for weighting")

# ---- gather the custom mesh (all primitives, world space)
CW = cu.node_world()
prims = []
for ni, n in enumerate(cu.j["nodes"]):
    if "mesh" not in n: continue
    M = CW[ni]; N = np.linalg.inv(M[:3, :3]).T
    for p in cu.j["meshes"][n["mesh"]]["primitives"]:
        pos = cu.accessor(p["attributes"]["POSITION"]).astype(np.float64)
        pos = (M[:3, :3] @ pos.T).T + M[:3, 3]
        nrm = cu.accessor(p["attributes"]["NORMAL"]).astype(np.float64) if "NORMAL" in p["attributes"] else None
        if nrm is not None: nrm = (N @ nrm.T).T; nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        uv = cu.accessor(p["attributes"]["TEXCOORD_0"]).astype(np.float32) if "TEXCOORD_0" in p["attributes"] else np.zeros((len(pos), 2), np.float32)
        idx = cu.accessor(p["indices"]).reshape(-1).astype(np.uint32) if "indices" in p else np.arange(len(pos), dtype=np.uint32)
        prims.append({"pos": pos, "nrm": nrm, "uv": uv, "idx": idx, "material": p.get("material")})
allpos = np.concatenate([p["pos"] for p in prims])
# ---- fit to skeleton mesh height
sk_pos = np.concatenate([sk.accessor(p["attributes"]["POSITION"]) for m in sk.j["meshes"] for p in m["primitives"]]).astype(np.float64)
if fit == "height":
    s = (sk_pos[:, 1].max() - sk_pos[:, 1].min()) / max(allpos[:, 1].max() - allpos[:, 1].min(), 1e-6)
    shift = np.array([(sk_pos[:, 0].max() + sk_pos[:, 0].min()) / 2 - s * (allpos[:, 0].max() + allpos[:, 0].min()) / 2, sk_pos[:, 1].min() - s * allpos[:, 1].min(), (sk_pos[:, 2].max() + sk_pos[:, 2].min()) / 2 - s * (allpos[:, 2].max() + allpos[:, 2].min()) / 2])
    for p in prims: p["pos"] = p["pos"] * s + shift
    print(f"fit: scale {s:.3f}, shift {shift.round(3)}")

def seg_dist(P, a, b):
    ab = b - a; L = ab @ ab
    t = np.clip(((P - a) @ ab) / L, 0, 1) if L > 1e-12 else np.zeros(len(P))
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)

glb = GLB()
# ---- copy skeleton nodes (same indices) + skin + animations into the new file
for n in nodes:
    nn = {k: v for k, v in n.items() if k in ("name", "translation", "rotation", "scale", "matrix", "children")}
    glb.j["nodes"].append(nn)
# remove old mesh nodes' mesh references (nodes that had "mesh")
mesh_nodes = [i for i, n in enumerate(nodes) if "mesh" in n]
ibm = sk.accessor(skin["inverseBindMatrices"]).astype(np.float32)
glb.j["skins"].append({"joints": joints, "inverseBindMatrices": glb.accessor(ibm), "skeleton": skin.get("skeleton", joints[0]), "name": "custom"})
for a in sk.j["animations"]:
    na = {"name": a.get("name"), "channels": [], "samplers": []}
    for smp in a["samplers"]:
        inp = sk.accessor(smp["input"]).astype(np.float32); out = sk.accessor(smp["output"]).astype(np.float32)
        na["samplers"].append({"input": glb.accessor(inp, minmax=True), "output": glb.accessor(out), "interpolation": smp.get("interpolation", "LINEAR")})
    na["channels"] = [{"sampler": c["sampler"], "target": dict(c["target"])} for c in a["channels"]]
    if "extras" in a: na["extras"] = a["extras"]
    glb.j["animations"].append(na)
# ---- materials/textures from the custom file
mat_map = {}
def copy_material(mi):
    if mi is None: return glb.material("custom")
    if mi in mat_map: return mat_map[mi]
    m = cu.j["materials"][mi]; pbr = m.get("pbrMetallicRoughness", {})
    tex = None
    bct = pbr.get("baseColorTexture")
    if bct is not None:
        t = cu.j["textures"][bct["index"]]; img = cu.j["images"][t["source"]]
        if "bufferView" in img:
            data = cu.view_bytes(img["bufferView"])
            glb.j["images"].append({"bufferView": glb.view(data), "mimeType": img.get("mimeType", "image/png")})
            if not glb.j["samplers"]: glb.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})
            glb.j["textures"].append({"source": len(glb.j["images"]) - 1, "sampler": 0}); tex = len(glb.j["textures"]) - 1
    idx = glb.material(m.get("name", f"mat{mi}"), tex, m.get("alphaMode"), m.get("doubleSided", False))
    if "baseColorFactor" in pbr: glb.j["materials"][idx]["pbrMetallicRoughness"]["baseColorFactor"] = pbr["baseColorFactor"]
    mat_map[mi] = idx; return idx
# ---- skin the custom primitives
out_prims = []
for p in prims:
    P = p["pos"]
    D = np.stack([seg_dist(P, *segs[i]) for i in deform], axis=1)       # (nverts, ndeform)
    order = np.argsort(D, axis=1)[:, :nb]
    J = np.zeros((len(P), 4), np.uint16); Wt = np.zeros((len(P), 4), np.float32)
    for k in range(nb):
        d = D[np.arange(len(P)), order[:, k]]
        J[:, k] = np.array(deform)[order[:, k]]; Wt[:, k] = 1.0 / np.maximum(d, 1e-3) ** 2
    # drop far secondary bones (keep crisp assignment on limbs)
    for k in range(1, nb):
        Wt[:, k] = np.where(D[np.arange(len(P)), order[:, k]] > 1.6 * D[np.arange(len(P)), order[:, 0]], 0, Wt[:, k])
    Wt /= Wt.sum(axis=1, keepdims=True)
    nrm = p["nrm"] if p["nrm"] is not None else np.zeros_like(P)
    attrs = {"POSITION": glb.accessor(P.astype(np.float32), 34962, minmax=True), "NORMAL": glb.accessor(nrm.astype(np.float32), 34962), "TEXCOORD_0": glb.accessor(p["uv"], 34962), "JOINTS_0": glb.accessor(J, 34962), "WEIGHTS_0": glb.accessor(Wt, 34962)}
    out_prims.append({"attributes": attrs, "indices": glb.accessor(p["idx"], 34963), "material": copy_material(p["material"]), "mode": 4})
glb.j["meshes"].append({"name": "CustomMesh", "primitives": out_prims})
# reuse the first old mesh node slot for the new mesh
mn = mesh_nodes[0] if mesh_nodes else glb.node(name="CustomMesh")
glb.j["nodes"][mn]["mesh"] = 0; glb.j["nodes"][mn]["skin"] = 0; glb.j["nodes"][mn]["name"] = "CustomMesh"
for extra in mesh_nodes[1:]: glb.j["nodes"][extra].pop("mesh", None)
glb.j["scenes"][0]["nodes"] = list(sk.j["scenes"][sk.j.get("scene", 0)]["nodes"])
glb.j["asset"]["extras"] = {"rigged_from": Path(skel_path).name, "custom": Path(custom_path).name}
size = glb.write(out_path)
print(f"wrote {out_path} ({size/1e6:.2f} MB): {sum(len(p['pos']) for p in prims)} verts, {len(glb.j['animations'])} clips")
