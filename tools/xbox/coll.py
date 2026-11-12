"""Treyarch 'COLL' collision resource (pack type 0x12, one per placed mesh: <MESH>000, 001...).
Header 16 B: 'COLL', u16 version (0x3f), u16 header size (0x10), u32 total size, u32 n_nodes.
Then n_nodes x 56 B BVH nodes: f32 centre[3], f32 radius, f32 m[3][3] (OBB axes scaled by half-extent + ~0.05 margin), u16 type, u16 param.
  type 0x400 root / 0x200 branch: param = child count (odd numbers 1,5,7,9,11...); type 0x1 leaf: param = byte offset from the node to its
  geometry chunk.  Geometry chunks follow the node array: {u16 n_verts, u16 n_tris, n_verts x f32[3], n_tris x u16[3]} (mesh-local D3D coords).
parse() returns the nodes and the merged triangle soup (verts, tris)."""
import struct
import numpy as np

def parse(d):
    assert d[:4] == b"COLL", "not a COLL resource"
    ver, hsz, size, n_nodes = struct.unpack_from("<HHII", d, 4)
    nodes = []; V = []; T = []; base = 0
    for i in range(n_nodes):
        o = hsz + 56 * i
        f = struct.unpack_from("<13f", d, o); typ, param = struct.unpack_from("<HH", d, o + 52)
        node = {"off": o, "centre": f[0:3], "radius": f[3], "m": f[4:13], "type": typ, "param": param}
        if typ == 1:
            g = o + param; nv, nt = struct.unpack_from("<HH", d, g)
            v = np.frombuffer(d, "<f4", nv * 3, g + 4).reshape(nv, 3); t = np.frombuffer(d, "<u2", nt * 3, g + 4 + nv * 12).reshape(nt, 3).astype(np.uint32)
            node["geom"] = g; node["n_verts"] = nv; node["n_tris"] = nt; V.append(v); T.append(t + base); base += nv
        nodes.append(node)
    return {"version": ver, "size": size, "n_nodes": n_nodes, "nodes": nodes,
            "verts": np.concatenate(V) if V else np.zeros((0, 3), np.float32), "tris": np.concatenate(T) if T else np.zeros((0, 3), np.uint32)}
