"""UE2 UTexture -> PIL image."""
import io, struct
from PIL import Image
from .props import object_props
from .package import ObjRef

FORMATS = {0: "P8", 1: "RGBA7", 2: "RGB16", 3: "DXT1", 4: "RGB8", 5: "RGBA8", 6: "NODATA", 7: "DXT3", 8: "DXT5", 9: "L8", 10: "G16", 11: "RRRGGGBBB"}


def _dds(fourcc, w, h, data):
    hdr = bytearray(128)
    struct.pack_into("<4sIIIIIII", hdr, 0, b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, h, w, len(data), 0, 1)
    struct.pack_into("<II4s", hdr, 76, 32, 0x4, fourcc)
    struct.pack_into("<I", hdr, 108, 0x1000)
    return bytes(hdr) + data


def read_mips(r):
    mips = []
    for _ in range(r.idx()):
        r.i32()
        n = r.idx(); data = r.bytes(n)
        usize, vsize = r.i32(), r.i32()
        r.u8(); r.u8()
        mips.append((usize, vsize, data))
    return mips


def load_palette(pkg, export):
    props, r, end = object_props(pkg, export)
    n = r.idx()
    cols = [r.color() for _ in range(n)]
    return cols


def decode(fmt, w, h, data, palette=None):
    f = FORMATS.get(fmt, fmt)
    if f == "P8":
        img = Image.frombytes("P", (w, h), data[:w * h])
        if palette:
            flat = []
            alpha = []
            for (rr, g, b, a) in palette[:256]:
                flat += [rr, g, b]; alpha.append(a)
            while len(flat) < 768: flat += [0, 0, 0]
            img.putpalette(flat)
            img = img.convert("RGBA")
            if any(a != 255 for a in alpha):
                idx = Image.frombytes("P", (w, h), data[:w * h])
                lut = bytes(alpha + [255] * (256 - len(alpha)))
                img.putalpha(idx.point(lut).convert("L"))
            return img
        return img.convert("RGBA")
    if f in ("DXT1", "DXT3", "DXT5"):
        return Image.open(io.BytesIO(_dds(f.encode(), w, h, data))).convert("RGBA")
    if f == "RGBA8":
        return Image.frombytes("RGBA", (w, h), data[:w * h * 4], "raw", "BGRA")
    if f == "RGB8":
        return Image.frombytes("RGB", (w, h), data[:w * h * 3], "raw", "BGR").convert("RGBA")
    if f == "L8":
        return Image.frombytes("L", (w, h), data[:w * h]).convert("RGBA")
    if f == "G16":
        return Image.frombytes("I;16", (w, h), data[:w * h * 2]).point(lambda v: v // 256).convert("RGBA")
    if f == "RGB16":
        return Image.frombytes("RGB", (w, h), data[:w * h * 2], "raw", "BGR;16").convert("RGBA")
    raise ValueError(f"unsupported texture format {f}")


def load_texture(pkg, export):
    """Return (PIL.Image RGBA, props) for a UTexture export."""
    props, r, end = object_props(pkg, export)
    fmt = props.get("Format", 0)
    mips = read_mips(r)
    if not mips:
        return None, props
    w, h, data = mips[0]
    palette = None
    if FORMATS.get(fmt) == "P8":
        pal = props.get("Palette")
        if isinstance(pal, ObjRef) and pal:
            ppkg, pexp = pal.resolve()
            if pexp:
                palette = load_palette(ppkg, pexp)
    img = decode(fmt, w, h, data, palette)
    return img, props
