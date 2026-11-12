#!/usr/bin/env python3
"""Export an Xbox character as a skinned GLB with a skeleton (from the mesh bone palette + XBSKEL hierarchy) and one or more
animation clips decoded from XBSANIM/XBANIM blocks via the emulated engine decoder.
usage: xbox_export_anim.py --skel GAME/SPIDERMAN --mesh SPIDERMAN/SPIDERMAN --anim STORY_37_SCENE_2/AC69_FINALBAT_04:hero_um[,...]
                           [--xbanim CITY/NAME] --out file.glb [--no-root-motion]"""
import sys, io, json, struct
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.xbmesh import parse
from xbox.nal_emu import NalEmu, parse_skeleton, parse_block, find_blocks
from xbox.anim_decode import decode_block
from xbox.palette_map import palette_matrices, map_palette, skeleton_out_index
from ue2.gltf import GLB
from PIL import Image

args = sys.argv[1:]
def opt(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default
index = json.load(open("intermediate/xbox/pack_index.json")); packs_dir = Path("intermediate/xbox/packs"); _pk = {}
def pack(n):
    if n not in _pk: _pk[n] = XBPack((packs_dir / f"{n}.pack").read_bytes())
    return _pk[n]
def res(spec, typ):
    pk, nm = spec.split("/"); return pack(pk).resource(nm, typ)
tex_where = {}; ifl_where = {}
_pref = [opt("--mesh").split("/")[0], opt("--skel").split("/")[0]] + [a.split(":")[0].split("/")[0] for a in opt("--anim", "").split(",") if a] + ["GAME", "CITY"]
for pkn in _pref + sorted(k for k in index if k not in _pref):      # textures may live in any pack (peds: CITY_EXTRA_*); prefer related packs
    for nm, t, o, s in index.get(pkn, []):
        if t == 4: tex_where.setdefault(nm.lower(), pkn)
        if t == 6: ifl_where.setdefault(nm.lower(), pkn)
def load_tex(name, depth=0):
    if name.lower() not in tex_where and name.lower() in ifl_where and depth < 3:   # IFL = text list of frame textures; use the first
        ifl = pack(ifl_where[name.lower()]).resource(name.upper(), 6) or pack(ifl_where[name.lower()]).resource(name, 6)
        if ifl:
            first = ifl.decode("latin-1").replace("\r", "\n").split("\n")[0].strip()
            if "." in first: first = first.rsplit(".", 1)[0]
            if first and first.lower() != name.lower(): return load_tex(first, depth + 1)
    pkn = tex_where.get(name.lower())
    if not pkn: return None
    try: return Image.open(io.BytesIO(pack(pkn).resource(name, 4))).convert("RGBA")
    except Exception: return None

P4 = np.diag([1.0, 1.0, -1.0, 1.0])                      # D3D LH -> glTF RH mirror (z)
def mirror(M): return P4 @ M @ P4
def quat_from_mat(R):
    t = np.trace(R)
    if t > 0: s = np.sqrt(t + 1) * 2; q = [(R[2,1]-R[1,2])/s, (R[0,2]-R[2,0])/s, (R[1,0]-R[0,1])/s, 0.25*s]
    else:
        i = int(np.argmax(np.diag(R))); j, k = (i+1)%3, (i+2)%3; s = np.sqrt(max(1e-12, 1 + R[i,i] - R[j,j] - R[k,k])) * 2; q = [0,0,0,0]
        q[i] = 0.25*s; q[j] = (R[j,i]+R[i,j])/s; q[k] = (R[k,i]+R[i,k])/s; q[3] = (R[k,j]-R[j,k])/s
    q = np.array(q); return q / np.linalg.norm(q)
def mat_from_quat(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
def mirror_quat(q): return np.array([-q[0], -q[1], q[2], q[3]])

# --- skeleton + mesh
skraw = res(opt("--skel"), 2); sk = parse_skeleton(skraw); bones = sk["bones"]
mesh_pk, mesh_nm = opt("--mesh").split("/"); raw = pack(mesh_pk).resource(mesh_nm, 0x11); m = parse(raw); sec = m["sections"][0]
RIGID = not sec.get("bone_count")                          # unskinned mesh (prop on the 'simple' skeleton, rigid rigs): no palette
OUT_IDX = {}
# RIG: a rigid multi-part rig (Doc Ock's OCRIG: 29 sections = root box + 4 tentacles x (limb root + 6 BOX segments)); every section is
# modelled in its bone's local space, so sections just hang off the animated joints.  Slots = pose-output indices.
RIG = RIGID and len(m["sections"]) > 1 and sk["n_bones"] > 2
def rig_section_bones():
    """OCRIG (Doc Ock): 4 telescoping tentacles.  Chain bones clavicle2->upperarm->upperarm2->forearm->forearm2 sit ~0.75 m apart along
    each bone's local -X; the mesh holds 3 pairs of segment pieces (0.43 m + 0.33 m) that are laid END TO END along -X in every gap
    (instanced), a claw hub at the hand, and 3 fingers (base piece on box01/03/05-type bones, tip on their children).
    Sections: 1-7 arm pieces (hub, A,B,A,B,A,B), 8-14 leg pieces, 15-21 arm claw (hub, base,tip x3), 22-28 leg claw, 0 = back harness.
    Returns [(section, bone, x_offset, x_scale)]."""
    byname = {b["name"]: i for i, b in enumerate(bones)}
    def ch(*names): return [byname.get(n) for n in names]
    limbs = [("l arm", ch("bip01 l clavicle2", "bip01 l upperarm", "bip01 l upperarm2", "bip01 l forearm", "bip01 l forearm2", "bip01 l hand"), 1, 15),
             ("r arm", ch("bip01 r clavicle2", "bip01 r upperarm", "bip01 r upperarm2", "bip01 r forearm", "bip01 r forearm2", "bip01 r hand"), 1, 15),
             ("l leg", ch("bip01 l thigh2", "bip01 l thigh3", "bip01 l calf", "bip01 l calf2", "bip01 l calf3", "bip01 l foot"), 8, 22),
             ("r leg", ch("bip01 r thigh2", "bip01 r thigh3", "bip01 r calf", "bip01 r calf2", "bip01 r calf3", "bip01 r foot"), 8, 22)]
    if any(x is None for _, c, _, _ in limbs for x in c) or len(m["sections"]) < 29: return [(i, 0, 0.0, 1.0) for i in range(len(m["sections"]))]
    def ext(si):   # length of a piece along -X
        pos = m["sections"][si]["subs"][0]["pos"]; return float(-pos[:, 0].min())
    out = [(0, byname.get("conglom", 0), 0.0, 1.0)]
    for name, c, s0, claw0 in limbs:
        out.append((s0, c[0], 0.0, 1.0))                                                # hub at the shoulder/hip joint
        for gi in range(4):                                                            # 4 telescoping gaps
            A, B = s0 + 1 + 2 * (gi % 3), s0 + 2 + 2 * (gi % 3); la = ext(A)
            out.append((A, c[gi], 0.0, 1.0)); out.append((B, c[gi], -la, 1.0))
        hand = c[5]; out.append((claw0, hand, 0.0, 1.0))
        bases = sorted([i for i, b in enumerate(bones) if b["parent"] == hand and b["name"].startswith("box")], key=lambda i: bones[i]["name"])
        for k, bs in enumerate(bases[:3]):
            tip = next((j for j, b in enumerate(bones) if b["parent"] == bs), bs)
            out.append((claw0 + 1 + 2 * k, bs, 0.0, 1.0)); out.append((claw0 + 2 + 2 * k, tip, 0.0, 1.0))
    return out
if RIG:
    OUT_IDX = skeleton_out_index(sk); n_out = max(OUT_IDX.values()) + 1
    bone_of = {s: b for b, s in OUT_IDX.items()}; slot_of = dict(OUT_IDX); M = [np.eye(4) for _ in range(n_out)]
    SEC_PAIRS = rig_section_bones(); print(f"rigid rig: {len(m['sections'])} sections, {len(SEC_PAIRS)} placements on {len(bone_of)} animated bones")
elif RIGID: M = [np.eye(4)]; slot_of = {0: 0}; bone_of = {0: 0}
else:
    M = palette_matrices(raw, sec); slot_of = map_palette(sk, M); bone_of = {s: b for b, s in slot_of.items()}
    OUT_IDX = skeleton_out_index(sk)                                # bone -> pose-output matrix index (bytecode order)
    # --allow-partial: palette slots with no matching skeleton bone stay in bind pose (assumes palette order == pose output order)
    assert len(bone_of) == len(M) or "--allow-partial" in args, f"palette mapping incomplete: {len(bone_of)}/{len(M)}"
    if len(bone_of) < len(M): print(f"partial palette match: {len(bone_of)}/{len(M)} slots animated")
n_slots = len(M)
Mg = [mirror(x) for x in M]
glb = GLB(); texcache = {}
root = glb.node(name="root"); traj_node = glb.node(name="trajectory"); glb.j["nodes"][root]["children"] = [traj_node]
joint_nodes = {}
# parent slot per slot
parent_slot = {}
for s in range(n_slots):
    if s not in bone_of: parent_slot[s] = None; continue          # unmapped slot: static under the trajectory node
    b = bones[bone_of[s]]; p = b["parent"]
    while p >= 0 and p not in slot_of: p = bones[p]["parent"]
    parent_slot[s] = slot_of[p] if p >= 0 else None
local_bind = {}
for s in range(n_slots):
    L = Mg[s] if parent_slot[s] is None else np.linalg.inv(Mg[parent_slot[s]]) @ Mg[s]
    local_bind[s] = L
    joint_nodes[s] = glb.node(name=bones[bone_of[s]]["name"] if s in bone_of else f"slot{s}", translation=[float(v) for v in L[:3, 3]], rotation=[float(v) for v in quat_from_mat(L[:3, :3])])
for s in range(n_slots):
    par = parent_slot[s]
    if par is None: glb.j["nodes"][traj_node].setdefault("children", []).append(joint_nodes[s])
    else: glb.j["nodes"][joint_nodes[par]].setdefault("children", []).append(joint_nodes[s])
skin = None
if not RIGID and not RIG:
    ibm = np.array([np.linalg.inv(Mg[s]).T.flatten() for s in range(n_slots)], np.float32)
    skin = len(glb.j["skins"]); glb.j["skins"].append({"joints": [joint_nodes[s] for s in range(n_slots)], "inverseBindMatrices": glb.accessor(ibm), "skeleton": joint_nodes[0]})
# mesh primitives
R3 = np.diag([1.0, 1.0, -1.0]); cvt = lambda v: (R3 @ np.asarray(v, np.float64).T).T
BLEND_SHADERS = {"smtranslucent", "smglass", "smfxenv"}
def material(matname):
    mat = m["materials"].get(matname, {}); tex = None; shader = str(mat.get("shader", "")).lower()
    for tn in (mat.get("tex0"), mat.get("tex1")):
        if tn and tn != "?":
            if tn not in texcache: img = load_tex(tn); texcache[tn] = glb.image_png(img, tn) if img else None
            if texcache[tn] is not None: tex = texcache[tn]; break
    mi = glb.material(matname, tex, "BLEND" if shader in BLEND_SHADERS else None, True)
    glb.j["materials"][mi]["extras"] = {"shader": shader}
    return mi
prims = []
if RIG:
    sec_mesh = {}
    for si, sc in enumerate(m["sections"]):
        sprims = []
        for sub in sc["subs"]:
            if not len(sub["tris"]) or not sub["nvert"]: continue
            attrs = {"POSITION": glb.accessor(cvt(sub["pos"]).astype(np.float32), 34962, minmax=True)}
            if sub.get("uv") is not None: attrs["TEXCOORD_0"] = glb.accessor(sub["uv"].astype(np.float32), 34962)
            if sub.get("nrm") is not None: attrs["NORMAL"] = glb.accessor(cvt(sub["nrm"]).astype(np.float32), 34962)
            sprims.append({"attributes": attrs, "indices": glb.accessor(sub["tris"][:, [0, 2, 1]].astype(np.uint32).flatten(), 34963), "material": material(sub["material"]), "mode": 4})
        if sprims: glb.j["meshes"].append({"name": sc["name"], "primitives": sprims}); sec_mesh[si] = len(glb.j["meshes"]) - 1
    for si, b, tx, sx in SEC_PAIRS:                           # the same section mesh may be instanced on several bones / offsets
        if si not in sec_mesh: continue
        mn_ = glb.node(name=f"{m['sections'][si]['name']}@{bones[b]['name']}", mesh=sec_mesh[si], translation=[float(tx), 0.0, 0.0], scale=[float(sx), 1.0, 1.0]); slot = OUT_IDX.get(b, 0)
        glb.j["nodes"][joint_nodes[slot] if slot in joint_nodes else traj_node].setdefault("children", []).append(mn_)
for sub in ([] if RIG else (sec["subs"] if not RIGID else [sb for sc in m["sections"] for sb in sc["subs"]])):
    if not len(sub["tris"]) or not sub["nvert"]: continue
    if (sub["stride"] != 32) != RIGID: continue
    if m["materials"].get(sub["material"], {}).get("shader", "").lower() in ("smshadowvol", "dropshadow"): continue   # shadow volumes (charactermorph heads ARE the visible heads on Peter/Harry)
    attrs = {"POSITION": glb.accessor(cvt(sub["pos"]).astype(np.float32), 34962, minmax=True)}
    if sub.get("uv") is not None: attrs["TEXCOORD_0"] = glb.accessor(sub["uv"].astype(np.float32), 34962)
    if sub.get("nrm") is not None: attrs["NORMAL"] = glb.accessor(cvt(sub["nrm"]).astype(np.float32), 34962)
    if not RIGID:
        bl = np.array(sub["bones"] + [0], dtype=np.uint16); J = sub["joints"].astype(np.int64); J = np.where(J == 255, len(sub["bones"]), J); Jg = bl[J].astype(np.uint16)
        Wt = sub["weights"].astype(np.float32); Wt[J == len(sub["bones"])] = 0; ssum = Wt.sum(1, keepdims=True); Wt = np.where(ssum > 0, Wt / np.maximum(ssum, 1e-6), np.array([1, 0, 0, 0], np.float32))
        attrs["JOINTS_0"] = glb.accessor(Jg, 34962); attrs["WEIGHTS_0"] = glb.accessor(Wt, 34962)
    prims.append({"attributes": attrs, "indices": glb.accessor(sub["tris"][:, [0, 2, 1]].astype(np.uint32).flatten(), 34963), "material": material(sub["material"]), "mode": 4})
if not RIG:
    glb.j["meshes"].append({"name": mesh_nm, "primitives": prims})
    if RIGID: mesh_node = glb.node(name=mesh_nm, mesh=len(glb.j["meshes"]) - 1); glb.j["nodes"][traj_node].setdefault("children", []).append(mesh_node)
    else: mesh_node = glb.node(name=mesh_nm, mesh=len(glb.j["meshes"]) - 1, skin=skin); glb.j["nodes"][root]["children"].append(mesh_node)
glb.j["scenes"][0]["nodes"] = [root]

# --- animations (full engine path: pose -> FK/IK bytecode -> bone matrices in palette order)
emu = NalEmu(); glb.j.setdefault("animations", [])
def decompose(L):
    R = L[:3, :3]; sc = np.linalg.norm(R, axis=0); Rn = R / np.where(sc > 1e-9, sc, 1); return L[:3, 3], quat_from_mat(Rn), sc
def add_clip(name, segments, root_motion=True, entity_fix=False):
    """segments: list of (rows, mats, chans, n_frames, fps, duration) in file order; consecutive segments overlap by one frame
    (segment k+1 frame 0 == segment k last frame), so later segments drop their first frame and continue at +1/fps."""
    rows_l, mats_l, chans_l, times_l, t0 = [], [], [], [], 0.0
    for si, (rows, mats, chans, n, fps, dur) in enumerate(segments):
        skip = 1 if si > 0 else 0
        rows_l.append(rows[skip:] if rows is not None else None); mats_l.append(mats[skip:]); chans_l.append((chans, skip))
        times_l.append(t0 + np.arange(skip, n) / fps); t0 += dur
    mats = np.concatenate(mats_l); n = mats.shape[0]; times = np.concatenate(times_l).astype(np.float32); t_acc = glb.accessor(times, None, minmax=True)
    def chan(pred):
        parts = []
        for chans, skip in chans_l:
            c = next((c for c in chans.values() if pred(c)), None)
            if c is None: return None
            parts.append({"quat": c["data"]["quat"][skip:], "pos": c["data"]["pos"][skip:]})
        return {"data": {"quat": np.concatenate([x["quat"] for x in parts]), "pos": np.concatenate([x["pos"] for x in parts])}}
    samplers, channels = [], []
    def add(node, path, vals):
        samplers.append({"input": t_acc, "output": glb.accessor(np.asarray(vals, np.float32)), "interpolation": "LINEAR"}); channels.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": path}})
    pal0 = M[0]                                                   # column-vector model-from-pelvis (bind)
    W = np.zeros((n, n_slots, 4, 4))
    for f in range(n):
        for s in range(n_slots):
            mi = OUT_IDX.get(bone_of.get(s), s) if (not RIGID or RIG) else 0   # pose output index for this palette slot
            Mrv = mats[f, mi].astype(np.float64) if ((not RIGID or RIG) and mi < mats.shape[1]) else np.eye(4)   # row-vector, pelvis-root space
            W[f, s] = mirror(pal0 @ Mrv.T)                          # column: model_from_bone = pal0 · mats^T  -> glTF handedness
    for s in (range(n_slots) if (not RIGID or RIG) else []):
        if s not in bone_of or OUT_IDX.get(bone_of[s], s) >= mats.shape[1]: continue
        par = parent_slot[s]; rots, poss, scs = [], [], []
        for f in range(n):
            L = W[f, s] if par is None else np.linalg.inv(W[f, par]) @ W[f, s]
            t, q, sc = decompose(L); rots.append(q); poss.append(t); scs.append(sc)
        add(joint_nodes[s], "rotation", rots); add(joint_nodes[s], "translation", poss)
        if np.abs(np.array(scs) - 1).max() > 0.02: add(joint_nodes[s], "scale", scs)
    po = chan(lambda c: c["type"] == "ae_base_bone" and c["kind"] == "posori")
    tr = chan(lambda c: c["type"] == "nal_trajectory")
    # Stored posori quats are "view-style" (same as the camera): column world_from_root = R(q)^T = R(conj q).  The pose
    # matrices are relative to the pelvis-root frame (not model space), so world_from_bone = T_traj · mats^T; since the joint
    # nodes carry model_from_bone = pal0 · mats^T, the trajectory node gets T_traj · inv(pal0).
    def conj(q): return np.array([-q[0], -q[1], -q[2], q[3]])
    # Gameplay (XBANIM) clips: the trajectory is relative (identity at frame 0) and ae_base_bone places the pelvis-root frame in the
    # ENTITY frame, whose axes are root-like (-X up, -Z forward).  Map it to Y-up with a fixed -90 deg turn about Z (D3D coords).
    RFIX = np.eye(4); RFIX[:3, :3] = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])   # x -> -y, y -> x  (so -X -> +Y)
    inv_pal0 = np.linalg.inv(pal0); rots, poss = [], []
    for f in range(n):
        E = np.eye(4)
        if po is not None: E[:3, :3] = mat_from_quat(conj(po["data"]["quat"][f])); E[:3, 3] = po["data"]["pos"][f]
        if root_motion and tr is not None:
            Tm = np.eye(4); Tm[:3, :3] = mat_from_quat(conj(tr["data"]["quat"][f])); Tm[:3, 3] = tr["data"]["pos"][f]; E = Tm @ E
        if entity_fix: E = RFIX @ E
        E = mirror(E @ inv_pal0); t, q, sc = decompose(E); rots.append(q); poss.append(t)
    add(traj_node, "rotation", rots); add(traj_node, "translation", poss)
    extras = {}
    fo = []
    for chans, skip in chans_l:
        c = next((c for c in chans.values() if c["type"] == "ae_floor_offset"), None)
        if c is None: fo = None; break
        fo += [float(v) for v in c["data"][skip:]]
    if fo: extras["floor_offset"] = [round(v, 4) for v in fo]          # entity origin sits at the pelvis; this is its height above the floor
    glb.j["animations"].append({"name": name, "samplers": samplers, "channels": channels, **({"extras": extras} if extras else {})})
for spec in [a for a in opt("--anim", "").split(",") if a]:
    rs, bname = spec.split(":"); d = res(rs, 0x14)
    segs = []
    for b in find_blocks(d):
        if d[b+0xc:b+0x28].split(b"\0")[0].decode() == bname and struct.unpack_from("<I", d, b + 0x44)[0] > 0 and struct.unpack_from("<I", d, b + 0x64)[0] > 0:
            blk = parse_block(d, b, sk["n_anim_channels"]); dec = decode_block(emu, skraw, d, blk)
            rows, mats = emu.decode_matrices(sk, d, blk) if (not RIGID or RIG) else (None, np.zeros((blk["n_frames"], 1, 4, 4)))
            segs.append((rows, mats, dec["channels"], blk["n_frames"], blk["fps"], blk["duration"]))
    assert segs, f"block {bname} not in {rs}"
    add_clip(f"{rs.split('/')[1]}:{bname}", segs, root_motion="--no-root-motion" not in args)
    print(f"clip {rs}:{bname}: {len(segs)} segments, {sum(x[3] for x in segs)} frames @ {segs[0][4]} fps, {sum(x[5] for x in segs):.2f}s")
for xa in [a for a in opt("--xbanim", "").split(",") if a]:            # gameplay clips: PACK/NAME[,PACK/NAME...]; in place (no root motion)
    d = res(xa, 1)
    if d is None: print("  xbanim missing:", xa); continue
    blk = parse_block(d, find_blocks(d)[0], sk["n_anim_channels"]); rows, mats = emu.decode_matrices(sk, d, blk); dec = decode_block(emu, skraw, d, blk)
    add_clip(xa.split("/")[1], [(rows, mats, dec["channels"], blk["n_frames"], blk["fps"], blk["duration"])], root_motion="--root-motion" in args, entity_fix=True)
    print(f"xbanim {xa}: {blk['n_frames']} frames, {blk['duration']:.2f}s")
out = opt("--out", f"public/models/xbox/anim/{mesh_nm.lower()}.glb"); Path(out).parent.mkdir(parents=True, exist_ok=True); size = glb.write(out)
print(f"wrote {out} ({size/1e6:.2f} MB): {n_slots} joints, {len(prims)} prims, {len(glb.j['animations'])} clips")
