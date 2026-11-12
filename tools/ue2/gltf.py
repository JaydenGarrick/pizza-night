"""Minimal GLB writer (glTF 2.0) with skins, animations, PNG textures."""
import json, struct, io
import numpy as np

COMP = {np.dtype("float32"): 5126, np.dtype("uint8"): 5121, np.dtype("uint16"): 5123, np.dtype("uint32"): 5125, np.dtype("int8"): 5120, np.dtype("int16"): 5122}


class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.j = {"asset": {"version": "2.0", "generator": "sm2-office ue2 exporter"}, "buffers": [], "bufferViews": [], "accessors": [],
                  "meshes": [], "nodes": [], "scenes": [{"nodes": []}], "scene": 0, "materials": [], "textures": [], "images": [], "samplers": [],
                  "skins": [], "animations": []}

    def _align(self, n=4):
        while len(self.bin) % n:
            self.bin.append(0)

    def view(self, data: bytes, target=None, stride=None):
        self._align()
        off = len(self.bin); self.bin += data
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target: v["target"] = target
        if stride: v["byteStride"] = stride
        self.j["bufferViews"].append(v)
        return len(self.j["bufferViews"]) - 1

    def accessor(self, arr, target=None, minmax=False, normalized=False):
        arr = np.ascontiguousarray(arr)
        if arr.ndim == 1: arr = arr.reshape(-1, 1)
        n, comps = arr.shape
        typ = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4", 16: "MAT4"}[comps]
        acc = {"bufferView": self.view(arr.tobytes(), target), "componentType": COMP[arr.dtype], "count": int(n), "type": typ}
        if normalized: acc["normalized"] = True
        if minmax:
            acc["min"] = [float(x) for x in arr.min(0)]; acc["max"] = [float(x) for x in arr.max(0)]
        self.j["accessors"].append(acc)
        return len(self.j["accessors"]) - 1

    def image_png(self, pil_img, name=None):
        buf = io.BytesIO(); pil_img.save(buf, format="PNG")
        img = {"bufferView": self.view(buf.getvalue()), "mimeType": "image/png"}
        if name: img["name"] = name
        self.j["images"].append(img)
        if not self.j["samplers"]:
            self.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})
        self.j["textures"].append({"source": len(self.j["images"]) - 1, "sampler": 0})
        return len(self.j["textures"]) - 1

    def material(self, name, tex=None, alpha_mode=None, double_sided=False, emissive_tex=None):
        m = {"name": name, "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9}}
        if tex is not None: m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex}
        if alpha_mode: m["alphaMode"] = alpha_mode
        if double_sided: m["doubleSided"] = True
        if emissive_tex is not None:
            m["emissiveTexture"] = {"index": emissive_tex}; m["emissiveFactor"] = [1, 1, 1]
        self.j["materials"].append(m)
        return len(self.j["materials"]) - 1

    def node(self, **kw):
        self.j["nodes"].append(kw)
        return len(self.j["nodes"]) - 1

    def write(self, path):
        self._align()
        self.j["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4: js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<4sII", b"glTF", 2, total))
            f.write(struct.pack("<I4s", len(js), b"JSON")); f.write(js)
            f.write(struct.pack("<I4s", len(self.bin), b"BIN\0")); f.write(self.bin)
        return total
