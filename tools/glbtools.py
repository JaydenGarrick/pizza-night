"""Small GLB read/write helpers: swap an embedded image, drop primitives by material name."""
import json, struct
def read_glb(path):
    d = open(path, "rb").read(); ln = struct.unpack_from("<I", d, 12)[0]; j = json.loads(d[20:20 + ln]); off = 20 + ln; cl = struct.unpack_from("<I", d, off)[0]
    return j, bytearray(d[off + 8: off + 8 + cl])
def write_glb(path, j, b):
    b = bytearray(b)
    while len(b) % 4: b.append(0)
    j["buffers"][0]["byteLength"] = len(b)
    js = json.dumps(j, separators=(",", ":")).encode(); js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(b)
    with open(path, "wb") as f: f.write(b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(js)) + b"JSON" + js + struct.pack("<I", len(b)) + b"BIN\0" + bytes(b))
    return total
def swap_image(j, b, name, png_bytes):
    n = 0
    for im in j["images"]:
        if (im.get("name") or "").lower() == name.lower():
            while len(b) % 4: b.append(0)
            j["bufferViews"].append({"buffer": 0, "byteOffset": len(b), "byteLength": len(png_bytes)}); b += png_bytes
            im["bufferView"] = len(j["bufferViews"]) - 1; im["mimeType"] = "image/png"; n += 1
    return n
def drop_prims(j, pred):
    n = 0
    for m in j["meshes"]:
        keep = [p for p in m["primitives"] if not pred(j["materials"][p["material"]])]; n += len(m["primitives"]) - len(keep); m["primitives"] = keep
    return n
