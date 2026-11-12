"""UE2 USkeletalMesh (package version 126, generic UE2 layout)."""
import numpy as np
from .props import object_props


def _read_lod(r):
    lod = {}
    lod["skinning"] = r.array_packed("<I")
    lod["skinpoints"] = r.array_packed("<3fI")
    lod["num_soft_wedges"] = r.i32()
    lod["soft_sections"] = r.array_packed("<9H")
    lod["rigid_sections"] = r.array_packed("<9H")
    lod["soft_indices"] = r.array_packed("<H"); r.i32()
    lod["rigid_indices"] = r.array_packed("<H"); r.i32()
    r.i32(); r.i32(); r.i32()
    lod["vertex_stream"] = r.array_packed("<8f")
    lod["influences"] = r.lazy_packed("<fHH")
    lod["wedges"] = r.lazy_packed("<Hff")
    lod["faces"] = r.lazy_packed("<4H")
    lod["points"] = r.lazy_packed("<3f")
    lod["lod_distance_factor"] = r.f32(); lod["lod_hysteresis"] = r.f32()
    lod["num_shared_verts"] = r.i32(); lod["max_influences"] = r.i32(); r.i32(); r.i32()
    return lod


def load_skelmesh(pkg, export):
    props, r, end = object_props(pkg, export)
    m = {"name": export.name, "props": props}
    # UPrimitive
    m["bbox"] = (r.vec(), r.vec(), r.u8())
    m["bsphere"] = (r.vec(), r.f32())
    # ULodMesh
    version = r.i32(); m["lod_version"] = version
    m["vertex_count"] = r.i32()
    r.array_packed("<I")                                  # Verts (vertex meshes only)
    if version <= 1:
        r.array_packed("<3H6fIi")
    m["textures"] = [pkg.ref(r.idx()) for _ in range(r.idx())]
    m["mesh_scale"] = r.vec(); m["mesh_origin"] = r.vec(); m["rot_origin"] = r.rot()
    if version <= 1:
        r.array_packed("<H")
    r.array_packed("<H")                                  # FaceLevel
    r.array_packed("<4H")                                 # Faces
    r.array_packed("<H")                                  # CollapseWedgeThus
    r.array_packed("<Hff")                                # Wedges (lod mesh)
    m["materials"] = r.array_packed("<Ii")                # (PolyFlags, TextureIndex)
    r.f32(); r.f32(); r.f32(); r.i32(); r.f32(); r.f32()
    if version >= 3:
        r.i32(); r.idx(); r.vec(); r.rot(); r.vec(); r.color(); r.i32(); r.i32(); r.i32()
    if version >= 4:
        r.f32()
    # USkeletalMesh
    r.array_packed("<3f")                                 # Points2
    bones = []
    for _ in range(r.idx()):
        name = pkg.names[r.idx()]; flags = r.u32()
        q = r.quat(); pos = r.vec(); length = r.f32(); size = r.vec()
        numchildren = r.i32(); parent = r.i32()
        bones.append({"name": name, "flags": flags, "quat": q, "pos": pos, "length": length, "size": size, "parent": parent, "children": numchildren})
    m["bones"] = bones
    m["animation"] = pkg.ref(r.idx())
    m["skeletal_depth"] = r.i32()
    for _ in range(r.idx()):                              # WeightIndices
        r.array_packed("<H"); r.i32()
    r.array_packed("<HH")                                 # BoneInfluences
    aliases = [pkg.names[r.idx()] for _ in range(r.idx())]
    abones = [pkg.names[r.idx()] for _ in range(r.idx())]
    acoords = r.array_packed("<12f")
    m["sockets"] = list(zip(aliases, abones, acoords))
    if version <= 1:
        raise ValueError("old skeletal mesh version <= 1 unsupported")
    m["lods"] = [_read_lod(r) for _ in range(r.idx())]
    r.idx()                                               # f224
    m["points"] = np.array(r.lazy_packed("<3f"), dtype=np.float32).reshape(-1, 3)
    m["wedges"] = r.lazy_packed("<Hff")
    m["triangles"] = r.lazy_packed("<3HBBI")
    m["influences"] = r.lazy_packed("<fHH")
    m["tail_bytes"] = end - r.tell()
    return m
