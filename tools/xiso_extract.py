#!/usr/bin/env python3
"""Extract an original-Xbox XISO (plain or redump/XGD image) filesystem. usage: xiso_extract.py image.iso outdir [--list]"""
import struct, sys
from pathlib import Path
SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
BASES = [0, 0x18300000, 0xFD90000, 0x2080000]      # plain, XGD1, XGD2, XGD3 game-partition offsets

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; listing = "--list" in sys.argv
    img = Path(args[0]); out = Path(args[1]) if len(args) > 1 else Path("source/xbox")
    with img.open("rb") as f:
        base = None
        for b in BASES:
            f.seek(b + 32 * SECTOR); hdr = f.read(SECTOR)
            if hdr[:20] == MAGIC: base = b; break
        if base is None: raise SystemExit("no XISO header found (not an Xbox image?)")
        root_sector, root_size = struct.unpack_from("<II", hdr, 20)
        print(f"XISO base offset 0x{base:X}, root dir sector {root_sector} size {root_size}")
        files = []
        def read_dir(sector, size, path):
            f.seek(base + sector * SECTOR); data = f.read(size)
            def walk(off):
                if off + 14 > len(data): return
                left, right, start, fsize, attr, nlen = struct.unpack_from("<HHIIBB", data, off)
                if left == 0xFFFF: return
                name = data[off + 14: off + 14 + nlen].decode("latin-1")
                if left: walk(left * 4)
                if attr & 0x10:
                    if fsize: read_dir(start, fsize, path + (name,))
                else:
                    files.append((path + (name,), start, fsize))
                if right: walk(right * 4)
            walk(0)
        read_dir(root_sector, root_size, ())
        print(f"{len(files)} files")
        if listing:
            for p, s, n in files: print(f"{n:12} {'/'.join(p)}")
            return
        total = 0
        for p, s, n in files:
            dst = out.joinpath(*p); dst.parent.mkdir(parents=True, exist_ok=True)
            f.seek(base + s * SECTOR)
            with dst.open("wb") as o:
                left = n
                while left > 0:
                    chunk = f.read(min(left, 1 << 22)); o.write(chunk); left -= len(chunk)
            total += n
        print(f"extracted {total/1e6:.1f} MB to {out}")
main()
