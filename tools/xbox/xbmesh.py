"""Treyarch NGL XBMESH (Spider-Man 2 Xbox) parser."""
import struct
import numpy as np

def cstr(m, ptr):
    return m[ptr + 4: ptr + 32].split(b"\0")[0].decode("latin-1") if 0 < ptr < len(m) else ""

def unpack_normals_11_11_10(u32):
    v = u32.astype(np.int64)
    x = ((v & 0x7ff) ^ 0x400) - 0x400; y = (((v >> 11) & 0x7ff) ^ 0x400) - 0x400; z = (((v >> 22) & 0x3ff) ^ 0x200) - 0x200
    n = np.stack([x / 1023.0, y / 1023.0, z / 511.0], 1)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)

def strip_to_list(ind):
    out = []
    for i in range(len(ind) - 2):
        a, b, c = int(ind[i]), int(ind[i + 1]), int(ind[i + 2])
        if a == b or b == c or a == c: continue
        out.append((a, c, b) if (i & 1) else (a, b, c))
    return np.array(out, dtype=np.uint32).reshape(-1, 3)

COLOUR_FIRST_SHADERS = {"smlegosimple", "smlego"}          # colour precedes the uv set(s)
COLOUR_LAST_SHADERS = {"smtranslucent", "smfxenv", "smglass", "smshiny"}   # uv (and tangent frame) precede the colour

def parse(m):
    assert m[:4] == b"XBXM", "not an XBMESH"
    n = struct.unpack_from("<I", m, 8)[0]
    ents = [struct.unpack_from("<3I", m, 0x20 + 12 * i) for i in range(n)]
    materials, sections = [], []
    shader_of = {}
    def colour_first(mat_name, raw, off):
        sh = shader_of.get(mat_name)
        if sh in COLOUR_FIRST_SHADERS: return True
        if sh in COLOUR_LAST_SHADERS: return False
        return len(raw) == 0 or float(np.mean(raw[:, off + 3] == 255)) > 0.9   # unknown shader: colour slots carry alpha 255
    for tag, off, sp in ents:
        typ, size = tag >> 24, tag & 0xffffff
        if typ == 1:
            u = struct.unpack_from("<12I", m, off)
            materials.append({"name": cstr(m, u[0]), "shader": cstr(m, u[1]), "tex0": cstr(m, u[6]), "tex1": cstr(m, u[8]), "tex2": cstr(m, u[9]), "raw": u})
            shader_of[materials[-1]["name"]] = materials[-1]["shader"]
        elif typ == 2:
            u = struct.unpack_from("<24I", m, off); f = struct.unpack_from("<24f", m, off)
            sec = {"name": cstr(m, u[0]), "nsub": u[2], "bone_count": u[4], "palette_off": u[5], "n_lod": u[6], "lod_off": u[7], "center": f[8:11], "radius": f[12], "subs": []}
            if sec["bone_count"] and sec["palette_off"]:
                sec["palette"] = np.frombuffer(m[sec["palette_off"]: sec["palette_off"] + 64 * sec["bone_count"]], "<f4").reshape(-1, 4, 4).copy()
            for k in range(sec["nsub"]):
                so = struct.unpack_from("<I", m, u[3] + 8 * k + 4)[0]
                s = struct.unpack_from("<24I", m, so); sf = struct.unpack_from("<24f", m, so)
                sub = {"material": cstr(m, s[0]), "nbones": s[2], "bones_off": s[3], "center": sf[4:7], "radius": sf[8], "prim": s[10], "nidx": s[11], "idx_off": s[12], "oidx_off": s[14], "oidx_size": s[15], "nvert": s[16], "vb_off": s[17], "vb_size": s[18], "stride": s[20]}
                sub["bones"] = np.frombuffer(m[sub["bones_off"]: sub["bones_off"] + 2 * sub["nbones"]], "<u2").tolist() if sub["nbones"] else []
                vb = m[sub["vb_off"]: sub["vb_off"] + sub["nvert"] * sub["stride"]]
                st = sub["stride"]; nv = sub["nvert"]
                raw = np.frombuffer(vb, dtype="u1").reshape(nv, st) if nv else np.zeros((0, st), "u1")
                F = np.frombuffer(vb, "<f4").reshape(nv, st // 4) if nv else np.zeros((0, st // 4), "f4")
                U = np.frombuffer(vb, "<u4").reshape(nv, st // 4) if nv else np.zeros((0, st // 4), "u4")
                sub["pos"] = F[:, 0:3].astype(np.float32)
                if st == 32 and not sub["nbones"]:   # static lightmapped (sm_grunge interiors): pos, uv, uv2 (lightmap), colour
                    sub["nrm"] = None; sub["uv"] = F[:, 3:5].astype(np.float32); sub["uv2"] = F[:, 5:7].astype(np.float32); sub["color"] = raw[:, 28:32].copy()
                elif st == 32:    # skinned: pos, normal(packed), uv, bone idx u8x4, weights u8x4
                    sub["nrm"] = unpack_normals_11_11_10(U[:, 3]).astype(np.float32); sub["uv"] = F[:, 4:6].astype(np.float32)
                    sub["joints"] = raw[:, 24:28].copy(); sub["weights"] = raw[:, 28:32].astype(np.float32) / 255.0
                elif st == 24:    # static: pos, uv, color
                    sub["nrm"] = None; sub["uv"] = F[:, 3:5].astype(np.float32); sub["color"] = raw[:, 20:24].copy()
                elif st == 28:    # lit; layout is per shader (vertex declaration):
                    sub["nrm"] = unpack_normals_11_11_10(U[:, 3]).astype(np.float32)
                    if colour_first(sub["material"], raw, 16):   # smlegosimple: pos, normal, color, uv
                        sub["color"] = raw[:, 16:20].copy(); sub["uv"] = F[:, 5:7].astype(np.float32)
                    else:                                       # smtranslucent/smfxenv/smglass: pos, normal, uv, color
                        sub["uv"] = F[:, 4:6].astype(np.float32); sub["color"] = raw[:, 24:28].copy()
                elif st == 36:    # lit, two layouts by shader:
                    sub["nrm"] = unpack_normals_11_11_10(U[:, 3]).astype(np.float32)
                    if colour_first(sub["material"], raw, 16):   # smlego: pos, normal, color, uv0, uv1 (lightmap)
                        sub["color"] = raw[:, 16:20].copy(); sub["uv"] = F[:, 5:7].astype(np.float32); sub["uv2"] = F[:, 7:9].astype(np.float32)
                    else:                                       # smshiny: pos, normal, tangent, binormal, uv, color
                        sub["uv"] = F[:, 6:8].astype(np.float32); sub["color"] = raw[:, 32:36].copy()
                elif st == 16:    # pos, color (untextured)
                    sub["nrm"] = None; sub["color"] = raw[:, 12:16].copy(); sub["uv"] = np.zeros((nv, 2), "f4")
                else:
                    sub["nrm"] = None; sub["uv"] = F[:, 3:5].astype(np.float32) if st >= 20 else np.zeros((nv, 2), "f4")
                # indices
                if sub["nidx"]:
                    if sub["idx_off"]: ib = m[sub["idx_off"]: sub["idx_off"] + 2 * sub["nidx"]]
                    else: ib = m[sub["oidx_off"] + 12: sub["oidx_off"] + 12 + 2 * sub["nidx"]]
                    ind = np.frombuffer(ib, "<u2")
                    if sub["prim"] == 6: tris = strip_to_list(ind)
                    elif sub["prim"] == 5: tris = ind[: len(ind) // 3 * 3].astype(np.uint32).reshape(-1, 3)
                    else: tris = strip_to_list(ind)
                else:
                    if sub["prim"] == 8:   # non-indexed quad list
                        q = np.arange(nv // 4 * 4, dtype=np.uint32).reshape(-1, 4); tris = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
                    elif sub["prim"] == 5: tris = np.arange(nv // 3 * 3, dtype=np.uint32).reshape(-1, 3)
                    else: tris = strip_to_list(np.arange(nv))
                tris = tris[(tris < nv).all(1)] if len(tris) else tris
                sub["tris"] = tris
                sec["subs"].append(sub)
            sections.append(sec)
    return {"materials": {mat["name"]: mat for mat in materials}, "materials_list": materials, "sections": sections}
