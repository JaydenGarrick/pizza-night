"""UE2 UStaticMesh (package version 126, generic UE2)."""
import numpy as np
from .props import object_props


def load_staticmesh(pkg, export):
    props, r, end = object_props(pkg, export)
    m = {"name": export.name, "props": props}
    mats = props.get("Materials")
    m["materials"] = [s.get("Material") for s in mats.structs()] if mats is not None and hasattr(mats, "structs") else []
    m["bbox"] = (r.vec(), r.vec(), r.u8()); m["bsphere"] = (r.vec(), r.f32())      # UPrimitive
    m["sections"] = r.array_packed("<i5H")                                          # f4, FirstIndex, FirstVertex, LastVertex, fE, NumFaces
    r.vec(); r.vec(); r.u8()                                                        # BoundingBox again
    verts = r.array_packed("<6f"); r.i32()                                          # VertexStream (pos, normal), Revision
    m["positions"] = np.array([v[:3] for v in verts], dtype=np.float32).reshape(-1, 3)
    m["normals"] = np.array([v[3:] for v in verts], dtype=np.float32).reshape(-1, 3)
    cols = r.array_packed("<4B"); r.i32()                                           # ColorStream
    m["colors"] = cols
    r.array_packed("<4B"); r.i32()                                                  # AlphaStream
    uvs = []
    for _ in range(r.idx()):
        data = r.array_packed("<2f"); r.i32(); r.i32()
        uvs.append(np.array(data, dtype=np.float32).reshape(-1, 2))
    m["uvs"] = uvs
    idx = r.array_packed("<H"); r.i32()                                             # IndexStream1
    m["indices"] = np.array([i[0] for i in idx], dtype=np.uint32)
    r.array_packed("<H"); r.i32()                                                   # IndexStream2 (wireframe)
    r.idx()                                                                         # f108
    m["tail_bytes"] = end - r.tell()
    return m
