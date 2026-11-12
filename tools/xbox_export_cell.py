#!/usr/bin/env python3
"""Export Xbox city cells / level packs to a stage: all static XBMESHes at identity + ENS entity instances.
usage: xbox_export_cell.py CELL [CELL ...] --out public/levels/XB_<name>   (meshes go to public/models/xbox/static/)"""
import sys, re, json, io, math
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.xbmesh import parse
from xbox.ens import parse_ens, parse_lights
from xbox.lego import parse_lego
from xbox.lego_mesh import build_lego
from collections import defaultdict
from ue2.gltf import GLB
from PIL import Image

args = sys.argv[1:]
out_dir = Path(args[args.index("--out") + 1]) if "--out" in args else None
cells = [a for a in args if not a.startswith("--") and a != (str(out_dir) if out_dir else None)]
out_dir = out_dir or Path(f"public/levels/XB_{cells[0]}")
index = json.load(open("intermediate/xbox/pack_index.json"))
packs_dir = Path("intermediate/xbox/packs"); static_dir = Path("public/models/xbox/static"); static_dir.mkdir(parents=True, exist_ok=True)
R = np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float64)   # D3D LH -> glTF RH
cvt = lambda v: (R @ np.asarray(v, dtype=np.float64).T).T
pack_cache = {}
def pack(n):
    if n not in pack_cache: pack_cache[n] = XBPack((packs_dir / f"{n}.pack").read_bytes())
    return pack_cache[n]
tex_where = {}
for pkn in cells + ["CITY", "GAME"] + [k for k in index if k.startswith(("CITY_STRIP", "CITY_EXTRA"))]:
    for nm, t, o, s in index.get(pkn, []):
        if t == 4: tex_where.setdefault(nm.lower(), pkn)
mesh_where = {}
for pkn in cells + ["CITY"] + [k for k in index if k.startswith(("CITY_STRIP", "CITY_EXTRA"))]:
    for nm, t, o, s in index.get(pkn, []):
        if t == 0x11: mesh_where.setdefault(nm.lower(), pkn)
ifl_where = {}
for pkn in cells + ["CITY", "GAME"] + [k for k in index if k.startswith(("CITY_STRIP", "CITY_EXTRA"))]:
    for nm, t, o, s in index.get(pkn, []):
        if t == 6: ifl_where.setdefault(nm.lower(), pkn)
def load_tex(name):
    if name.lower() not in tex_where and name.lower() in ifl_where:          # IFL = text list of frames; use the first
        ifl = pack(ifl_where[name.lower()]).resource(name.upper(), 6) or pack(ifl_where[name.lower()]).resource(name, 6)
        if ifl:
            first = ifl.decode("latin-1").replace("\r", "\n").split("\n")[0].strip()
            if "." in first: first = first.rsplit(".", 1)[0]
            if first and first.lower() != name.lower(): return load_tex(first)
    pkn = tex_where.get(name.lower())
    if not pkn: return None
    try: return Image.open(io.BytesIO(pack(pkn).resource(name, 4))).convert("RGBA")
    except Exception: return None

SKIP_SHADERS = {"smshadowvol"}
SKIP_MATERIALS = {"dropshadow", "obb_shadow"}
BLEND_SHADERS = {"smtranslucent", "smfxenv", "smglass", "smcloud", "smstar", "smocean"}
COLOR_GAIN = 1.0           # baked vertex colours are modulate x1 (255 = full); converted to linear below
LIGHTMAP_SHADERS = {"sm_grunge"}
def export_static(pkn, mname, dst):
    raw_m = pack(pkn).resource(mname, 0x11); m = parse(raw_m)
    def cstr_(off): return raw_m[off: raw_m.find(b"\0", off)].decode("latin-1", "replace")
    glb = GLB(); texcache = {}; prims = []
    for sub in [sb for sec in m["sections"] for sb in sec["subs"]]:          # all sections (rooms are split into several parts)
        if not len(sub["tris"]) or not sub["nvert"]: continue
        P = cvt(sub["pos"]).astype(np.float32)
        attrs = {"POSITION": glb.accessor(P, 34962, minmax=True), "TEXCOORD_0": glb.accessor(sub["uv"].astype(np.float32), 34962)}
        if sub.get("nrm") is not None: attrs["NORMAL"] = glb.accessor(cvt(sub["nrm"]).astype(np.float32), 34962)
        mat = m["materials"].get(sub["material"], {}); tex = None
        shader = str(mat.get("shader", "")).lower()
        if shader in SKIP_SHADERS or sub["material"].lower() in SKIP_MATERIALS: continue
        if "placeholder" in str(mat.get("tex0", "")).lower(): continue                         # fx_placeholdera = collision/placeholder geometry
        translucent = shader in BLEND_SHADERS
        for tn in (mat.get("tex0"), mat.get("tex1"), mat.get("tex2")):
            if tn and tn != "?":
                if tn not in texcache: img = load_tex(tn); texcache[tn] = glb.image_png(img, tn) if img else None
                if texcache[tn] is not None: tex = texcache[tn]; break
        if sub.get("color") is not None:
            c = sub["color"][:, [2, 1, 0, 3]].astype(np.float32) / 255.0   # D3DCOLOR BGRA -> RGBA
            c[:, :3] = (c[:, :3] * COLOR_GAIN) ** 2.2                       # the game multiplies in gamma space; glTF vertex colours are linear
            if not translucent: c[:, 3] = 1.0
            attrs["COLOR_0"] = glb.accessor(c.astype(np.float32), 34962)
        lm_tex = None
        if sub.get("uv2") is not None and np.isfinite(sub["uv2"]).all():
            attrs["TEXCOORD_1"] = glb.accessor(sub["uv2"].astype(np.float32), 34962)
            if shader in LIGHTMAP_SHADERS:
                lm_name = next((cstr_(mat["raw"][k]) for k in (10, 9, 8) if mat.get("raw") and 0 < mat["raw"][k] < 1 << 20 and "shdw" in cstr_(mat["raw"][k]).lower()), None)
                if lm_name:
                    key = "LM:" + lm_name
                    if key not in texcache:
                        img = load_tex(lm_name); texcache[key] = glb.image_png(img.getchannel("A").convert("L"), lm_name) if img is not None else None   # DXT5: lighting lives in alpha
                    lm_tex = texcache[key]
        mi = glb.material(sub["material"], tex, "BLEND" if translucent else None, True)
        glb.j["materials"][mi]["extras"] = {"unlit": True, "shader": shader, **({"lightmap": lm_tex} if lm_tex is not None else {})}
        prims.append({"attributes": attrs, "indices": glb.accessor(sub["tris"][:, [0, 2, 1]].astype(np.uint32).flatten(), 34963), "material": mi, "mode": 4})
    if not prims: return False
    glb.j["meshes"].append({"name": mname, "primitives": prims}); n = glb.node(name=mname, mesh=0); glb.j["scenes"][0]["nodes"] = [n]
    glb.write(dst); return True


def export_lego(cell, L, dst):
    """the game's unit ring meshes instanced per record with the record's side / edge textures (tools/xbox/lego_mesh.py)"""
    def load_ring(name):
        pkn = mesh_where.get(name.lower())
        return parse(pack(pkn).resource(name, 0x11)) if pkn else None
    orient = json.load(open("intermediate/xbox/lego_orient.json")) if Path("intermediate/xbox/lego_orient.json").exists() else {}
    return build_lego(cell, L, dst, load_tex, load_ring, orient=orient)

def yaw_matrix(pos, yaw_deg):
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    M = np.eye(4); M[0, :3] = [c, 0, -s]; M[2, :3] = [s, 0, c]; M[3, :3] = pos; return M

def mat_to_pos_quat(M):
    """row-vector D3D matrix -> glTF position + quaternion (with LH->RH flip)."""
    Rm = M[:3, :3].T.astype(np.float64)   # column-vector rotation
    Rg = R @ Rm @ R.T
    # polar-ish: strip scale
    sx, sy, sz = [np.linalg.norm(Rg[:, i]) for i in range(3)]
    Rn = Rg / np.array([sx, sy, sz])
    if np.linalg.det(Rn) < 0: Rn[:, 2] *= -1; sz = -sz
    t = np.trace(Rn)
    if t > 0: s = math.sqrt(t + 1) * 2; q = [(Rn[2,1]-Rn[1,2])/s, (Rn[0,2]-Rn[2,0])/s, (Rn[1,0]-Rn[0,1])/s, 0.25*s]
    elif Rn[0,0] > Rn[1,1] and Rn[0,0] > Rn[2,2]: s = math.sqrt(1+Rn[0,0]-Rn[1,1]-Rn[2,2])*2; q = [0.25*s, (Rn[0,1]+Rn[1,0])/s, (Rn[0,2]+Rn[2,0])/s, (Rn[2,1]-Rn[1,2])/s]
    elif Rn[1,1] > Rn[2,2]: s = math.sqrt(1+Rn[1,1]-Rn[0,0]-Rn[2,2])*2; q = [(Rn[0,1]+Rn[1,0])/s, 0.25*s, (Rn[1,2]+Rn[2,1])/s, (Rn[0,2]-Rn[2,0])/s]
    else: s = math.sqrt(1+Rn[2,2]-Rn[0,0]-Rn[1,1])*2; q = [(Rn[0,2]+Rn[2,0])/s, (Rn[1,2]+Rn[2,1])/s, 0.25*s, (Rn[1,0]-Rn[0,1])/s]
    return [float(x) for x in cvt(M[3, :3])], [float(x) for x in q], [float(sx), float(sy), float(sz)]

placements = []; exported = {}; missing = set()
def mesh_url(pkn, mname):
    key = (pkn, mname.lower())
    if key not in exported:
        dst = static_dir / f"{pkn}__{mname.lower()}.glb"
        if not dst.exists():
            try: ok = export_static(pkn, mname, dst)
            except Exception as ex: print(f"  ERR {pkn}/{mname}: {type(ex).__name__}: {ex}"); ok = False
            if not ok: exported[key] = None; return None
        exported[key] = f"/public/models/xbox/static/{dst.name}"
    return exported[key]
lights = []
for cell in cells:
    p = pack(cell)
    ens = p.resource(cell, 8)
    hdr, recs = parse_ens(ens, set(mesh_where)) if ens else (None, [])
    for lt in (parse_lights(ens) if ens else []):
        lights.append({**lt, "pos": [lt["pos"][0], lt["pos"][1], -lt["pos"][2]], "cell": cell})          # D3D -> three (z flipped)
    L = parse_lego(ens) if ens else None
    referenced = {r["type"].lower() for r in recs if r["type"]}
    if L: referenced |= {r["type"].lower() for r in L["records"] if not r["lego"]}
    for nm, t, o, s in index[cell]:
        if t != 0x11 or nm.lower().startswith("minimap") or nm.lower() in referenced: continue   # ENS-placed meshes are local-space
        if re.search(r"(^|_)COL\d*$|SCENECOL|GROUNDCOL|^COL_", nm, re.I): continue                 # collision proxy meshes
        try:
            mm = parse(pack(cell).resource(nm, 0x11)); P_ = np.concatenate([sb["pos"] for sc in mm["sections"] for sb in sc["subs"] if sb["nvert"]])
            ctr = (P_.min(0) + P_.max(0)) / 2; ext = (P_.max(0) - P_.min(0)).max()
            if np.linalg.norm(ctr) < 4 and ext < 10: continue                 # entity template modelled at the origin (unplaced ped/prop): not world geometry
        except Exception: pass
        url = mesh_url(cell, nm)
        if url: placements.append({"actor": nm, "class": "cell", "cell": cell, "mesh": f"{cell}.{nm}", "url": url, "tag": nm, "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "scale": [1, 1, 1]})
    if L:
        lego_dst = static_dir / f"{cell}__lego.glb"; n_seg = export_lego(cell, L, lego_dst)
        if n_seg: placements.append({"actor": f"{cell}_LEGO", "class": "lego", "mesh": f"{cell}.lego", "url": f"/public/models/xbox/static/{lego_dst.name}", "tag": f"{cell}_LEGO", "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "scale": [1, 1, 1]})
        for r in L["records"]:
            if r["lego"]: continue
            pkn = mesh_where.get(r["type"].lower())
            if not pkn: missing.add(r["type"]); continue
            url = mesh_url(pkn, r["type"].upper())
            if not url: continue
            pos, quat, scale = mat_to_pos_quat(yaw_matrix(r["pos"], r["yaw"]))
            placements.append({"actor": r["inst"], "class": "lego_prop", "cell": cell, "mesh": f"{pkn}.{r['type'].upper()}", "url": url, "tag": r["inst"], "pos": pos, "quat": quat, "scale": scale})
        print(f"  {cell}: lego segments {n_seg}, lego props {sum(1 for r in L['records'] if not r['lego'])}")
    if recs:
        for r in recs:
            if not r["type"]: missing.add(r["name"]); continue
            pkn = mesh_where.get(r["type"].lower())
            if not pkn: missing.add(r["type"]); continue
            url = mesh_url(pkn, r["type"])
            if not url: continue
            pos, quat, scale = mat_to_pos_quat(r["M"])
            placements.append({"actor": r["name"], "class": "entity", "cell": cell, "mesh": f"{pkn}.{r['type']}", "url": url, "tag": r["name"], "pos": pos, "quat": quat, "scale": scale})
if not any(c.upper().endswith(("I01", "I02", "I03", "I04", "I05")) or re.match(r"^X[A-Z]\d{2}$", c.upper()) for c in cells) and "city" in mesh_where.get("city_ground", "").lower():   # no city ground under interiors / underground X sets
    url = mesh_url("CITY", "CITY_GROUND")
    if url: placements.append({"actor": "CITY_GROUND", "class": "ground", "mesh": "CITY.CITY_GROUND", "url": url, "tag": "CITY_GROUND", "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "scale": [1, 1, 1]})
out_dir.mkdir(parents=True, exist_ok=True)
# drop entity placements that sit far from THEIR OWN CELL's world-baked geometry: records whose only matrices are child/local offsets
# parse as world positions near the origin (SHAFT_OF_LIGHT02 at (-0.1,-10,0) in the XB02 arena at (600,-480,230)).  Per cell, never
# city-wide (the city's cells are spread over 6 km).
room_centre_of = {}
for p in placements:
    if p["class"] != "cell": continue
    try:
        mm = parse(pack(p["mesh"].split(".")[0]).resource(p["mesh"].split(".")[1], 0x11)); P_ = np.concatenate([sb["pos"] for sc in mm["sections"] for sb in sc["subs"] if sb["nvert"]])
        room_centre_of.setdefault(p["cell"], []).append(((P_.min(0) + P_.max(0)) / 2) * np.array([1, 1, -1]))
    except Exception: pass
room_centre_of = {c: np.mean(v, 0) for c, v in room_centre_of.items()}
keep = []; dropped = 0; _gc = {}
def geom_centre(mesh_key):                       # world-space centre of the mesh's own vertices (world-baked ENT_* meshes sit at identity but far from the origin)
    if mesh_key not in _gc:
        try:
            pkn, mn = mesh_key.split(".", 1); mm = parse(pack(pkn).resource(mn, 0x11)); P_ = np.concatenate([sb["pos"] for sc in mm["sections"] for sb in sc["subs"] if sb["nvert"]])
            _gc[mesh_key] = ((P_.min(0) + P_.max(0)) / 2) * np.array([1, 1, -1])
        except Exception: _gc[mesh_key] = np.zeros(3)
    return _gc[mesh_key]
for p in placements:
    c = p.get("cell"); ref = room_centre_of.get(c)
    # the failure signature: a placement whose WORLD geometry centre (vertex centre + position) lands within 60 m of the origin while the
    # cell's room sits > 300 m away: a child/local matrix parsed as a world one.  World-baked meshes at identity are far from the origin and stay.
    if ref is not None and p["class"] in ("entity", "lego_prop") and np.linalg.norm(ref) > 300 and np.linalg.norm(geom_centre(p["mesh"]) + np.array(p["pos"])) < 60: dropped += 1; continue
    keep.append(p)
if dropped: print(f"  dropped {dropped} far-off placements")
placements = keep
room_centre = np.mean(list(room_centre_of.values()), 0) if room_centre_of else None
# building interiors (<A><nn>I<nn>) are enclosed rooms; X story levels are enclosed only when they sit far below the city (lab at y≈-490);
# street-level X sets (rooftops, alleys) are exteriors lit by the sun
ent_y = [p["pos"][1] for p in placements if p["class"] == "entity" and any(abs(v) > 1e-6 for v in p["pos"])]
depth_y = float(room_centre[1]) if room_centre is not None else (float(np.median(ent_y)) if ent_y else 0.0)
interior = all(re.match(r"^[A-Z]\d{2}I\d{2}$", c.upper()) for c in cells) or (all(re.match(r"^X[A-Z]\d{2}$", c.upper()) for c in cells) and depth_y < -100)
json.dump({"map": "+".join(cells), "unit_scale": 1.0, "statics": placements, "bsp": None, "lights": lights, "interior": interior}, open(out_dir / "stage.json", "w"))
print(f"  lights: {len(lights)}, interior: {interior}")
pos = np.array([p["pos"] for p in placements]) if placements else np.zeros((1, 3))
print(f"{'+'.join(cells)}: {len(placements)} placements ({sum(1 for p in placements if p['class']=='entity')} entities), {len([v for v in exported.values() if v])} meshes exported, missing types {sorted(missing)[:10]} -> {out_dir/'stage.json'}; entity bbox {pos.min(0).round(0)}..{pos.max(0).round(0)}")
