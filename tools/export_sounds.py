#!/usr/bin/env python3
"""Export USound objects from a .uax package. usage: export_sounds.py PKG.uax OUTDIR [--filter substr] [--list]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet
from ue2.props import object_props

args = sys.argv[1:]
flt = None; listing = "--list" in args
if "--filter" in args: i = args.index("--filter"); flt = args[i + 1].lower(); del args[i:i + 2]
args = [a for a in args if a != "--list"]
pkg_path = Path(args[0]).resolve(); outdir = Path(args[1]) if len(args) > 1 else Path("intermediate/audio")
pset = PackageSet([pkg_path.parents[1]]); pkg = pset.open(pkg_path)
outdir.mkdir(parents=True, exist_ok=True)
n = 0
for e in pkg.exports_of_class("Sound"):
    if flt and flt not in e.name.lower(): continue
    props, r, end = object_props(pkg, e)
    ftype = pkg.names[r.idx()]
    r.i32(); size = r.idx(); data = r.bytes(size)
    if listing:
        print(f"{e.name:40} {ftype:4} {size:8} bytes  group={pkg.full_name(e.pkg_ref)}"); continue
    ext = ".ogg" if ftype.upper() == "OGG" else ".wav" if ftype.upper() == "WAV" else "." + ftype.lower()
    (outdir / f"{e.name}{ext}").write_bytes(data); n += 1
print(f"{pkg.name}: {n} sounds written to {outdir}" if not listing else f"{pkg.name}: listed")
