#!/usr/bin/env python3
"""Export an XBMESH from a packfile to GLB.
usage: xbox_export_mesh.py PACKNAME MESHNAME [--out file.glb] [--lod 0] [--scale 1.0] [--axis xup|yup|zup]"""
import sys, json, io
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.xbmesh import parse
from ue2.gltf import GLB
from PIL import Image

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
out = opt("--out"); lod = int(opt("--lod", "0")); scale = float(opt("--scale", "1.0")); axis = opt("--axis", "yup")
packname, meshname = args[0], args[1]
packs = Path("intermediate/xbox/packs")
pk = XBPack((packs / f"{packname}.pack").read_bytes())
m = pk.resource(meshname, 0x11)
if m is None: sys.exit(f"mesh {meshname} not in {packname}")
mesh = parse(m)

# texture lookup across this pack + common packs
index = json.load(open("intermediate/xbox/pack_index.json"))
tex_where = {}
for pkn in [packname, "GAME", "CITY"]:
    for nm, t, o, s in index.get(pkn, []):
        if t == 4: tex_where.setdefault(nm.lower(), pkn)
pack_cache = {packname: pk}
def load_tex(name):
    pkn = tex_where.get(name.lower())
    if not pkn: return None
    p = pack_cache.setdefault(pkn, XBPack((packs / f"{pkn}.pack").read_bytes()))
    blob = p.resource(name, 0x04)
    try: return Image.open(io.BytesIO(blob)).convert("RGBA")
    except Exception: return None

# axis conversion: model X-up (Treyarch) -> glTF Y-up
if axis == "xup":   R = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]], dtype=np.float64)   # gltf = (y, x, -z)
elif axis == "zup": R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)
elif axis == "yup": R = np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float64)   # D3D left-handed -> glTF right-handed
else:               R = np.eye(3)
det = np.linalg.det(R)
cvt = lambda v: (R @ np.asarray(v, dtype=np.float64).T).T

glb = GLB(); texcache = {}
def material(matname):
    mat = mesh["materials"].get(matname, {})
    tex = None
    for tn in (mat.get("tex0"), mat.get("tex1"), mat.get("tex2")):
        if tn and tn.lower() not in ("", "?"):
            if tn not in texcache:
                img = load_tex(tn); texcache[tn] = glb.image_png(img, tn) if img else None
            if texcache[tn] is not None: tex = texcache[tn]; break
    return glb.material(matname or "mat", tex, None, True)

sec = mesh["sections"][min(lod, len(mesh["sections"]) - 1)]
skinned = any(s["stride"] == 32 for s in sec["subs"]) and sec.get("palette") is not None
prims = []; joint_nodes = []
root = glb.node(name=f"{meshname}_root")
if skinned:
    pal = sec["palette"]                      # row-vector D3D matrices (translation in last row): v_bone = v_model * M
    nb = len(pal)
    R4 = np.eye(4); R4[:3, :3] = R
    S4 = np.eye(4) * scale; S4[3, 3] = 1
    ibms = []
    for i in range(nb):
        Mi = pal[i].T.astype(np.float64)      # column-vector form: bone_from_model
        Mi_g = Mi @ np.linalg.inv(S4 @ R4)    # bone_from_gltf  (gltf = S R model)
        W = np.linalg.inv(Mi_g)               # gltf_from_bone
        ibms.append(Mi_g)
        joint_nodes.append(glb.node(name=f"bone{i}", matrix=[float(x) for x in W.T.flatten()]))
    glb.j["nodes"][root]["children"] = list(joint_nodes)
    ibm = np.array([x.T.flatten() for x in ibms], dtype=np.float32)
    glb.j["skins"].append({"joints": joint_nodes, "inverseBindMatrices": glb.accessor(ibm), "skeleton": root, "name": meshname})
for sub in sec["subs"]:
    if not len(sub["tris"]) or not sub["nvert"]: continue
    P = (cvt(sub["pos"]) * scale).astype(np.float32)
    attrs = {"POSITION": glb.accessor(P, 34962, minmax=True), "TEXCOORD_0": glb.accessor(sub["uv"].astype(np.float32), 34962)}
    if sub.get("nrm") is not None: attrs["NORMAL"] = glb.accessor(cvt(sub["nrm"]).astype(np.float32), 34962)
    if skinned and sub["stride"] == 32:
        bl = np.array(sub["bones"] + [0], dtype=np.uint16)
        J = sub["joints"].astype(np.int64); J = np.where(J == 255, len(sub["bones"]), J); Jg = bl[J].astype(np.uint16)
        Wt = sub["weights"].astype(np.float32); Wt[J == len(sub["bones"])] = 0
        s = Wt.sum(1, keepdims=True); Wt = np.where(s > 0, Wt / np.maximum(s, 1e-6), np.array([1, 0, 0, 0], np.float32))
        attrs["JOINTS_0"] = glb.accessor(Jg, 34962); attrs["WEIGHTS_0"] = glb.accessor(Wt, 34962)
    tris = sub["tris"][:, [0, 2, 1]] if det < 0 else sub["tris"]
    prims.append({"attributes": attrs, "indices": glb.accessor(tris.astype(np.uint32).flatten(), 34963), "material": material(sub["material"]), "mode": 4})
glb.j["meshes"].append({"name": meshname, "primitives": prims})
mn = glb.node(name=meshname, mesh=0, **({"skin": 0} if skinned else {}))
glb.j["nodes"][root].setdefault("children", []).append(mn)
glb.j["scenes"][0]["nodes"] = [root]
out = out or f"public/models/xbox/{packname}__{meshname}.glb"
Path(out).parent.mkdir(parents=True, exist_ok=True)
size = glb.write(out)
print(f"{packname}/{meshname} LOD{lod}: {len(prims)} submeshes, {sum(len(s['tris']) for s in sec['subs'])} tris, skinned={skinned} -> {out} ({size/1e6:.2f} MB)")
