#!/usr/bin/env python3
"""F&F Pizzeria skin for Joe's Pizza (F48 facade + F48I01 interior): navy textures (ff_recolor.py output), new sign art and 3D sign models.
Writes: intermediate/ff/billboard_v{1,2,3}.png, public/models/xbox/static/F48__f48_i01front_ff_v{1,2,3}.glb, F48I01__*_ff.glb,
FF__ff_sign_v2.glb (extruded script F&F + PIZZERIA letters + crest plaque), FF__ff_blade.glb (hanging blade sign), public/ff/skin_v{1,2,3}.json.
3D letters are pixel-extruded from the logo masks (no mesh libs): merged front/back runs + boundary side quads, vertex-colour shaded (world is unlit)."""
import sys, json, io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
sys.path.insert(0, "tools")
from ue2.gltf import GLB
from glbtools import read_glb, write_glb, swap_image, drop_prims
FF = Path("intermediate/ff"); ST = Path("public/models/xbox/static"); SK = Path("public/ff")
NAVY = (28, 78, 142); GOLD = (196, 162, 96); CREAM = (241, 234, 217); NAVY_LIN = np.array([(c / 255) ** 2.2 for c in NAVY]); GOLD_LIN = np.array([(c / 255) ** 2.2 for c in GOLD]); CREAM_LIN = np.array([(c / 255) ** 2.2 for c in CREAM])
FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"
crest = Image.open(FF / "ff_crest.png").convert("RGBA")
script = Image.open(FF / "ff_script_logo.png").convert("L"); script_mask = ImageOps.invert(script).point(lambda v: 255 if v > 110 else 0); script_mask = script_mask.crop(script_mask.getbbox())

# ---------------------------------------------------------------- billboard textures (front quad samples v 0.05..0.5 = rows 51..512 of 1024)
def text_img(txt, font_px, color, index=0, tracking=0):
    f = ImageFont.truetype(FUTURA, font_px, index=index); w = sum(f.getlength(ch) for ch in txt) + tracking * (len(txt) - 1); h = font_px * 1.3
    im = Image.new("RGBA", (int(w) + 4, int(h) + 4), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = 2
    for ch in txt: d.text((x, 2), ch, font=f, fill=color); x += f.getlength(ch) + tracking
    return im.crop(im.getbbox())
def script_rgba(width, color):
    m = script_mask.resize((width, int(width * script_mask.height / script_mask.width)), Image.LANCZOS); im = Image.new("RGBA", m.size, color + (255,)); im.putalpha(m); return im
def board(kind):
    art = Image.new("RGBA", (1229, 461), CREAM + (255,)); d = ImageDraw.Draw(art)
    d.rectangle([8, 8, 1220, 452], outline=NAVY, width=10); d.rectangle([24, 24, 1204, 436], outline=GOLD, width=4)
    if kind == "v1":   # v2 gets its crest from the raised plaque, a painted one behind it doubled the wordmark
        c = crest.resize((int(crest.width * 380 / crest.height), 380), Image.LANCZOS); art.alpha_composite(c, (60, 40))
    if kind == "v1":
        s = script_rgba(480, NAVY); art.alpha_composite(s, (490, 28)); t = text_img("PIZZERIA", 84, NAVY, 0, 10); art.alpha_composite(t, (490 + (480 - t.width) // 2, 358))   # script sits clear of the wordmark
    if kind == "v3":
        c = crest.resize((int(crest.width * 400 / crest.height), 400), Image.LANCZOS); art.alpha_composite(c, ((1229 - c.width) // 2, 30))
        tl = text_img("F&F", 110, NAVY, 2, 6); tr = text_img("PIZZERIA", 70, NAVY, 0, 8); art.alpha_composite(tl, (120, 170)); art.alpha_composite(tr, (1229 - 120 - tr.width, 190))
    tex = Image.new("RGBA", (1024, 1024)); orig = Image.open(FF / "f48_i01sign.png").convert("RGBA").resize((1024, 1024), Image.LANCZOS); tex.paste(orig, (0, 0))
    tex.paste(art.resize((1024, 461), Image.LANCZOS), (0, 51)); tex.save(FF / f"billboard_{kind}.png"); return tex

# ---------------------------------------------------------------- pixel extrusion
class MeshBuf:
    def __init__(self): self.P = []; self.C = []; self.UV = []; self.I = []
    def quad(self, pts, col, uvs=None):
        b = len(self.P); self.P += [np.asarray(p, float) for p in pts]; self.C += [np.clip(col, 0, 1)] * 4; self.UV += (uvs or [(0, 0)] * 4); self.I += [b, b + 1, b + 2, b, b + 2, b + 3]
def extrude(buf, mask, px, O, U, V, N, depth, col):
    """mask HxW bool (row 0 top); O = world of mask pixel (0,0) corner on the front plane; U/V = world unit vectors along image x / image y (down);
    N = outward normal of the front face.  Shading (unlit world): front 1.0, back 0.9, up-facing 1.15, down-facing 0.55, sides 0.72."""
    H, W = mask.shape; O = np.asarray(O, float); U = np.asarray(U, float); V = np.asarray(V, float); N = np.asarray(N, float)
    pt = lambda c, r, z: O + U * (c * px) + V * (r * px) - N * z
    m = np.zeros((H + 2, W + 2), bool); m[1:-1, 1:-1] = mask
    for r in range(H):
        c = 0
        while c < W:
            if not mask[r, c]: c += 1; continue
            c0 = c
            while c < W and mask[r, c]: c += 1
            buf.quad([pt(c0, r, 0), pt(c0, r + 1, 0), pt(c, r + 1, 0), pt(c, r, 0)], col * 1.0); buf.quad([pt(c0, r, depth), pt(c, r, depth), pt(c, r + 1, depth), pt(c0, r + 1, depth)], col * 0.9)
    for c in range(W + 1):
        r = 0
        while r < H:
            L, R = m[r + 1, c], m[r + 1, c + 1]
            if L == R: r += 1; continue
            r0 = r
            while r < H and m[r + 1, c] == L and m[r + 1, c + 1] == R: r += 1
            buf.quad([pt(c, r0, 0), pt(c, r, 0), pt(c, r, depth), pt(c, r0, depth)], col * 0.72)
    for r in range(H + 1):
        c = 0
        while c < W:
            T, B = m[r, c + 1], m[r + 1, c + 1]
            if T == B: c += 1; continue
            c0 = c
            while c < W and m[r, c + 1] == T and m[r + 1, c + 1] == B: c += 1
            buf.quad([pt(c0, r, 0), pt(c, r, 0), pt(c, r, depth), pt(c0, r, depth)], col * (1.15 if (B and not T) else 0.55))   # solid below the edge = a top face
def box(buf, lo, hi, col):
    x0, y0, z0 = lo; x1, y1, z1 = hi
    buf.quad([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], col * 1.0); buf.quad([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], col * 0.9)
    buf.quad([(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)], col * 1.15); buf.quad([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], col * 0.55)
    buf.quad([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], col * 0.72); buf.quad([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], col * 0.72)
def mask_from(img_mask, width_px):
    m = img_mask.resize((width_px, max(1, int(width_px * img_mask.height / img_mask.width))), Image.LANCZOS); return np.asarray(m) > 128
def text_mask(txt, px_height, index=0, tracking=0):
    f = ImageFont.truetype(FUTURA, 200, index=index); w = int(sum(f.getlength(ch) for ch in txt) + tracking * (len(txt) - 1)) + 8
    im = Image.new("L", (w, 280), 0); d = ImageDraw.Draw(im); x = 4
    for ch in txt: d.text((x, 20), ch, font=f, fill=255); x += f.getlength(ch) + tracking
    im = im.crop(im.getbbox()); return np.asarray(im.resize((int(im.width * px_height / im.height), px_height), Image.LANCZOS)) > 128
def flush(glb, buf, name, mat):
    P = np.array(buf.P, np.float32); C = np.array(buf.C, np.float32); UV = np.array(buf.UV, np.float32); I = np.array(buf.I, np.uint32)
    attrs = {"POSITION": glb.accessor(P, 34962, minmax=True), "COLOR_0": glb.accessor(np.concatenate([C, np.ones((len(C), 1), np.float32)], 1), 34962), "TEXCOORD_0": glb.accessor(UV, 34962)}
    glb.j["meshes"].append({"name": name, "primitives": [{"attributes": attrs, "indices": glb.accessor(I, 34963), "material": mat, "mode": 4}]}); return glb.node(name=name, mesh=len(glb.j["meshes"]) - 1)

# ---------------------------------------------------------------- sign models (world coordinates; the facade sign board is x -264.5..-256.5, y 7..10, z 735.2, street at z < 735)
# viewer looks north (+z): screen-right = world -x, so image x runs along -x
def build_relief():
    glb = GLB(); plain = glb.material("ff_navy", None, None, True); glb.j["materials"][plain]["extras"] = {"unlit": True}
    buf = MeshBuf()
    sm = mask_from(script_mask, 170); px = 2.5 / 170; H = sm.shape[0] * px                          # script F&F 2.5 m wide
    extrude(buf, sm, px, O=(-259.15, 9.85, 735.0), U=(-1, 0, 0), V=(0, -1, 0), N=(0, 0, -1), depth=0.18, col=NAVY_LIN)
    tm = text_mask("PIZZERIA", 36, 0, 14); tpx = 3.3 / tm.shape[1]
    extrude(buf, tm, tpx, O=(-259.2 - (5.1 - 3.3) / 2 + 0.0, 7.8, 735.0), U=(-1, 0, 0), V=(0, -1, 0), N=(0, 0, -1), depth=0.14, col=NAVY_LIN)
    n1 = flush(glb, buf, "FF_LETTERS", plain)
    # crest plaque: alpha-masked quad 8 cm proud of the board, 2.6 m tall at the viewer's left (east)
    tex = glb.image_png(crest, "ff_crest"); pm = glb.material("ff_crest", tex, "MASK", True); glb.j["materials"][pm]["alphaCutoff"] = 0.5; glb.j["materials"][pm]["extras"] = {"unlit": True}
    pb = MeshBuf(); h = 2.6; w = h * crest.width / crest.height; x0 = -256.75; y1 = 9.8; z = 735.12
    pb.quad([(x0, y1, z), (x0, y1 - h, z), (x0 - w, y1 - h, z), (x0 - w, y1, z)], np.ones(3), uvs=[(0, 0), (0, 1), (1, 1), (1, 0)])
    n2 = flush(glb, pb, "FF_CREST", pm); glb.j["scenes"][0]["nodes"] = [n1, n2]; glb.write(ST / "FF__ff_sign_v2.glb"); return (ST / "FF__ff_sign_v2.glb").name
def build_blade():
    glb = GLB(); plain = glb.material("ff_blade", None, None, True); glb.j["materials"][plain]["extras"] = {"unlit": True}
    buf = MeshBuf(); xa, xb = -245.74, -245.66; z0, z1 = 733.45, 734.95; y0, y1 = 5.35, 6.3
    box(buf, (xa, y0, z0), (xb, y1, z1), CREAM_LIN)                                                       # panel
    for (zz0, zz1) in ((z0 - 0.04, z0), (z1, z1 + 0.04)): box(buf, (xa - 0.01, y0 - 0.04, zz0), (xb + 0.01, y1 + 0.04, zz1), GOLD_LIN)   # gold edge frame
    box(buf, (xa - 0.01, y1, z0 - 0.04), (xb + 0.01, y1 + 0.04, z1 + 0.04), GOLD_LIN); box(buf, (xa - 0.01, y0 - 0.04, z0 - 0.04), (xb + 0.01, y0, z1 + 0.04), GOLD_LIN)
    box(buf, (xa + 0.01, y1 + 0.04, z1 - 0.02), (xb - 0.01, y1 + 0.1, 735.3), NAVY_LIN); box(buf, (xa + 0.01, y0 - 0.1, z1 - 0.02), (xb - 0.01, y0 - 0.04, 735.3), NAVY_LIN)   # brackets to the wall
    sm = mask_from(script_mask, 150); px = 1.1 / 150; sh = sm.shape[0] * px; yt = y1 - 0.06 - (0.95 - 0.12 - sh) / 2
    extrude(buf, sm, px, O=(xa, yt, z0 + 0.2), U=(0, 0, 1), V=(0, -1, 0), N=(-1, 0, 0), depth=0.03, col=NAVY_LIN)       # west face (viewer looking +x: right = +z)
    extrude(buf, sm, px, O=(xb, yt, z1 - 0.2), U=(0, 0, -1), V=(0, -1, 0), N=(1, 0, 0), depth=0.03, col=NAVY_LIN)       # east face
    n = flush(glb, buf, "FF_BLADE", plain); glb.j["scenes"][0]["nodes"] = [n]; glb.write(ST / "FF__ff_blade.glb"); return (ST / "FF__ff_blade.glb").name

# ---------------------------------------------------------------- facade / interior GLB variants with the navy textures
def png(path): return open(path, "rb").read()
def facade(kind, board_png):
    j, b = read_glb(ST / "F48__f48_i01front.glb")
    for n in ("f48_i01awn", "f48_i01win", "f48_i01door"): swap_image(j, b, n, png(FF / f"{n}_ff.png"))
    swap_image(j, b, "f48_i01sign", png(board_png)); dropped = drop_prims(j, lambda m: (m.get("name") or "").startswith("sf_hf_grad"))
    out = ST / f"F48__f48_i01front_ff_{kind}.glb"; write_glb(out, j, b); return out.name, dropped
def interior():
    outs = {}
    for src, imgs in [("F48I01__f48i01r.glb", ["f48i01_counter", "f48i01_wall", "f48i01_countertrm", "f48i01_doors", "f48i01_win", "f48i01_sign", "f48i01_floor2"]), ("F48I01__f48i01_chair.glb", ["f48i01_chair"]),
                      ("F48I01__f48i01_tablea.glb", ["f48i01_table"]), ("F48I01__f48i01_tableb.glb", ["f48i01_table"]), ("F48I01__f48i01_lamp.glb", ["f48i01_win"])]:
        j, b = read_glb(ST / src); n = 0
        for im in imgs:
            p = FF / f"{im}_ff.png"
            if p.exists(): n += swap_image(j, b, im, png(p))
        out = ST / src.replace(".glb", "_ff.glb"); write_glb(out, j, b); outs["/public/models/xbox/static/" + src] = "/public/models/xbox/static/" + out.name
    return outs
if __name__ == "__main__":
    for k in ("v1", "v2", "v3"): board(k)
    relief = build_relief(); blade = build_blade(); inner = interior()
    for k in ("v1", "v2", "v3"):
        name, dropped = facade(k, FF / f"billboard_{k}.png")
        remap = dict(inner); remap["/public/models/xbox/static/F48__f48_i01front.glb"] = "/public/models/xbox/static/" + name
        add = []
        if k == "v2": add.append({"actor": "FF_SIGN", "class": "entity", "cell": "F48", "mesh": "FF.FF_SIGN", "url": "/public/models/xbox/static/" + relief, "tag": "FF_SIGN", "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "scale": [1, 1, 1]})
        if k == "v3": add.append({"actor": "FF_BLADE", "class": "entity", "cell": "F48", "mesh": "FF.FF_BLADE", "url": "/public/models/xbox/static/" + blade, "tag": "FF_BLADE", "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "scale": [1, 1, 1]})
        json.dump({"name": f"F&F Pizzeria {k}", "remap": remap, "add": add}, open(SK / f"skin_{k}.json", "w"), indent=1); print(f"skin_{k}: facade {name} (dropped {dropped} neon prims), extra {[a['mesh'] for a in add]}")
    import shutil; shutil.copy(SK / "skin_v1.json", SK / "default.json"); print("default skin = v1 (painted board; user's pick)")
    print("sign models:", relief, blade)
