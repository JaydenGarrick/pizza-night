#!/usr/bin/env python3
"""Dump tagged properties of UE2 objects.
usage: dump_object.py PKG [--class C1,C2] [--name N] [--limit N] [--raw-after N]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet
from ue2.props import object_props, fmt_value

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args:
        i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
classes = opt("--class"); name = opt("--name"); limit = int(opt("--limit", "50")); raw_after = int(opt("--raw-after", "0"))
pkg_path = args[0]
root = Path(pkg_path).resolve().parents[1]
pset = PackageSet([root])
pkg = pset.open(pkg_path)
exps = pkg.exports
if classes: exps = [e for e in exps if e.cls.lower() in {c.lower() for c in classes.split(",")}]
if name: exps = [e for e in exps if e.name.lower() == name.lower()]
print(f"{pkg.name}: {len(exps)} matching exports")
for e in exps[:limit]:
    try:
        props, r, end = object_props(pkg, e)
        print(f"\n[{e.index}] {e.cls} {pkg.full_name(e.index)}  size={e.size} flags={e.flags:08x} native_bytes={end - r.tell()}")
        for k, v in props.items():
            print(f"    {k} = {fmt_value(v)}")
        if raw_after:
            print("    native:", r.d[r.tell():r.tell() + raw_after].hex())
    except Exception as ex:
        print(f"\n[{e.index}] {e.cls} {e.name}: ERROR {type(ex).__name__}: {ex}")
