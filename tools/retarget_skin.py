#!/usr/bin/env python3
"""Move a skinned character from one exported SM2 rig to another by bone-name mapping, keeping its original skin weights.
(rig_custom.py re-weights by nearest bone, which smears rigid parts such as shoes and an attached head; this keeps the artist weights.)

usage: retarget_skin.py --src public/models/characters/birdman.glb --skeleton public/models/xbox/anim/spidey_loco.glb --out birdman_loco.glb
Vertices are re-expressed per bone: v' = sum_k w_k * Bind_dst[map(b_k)] * InvBind_src[b_k] * v, so a T-pose vs A-pose difference is absorbed.
The PC (UE2) -> Xbox (bip01) map is built in; add --map name=name pairs for other rigs. Unmapped bones fall back to the nearest mapped ancestor."""
import sys, re, json
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile
from ue2.gltf import GLB

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
src_path = opt("--src"); skel_path = opt("--skeleton"); out_path = opt("--out", "retargeted.glb"); scale = float(opt("--scale", "0"))   # 0 = auto (leg-length ratio)
extra = {}
while "--map" in args: k, v = opt("--map").split("="); extra[k] = v

# ---- PC (UE2 Spidey/civilian) -> Xbox (bip01) bone names
PC2XB = {"RootParent": "bip01 pelvis", "hip": "bip01 pelvis", "spine_01": "bip01 spine", "spine_02": "bip01 spine1", "spine_03": "bip01 spine2", "spine_04": "bip01 spine2", "breather": "bip01 spine2",
         "neck": "bip01 neck", "neck_02": "bip01 neck", "head": "bip01 head", "jaw": "bip01 head"}
for S, s in (("R", "r"), ("L", "l")):
    PC2XB.update({f"{S}_clavicle": f"bip01 {s} clavicle", f"{S}_shoulder": f"bip01 {s} clavicle", f"{S}_upper_arm": f"bip01 {s} upperarm", f"{S}_upper_arm_CONT": f"bip01 {s} upperarm",
                  f"{S}_elbow_twist": f"bip01 {s} forearm", f"{S}_elbow_auto_sca": f"bip01 {s} forearm", f"{S}_lower_arm": f"bip01 {s} forearm", f"{S}_lower_arm_CONT": f"bip01 {s} forearm",
                  f"{S}_wrist": f"bip01 {s} hand", f"{S}_hand": f"bip01 {s} hand", f"{S}_hand_CONTROL": f"bip01 {s} hand", f"{S}_fingers_conn": f"bip01 {s} hand",
                  f"{S}_thumb_01": f"bip01 {s} finger0", f"{S}_thumb_02": f"bip01 {s} finger01", f"{S}_thumb_03": f"bip01 {s} finger02",
                  f"{S}_index_01": f"bip01 {s} finger1", f"{S}_index_02": f"bip01 {s} finger11", f"{S}_middle_01": f"bip01 {s} finger2", f"{S}_middle_02": f"bip01 {s} finger21",
                  f"{S}_ring_01": f"bip01 {s} finger3", f"{S}_ring_02": f"bip01 {s} finger31", f"{S}_pinky_01": f"bip01 {s} finger4", f"{S}_pinky_02": f"bip01 {s} finger41",
                  f"{S}_upper_leg": f"bip01 {s} thigh", f"{S}_hip_auto_scale": f"bip01 {s} thigh", f"{S}_lower_leg": f"bip01 {s} calf",
                  f"{S}_ankle": f"bip01 {s} foot", f"{S}_ankle_RF": f"bip01 {s} foot", f"{S}_foot_RF": f"bip01 {s} foot",
                  f"{S}_ball": f"bip01 {s} toe0", f"{S}_toe": f"bip01 {s} toe0", f"{S}_ball_RF": f"bip01 {s} toe0", f"{S}_toe_RF": f"bip01 {s} toe0"})
PC2XB.update(extra)

src = GLBFile(src_path); dst = GLBFile(skel_path)
sskin = src.j["skins"][0]; dskin = dst.j["skins"][0]
snames = [src.j["nodes"][i].get("name", "") for i in sskin["joints"]]; dnames = [dst.j["nodes"][i].get("name", "") for i in dskin["joints"]]
dindex = {n: i for i, n in enumerate(dnames)}
IB_src = src.accessor(sskin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)   # glTF column-major -> row-major math
IB_dst = dst.accessor(dskin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
B_dst = np.linalg.inv(IB_dst)
# parent chain of the source joints (for unmapped-bone fallback)
sparent = {}
for i, n in enumerate(src.j["nodes"]):
    for c in n.get("children", []): sparent[c] = i
def map_bone(si):
    j = sskin["joints"][si]
    while j is not None:
        nm = src.j["nodes"][j].get("name", "")
        if nm in PC2XB and PC2XB[nm] in dindex: return dindex[PC2XB[nm]]
        j = sparent.get(j)
    return dindex.get("bip01 pelvis", 0)
smap = np.array([map_bone(i) for i in range(len(snames))]); unmapped = sorted({snames[i] for i in range(len(snames)) if snames[i] not in PC2XB})
print(f"source {len(snames)} joints -> {len(set(smap.tolist()))} target joints; unmapped (fell back to ancestor): {unmapped}")
# Both rigs are T-posed but their bones' local axes differ, so moving vertices through full bone frames spins each part around its joint.
# Transfer POSITIONALLY instead: uniform scale to the target's proportions, then shift each vertex by its blended joint offset (keeps the
# original orientation and the artist weights; the target's own inverse-bind matrices do the skinning).
B_src = np.linalg.inv(IB_src); p_src = B_src[:, :3, 3]; p_dst = B_dst[:, :3, 3]
if scale == 0.0:   # auto: pelvis-to-foot length ratio
    def leg(p, names, hip, foot): return abs(p[names.index(hip)][1] - p[names.index(foot)][1])
    try: scale = leg(p_dst, dnames, "bip01 pelvis", "bip01 l foot") / leg(p_src, snames, "hip", "L_ankle")
    except ValueError: scale = 1.0
    print(f"auto scale {scale:.3f}")
T = np.tile(np.eye(4), (len(snames), 1, 1)); T[:, :3, :3] *= scale; T[:, :3, 3] = p_dst[smap] - scale * p_src

glb = GLB()
for n in dst.j["nodes"]:
    glb.j["nodes"].append({k: v for k, v in n.items() if k in ("name", "translation", "rotation", "scale", "matrix", "children")})
mesh_nodes = [i for i, n in enumerate(dst.j["nodes"]) if "mesh" in n]
glb.j["skins"].append({"joints": dskin["joints"], "inverseBindMatrices": glb.accessor(dst.accessor(dskin["inverseBindMatrices"]).astype(np.float32)), "skeleton": dskin.get("skeleton", dskin["joints"][0]), "name": "retargeted"})
for a in dst.j["animations"]:
    na = {"name": a.get("name"), "channels": [], "samplers": []}
    for smp in a["samplers"]:
        na["samplers"].append({"input": glb.accessor(dst.accessor(smp["input"]).astype(np.float32), minmax=True), "output": glb.accessor(dst.accessor(smp["output"]).astype(np.float32)), "interpolation": smp.get("interpolation", "LINEAR")})
    na["channels"] = [{"sampler": c["sampler"], "target": dict(c["target"])} for c in a["channels"]]
    if "extras" in a: na["extras"] = a["extras"]
    glb.j["animations"].append(na)
mat_map = {}
def copy_material(mi):
    if mi is None: return glb.material("custom")
    if mi in mat_map: return mat_map[mi]
    m = src.j["materials"][mi]; pbr = m.get("pbrMetallicRoughness", {}); tex = None; bct = pbr.get("baseColorTexture")
    if bct is not None:
        t = src.j["textures"][bct["index"]]; img = src.j["images"][t["source"]]
        if "bufferView" in img:
            glb.j["images"].append({"bufferView": glb.view(src.view_bytes(img["bufferView"])), "mimeType": img.get("mimeType", "image/png")})
            if not glb.j["samplers"]: glb.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})
            glb.j["textures"].append({"source": len(glb.j["images"]) - 1, "sampler": 0}); tex = len(glb.j["textures"]) - 1
    idx = glb.material(m.get("name", f"mat{mi}"), tex, m.get("alphaMode"), m.get("doubleSided", False))
    if "baseColorFactor" in pbr: glb.j["materials"][idx]["pbrMetallicRoughness"]["baseColorFactor"] = pbr["baseColorFactor"]
    mat_map[mi] = idx; return idx
out_prims = []; nverts = 0
for mi_, m in enumerate(src.j["meshes"]):
    for p in m["primitives"]:
        pos = src.accessor(p["attributes"]["POSITION"]).astype(np.float64); n = len(pos)
        J = src.accessor(p["attributes"]["JOINTS_0"]).astype(np.int64).reshape(n, 4); W = src.accessor(p["attributes"]["WEIGHTS_0"]).astype(np.float64).reshape(n, 4)
        W = W / np.maximum(W.sum(1, keepdims=True), 1e-9)
        M = np.einsum("nk,nkij->nij", W, T[J])                              # per-vertex blended transform (n,4,4)
        newpos = np.einsum("nij,nj->ni", M[:, :3, :3], pos) + M[:, :3, 3]
        nrm = src.accessor(p["attributes"]["NORMAL"]).astype(np.float64) if "NORMAL" in p["attributes"] else None
        if nrm is not None: nrm = np.einsum("nij,nj->ni", M[:, :3, :3], nrm); nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        uv = src.accessor(p["attributes"]["TEXCOORD_0"]).astype(np.float32) if "TEXCOORD_0" in p["attributes"] else np.zeros((n, 2), np.float32)
        idx = src.accessor(p["indices"]).reshape(-1).astype(np.uint32) if "indices" in p else np.arange(n, dtype=np.uint32)
        NJ = smap[J].astype(np.uint16)
        attrs = {"POSITION": glb.accessor(newpos.astype(np.float32), 34962, minmax=True), "TEXCOORD_0": glb.accessor(uv, 34962), "JOINTS_0": glb.accessor(NJ, 34962), "WEIGHTS_0": glb.accessor(W.astype(np.float32), 34962)}
        if nrm is not None: attrs["NORMAL"] = glb.accessor(nrm.astype(np.float32), 34962)
        out_prims.append({"attributes": attrs, "indices": glb.accessor(idx, 34963), "material": copy_material(p.get("material")), "mode": 4}); nverts += n
glb.j["meshes"].append({"name": "RetargetedMesh", "primitives": out_prims})
mn = mesh_nodes[0] if mesh_nodes else glb.node(name="RetargetedMesh")
glb.j["nodes"][mn]["mesh"] = 0; glb.j["nodes"][mn]["skin"] = 0; glb.j["nodes"][mn]["name"] = "RetargetedMesh"
for e in mesh_nodes[1:]: glb.j["nodes"][e].pop("mesh", None)
glb.j["scenes"][0]["nodes"] = list(dst.j["scenes"][dst.j.get("scene", 0)]["nodes"])
glb.j["asset"]["extras"] = {"rigged_from": Path(skel_path).name, "custom": Path(src_path).name, "method": "retarget_skin"}
size = glb.write(out_path)
print(f"wrote {out_path} ({size/1e6:.2f} MB): {nverts} verts, {len(glb.j['animations'])} clips")
