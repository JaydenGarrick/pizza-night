"""Decode Xbox NAL animation blocks into per-channel values using the emulated engine decoder (nal_emu) + the row layout
derived from the codec page-decode routines (slot 6):
  posori / trajectory : align16, 0x20 B  = quat(4 f32) pos(3 f32) pad
  packed16 quaternion : align2,  6 B     = 3 x int16 (x,y,z) * K ; w = sqrt(|1-|v|^2|)
  packed16 ikspin     : align2,  0x16 B  = 2 packed quats (12) + 3 x int16 position + int16 flags
  entropy float1      : align4,  4 B
  signal counter      : align4,  1 B per channel
Alignment is applied at each group start; only channels whose mask bit is set occupy row bytes."""
import struct, numpy as np
from .nal_emu import NalEmu, parse_skeleton, parse_block, find_blocks

K16 = 1.0 / 32767.0   # DAT_0044e264 (see read-out)
LAYOUT = {  # codec name prefix -> (align, bytes per channel, kind)
    "nal_entropypositionorientat": (16, 0x20, "posori"), "nal_positionorientation": (16, 0x20, "posori"),
    "nal_entropytrajectorypositi": (16, 0x20, "posori"), "nal_trajectorypositionori": (16, 0x20, "posori"),
    "nal_packed16entropyquaterni": (2, 6, "quat16"), "nal_packed8entropyquaternio": (2, 3, "quat8"),
    "nal_entropyquaternion": (16, 16, "quatf"), "nal_quaternion": (16, 16, "quatf"),
    "nal_packed16entropyikspin": (2, 0x16, "ikspin"), "nal_entropyfloat1": (4, 4, "float1"), "nal_entropyfloat3": (4, 12, "float3"),
    "spidey_signal": (4, 1, "signal"), "nal_signalcounter": (4, 1, "signal"),
}
def layout_for(name):
    n = name.lower()
    for k, v in LAYOUT.items():
        if n.startswith(k[:min(len(k), len(n))]) or k.startswith(n): return v
    raise KeyError(name)

def mask_bit(mask, ch): return (mask[ch >> 5] >> (ch & 31)) & 1

def row_layout(sk, blk):
    """returns list of (channel_index, kind, row_offset) in stream order"""
    out = []; off = 0
    for g in sk["groups"]:
        al, size, kind = layout_for(g["name"]); off = (off + al - 1) // al * al
        for k in range(g["count"]):
            ch = g["first"] + k
            if mask_bit(blk["mask"], ch): out.append((ch, kind, off)); off += size
    return out

def unpack_quat16(b):
    v = np.frombuffer(b[:6], "<i2").astype(np.float64) * K16; w = np.sqrt(abs(1.0 - float(v @ v))); return np.array([v[0], v[1], v[2], w])

def decode_block(emu, skel_raw, file_bytes, blk):
    sk = parse_skeleton(skel_raw); rows = emu.decode_native(skel_raw, file_bytes, blk); lay = row_layout(sk, blk)
    chans = {}
    for ch, kind, off in lay:
        c = sk["channels"][ch]; bone = sk["bones"][c["bone"]]["name"] if c["bone"] < len(sk["bones"]) else None
        if kind == "posori":
            f = np.frombuffer(rows[:, off:off + 0x20].tobytes(), "<f4").reshape(-1, 8); val = {"quat": f[:, 0:4].copy(), "pos": f[:, 4:7].copy()}
        elif kind == "quat16": val = np.array([unpack_quat16(r[off:off + 6].tobytes()) for r in rows])
        elif kind == "quatf": val = np.frombuffer(rows[:, off:off + 16].tobytes(), "<f4").reshape(-1, 4).copy()
        elif kind == "ikspin":
            raw = rows[:, off:off + 0x16]
            val = {"qa": np.array([unpack_quat16(r[0:6].tobytes()) for r in raw]), "qb": np.array([unpack_quat16(r[6:12].tobytes()) for r in raw]),
                   "pos_i16": np.frombuffer(raw[:, 12:18].tobytes(), "<i2").reshape(-1, 3).copy(), "flags": np.frombuffer(raw[:, 18:20].tobytes(), "<i2").copy()}
        elif kind == "float1": val = np.frombuffer(rows[:, off:off + 4].tobytes(), "<f4").copy()
        elif kind == "float3": val = np.frombuffer(rows[:, off:off + 12].tobytes(), "<f4").reshape(-1, 3).copy()
        else: val = rows[:, off].copy()
        chans[ch] = {"type": c["type"], "bone": bone, "kind": kind, "data": val}
    return {"skeleton": sk, "block": blk, "channels": chans, "n_frames": blk["n_frames"], "fps": blk["fps"]}
