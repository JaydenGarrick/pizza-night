"""Treyarch 'lego' generic-building section of an ENS (entity set).
Layout (found after the ordinary entity records):
  u32 9, u32 n_lists, 16 B zero, then n_lists texture master lists:
      name[32] (S_BLG_BLGMASTER sides / S_BLG_TRM trims / S_BLG_PEDMASTER pedestals), u32[4] zero, u32 0x100, u32 count, u32 0,
      count x {char tex[32], u16 ?, u16 id}
  header: u32 0x0b, u32 rec_bytes, u16 n_types, u16 0xc0de, u32 n_recs, u32 tail_size, u32 hash
  n_types x {char name[28] (mesh instance e.g. 'blg30x1000', 'sb_stor_10d000'), u32 hash}
  n_recs x 52 B placement record:
      f32 x,y,z | u16 sub, u16 type_idx | u32 1/0 | u32 0xffffff | i16 w, i16 d (lego) or i16 x_int, i16 y_int (prop)
      | i16 h (lego) or i16 z_int (prop) | u8 a, u8 b | u8[4] | u8[4] | u8 tex_id0, tex_id1, u8 ?, u8 ped_id0 | u8 ped_id1, 0xff, flags, 0 | u16 9 (class), u16 yaw_deg
  Segment = ring (w x d footprint) from y to y+h, 2-unit trim band on top (next setback segment starts at y+h+2);
  base segments sit on a pedestal 0..y (pedbas 0-5, pedtop 5-y). Lego meshes (CITY blgNNx1/aptNNx1) are the 5-tall unit rings.
  then u16 offsets, then groups {u8 0x0a, u8 n, u16 idx[n]} (4-aligned), then pedestal placements (variable, not decoded)."""
import struct, re

def _find_header(ens):
    """interiors have no master texture lists: locate the 0x0b header by its 0xc0de magic + consistent record count"""
    i = ens.find(b"\x0b\x00\x00\x00", 0x20)
    while i != -1:
        o = (i + 4 + 7) & ~7
        if o + 20 <= len(ens):
            rec_bytes, n_types, magic, n_recs = struct.unpack_from("<IHHI", ens, o)
            if magic == 0xc0de and n_recs * 52 == rec_bytes and 0 < n_types < 512: return i
        i = ens.find(b"\x0b\x00\x00\x00", i + 4)
    return -1

def parse_lego(ens):
    p = ens.find(b"S_BLG_BLGMASTER")
    if p < 0:
        p = _find_header(ens)
        if p < 0: return None
    lists = {}; o = p
    while True:   # master lists until the 0x0b header tag
        name = ens[o:o+32].split(b"\0")[0]
        if not name or not re.fullmatch(rb"[A-Z][A-Z_0-9]+", name): break
        cnt = struct.unpack_from("<I", ens, o + 0x24)[0]; o += 0x2c; ents = []
        for _ in range(cnt):
            tex = ens[o:o+32].split(b"\0")[0].decode("latin-1"); k, tid = struct.unpack_from("<HH", ens, o + 32); ents.append((tex, tid, k)); o += 36
        lists[name.decode()] = ents
        if struct.unpack_from("<I", ens, o)[0] == 0: o += 4      # u32 terminator between lists
    if struct.unpack_from("<I", ens, o)[0] != 0x0b: return None
    o = (o + 4 + 7) & ~7                                           # header body is 8-aligned (cdcdcdcd pad)
    rec_bytes, n_types, magic, n_recs, tail_size, hsh = struct.unpack_from("<IHHIII", ens, o); o += 20
    if magic != 0xc0de or n_recs * 52 != rec_bytes: return None
    types = []
    for _ in range(n_types):
        types.append(ens[o:o+28].split(b"\0")[0].decode("latin-1")); o += 32
    recs = []
    for i in range(n_recs):
        b = ens[o:o+52]; x, y, z = struct.unpack_from("<3f", b, 0); sub, ti = struct.unpack_from("<HH", b, 12)
        w, d, h = struct.unpack_from("<3h", b, 24); a, bb = b[30], b[31]
        tex = (b[40], b[41]); ped = (b[43], b[44]); flags = b[46]; cls, yaw = struct.unpack_from("<HH", b, 48)
        name = types[ti] if ti < len(types) else "?"; base = re.sub(r"\d{3}$", "", name)
        lego = re.fullmatch(r"(blg|apt|twa|twb)(5|15|20|25|30|40|50|60)x1[ab]?", base) is not None   # unit rings only; e.g. blg30x10 is a plain mesh
        recs.append({"i": i, "type": base, "inst": name, "pos": (x, y, z), "yaw": yaw, "lego": lego,
                     "w": w if lego else None, "d": d if lego else None, "h": h if lego else None,
                     "a": a, "b": bb, "tex_ids": tex, "ped_ids": ped, "flags": flags, "sub": sub})
        o += 52
    by_id = {}
    for lname, ents in lists.items():
        for tex, tid, k in ents: by_id.setdefault(tid, tex)
    return {"lists": lists, "tex_by_id": by_id, "types": types, "records": recs, "header": {"rec_bytes": rec_bytes, "n_recs": n_recs, "tail_size": tail_size}}
