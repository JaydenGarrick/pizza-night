#!/usr/bin/env python3
"""Export the PC game's UE2 fonts (source/pc/Textures/WebheadFonts.utx, FizzFonts.utx: TrueType-rendered, antialiased, with lower case) into the
same bitmap-font format as the Xbox HUD fonts (public/ui/fonts/<name>.json + public/ui/<name>.png) so public/js/bitmapfont.js can draw them.
UFont native data (package version 126): idx count, then per char StartU/StartV/USize/VSize (int32) + TextureIndex (u8), idx count + object refs
for the pages, then Kerning (int32: extra advance per glyph), IsRemapped, CharRemap.  Pages are DXT5 (white glyphs + a baked drop shadow in the
alpha); multi-page fonts are stacked vertically into one atlas.  Each font's cell is cropped to the rows its glyphs actually use so the line
height is the face's own leading rather than the page's padded cell.   usage: export_fonts.py [FontNeuzeit14 FontNeuzeit29 ...]"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet
from ue2.props import object_props
from ue2.texture import load_texture
from PIL import Image
ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ["FontNeuzeit12", "FontNeuzeit14", "FontNeuzeit17", "FontNeuzeit21", "FontNeuzeit24", "FontNeuzeit29"]   # the page picks the size nearest 14 px (12 on phones) x devicePixelRatio
def parse_font(pkg, e):
    props, r, end = object_props(pkg, e)
    n = r.idx(); chars = []
    for _ in range(n):
        su, sv, us, vs = r.i32(), r.i32(), r.i32(), r.i32(); ti = r.u8(); chars.append((su, sv, us, vs, ti))
    nt = r.idx(); texs = [pkg.ref(r.idx()) for _ in range(nt)]
    kerning = r.i32() if end - r.tell() >= 4 else 0
    return chars, texs, kerning
def export(ps, name):
    pkg = None
    for pn in ("WebheadFonts", "FizzFonts", "GUIFONTS"):
        p = ps.get(pn); e = p.export_by_name(name, "Font") if p else None
        if e: pkg = p; break
    if not pkg: print("no such font", name); return
    chars, texs, kerning = parse_font(pkg, e)
    pages = []
    for t in texs:
        tp, te = t.resolve(); img, _ = load_texture(tp, te); pages.append(img)
    W = max(p.width for p in pages); H = sum(p.height for p in pages)
    atlas = Image.new("RGBA", (W, H)); offs = []; y = 0
    for p in pages: atlas.paste(p, (0, y)); offs.append(y); y += p.height
    A = atlas.getchannel("A")
    # crop the cell: the rows the ASCII glyphs really use (the page cell is padded above and below the face)
    top, bot = None, None
    for code, (su, sv, us, vs, ti) in enumerate(chars):
        if us <= 0 or vs <= 0 or code == 32 or code > 126: continue   # ASCII only: the accented capitals would add a row of leading nothing here uses
        box = A.crop((su, sv + offs[ti], su + us, sv + offs[ti] + vs)).getbbox()
        if not box: continue
        top = box[1] if top is None else min(top, box[1]); bot = box[3] if bot is None else max(bot, box[3])
    top = top or 0; cell = (bot or max(c[3] for c in chars)) - top
    glyphs = []
    for code, (su, sv, us, vs, ti) in enumerate(chars):
        if us <= 0 or vs <= 0 or code < 32: continue
        gh = max(0, min(vs, bot) - top)
        glyphs.append({"char": chr(code), "code": code, "x": su, "y": sv + offs[ti] + top, "advance": us + kerning, "gx": 0, "gy": 0, "gw": us, "gh": gh})
    (ROOT / "public/ui" / f"{name}.png").parent.mkdir(parents=True, exist_ok=True)
    atlas.save(ROOT / "public/ui" / f"{name}.png")
    meta = {"pack": pkg.name, "atlas": f"/public/ui/{name}.png", "cellheight": cell, "ascent": cell, "kerning": kerning, "lower": True, "glyphs": glyphs}
    (ROOT / "public/ui/fonts" / f"{name}.json").write_text(json.dumps(meta, separators=(",", ":")))
    print(f"{name}: {len(glyphs)} glyphs, {len(pages)} page(s) {W}x{H}, cell {cell} (page cell {max(c[3] for c in chars)}, cropped {top} above), kerning {kerning}")
if __name__ == "__main__":
    ps = PackageSet([ROOT / "source/pc"])
    for n in (sys.argv[1:] or DEFAULT): export(ps, n)
