"""Minimal GLB (glTF binary) read/write + accessor helpers shared by merge_clips.py and bulk_mesh.py: no external packages."""
import json, struct
import numpy as np

CT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

def read_glb(path):
    d = open(path, "rb").read(); assert d[:4] == b"glTF", path
    ln = struct.unpack_from("<I", d, 12)[0]; j = json.loads(d[20:20 + ln]); off = 20 + ln
    cl, ct = struct.unpack_from("<II", d, off); assert ct == 0x004E4942
    return j, bytearray(d[off + 8: off + 8 + cl])

def write_glb(path, j, binb):
    jb = json.dumps(j, separators=(",", ":")).encode(); jb += b" " * (-len(jb) % 4); binb = bytes(binb) + b"\0" * (-len(binb) % 4)
    j["buffers"][0]["byteLength"] = len(binb); jb = json.dumps(j, separators=(",", ":")).encode(); jb += b" " * (-len(jb) % 4)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(jb) + 8 + len(binb)) + struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(binb), 0x004E4942) + binb
    open(path, "wb").write(out)

def acc_read(j, binb, i):
    a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]; n = NC[a["type"]]; dt = np.dtype(CT[a["componentType"]])
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0); stride = bv.get("byteStride")
    if stride and stride != n * dt.itemsize:
        raw = np.frombuffer(binb, dtype="u1", count=stride * a["count"] - (stride - n * dt.itemsize), offset=off)
        return np.lib.stride_tricks.as_strided(raw.view(dt)[:0], shape=(0,)) if False else np.array([np.frombuffer(binb, dtype=dt, count=n, offset=off + k * stride) for k in range(a["count"])]).reshape(a["count"], n)
    return np.frombuffer(binb, dtype=dt, count=a["count"] * n, offset=off).reshape(a["count"], n).copy()

def acc_write_inplace(j, binb, i, arr):
    a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]; n = NC[a["type"]]; dt = np.dtype(CT[a["componentType"]])
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0); stride = bv.get("byteStride") or n * dt.itemsize
    arr = np.ascontiguousarray(arr, dtype=dt).reshape(a["count"], n)
    for k in range(a["count"]): binb[off + k * stride: off + k * stride + n * dt.itemsize] = arr[k].tobytes()
    a["min"] = [float(v) for v in arr.min(axis=0)]; a["max"] = [float(v) for v in arr.max(axis=0)]

def acc_append(j, binb, arr, ctype, atype, with_bounds=False):
    arr = np.ascontiguousarray(arr, dtype=np.dtype(CT[ctype])); raw = arr.tobytes(); binb += b"\0" * (-len(binb) % 4); off = len(binb); binb += raw
    j.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": off, "byteLength": len(raw)})
    acc = {"bufferView": len(j["bufferViews"]) - 1, "componentType": ctype, "count": int(arr.shape[0]), "type": atype}
    if with_bounds: acc["min"] = [float(v) for v in arr.reshape(arr.shape[0], -1).min(axis=0)]; acc["max"] = [float(v) for v in arr.reshape(arr.shape[0], -1).max(axis=0)]
    j.setdefault("accessors", []).append(acc); return len(j["accessors"]) - 1
