#!/usr/bin/env python3
"""Move a skinned mesh from one character onto another character's skeleton (bones matched by name),
so e.g. a civilian body can play every Spider-Man clip.

usage: transfer_mesh.py --source male02mesh.glb --target spideymesh.glb --out out.glb [--texture name=png] [--keep-source-pose]
Vertices are re-posed from the source bind pose to the target bind pose: v' = sum_i w_i * W_tgt[map(i)] * IBM_src[i] * v
Unmatched source bones fall back to their nearest matched ancestor.
"""
import sys, io
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile
from ue2.gltf import GLB

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
src_path = opt("--source"); tgt_path = opt("--target"); out_path = opt("--out", "transferred.glb"); tex_override = opt("--texture")
S = GLBFile(src_path); T = GLBFile(tgt_path)
sskin = S.j["skins"][0]; tskin = T.j["skins"][0]
sj = sskin["joints"]; tj = tskin["joints"]
sname = [S.j["nodes"][n].get("name", "") for n in sj]; tname = [T.j["nodes"][n].get("name", "") for n in tj]
tindex = {n.lower(): i for i, n in enumerate(tname)}
# parent map in source
sparent = {}
for ni, n in enumerate(S.j["nodes"]):
    for c in n.get("children", []): sparent[c] = ni
def map_bone(si):
    node = sj[si]
    while node is not None:
        nm = S.j["nodes"][node].get("name", "").lower()
        if nm in tindex: return tindex[nm]
        node = sparent.get(node)
    return 0
bmap = [map_bone(i) for i in range(len(sj))]
unmatched = [sname[i] for i in range(len(sj)) if sname[i].lower() not in tindex]
print(f"source bones {len(sj)}, target bones {len(tj)}, unmatched (fall back to ancestor): {unmatched}")
sIBM = S.accessor(sskin["inverseBindMatrices"]).astype(np.float64).reshape(-1, 4, 4).transpose(0, 2, 1)   # column-major -> row-major math
TW = T.node_world(); tgt_world = [TW[n] for n in tj]
# per-source-bone transform: target bone world * source IBM
X = np.array([tgt_world[bmap[i]] @ sIBM[i] for i in range(len(sj))])

glb = GLB()
for n in T.j["nodes"]: glb.j["nodes"].append({k: v for k, v in n.items() if k in ("name", "translation", "rotation", "scale", "matrix", "children")})
tIBM = T.accessor(tskin["inverseBindMatrices"]).astype(np.float32)
glb.j["skins"].append({"joints": tj, "inverseBindMatrices": glb.accessor(tIBM), "skeleton": tskin.get("skeleton", tj[0]), "name": "skin"})
for a in T.j.get("animations", []):
    na = {"name": a.get("name"), "channels": [{"sampler": c["sampler"], "target": dict(c["target"])} for c in a["channels"]], "samplers": []}
    for smp in a["samplers"]: na["samplers"].append({"input": glb.accessor(T.accessor(smp["input"]).astype(np.float32), minmax=True), "output": glb.accessor(T.accessor(smp["output"]).astype(np.float32)), "interpolation": smp.get("interpolation", "LINEAR")})
    if "extras" in a: na["extras"] = a["extras"]
    glb.j["animations"].append(na)
def copy_material(mi):
    if mi is None: return glb.material("mat")
    m = S.j["materials"][mi]; pbr = m.get("pbrMetallicRoughness", {}); tex = None
    bct = pbr.get("baseColorTexture")
    if bct is not None:
        im = S.j["images"][S.j["textures"][bct["index"]]["source"]]
        pil = Image.open(io.BytesIO(S.view_bytes(im["bufferView"]))).convert("RGBA")
        if tex_override:
            nm, path = tex_override.split("=", 1)
            if (im.get("name") or "").lower().endswith(nm.lower()) or nm == "*": pil = Image.open(path).convert("RGBA")
        tex = glb.image_png(pil, im.get("name"))
    idx = glb.material(m.get("name", f"mat{mi}"), tex, m.get("alphaMode"), m.get("doubleSided", False))
    if "baseColorFactor" in pbr: glb.j["materials"][idx]["pbrMetallicRoughness"]["baseColorFactor"] = pbr["baseColorFactor"]
    return idx
prims = []
for mesh_node in [i for i, n in enumerate(S.j["nodes"]) if "mesh" in n]:
    for p in S.j["meshes"][S.j["nodes"][mesh_node]["mesh"]]["primitives"]:
        P = S.accessor(p["attributes"]["POSITION"]).astype(np.float64); N = S.accessor(p["attributes"]["NORMAL"]).astype(np.float64)
        UV = S.accessor(p["attributes"]["TEXCOORD_0"]).astype(np.float32); J = S.accessor(p["attributes"]["JOINTS_0"]).astype(np.int64); W = S.accessor(p["attributes"]["WEIGHTS_0"]).astype(np.float64)
        I = S.accessor(p["indices"]).reshape(-1).astype(np.uint32)
        Ph = np.concatenate([P, np.ones((len(P), 1))], axis=1)
        newP = np.zeros_like(P); newN = np.zeros_like(N)
        for k in range(4):
            M = X[J[:, k]]                                   # (n,4,4)
            newP += W[:, k:k + 1] * np.einsum("nij,nj->ni", M, Ph)[:, :3]
            newN += W[:, k:k + 1] * np.einsum("nij,nj->ni", M[:, :3, :3], N)
        newN /= np.maximum(np.linalg.norm(newN, axis=1, keepdims=True), 1e-9)
        newJ = np.vectorize(lambda i: bmap[i])(J).astype(np.uint16)
        prims.append({"attributes": {"POSITION": glb.accessor(newP.astype(np.float32), 34962, minmax=True), "NORMAL": glb.accessor(newN.astype(np.float32), 34962), "TEXCOORD_0": glb.accessor(UV, 34962), "JOINTS_0": glb.accessor(newJ, 34962), "WEIGHTS_0": glb.accessor(W.astype(np.float32), 34962)}, "indices": glb.accessor(I, 34963), "material": copy_material(p.get("material")), "mode": 4})
        print(f"  primitive: {len(P)} verts, bbox y {newP[:,1].min():.2f}..{newP[:,1].max():.2f}")
glb.j["meshes"].append({"name": Path(src_path).stem, "primitives": prims})
mn = next(i for i, n in enumerate(T.j["nodes"]) if "mesh" in n)
glb.j["nodes"][mn]["mesh"] = 0; glb.j["nodes"][mn]["skin"] = 0; glb.j["nodes"][mn]["name"] = Path(src_path).stem
glb.j["scenes"][0]["nodes"] = list(T.j["scenes"][T.j.get("scene", 0)]["nodes"])
size = glb.write(out_path); print(f"wrote {out_path} ({size/1e6:.2f} MB), {len(glb.j['animations'])} clips")
