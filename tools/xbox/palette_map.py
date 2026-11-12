"""Map mesh bone-palette slots (bind matrices, model space) to XBSKEL bones.
Rule: walk the skeleton from the root; a child's slot is the unassigned slot whose translation in the parent's bind frame matches the
stored local translation (FK bones) or lies along -X (Biped IK bones without stored translation)."""
import numpy as np

def palette_matrices(raw, sec):
    pal = np.frombuffer(raw[sec["palette_off"]: sec["palette_off"] + 64 * sec["bone_count"]], "<f4").reshape(-1, 4, 4).astype(np.float64)
    return [p.T.copy() for p in pal]          # column-vector model-from-bone

def map_palette(sk, M, tol=0.006):
    bones = sk["bones"]; d = sk["raw"]; TB = sk["offsets"]["trans"]
    def stored_t(b):
        if b["a"] == 0 and b["name"] != "bip01 spine": return None
        return np.frombuffer(d[TB + b["a"]: TB + b["a"] + 12], "<f4").astype(np.float64)
    inv = [np.linalg.inv(m) for m in M]; n = len(M)
    children = {}
    for i, b in enumerate(bones): children.setdefault(b["parent"], []).append(i)
    slot_of = {}; used = set()
    roots = [i for i, b in enumerate(bones) if b["parent"] < 0]
    # root = slot with (near) zero translation and the largest subtree; for bipeds slot 0
    root_bone = next((i for i in roots if children.get(i)), roots[0]); slot_of[root_bone] = 0; used.add(0)
    queue = [root_bone]
    while queue:
        b = queue.pop(0); p = slot_of[b]
        for c in children.get(b, []):
            t = stored_t(bones[c]); best = None
            for s in range(n):
                if s in used: continue
                L = inv[p] @ M[s]; tl = L[:3, 3]
                if t is not None: err = np.linalg.norm(tl - t)
                else: err = (abs(tl[1]) + abs(tl[2])) if (tl[0] < -0.02) else 1e9     # IK bone: along -X, no stored length
                if best is None or err < best[0]: best = (err, s)
            lim = tol if t is None else max(tol, min(0.03, 0.08 * float(np.linalg.norm(t))))   # 8% of bone length (BLACK_CAT spine stores y=0.006)
            if best and best[0] < lim: slot_of[c] = best[1]; used.add(best[1]); queue.append(c)
    return slot_of


# --- matrix output order from the skeleton bytecode (FUN_00338980) ---------------------------------------------------
# The pose evaluator walks the skeleton bytecode; every op whose high bit is clear consumes the NEXT element of the pose
# buffer (channels in group order), and its operand byte is the output matrix index it writes.  Opcode sizes (pose bytes):
# 0 trans 12, 1 quat 16, 2 posori 32, 3 scale 12, 5 IK 80 (operands: parent, upperarm, forearm, hand, ref + 0x14 param bytes),
# 0xc compose (parent, child; no pose data), 0xe seek (operand = bytes).  So matrix index <-> channel <-> channel.bone.
import struct as _struct
_POSE_SIZES = {"posori": 0x20, "quat16": 0x10, "quat8": 0x10, "quatf": 0x10, "ikspin": 0x50, "float1": 4, "float3": 12, "signal": 1}
def skeleton_out_index(sk):
    """returns {bone_index: output_matrix_index} derived from the skeleton bytecode"""
    from .anim_decode import layout_for
    raw = sk["raw"]; A = _struct.unpack_from("<I", raw, 0x64)[0]; bc = raw[0xe0:0xe0 + A]
    ch_at = {}
    for g in sk["groups"]:
        try: al, size, kind = layout_for(g["name"])
        except KeyError: continue
        for k in range(g["count"]): ch_at[g["out_off"] + k * _POSE_SIZES[kind]] = g["first"] + k
    bones = sk["bones"]; out = {}; pose = 0; i = 0
    def chan_bone(off):
        c = ch_at.get(off); return sk["channels"][c]["bone"] if c is not None and c < len(sk["channels"]) else None
    while i < len(bc):
        op = bc[i]; rest = bool(op & 0x80); op &= 0x7f
        if op in (0, 1, 2, 3):
            m = bc[i + 1]; size = {0: 12, 1: 16, 2: 32, 3: 12}[op]
            if not rest:
                b = chan_bone(pose)
                if b is not None and op != 3: out.setdefault(b, m)
                pose += size
            i += 2
        elif op == 5:
            par, upper, fore, hand = bc[i + 1], bc[i + 2], bc[i + 3], bc[i + 4]
            if not rest:
                b = chan_bone(pose)                                   # generic_ik channel's bone = effector (hand/foot)
                if b is not None:
                    out.setdefault(b, hand); pb = bones[b]["parent"]
                    if pb >= 0: out.setdefault(pb, fore); ppb = bones[pb]["parent"]
                    if pb >= 0 and ppb >= 0: out.setdefault(ppb, upper)
                pose += 0x50
            i += 0x1a
        elif op == 0xc: i += 3
        elif op == 0xe:
            if not rest: pose += bc[i + 1]
            i += 2
        else: break
    return out
