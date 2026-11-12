"""UE2 UModel (BSP) reader for package version 126 (Spider-Man 2 PC): Vectors, Points, Nodes, Surfs, Verts."""
import numpy as np
from .props import object_props

PF_INVISIBLE = 0x1; PF_MASKED = 0x2; PF_TRANSLUCENT = 0x4; PF_FAKEBACKDROP = 0x80; PF_TWOSIDED = 0x100; PF_PORTAL = 0x4000000; PF_MIRRORED = 0x8000000; PF_UNLIT = 0x400000


def load_bsp(pkg, export):
    props, r, end = object_props(pkg, export)
    m = {"name": export.name}
    r.vec(); r.vec(); r.u8(); r.vec(); r.f32()
    m["vectors"] = np.array(r.array_packed("<3f"), dtype=np.float64).reshape(-1, 3)
    m["points"] = np.array(r.array_packed("<3f"), dtype=np.float64).reshape(-1, 3)
    nodes = []
    for _ in range(r.idx()):
        plane = r.quat(); r.i64(); flags = r.u8()
        iv = r.idx(); isf = r.idx(); r.idx(); r.idx(); r.idx(); r.idx(); r.idx()
        r.quat(); r.i32(); r.i32(); r.i32(); r.i32()
        iz0 = r.u8(); iz1 = r.u8(); nv = r.u8(); r.i32(); r.i32(); r.i32(); r.i32(); r.i32()
        nodes.append({"plane": plane, "flags": flags, "ivert": iv, "isurf": isf, "nverts": nv, "zones": (iz0, iz1)})
    m["nodes"] = nodes
    surfs = []
    for _ in range(r.idx()):
        mat = r.idx(); pf = r.u32(); pb = r.idx(); vn = r.idx(); vu = r.idx(); vv = r.idx(); r.idx(); ac = r.idx(); r.quat(); r.f32()
        surfs.append({"material": pkg.ref(mat), "flags": pf, "pbase": pb, "vnormal": vn, "vtu": vu, "vtv": vv, "actor": pkg.ref(ac)})
    m["surfs"] = surfs
    verts = []
    for _ in range(r.idx()):
        pv = r.idx(); r.idx(); verts.append(pv)
    m["verts"] = np.array(verts, dtype=np.int64)
    m["num_shared_sides"] = r.i32(); m["num_zones"] = r.i32()
    return m
