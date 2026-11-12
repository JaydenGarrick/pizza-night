#!/usr/bin/env python3
"""F&F pizza box (reference: white box, crest centred on the lid, 'FRANKS.PIZZA' on the long sides, 'F&F PIZZERIA' on the front/back).
The game's atlas gives all four edges ONE shared 4%-tall strip and the printed lid is the sagging -z side (+z is the recessed bottom),
so both meshes are re-UV'd by projection in the box's own frame (every triangle gets its own vertices): lid exterior -> crest slot,
sides -> text slot per face, interior -> plain white, tuck tabs / flaps dropped, the open box's pizza keeps its original UVs; the closed box's crumpled
lid and recessed floor are replaced by clean quads so the crest reads crisply like the reference.
Because true 'up' is local -z, pizza.html's grips hold the box -z up.
Writes public/models/xbox/props/itm_pizzaboxflat_ff.glb, itm_pizzabox_ff.glb and intermediate/ff/itm_pizzabox_ff.png."""
import sys, io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, "tools")
from glbtools import read_glb
from ue2.gltf import GLB
FF = Path("intermediate/ff"); PR = Path("public/models/xbox/props")
NAVY = (28, 78, 142); WHITE = (246, 246, 243); FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"; S = 1024
SLOT = {"pizza": (0.0, 0.5, 0.0, 0.40), "A": (0.5, 1.0, 0.02, 0.18), "B": (0.5, 1.0, 0.22, 0.38), "lid": (0.0, 0.5, 0.42, 1.0), "white": (0.5, 1.0, 0.44, 1.0)}   # u0,u1,v0,v1
crest = Image.open(FF / "ff_crest.png").convert("RGBA"); orig = Image.open(FF / "itm_pizzabox.png").convert("RGBA")

def px(slot): u0, u1, v0, v1 = slot; return int(u0 * S), int(u1 * S), int(v0 * S), int(v1 * S)
def text_img(txt, w_m, h_m, size_frac=0.50, ppm=1000):
    """square-texel composition (ppm px per metre) of letter-spaced navy Futura, centred"""
    W, H = int(w_m * ppm), int(h_m * ppm); im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FUTURA, int(H * size_frac), index=0); sp = int(H * size_frac * 0.07)
    tw = sum(f.getlength(ch) for ch in txt) + sp * (len(txt) - 1); bb = f.getbbox("H"); x = (W - tw) / 2; y = (H - (bb[3] - bb[1])) / 2 - bb[1]
    for ch in txt: d.text((x, y), ch, font=f, fill=NAVY); x += f.getlength(ch) + sp
    return im
def build_texture():
    tex = Image.new("RGBA", (S, S), WHITE + (255,))
    x0, x1, y0, y1 = px(SLOT["pizza"]); tex.paste(orig.crop((0, 0, 64, 51)).resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))   # open box's pizza (top-left of the game atlas)
    for key, txt, w_m in (("A", "FRANKS.PIZZA", 0.90), ("B", "F&F PIZZERIA", 0.80)):
        x0, x1, y0, y1 = px(SLOT[key]); tex.alpha_composite(text_img(txt, w_m, 0.21).resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    x0, x1, y0, y1 = px(SLOT["lid"]); W, H = 900, 800; lid = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # lid slot = 0.9 m (u, along -y') x 0.8 m (v, along +x')
    ch = int(H * 0.62); c = crest.resize((int(crest.width * ch / crest.height), ch), Image.LANCZOS); lid.alpha_composite(c, ((W - c.width) // 2, (H - ch) // 2))
    tex.alpha_composite(lid.resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    tex.save(FF / "itm_pizzabox_ff.png"); return tex

def acc(j, b, i):
    a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]; ct = {5126: "f4", 5121: "u1", 5123: "u2", 5125: "u4"}[a["componentType"]]; k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    return np.frombuffer(bytes(b), dtype=ct, count=a["count"] * k, offset=bv.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(a["count"], k).astype(np.float64)
def load(src):
    j, b = read_glb(PR / src); pr = j["meshes"][0]["primitives"][0]; at = pr["attributes"]
    return j, acc(j, b, at["POSITION"]), acc(j, b, at["TEXCOORD_0"]), acc(j, b, pr["indices"]).astype(int).reshape(-1, 3), (acc(j, b, at["NORMAL"]) if "NORMAL" in at else None)

# ---- box frame + extents from the flat box (the mesh is tilted ~8 deg inside its own node): z' = thinnest PCA axis, x' = original x projected
_, P0, UV0, I0, _ = load("itm_pizzaboxflat.glb"); C0 = P0.mean(0); _, V = np.linalg.eigh(np.cov((P0 - C0).T))
zc = V[:, 0] * np.sign(V[2, 0]); xc = np.array([1.0, 0, 0]) - zc * zc[0]; xc /= np.linalg.norm(xc); yc = np.cross(zc, xc); R = np.stack([xc, yc, zc], 1)
def tri_list(Pb, UV, I):
    out = []
    for t in I:
        a, b_, c = Pb[t]; n = np.cross(b_ - a, c - a); L = np.linalg.norm(n)
        if L > 1e-12: out.append(dict(t=t, n=n / L, A=L / 2, c=Pb[t].mean(0), uvc=UV[t].mean(0)))
    return out
Pb0 = (P0 - C0) @ R; sides0 = [tr for tr in tri_list(Pb0, UV0, I0) if abs(tr["n"][2]) <= 0.5 and tr["A"] > 0.012]
sv = np.concatenate([Pb0[tr["t"]] for tr in sides0]); ZS0, ZS1 = sv[:, 2].min(), sv[:, 2].max()       # true top edge = ZS0 (local -z is up), bottom = ZS1
xs = [tr["c"][0] for tr in sides0 if abs(tr["n"][0]) > abs(tr["n"][1])]; ys = [tr["c"][1] for tr in sides0 if abs(tr["n"][1]) >= abs(tr["n"][0])]
X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys); CEN = np.array([(X0 + X1) / 2, (Y0 + Y1) / 2, 0])
ZTOP_SPLIT = ZS0 + 0.65 * (ZS1 - ZS0); ZLID = ZS0 - 0.02                                                 # sagging lid above the split, recessed floor below; open box's lid above the rim
print(f"box frame z'={zc.round(3)} x'[{X0:.2f},{X1:.2f}] y'[{Y0:.2f},{Y1:.2f}] z'[{ZS0:.2f},{ZS1:.2f}]")
lerp = lambda s, a, b, f: (s[a] + (s[b] - s[a]) * np.clip(f, 0, 1))
def top_uv(x, y): return np.array([lerp(SLOT["lid"], 0, 1, (Y1 - y) / (Y1 - Y0)), lerp(SLOT["lid"], 2, 3, (x - X0) / (X1 - X0))])   # crest right = -y', crest down = +x' (front = opening edge)
def white_uv(x, y): return np.array([lerp(SLOT["white"], 0, 1, (x - X0) / (X1 - X0)), lerp(SLOT["white"], 2, 3, (y - Y0) / (Y1 - Y0))])

def rebuild(src):
    open_box = src == "itm_pizzabox.glb"
    j, P, UV, I, N = load(src); Pb = (P - C0) @ R; tris = tri_list(Pb, UV, I); lid = {}
    if open_box:
        lt = [tr for tr in tris if tr["c"][2] < ZLID]; lv = np.unique(np.concatenate([tr["t"] for tr in lt])); LP = Pb[lv]; lc = LP.mean(0)
        _, LV = np.linalg.eigh(np.cov((LP - lc).T)); nL = LV[:, 0]; bc = Pb[np.unique(np.concatenate([tr["t"] for tr in tris if tr["c"][2] >= ZLID]))].mean(0)
        if np.dot(nL, lc - bc) < 0: nL = -nL                                               # away from the base = lid exterior side
        hinge = LP[LP[:, 2] > LP[:, 2].max() - 0.04].mean(0); along = (lc - hinge) - nL * np.dot(lc - hinge, nL); along /= np.linalg.norm(along)
        faces = sorted(np.dot(tr["c"] - lc, nL) for tr in lt if abs(np.dot(tr["n"], nL)) >= 0.5); gaps = np.diff(faces); gi = int(np.argmax(gaps))
        dext = (faces[gi] + faces[gi + 1]) / 2; print("  lid layer offsets", np.round(faces, 3), "split at", round(dext, 3))      # two coincident layers ~2 cm apart: outer one = exterior
        lid = dict(nL=nL, lc=lc, hinge=hinge, along=along, dext=dext); print(f"  lid normal {nL.round(2)} hinge x' {hinge[0]:.2f} (x'min {X0:.2f}) along {along.round(2)}")
    newP, newUV, newN, newI, counts = [], [], [], [], {}
    for tr in tris:
        t, n, c = tr["t"], tr["n"], tr["c"]
        if open_box and c[2] < ZLID: kind = "lid" if abs(np.dot(n, lid["nL"])) >= 0.5 and np.dot(c - lid["lc"], lid["nL"]) > lid["dext"] else "white"
        elif open_box and tr["uvc"][0] < 0.5 and tr["uvc"][1] < 0.40: kind = "keep"                            # the pizza (incl. its crust facets)
        elif not (X0 - 0.005 <= c[0] <= X1 + 0.005 and Y0 - 0.005 <= c[1] <= Y1 + 0.005): kind = "drop"       # the lid's tuck tabs / side flaps past the rim
        elif abs(n[2]) <= 0.5 and (c[2] < ZS0 - 0.015 or Pb[t][:, 2].max() > ZS1 + 0.01): kind = "drop"      # upright / hanging tabs
        elif abs(n[2]) > 0.5: kind = "white" if open_box else "drop"                                          # flat box: crumpled lid + recessed floor -> clean quads below
        else: kind = "side"
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "drop": continue
        if kind == "lid": print(f"    lid exterior tri A={tr['A']:.3f} orig uv={tr['uvc'].round(2)}")
        for k in range(3):
            p = Pb[t[k]]
            if kind == "keep": uv = UV[t[k]]
            elif kind == "lid": uv = top_uv(X0 + np.dot(p - lid["hinge"], lid["along"]), p[1])            # unfold the raised lid flat (hinge at x'min)
            elif kind == "white": uv = white_uv(p[0], p[1])
            else:
                ax = 0 if abs(n[0]) > abs(n[1]) else 1; sgn = 1 if c[ax] > CEN[ax] else -1
                if ax == 0: f = (p[1] - Y0) / (Y1 - Y0); f = f if sgn < 0 else 1 - f; slot = SLOT["B"]    # +x' face reads toward -y', -x' toward +y'
                else: f = (p[0] - X0) / (X1 - X0); f = f if sgn > 0 else 1 - f; slot = SLOT["A"]      # +y' face reads toward +x', -y' toward -x'
                uv = np.array([lerp(slot, 0, 1, f), lerp(slot, 2, 3, (p[2] - ZS0) / (ZS1 - ZS0))])
            newP.append(C0 + p @ R.T); newUV.append(uv); newI.append(len(newP) - 1)
            if N is not None: newN.append(N[t[k]])
    if not open_box:   # clean closed box: lid quad on the rim plane (crest) + flat bottom quad (white)
        for zq, uvf, nz in ((ZS0, top_uv, -1.0), (ZS1, white_uv, 1.0)):
            for (x, y) in ((X0, Y0), (X1, Y0), (X1, Y1), (X0, Y0), (X1, Y1), (X0, Y1)):
                q = np.array([x, y, zq]); newP.append(C0 + q @ R.T); newUV.append(uvf(x, y)); newI.append(len(newP) - 1)
                if N is not None: newN.append(R @ np.array([0, 0, nz]))
        counts["quads"] = 4
    if open_box:   # inner wall layer (1 cm inside, plain white) so the open box's walls don't show the outside lettering mirrored from within
        for tr in tris:
            if tr["c"][2] >= ZLID and abs(tr["n"][2]) <= 0.5 and tr["A"] > 0.012 and (X0 - 0.03 <= tr["c"][0] <= X1 + 0.03 and Y0 - 0.03 <= tr["c"][1] <= Y1 + 0.03):
                ax = 0 if abs(tr["n"][0]) > abs(tr["n"][1]) else 1; inward = np.zeros(3); inward[ax] = -1 if tr["c"][ax] > CEN[ax] else 1
                for k in (2, 1, 0):
                    q = Pb[tr["t"][k]] + inward * 0.01; newP.append(C0 + q @ R.T); newUV.append(white_uv(q[0], q[1])); newI.append(len(newP) - 1)
                    if N is not None: newN.append(-N[tr["t"][k]])
                counts["inner"] = counts.get("inner", 0) + 1
    print(f"  {src}: {counts}")
    return j, np.array(newP, np.float32), np.array(newUV, np.float32), (np.array(newN, np.float32) if N is not None else None), np.array(newI, np.uint32)

tex = build_texture(); buf = io.BytesIO(); tex.save(buf, format="PNG"); png = buf.getvalue()
for src in ("itm_pizzaboxflat.glb", "itm_pizzabox.glb"):
    j, P, UV, N, I = rebuild(src)
    glb = GLB(); ti = glb.image_png(Image.open(io.BytesIO(png)), "itm_pizzabox_ff"); mat = glb.material("pizzabox_ff", ti, None, True)
    attrs = {"POSITION": glb.accessor(P, 34962, minmax=True), "TEXCOORD_0": glb.accessor(UV, 34962)}
    if N is not None: attrs["NORMAL"] = glb.accessor(N, 34962)
    glb.j["meshes"].append({"name": j["meshes"][0].get("name", "box"), "primitives": [{"attributes": attrs, "indices": glb.accessor(I, 34963), "material": mat, "mode": 4}]})
    for n in j["nodes"]: glb.j["nodes"].append({k: v for k, v in n.items() if k in ("name", "translation", "rotation", "scale", "matrix", "children")})
    mn = next(i for i, n in enumerate(j["nodes"]) if "mesh" in n); glb.j["nodes"][mn]["mesh"] = 0; glb.j["scenes"][0]["nodes"] = list(j["scenes"][j.get("scene", 0)]["nodes"])
    out = PR / src.replace(".glb", "_ff.glb"); glb.write(out); print("wrote", out.name, len(P), "verts", len(I) // 3, "tris")
