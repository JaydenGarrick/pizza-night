"""Minimal GLB reader: JSON + accessors to numpy."""
import json, struct
import numpy as np
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GLBFile:
    def __init__(self, path):
        with open(path, "rb") as f:
            f.read(12)
            ln, = struct.unpack("<I", f.read(4)); f.read(4); self.j = json.loads(f.read(ln))
            self.bin = b""
            while True:
                h = f.read(8)
                if len(h) < 8: break
                n, typ = struct.unpack("<I4s", h); data = f.read(n)
                if typ == b"BIN\0": self.bin = data

    def accessor(self, idx):
        a = self.j["accessors"][idx]; bv = self.j["bufferViews"][a["bufferView"]]
        dt = np.dtype(CT[a["componentType"]]); nc = NC[a["type"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride")
        if stride and stride != dt.itemsize * nc:
            raw = np.frombuffer(self.bin, dtype=np.uint8, count=stride * a["count"], offset=off).reshape(a["count"], stride)[:, :dt.itemsize * nc].copy()
            arr = np.frombuffer(raw.tobytes(), dtype=dt).reshape(a["count"], nc)
        else:
            arr = np.frombuffer(self.bin, dtype=dt, count=a["count"] * nc, offset=off).reshape(a["count"], nc)
        return arr

    def view_bytes(self, idx):
        bv = self.j["bufferViews"][idx]; off = bv.get("byteOffset", 0)
        return self.bin[off:off + bv["byteLength"]]

    def node_world(self):
        """world matrices for all nodes (scene 0)."""
        nodes = self.j["nodes"]; W = [None] * len(nodes)
        def local(n):
            if "matrix" in n: return np.array(n["matrix"], dtype=np.float64).reshape(4, 4).T
            m = np.eye(4)
            t = n.get("translation", [0, 0, 0]); q = n.get("rotation", [0, 0, 0, 1]); s = n.get("scale", [1, 1, 1])
            x, y, z, w = q
            R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            m[:3, :3] = R * np.array(s); m[:3, 3] = t; return m
        def rec(i, parent):
            W[i] = parent @ local(nodes[i])
            for c in nodes[i].get("children", []): rec(c, W[i])
        for r in self.j["scenes"][self.j.get("scene", 0)]["nodes"]: rec(r, np.eye(4))
        for i in range(len(nodes)):
            if W[i] is None: W[i] = local(nodes[i])
        return W
