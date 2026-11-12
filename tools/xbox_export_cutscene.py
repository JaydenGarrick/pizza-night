#!/usr/bin/env python3
"""Export one Xbox cutscene shot (XBSANIM) as a scene JSON + per-actor animated GLBs for xbscene.html.
usage: xbox_export_cutscene.py PACK/SANIM [--out public/xbox_cutscenes/<SANIM>]"""
import sys, re, json, struct, subprocess
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.nal_emu import NalEmu, parse_skeleton, parse_block, find_blocks
from xbox.anim_decode import decode_block
from xbox.xbmesh import parse
_skin_cache = {}
def _skinned(pk_, name_):
    key = (pk_, name_)
    if key not in _skin_cache:
        try: _skin_cache[key] = bool(parse(XBPack((Path("intermediate/xbox/packs") / f"{pk_}.pack").read_bytes()).resource(name_, 0x11))["sections"][0].get("bone_count"))
        except Exception: _skin_cache[key] = True
    return _skin_cache[key]
from xbox.palette_map import palette_matrices, map_palette
used_meshes = set()

args = sys.argv[1:]; spec = args[0]; pk, nm = spec.split("/")
index = json.load(open("intermediate/xbox/pack_index.json")); packs_dir = Path("intermediate/xbox/packs")
def nhash(s):
    h = 0
    for c in s.encode("latin-1"):
        if chr(c).isalpha(): c = ord(chr(c).lower())
        h = ((h >> 27) | (h << 5)) & 0xffffffff; h ^= c
    return h
skel_by_name = {}; mesh_by_name = {}
for p, ents in index.items():
    for n, t, o, s in ents:
        if t == 2: skel_by_name.setdefault(n.lower(), []).append(p)
        if t == 0x11: mesh_by_name.setdefault(n.lower(), []).append(p)
def pick(cands, prefer):
    if not cands: return None
    for c in cands:
        if c == prefer: return c
    for c in cands:
        if c in ("GAME", "CITY"): return c
    return cands[0]
MESH_ALIAS = {"spiderman": "spiderman", "camera": None, "ped_fem_skel": None, "ped_male_skel": None, "simple": None}
out_dir = Path(args[args.index("--out") + 1]) if "--out" in args else Path(f"public/xbox_cutscenes/{nm}"); out_dir.mkdir(parents=True, exist_ok=True)
d = XBPack((packs_dir / f"{pk}.pack").read_bytes()).resource(nm, 0x14)
n_names = struct.unpack_from("<I", d, 0xc)[0]; names = [d[0x54 + 0x20*i: 0x70 + 0x20*i].split(b"\0")[0].decode() for i in range(n_names)]
duration = struct.unpack_from("<f", d, 0x3c)[0]
emu = NalEmu(); scene = {"name": nm, "pack": pk, "duration": duration, "fps": 30.0, "camera": None, "actors": [], "world": "xbox"}
P = np.diag([1.0, 1.0, -1.0])
def mirror_quat(q): return [-float(q[0]), -float(q[1]), float(q[2]), float(q[3])]
# a shot is stored as consecutive <=151-frame (5 s) segments per block name; consecutive segments overlap by one frame
groups = {}; frozen = []
all_blocks = find_blocks(d)
for i, b in enumerate(all_blocks):
    size = struct.unpack_from("<I", d, b + 4)[0]; bname = d[b+0xc:b+0x28].split(b"\0")[0].decode(); sidx = struct.unpack_from("<I", d, b + 0x28)[0]
    gap = (all_blocks[i + 1] if i + 1 < len(all_blocks) else len(d)) - b
    n_frames = struct.unpack_from("<I", d, b + 0x44)[0]; n_chunks = struct.unpack_from("<I", d, b + 0x64)[0]
    # the +4 size field is 0 on many fully-animated blocks (whole flythrough cameras, Jameson reaction shots): judge by content instead
    if gap < 0xe0 or n_frames == 0 or n_chunks == 0:
        if bname not in frozen: frozen.append(bname)          # really empty: entity holds its last pose
        continue
    groups.setdefault(bname, {"sidx": sidx, "blocks": []})["blocks"].append(b)
for bname, g in groups.items():
    sidx = g["sidx"]; skname = names[sidx] if sidx < len(names) else bname
    skpk = pick(skel_by_name.get(skname.lower()), pk)
    if not skpk: print("  no skeleton for", bname, skname); continue
    skraw = XBPack((packs_dir / f"{skpk}.pack").read_bytes()).resource(skname.upper(), 2) or XBPack((packs_dir / f"{skpk}.pack").read_bytes()).resource(skname, 2)
    sk = parse_skeleton(skraw)
    if skname.lower() == "camera":
        pos_l, quat_l, fov_l, t0, fps = [], [], [], 0.0, 30.0
        for si, b in enumerate(g["blocks"]):
            blk = parse_block(d, b, sk["n_anim_channels"]); dec = decode_block(emu, skraw, d, blk); fps = blk["fps"]; skip = 1 if si > 0 else 0
            ch = next(c for c in dec["channels"].values() if c["kind"] == "posori"); fov = next((c for c in dec["channels"].values() if c["kind"] == "float1"), None)
            # stored camera quat is the view (world->camera) rotation in D3D LH (+Z forward, +Y up); three.js camera = inverse, mirrored:
            # q_three = mirror(conj(q)) = (x, y, -z, w), and three.js's -Z forward then matches automatically.
            pos_l.append(ch["data"]["pos"][skip:] @ P); quat_l += [[float(q[0]), float(q[1]), -float(q[2]), float(q[3])] for q in ch["data"]["quat"][skip:]]
            fov_l += (fov["data"][skip:].tolist() if fov is not None else [0.785] * (blk["n_frames"] - skip)); t0 += blk["duration"]
        pos = np.concatenate(pos_l)
        scene["camera"] = {"n": len(quat_l), "fps": fps, "pos": pos.round(4).tolist(), "quat": np.round(quat_l, 5).tolist(), "fov": np.round(fov_l, 4).tolist()}
        print(f"  camera: {len(g['blocks'])} segments, {len(quat_l)} frames, {t0:.2f}s"); continue
    # mesh selection: score every candidate by how completely its bone palette maps onto the skeleton.
    # candidates: same-name-as-skeleton meshes, same-name-as-block meshes (block 'ped_fem_norm' on skeleton 'ped_fem_skel'),
    # for 1-bone props any mesh containing the block name (block 'briefcase' -> ITM_BRIEFCASEA), then every skinned mesh in the shot pack.
    base = re.sub(r"\d+$", "", bname.lower())                       # ent_e39i02_chaira16 -> ent_e39i02_chaira
    tokens = [t for t in re.split(r"[^a-z]+", base) if len(t) >= 4 and t not in ("ent", "itm", "prop", "simple")]   # box01panel -> panel
    def name_match(mres_):
        ml = mres_.lower()
        return ml in (skname.lower(), bname.lower(), base) or (len(base) >= 4 and base in ml) or any(t in ml for t in tokens)
    rigid_in_pack = [n for n, t, o, s in index.get(pk, []) if t == 0x11 and not n.upper().endswith("_MORPH") and not _skinned(pk, n)]
    def mesh_score(mpk_, mres_):
        try:
            mraw = XBPack((packs_dir / f"{mpk_}.pack").read_bytes()).resource(mres_, 0x11); m = parse(mraw); sec = m["sections"][0]
            if not sec.get("bone_count"):   # unskinned prop / rig (OCRIG, cars, chairs): the block name must identify the mesh
                if name_match(mres_) or (sk["n_bones"] > 2 and mres_.lower() in (skname.lower(), bname.lower())): return (1.0, "rigid")
                if sk["n_bones"] <= 2 and mpk_ == pk and len(rigid_in_pack) == 1: return (0.9, "rigid")   # only prop in the cutscene pack (flowers -> ITM_MJBOUQUET)
                return (0.5, "rigid")
            Mp = palette_matrices(mraw, sec); return (len(map_palette(sk, Mp)) / len(Mp), "skinned")
        except Exception: return (0.0, "err")
    def named(mname):
        out = []
        for mpk_ in sorted(mesh_by_name.get(mname, []), key=lambda x: (x != pk, x != skpk, x not in ("GAME", "CITY"), x)):
            out.append((mpk_, next(n for n, t, o, s in index[mpk_] if t == 0x11 and n.lower() == mname)))
        return out[:3]
    cands = named(MESH_ALIAS.get(skname.lower(), skname.lower()) or "") + named(bname.lower())
    if sk["n_bones"] <= 2:
        pack_order = [pk, skpk, "CITY", "GAME"] + sorted(index)
        for test in (lambda n: n.lower() == base or base in n.lower(), lambda n: any(t_ in n.lower() for t_ in tokens)):   # exact/contains across ALL packs first, tokens only as a fallback
            found = False
            for cand_pk in pack_order:
                cc = [n for n, t, o, s in index.get(cand_pk, []) if t == 0x11 and not n.upper().endswith("_MORPH") and test(n)]
                if cc: cands.append((cand_pk, sorted(cc, key=lambda n: (n.lower() != base, len(n)))[0])); found = True; break
            if found: break
    cands += [(pk, n) for n, t, o, s in index[pk] if t == 0x11 and not n.upper().endswith("_MORPH") and (pk, n) not in cands]
    best = None
    for ci, (mpk_, mres_) in enumerate(cands):
        sc, kind = mesh_score(mpk_, mres_); key = (round(sc, 3), f"{mpk_}/{mres_}" not in used_meshes, -ci)   # score, then unused, then candidate order
        if best is None or key > best[0]: best = (key, sc, kind, mpk_, mres_)
        if sc >= 0.999 and key[1]: break
    if best is None or best[1] < 0.8: print(f"  no mesh for {bname} ({skname}); best {best and best[1:]}"); continue
    _, sc, kind, mpk, mesh_res = best
    partial = sc < 0.999
    print(f"  {bname}: mesh {mpk}/{mesh_res} ({kind}, {sc*100:.0f}% palette{', PARTIAL' if partial else ''})")
    used_meshes.add(f"{mpk}/{mesh_res}")
    glb = out_dir / f"{bname}.glb"
    cmd = [sys.executable, "-I", "tools/xbox_export_anim.py", "--skel", f"{skpk}/{skname.upper()}", "--mesh", f"{mpk}/{mesh_res}", "--anim", f"{spec}:{bname}", "--out", str(glb)] + (["--allow-partial"] if partial else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: print("  export failed for", bname, r.stderr[-400:]); continue
    n_frames = sum(parse_block(d, b, sk["n_anim_channels"])["n_frames"] for b in g["blocks"]) - (len(g["blocks"]) - 1)
    scene["actors"].append({"name": bname, "skeleton": skname, "mesh": f"{mpk}/{mesh_res}", "glb": f"/{glb.as_posix()}", "clip": f"{nm}:{bname}", "frames": n_frames, "segments": len(g["blocks"])})
    print(f"  actor {bname} ({skname}) -> {glb}  [{len(g['blocks'])} segments]")
scene["frozen"] = [f for f in frozen if f not in {a["name"] for a in scene["actors"]} and f.lower() != "camera"]
json.dump(scene, open(out_dir / "scene.json", "w")); print("wrote", out_dir / "scene.json", "camera" if scene["camera"] else "no camera", len(scene["actors"]), "actors")
