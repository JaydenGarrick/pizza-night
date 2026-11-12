#!/usr/bin/env python3
"""Replace an embedded image in a GLB: glb_swap_texture.py --glb in.glb --image-name <image name substring> --png new.png --out out.glb"""
import sys, json, struct
args = sys.argv[1:]
def opt(f, d=None):
    if f in args: i = args.index(f); v = args[i + 1]; del args[i:i + 2]; return v
    return d
src, name, png, out = opt("--glb"), opt("--image-name"), opt("--png"), opt("--out")
d = open(src, "rb").read(); ln = struct.unpack_from("<I", d, 12)[0]; j = json.loads(d[20:20 + ln]); off = 20 + ln; cl = struct.unpack_from("<I", d, off)[0]; b = bytearray(d[off + 8: off + 8 + cl])
new = open(png, "rb").read(); n = 0
for im in j["images"]:
    if name.lower() in (im.get("name") or im.get("uri") or "").lower():
        while len(b) % 4: b.append(0)
        j["bufferViews"].append({"buffer": 0, "byteOffset": len(b), "byteLength": len(new)}); b += new; im["bufferView"] = len(j["bufferViews"]) - 1; im["mimeType"] = "image/png"; n += 1
j["buffers"][0]["byteLength"] = len(b)
js = json.dumps(j, separators=(",", ":")).encode(); js += b" " * ((4 - len(js) % 4) % 4)
while len(b) % 4: b.append(0)
total = 12 + 8 + len(js) + 8 + len(b)
with open(out, "wb") as f:
    f.write(b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(js)) + b"JSON" + js + struct.pack("<I", len(b)) + b"BIN\0" + bytes(b))
print(f"replaced {n} image(s) -> {out} ({total/1e6:.2f} MB)")
