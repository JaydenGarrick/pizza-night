#!/usr/bin/env python3
"""Export every SkeletalMesh in source/pc/Animations/*.ukx to public/models/characters/*.glb"""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet
root = Path("source/pc"); out = Path("public/models/characters"); out.mkdir(parents=True, exist_ok=True)
pset = PackageSet([root])
py = sys.executable
for ukx in sorted((root / "Animations").glob("*.ukx")):
    pkg = pset.open(ukx)
    meshes = pkg.exports_of_class("SkeletalMesh")
    for m in meshes:
        dst = out / f"{m.name.lower()}.glb"
        r = subprocess.run([py, "-I", "tools/export_character.py", str(ukx), "--mesh", m.name, "--out", str(dst), "--textures-dir", "intermediate/textures"], capture_output=True, text=True)
        last = [l for l in r.stdout.splitlines() if l.startswith(("wrote", "  quaternion", "  material", "  exported"))]
        status = "OK " if r.returncode == 0 else "ERR"
        print(f"{status} {ukx.name:34} {m.name:28} " + (" | ".join(l.strip() for l in last if l.startswith(("wrote","  exported"))) if r.returncode == 0 else (r.stderr.strip().splitlines() or ['?'])[-1][:160]))
        for l in last:
            if l.startswith("  quaternion") and "-> all" not in l: print("      NOTE", l.strip())
            if l.startswith("  material") and "no texture" in l: print("      NOTE", l.strip())
