#!/usr/bin/env python3
"""Treyarch amalgapak (Spider-Man 2 Xbox) directory reader.
usage: amalgapak.py PAK --list | --extract NAME OUTFILE | --extract-all OUTDIR"""
import struct, sys
from pathlib import Path

class Amalgapak:
    def __init__(self, path):
        self.path = Path(path); self.f = open(path, "rb")
        hdr = struct.unpack("<12I", self.f.read(48))
        self.version, self.v1, self.v2, self.v3, self.data_start, self.table_start, self.t2, self.t3 = hdr[:8]
        self.data_size = hdr[9]
        self.entries = []
        self.f.seek(self.table_start)
        n = (self.t2 - self.table_start) // 56
        for i in range(n):
            e = self.f.read(56)
            name = e[:31].split(b"\0")[0].decode("latin-1"); flag = e[31]
            off, size, a, b, idx, c = struct.unpack_from("<6I", e, 32)
            self.entries.append({"name": name, "flag": flag, "offset": off, "size": size, "idx": idx, "a": a, "b": b, "c": c})
        self.by_name = {e["name"].lower(): e for e in self.entries}

    def read(self, name):
        e = self.by_name[name.lower()]; self.f.seek(self.data_start + e["offset"]); return self.f.read(e["size"])

if __name__ == "__main__":
    pak = Amalgapak(sys.argv[1])
    if "--list" in sys.argv:
        print(f"version {pak.version} ({pak.v1}.{pak.v2}.{pak.v3}), {len(pak.entries)} packfiles, data @0x{pak.data_start:x} size {pak.data_size}")
        for e in pak.entries: print(f"{e['idx']:4} {e['size']:10} {e['name']}")
    elif "--extract" in sys.argv:
        i = sys.argv.index("--extract"); Path(sys.argv[i + 2]).write_bytes(pak.read(sys.argv[i + 1])); print("ok")
    elif "--extract-all" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--extract-all") + 1]); out.mkdir(parents=True, exist_ok=True)
        for e in pak.entries: (out / f"{e['name']}.pack").write_bytes(pak.read(e["name"]))
        print(f"extracted {len(pak.entries)} packfiles to {out}")
