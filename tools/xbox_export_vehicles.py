"""Export the city traffic vehicle variants (CITY/V_CITYCARA, V_CITYCARB) as one GLB per variant, wheels attached.
Each pack mesh is a kit: body sections (taxi + roof sign, sedans, van, truck) share two wheel-pair sections; a body's 'tire' sub is a pair
of marker quads at the front/rear axle (8 verts), so the wheel pairs are placed at those axle centres.  Output: public/models/xbox/vehicles/<name>.glb
+ vehicles.json {name, length, width, kind}."""
import sys, json, io, re
from pathlib import Path
import numpy as np
sys.path.insert(0, "tools")
from xbpack import XBPack
from xbox.xbmesh import parse
from ue2.gltf import GLB
from PIL import Image
index = json.load(open("intermediate/xbox/pack_index.json"))
packs_dir = Path("intermediate/xbox/packs"); out_dir = Path("public/models/xbox/vehicles"); out_dir.mkdir(parents=True, exist_ok=True)
R = np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float64); cvt = lambda v: (R @ np.asarray(v, dtype=np.float64).T).T
pack_cache = {}
def pack(n):
    if n not in pack_cache: pack_cache[n] = XBPack((packs_dir / f"{n}.pack").read_bytes())
    return pack_cache[n]
tex_where = {}
for pkn in ["CITY", "GAME"]:
    for nm, t, o, s in index.get(pkn, []):
        if t == 4: tex_where.setdefault(nm.lower(), pkn)
def load_tex(name):
    pkn = tex_where.get(name.lower())
    if not pkn: return None
    try: return Image.open(io.BytesIO(pack(pkn).resource(name, 4))).convert("RGBA")
    except Exception: return None
BLEND = {"smtranslucent", "smfxenv", "smglass"}
def add_section(glb, m, sec, texcache, node_name, translation=None, skip_mats=()):
    prims = []
    for sub in sec["subs"]:
        if not len(sub["tris"]) or not sub["nvert"] or sub["material"].lower() in skip_mats: continue
        mat = m["materials"].get(sub["material"], {}); shader = str(mat.get("shader", "")).lower()
        if "placeholder" in str(mat.get("tex0", "")).lower() or sub["material"].lower() in ("shadow", "alpha", "street glow", "s_dcl_lamplite1_a"): continue   # drop shadow decals / ground glow quads
        if "tire" in sub["material"].lower() and sub["nvert"] <= 8: continue   # the two 8-vertex 'tire' marker quads float 3-4 m ahead/behind the body: not geometry
        P = cvt(sub["pos"]).astype(np.float32)
        attrs = {"POSITION": glb.accessor(P, 34962, minmax=True), "TEXCOORD_0": glb.accessor(sub["uv"].astype(np.float32), 34962)}
        if sub.get("nrm") is not None: attrs["NORMAL"] = glb.accessor(cvt(sub["nrm"]).astype(np.float32), 34962)
        tex = None
        for tn in (mat.get("tex0"), mat.get("tex1"), mat.get("tex2")):
            if tn and tn != "?":
                if tn not in texcache: img = load_tex(tn); texcache[tn] = glb.image_png(img, tn) if img else None
                if texcache[tn] is not None: tex = texcache[tn]; break
        if sub.get("color") is not None:
            c = sub["color"][:, [2, 1, 0, 3]].astype(np.float32) / 255.0; c[:, :3] = c[:, :3] ** 2.2
            if shader not in BLEND: c[:, 3] = 1.0
            attrs["COLOR_0"] = glb.accessor(c.astype(np.float32), 34962)
        mi = glb.material(sub["material"], tex, "BLEND" if shader in BLEND else None, True)
        glb.j["materials"][mi]["extras"] = {"unlit": True, "shader": shader}
        prims.append({"attributes": attrs, "indices": glb.accessor(sub["tris"][:, [0, 2, 1]].astype(np.uint32).flatten(), 34963), "material": mi, "mode": 4})
    if not prims: return None
    glb.j["meshes"].append({"name": node_name, "primitives": prims}); kw = {"name": node_name, "mesh": len(glb.j["meshes"]) - 1}
    if translation is not None: kw["translation"] = [float(x) for x in translation]
    return glb.node(**kw)
def axles(sec):
    """front/rear axle centres from the 8-vertex 'tire' marker sub (two quads), in glTF coords: (y, z_front, z_rear) or None"""
    for sub in sec["subs"]:
        if "tire" in sub["material"].lower() and 6 <= sub["nvert"] <= 12:
            P = cvt(sub["pos"]); zs = P[:, 2]; lo, hi = zs.min(), zs.max()
            if hi - lo < 1.0: continue
            a = P[zs < (lo + hi) / 2]; b = P[zs >= (lo + hi) / 2]
            return float(P[:, 1].mean()), float(a[:, 2].mean()), float(b[:, 2].mean()), (a[:, 1].max() - a[:, 1].min()) / 2
    return None
out = []
for mesh_name, wheel_ids in [("V_CITYCARA", (7, 8)), ("V_CITYCARB", (0, 1))]:
    m = parse(pack("CITY").resource(mesh_name, 0x11)); secs = m["sections"]
    wheels = [secs[i] for i in wheel_ids]
    for si, sec in enumerate(secs):
        if si in wheel_ids: continue
        mats = [s["material"].lower() for s in sec["subs"]]
        if not any(k in " ".join(mats) for k in ("v_itm_gen", "v_itm_taxi", "body", "truck", "car ")) or si == 1 and mesh_name == "V_CITYCARA": continue   # 001 = taxi roof sign (merged into the taxi below)
        glb = GLB(); texcache = {}; nodes = []
        n = add_section(glb, m, sec, texcache, "body")
        if n is None: continue
        nodes.append(n)
        if mesh_name == "V_CITYCARA" and si == 0:
            n2 = add_section(glb, m, secs[1], texcache, "sign")
            if n2 is not None: nodes.append(n2)
        P = cvt(np.concatenate([s["pos"] for s in sec["subs"] if len(s["pos"]) and "tire" not in s["material"].lower() and s["material"].lower() not in ("alpha", "shadow")]))
        # the 8-vertex 'tire' marker quads are NOT axle positions (one sits 4 m behind the body); place the wheel pairs 0.9 m in from the body ends,
        # wheel centre one radius (0.42 m) above the body's lowest point
        y = float(P[:, 1].min()) + 0.42; ax = (y, float(P[:, 2].min()) + 0.9, float(P[:, 2].max()) - 0.9)
        for wsec, z, nm in ((wheels[0], ax[1], "wheel_front"), (wheels[1], ax[2], "wheel_rear")):
            n3 = add_section(glb, m, wsec, texcache, nm, translation=(0, y, z))
            if n3 is not None: nodes.append(n3)
        glb.j["scenes"][0]["nodes"] = nodes
        kind = "taxi" if "v_itm_taxi" in mats else ("truck" if "truck" in mats else ("van" if "car " in mats else "car"))
        name = f"{mesh_name.lower()}_{si:03d}"; glb.write(out_dir / f"{name}.glb")
        rec = {"name": name, "glb": f"/public/models/xbox/vehicles/{name}.glb", "kind": kind, "length": float(P[:, 2].max() - P[:, 2].min()), "width": float(P[:, 0].max() - P[:, 0].min()),
               "zmin": float(P[:, 2].min()), "zmax": float(P[:, 2].max()), "ymin": float(P[:, 1].min()), "axles": [round(v, 2) for v in ax]}
        out.append(rec); print(rec)
# whole single-section vehicles (tires included): the F48 box truck
for pk, mesh_name, kind in [("F48", "F_BOXTRUCK", "truck")]:
    m = parse(pack(pk).resource(mesh_name, 0x11)); sec = m["sections"][0]
    for pkn in [pk]:
        for nm, t, o, s_ in index.get(pkn, []):
            if t == 4: tex_where.setdefault(nm.lower(), pkn)
    glb = GLB(); texcache = {}; n = add_section(glb, m, sec, texcache, "body")
    if n is not None:
        glb.j["scenes"][0]["nodes"] = [n]; P = cvt(np.concatenate([s_["pos"] for s_ in sec["subs"] if len(s_["pos"]) and s_["material"].lower() not in ("alpha", "shadow")]))
        name = mesh_name.lower(); glb.write(out_dir / f"{name}.glb")
        rec = {"name": name, "glb": f"/public/models/xbox/vehicles/{name}.glb", "kind": kind, "length": float(P[:, 2].max() - P[:, 2].min()), "width": float(P[:, 0].max() - P[:, 0].min()), "zmin": float(P[:, 2].min()), "zmax": float(P[:, 2].max()), "ymin": float(P[:, 1].min()), "axles": None, "whole": True}
        out.append(rec); print(rec)
json.dump(out, open(out_dir / "vehicles.json", "w"), indent=1); print(len(out), "vehicles")
