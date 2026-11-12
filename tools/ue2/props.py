"""UE2 tagged-property parser."""
from .package import ObjRef, RF_HAS_STACK

T_BYTE, T_INT, T_BOOL, T_FLOAT, T_OBJECT, T_NAME, T_STRING, T_CLASS, T_ARRAY, T_STRUCT, T_VECTOR, T_ROTATOR, T_STR, T_MAP, T_FIXED = range(1, 16)
TYPE_NAMES = {1: "Byte", 2: "Int", 3: "Bool", 4: "Float", 5: "Object", 6: "Name", 7: "String", 8: "Class", 9: "Array",
              10: "Struct", 11: "Vector", 12: "Rotator", 13: "Str", 14: "Map", 15: "FixedArray"}


class RawArray:
    """Dynamic array whose element type isn't encoded in the file; decode on demand."""
    __slots__ = ("count", "data", "pkg", "prop")
    def __init__(self, count, data, pkg, prop):
        self.count, self.data, self.pkg, self.prop = count, data, pkg, prop
    def __len__(self): return self.count
    def __repr__(self): return f"Array[{self.count}]({len(self.data)}B)"
    def _reader(self):
        from .reader import BinReader
        return BinReader(self.data)
    def objs(self):
        r = self._reader(); return [ObjRef(r.idx(), self.pkg) for _ in range(self.count)]
    def names(self):
        r = self._reader(); return [self.pkg.names[r.idx()] for _ in range(self.count)]
    def ints(self):
        r = self._reader(); return [r.i32() for _ in range(self.count)]
    def floats(self):
        r = self._reader(); return [r.f32() for _ in range(self.count)]
    def bytes_(self):
        return list(self.data[:self.count])
    def structs(self):
        """Elements are script structs serialized as nested tagged properties."""
        r = self._reader(); return [read_props(r, self.pkg) for _ in range(self.count)]
    def vectors(self):
        r = self._reader(); return [r.vec() for _ in range(self.count)]


def skip_state_frame(r, export):
    if export.flags & RF_HAS_STACK:
        node = r.idx(); r.idx(); r.i64(); r.i32()
        if node:
            r.idx()


def _read_struct(r, pkg, sname, size):
    s = sname.lower()
    if s == "vector": return r.vec()
    if s == "rotator": return r.rot()
    if s == "color": return r.color()
    if s == "quat": return r.quat()
    if s == "plane": return (r.f32(), r.f32(), r.f32(), r.f32())
    if s == "range": return (r.f32(), r.f32())
    if s == "rangevector": return (r.vec(), r.vec())
    if s == "scale": return {"_struct": "Scale", "Scale": r.vec(), "SheerRate": r.f32(), "SheerAxis": r.u8()}
    if s == "coords": return {"_struct": "Coords", "Origin": r.vec(), "XAxis": r.vec(), "YAxis": r.vec(), "ZAxis": r.vec()}
    if s == "box": return {"_struct": "Box", "Min": r.vec(), "Max": r.vec(), "IsValid": r.u8()}
    if s == "sphere": return {"_struct": "Sphere", "Center": r.vec(), "R": r.f32()}
    if s == "pointregion": return {"_struct": "PointRegion", "Zone": ObjRef(r.idx(), pkg), "iLeaf": r.i32(), "ZoneNumber": r.u8()}
    if s == "guid": return r.bytes(16).hex()
    if s == "matrix": return {"_struct": "Matrix", "rows": [r.quat() for _ in range(4)]}
    # script struct: nested tagged properties
    d = read_props(r, pkg)
    d["_struct"] = sname
    return d


def read_props(r, pkg):
    """Read a tagged property list up to the 'None' terminator. Returns dict."""
    out = {}
    while True:
        name = pkg.names[r.idx()]
        if name == "None":
            return out
        info = r.u8()
        is_array = bool(info & 0x80)
        ptype = info & 0x0F
        sname = pkg.names[r.idx()] if ptype == T_STRUCT else None
        sz = (info >> 4) & 7
        size = (1, 2, 4, 12, 16)[sz] if sz < 5 else (r.u8() if sz == 5 else r.u16() if sz == 6 else r.i32())
        aidx = 0
        if ptype != T_BOOL and is_array:
            b = r.u8()
            if b < 128:
                aidx = b
            else:
                b2 = r.u8()
                if b & 0x40:
                    b3, b4 = r.u8(), r.u8()
                    aidx = ((b << 24) | (b2 << 16) | (b3 << 8) | b4) & 0x3FFFFF
                else:
                    aidx = ((b << 8) | b2) & 0x3FFF
        if ptype == T_BOOL:
            val = is_array
        else:
            start = r.tell(); stop = start + size
            if ptype == T_BYTE: val = r.u8()
            elif ptype == T_INT: val = r.i32()
            elif ptype == T_FLOAT: val = r.f32()
            elif ptype in (T_OBJECT, T_CLASS): val = ObjRef(r.idx(), pkg)
            elif ptype == T_NAME: val = pkg.names[r.idx()]
            elif ptype in (T_STR, T_STRING): val = r.fstr()
            elif ptype == T_VECTOR: val = r.vec()
            elif ptype == T_ROTATOR: val = r.rot()
            elif ptype == T_STRUCT: val = _read_struct(r, pkg, sname, size)
            elif ptype == T_ARRAY:
                cnt = r.idx()
                val = RawArray(cnt, r.d[r.tell():stop], pkg, name)
            else:
                val = ("?", TYPE_NAMES.get(ptype, ptype), r.d[start:stop])
            r.seek(stop)
        if aidx or name in out and isinstance(out[name], dict) and out[name].get("_fixed"):
            slot = out.setdefault(name, {"_fixed": True})
            if not isinstance(slot, dict) or not slot.get("_fixed"):
                slot = {"_fixed": True, 0: slot}; out[name] = slot
            slot[aidx] = val
        else:
            out[name] = val


def finalize(d):
    """Convert fixed-array dicts {_fixed:True, 0:..,1:..} to lists."""
    for k, v in list(d.items()):
        if isinstance(v, dict) and v.get("_fixed"):
            n = max(i for i in v if isinstance(i, int)) + 1
            d[k] = [v.get(i) for i in range(n)]
    return d


def object_props(pkg, export):
    """Read an export's tagged properties; returns (props, reader positioned after props, end_offset)."""
    r, end = pkg.reader(export)
    skip_state_frame(r, export)
    props = finalize(read_props(r, pkg))
    return props, r, end


def fmt_value(v, depth=0):
    if isinstance(v, ObjRef): return repr(v)
    if isinstance(v, RawArray): return repr(v)
    if isinstance(v, float): return f"{v:.4g}"
    if isinstance(v, tuple): return "(" + ", ".join(fmt_value(x) for x in v) + ")"
    if isinstance(v, list): return "[" + ", ".join(fmt_value(x) for x in v) + "]"
    if isinstance(v, dict):
        items = [f"{k}={fmt_value(x, depth + 1)}" for k, x in v.items() if k != "_struct"]
        return f"{v.get('_struct', '')}{{" + ", ".join(items) + "}"
    return repr(v)
