#!/usr/bin/env python3
"""Treyarch XBPACK (packfile inside amalgapak) directory parser.
usage: xbpack.py FILE.pack [--dump NAME] [--hex N]"""
import struct, sys
from pathlib import Path

TYPE_NAMES = {}  # filled by caller / learned from the XBE table

class XBPack:
    def __init__(self, data):
        self.d = data
        h = struct.unpack_from("<16I", data, 0)
        self.version, self.v1, self.v2, self.v3 = h[:4]
        self.dir_start, self.dir_end = h[5], h[6]
        self.data_base = self.dir_end
        # 0x30: hash, 0, dir_size, 0xffff ; 0x40: 10 x (u32 zero, u32 count|flag<<24)
        self.type_counts = [struct.unpack_from("<I", data, 0x44 + 8 * i)[0] & 0xFFFFFF for i in range(10)]
        self.type_flags = [struct.unpack_from("<I", data, 0x44 + 8 * i)[0] >> 24 for i in range(10)]
        # entries are 40 bytes; find the first one by scanning back from dir_end
        self.entries = []
        self.group0 = [struct.unpack_from("<I", data, 0x250 + 4 * i)[0] for i in range(self.type_counts[0])]
        pos = (0x250 + 4 * self.type_counts[0] + 7) & ~7     # 40-byte entries start 8-aligned after the group-0 u32 list
        self.entries_start = pos
        for group, cnt in enumerate(self.type_counts):
            if group == 0: continue
            for _ in range(cnt):
                e = data[pos:pos + 40]
                name31 = e[:31]; tbyte = e[31]
                nm = name31.split(b"\0")[0]
                if group == 1:                      # group 1 = resources; all other groups are hash lookups
                    rec = {"group": group, "kind": "resource", "name": nm.decode(), "type": tbyte, "offset": struct.unpack_from("<I", e, 32)[0], "size": struct.unpack_from("<I", e, 36)[0]}
                else:
                    # lookup entry: u32 hash, name[28], u32 flags, u32 offset
                    hsh = struct.unpack_from("<I", e, 0)[0]; nm2 = e[4:32].split(b"\0")[0].decode("latin-1", "replace")
                    rec = {"group": group, "kind": "lookup", "name": nm2, "hash": hsh, "flags": struct.unpack_from("<I", e, 32)[0], "offset": struct.unpack_from("<I", e, 36)[0]}
                self.entries.append(rec); pos += 40

    def resource(self, name, type_byte=None):
        for e in self.entries:
            if e["kind"] == "resource" and e["name"].lower() == name.lower() and (type_byte is None or e["type"] == type_byte):
                return self.d[self.data_base + e["offset"]: self.data_base + e["offset"] + e["size"]]
        return None

if __name__ == "__main__":
    p = XBPack(Path(sys.argv[1]).read_bytes())
    print(f"{sys.argv[1]}: v{p.version} dir 0x{p.dir_start:x}-0x{p.dir_end:x}, type counts {p.type_counts} flags {p.type_flags}, entries from 0x{p.entries_start:x}")
    for e in p.entries:
        if e["kind"] == "resource": print(f"  [g{e['group']}] RES  type=0x{e['type']:02x} off={e['offset']:8} size={e['size']:8}  {e['name']}")
        else: print(f"  [g{e['group']}] LOOK hash={e['hash']:08x} flags={e['flags']:08x} off={e['offset']:8}  {e['name']}")
    if "--dump" in sys.argv:
        n = sys.argv[sys.argv.index("--dump") + 1]; nbytes = int(sys.argv[sys.argv.index("--hex") + 1]) if "--hex" in sys.argv else 256
        r = p.resource(n); print(f"\n{n}: {len(r)} bytes")
        for o in range(0, min(len(r), nbytes), 16): print(f"  {o:05x}: {r[o:o+16].hex()}  {''.join(chr(c) if 32<=c<127 else '.' for c in r[o:o+16])}")
