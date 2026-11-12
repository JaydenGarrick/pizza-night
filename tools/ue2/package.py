"""UE2 package tables + cross-package object resolution."""
from pathlib import Path
from .reader import BinReader

PKG_EXTS = (".u", ".utx", ".ukx", ".usx", ".uax", ".whr")
RF_HAS_STACK = 0x02000000


class Import:
    __slots__ = ("class_pkg", "class_name", "pkg_ref", "name", "index")
    def __init__(self, class_pkg, class_name, pkg_ref, name, index):
        self.class_pkg, self.class_name, self.pkg_ref, self.name, self.index = class_pkg, class_name, pkg_ref, name, index


class Export:
    __slots__ = ("class_ref", "super_ref", "pkg_ref", "name", "flags", "size", "offset", "index", "cls")
    def __init__(self, class_ref, super_ref, pkg_ref, name, flags, size, offset, index):
        self.class_ref, self.super_ref, self.pkg_ref, self.name = class_ref, super_ref, pkg_ref, name
        self.flags, self.size, self.offset, self.index = flags, size, offset, index
        self.cls = None


class ObjRef:
    """An object reference (compact index) bound to the package it was read from."""
    __slots__ = ("ref", "pkg")
    def __init__(self, ref, pkg):
        self.ref, self.pkg = ref, pkg
    def __bool__(self): return self.ref != 0
    @property
    def name(self): return self.pkg.obj_name(self.ref)
    @property
    def full(self): return self.pkg.full_name(self.ref)
    @property
    def cls(self): return self.pkg.obj_class(self.ref)
    def resolve(self): return self.pkg.resolve(self.ref)
    def __repr__(self): return f"{self.cls}'{self.full}'" if self.ref else "None"


class Package:
    def __init__(self, path, pset=None):
        self.path = Path(path)
        self.name = self.path.stem
        self.pset = pset
        self.data = self.path.read_bytes()
        r = BinReader(self.data)
        magic = r.u32()
        if magic != 0x9E2A83C1:
            raise ValueError(f"{path}: bad magic {magic:08x}")
        self.version = r.u16()
        self.licensee = r.u16()
        self.flags = r.u32()
        nc, no, ec, eo, ic, io = r.u32(), r.u32(), r.u32(), r.u32(), r.u32(), r.u32()
        r.seek(no)
        self.names = []
        for _ in range(nc):
            self.names.append(r.fstr()); r.u32()
        r.seek(io)
        self.imports = []
        for i in range(ic):
            cp = self.names[r.idx()]; cn = self.names[r.idx()]; pk = r.i32(); on = self.names[r.idx()]
            self.imports.append(Import(cp, cn, pk, on, -(i + 1)))
        r.seek(eo)
        self.exports = []
        for i in range(ec):
            ci = r.idx(); si = r.idx(); pk = r.i32(); on = self.names[r.idx()]; fl = r.u32(); sz = r.idx()
            off = r.idx() if sz > 0 else 0
            self.exports.append(Export(ci, si, pk, on, fl, sz, off, i + 1))
        for e in self.exports:
            e.cls = self.obj_name(e.class_ref) if e.class_ref else "Class"
        self._by_name = {}
        for e in self.exports:
            self._by_name.setdefault(e.name.lower(), []).append(e)

    # ---- naming helpers
    def obj_name(self, ref):
        if ref > 0: return self.exports[ref - 1].name
        if ref < 0: return self.imports[-ref - 1].name
        return "None"

    def obj_class(self, ref):
        if ref > 0: return self.exports[ref - 1].cls
        if ref < 0: return self.imports[-ref - 1].class_name
        return "None"

    def full_name(self, ref):
        parts = []
        while ref:
            if ref > 0:
                e = self.exports[ref - 1]; parts.append(e.name); ref = e.pkg_ref
            else:
                i = self.imports[-ref - 1]; parts.append(i.name); ref = i.pkg_ref
        return ".".join(reversed(parts))

    def outermost_import_pkg(self, ref):
        """For an import ref, return the top-level package name it lives in."""
        name = None
        while ref < 0:
            i = self.imports[-ref - 1]
            name = i.name
            ref = i.pkg_ref
        return name

    # ---- lookup
    def export_by_name(self, name, cls=None):
        for e in self._by_name.get(name.lower(), []):
            if cls is None or e.cls.lower() == cls.lower():
                return e
        return None

    def exports_of_class(self, *classes):
        cl = {c.lower() for c in classes}
        return [e for e in self.exports if e.cls.lower() in cl]

    def export_data(self, e):
        return self.data[e.offset:e.offset + e.size]

    def reader(self, e):
        return BinReader(self.data, e.offset), e.offset + e.size

    def ref(self, ref):
        return ObjRef(ref, self)

    def resolve(self, ref):
        """Return (Package, Export) for a ref, following imports through the PackageSet."""
        if ref > 0:
            return self, self.exports[ref - 1]
        if ref < 0:
            imp = self.imports[-ref - 1]
            pkgname = self.outermost_import_pkg(ref)
            if self.pset is None:
                return None, None
            pkg = self.pset.get(pkgname)
            if pkg is None:
                return None, None
            e = pkg.export_by_name(imp.name, imp.class_name) or pkg.export_by_name(imp.name)
            return (pkg, e) if e else (None, None)
        return None, None


class PackageSet:
    """Index every package under the given roots by stem (case-insensitive)."""
    def __init__(self, roots):
        self.files = {}
        for root in roots:
            for p in Path(root).rglob("*"):
                if p.is_file() and p.suffix.lower() in PKG_EXTS:
                    self.files.setdefault(p.stem.lower(), p)
        self.cache = {}

    def get(self, name):
        key = name.lower()
        if key in self.cache:
            return self.cache[key]
        p = self.files.get(key)
        pkg = Package(p, self) if p else None
        self.cache[key] = pkg
        return pkg

    def open(self, path):
        p = Path(path)
        key = p.stem.lower()
        if key not in self.cache:
            self.cache[key] = Package(p, self)
        return self.cache[key]
