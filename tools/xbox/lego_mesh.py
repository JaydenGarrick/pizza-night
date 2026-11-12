"""Build a cell's 'lego' generic buildings the way the game does: instance its unit ring meshes (CITY blgNNx1 / aptNNx1, 5 units tall,
footprint from the type name) once per 5 units of a record's height, with the record's two master textures substituted per material slot
('1face' = the side texture, tex id 0; '2edge' = the corner pieces, tex id 1), plus a trim band on top of every segment, a roof cap and
pedestal bands under base segments (those three are textured quads, tiled by each texture's aspect).  Records whose ring mesh is missing
fall back to plain quads.  The old generator tiled one texture every 5 m on 4 flat faces: the blg side/edge textures are 10 x 5 m, so
windows came out half width, the corner (edge) texture never appeared and 4:1 trim textures were squashed 4x."""
import math, re
from collections import defaultdict
import numpy as np
from ue2.gltf import GLB

ROOF_TEX = ["s_blg_rofmid1", "s_blg_rofmid2"]; TRIM_TEX = ["s_blg_trm1", "s_blg_trm2", "s_blg_trm3"]; TRIM_H = 2.0; RING_H = 5.0

def ring_axes(yaw_deg):
    """glTF-space unit vectors of a ring's local +x and +z for a record yaw.  The records' yaw is a left-handed (D3D) rotation about +y; after
    the z flip into glTF it must be applied NEGATED, otherwise every odd-angle block (A03 at 27 deg, H71 at 43 deg) lands rotated the wrong way
    (tools/xbox_lego_orient.py scored it against the game's LOD city mesh: 20366 vs 18561 matching face samples)."""
    th = math.radians(-yaw_deg); c, s = math.cos(th), math.sin(th)
    return (c, -s), (s, c)        # D3D row-vector RotY -> glTF (x, -z)
def ring_frame(rec, orient=None, cell=None, index=None):
    """(centre_glTF_xz, ax, az) with the per-ring +90 correction from intermediate/xbox/lego_orient.json applied"""
    dyaw = (orient or {}).get(cell, {}).get(str(index), 0) if orient is not None else 0
    ax, az = ring_axes(rec["yaw"] + dyaw); return (rec["pos"][0], -rec["pos"][2]), ax, az
def build_lego(cell, L, dst, load_tex, load_mesh, log=print, orient=None):
    glb = GLB(); texcache = {}; mats = {}; sizes = {}; groups = defaultdict(lambda: {"P": [], "N": [], "UV": [], "I": []}); rings = {}
    def tex(name):
        if name not in texcache:
            img = load_tex(name) if name else None; texcache[name] = glb.image_png(img, name) if img is not None else None
            if img is not None: sizes[name] = img.size
        return texcache[name]
    def mat_for(name):
        if name not in mats: mats[name] = glb.material(name, tex(name), None, False); glb.j["materials"][mats[name]]["extras"] = {"unlit": True, "shader": "smlego", "single_sided": True}   # the game draws these one-sided: a camera behind a one-sided wing piece (AC72) or inside a ground floor (SA24) must see through
        return mats[name]
    def tile_w(name, band_h):   # horizontal repeat length for a band band_h tall, from the texture's aspect (2:1 -> 10 m per 5 m)
        w, h = sizes.get(name, (1, 1)); return band_h * w / max(1, h)
    def place(rec):
        (cx, cz), ax, az = ring_frame(rec, orient, cell, rec.get("i"))          # glTF centre + local axes (negated yaw, per-ring +90 fix)
        def W(x, y, z): return (cx + ax[0] * x + az[0] * z, y, cz + ax[1] * x + az[1] * z)
        def Wn(x, y, z): return (ax[0] * x + az[0] * z, y, ax[1] * x + az[1] * z)
        return W, Wn
    def quad(mi, pts, uvs, outward):
        pts = [np.asarray(q, dtype=np.float64) for q in pts]; n = np.cross(pts[1] - pts[0], pts[2] - pts[0]); ln = np.linalg.norm(n)
        if ln < 1e-9: return
        n /= ln; order = [0, 1, 2, 0, 2, 3]
        if np.dot(n, outward) < 0: n = -n; order = [0, 2, 1, 0, 3, 2]
        g = groups[mi]; base = len(g["P"]); g["P"] += [q.tolist() for q in pts]; g["N"] += [n.tolist()] * 4; g["UV"] += uvs; g["I"] += [base + k for k in order]
    def band(rec, y0, y1, texname):
        """a textured ring of quads around the record's footprint (trims, pedestals, fallback walls)"""
        mi = mat_for(texname); tw = tile_w(texname, y1 - y0); W, _ = place(rec); hw, hd = rec["w"] / 2.0, rec["d"] / 2.0
        corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
        for k in range(4):
            (ax, az), (bx, bz) = corners[k], corners[(k + 1) % 4]; length = math.hypot(bx - ax, bz - az)
            mid = W((ax + bx) / 2, (y0 + y1) / 2, (az + bz) / 2); ctr = W(0, (y0 + y1) / 2, 0); outward = np.subtract(mid, ctr)
            quad(mi, [W(ax, y0, az), W(bx, y0, bz), W(bx, y1, bz), W(ax, y1, az)], [[0, 1], [length / tw, 1], [length / tw, 0], [0, 0]], outward)
    def cap(rec, y, texname, tile=5.0):
        mi = mat_for(texname); W, _ = place(rec); hw, hd = rec["w"] / 2.0, rec["d"] / 2.0
        quad(mi, [W(-hw, y, -hd), W(hw, y, -hd), W(hw, y, hd), W(-hw, y, hd)], [[0, 0], [2 * hw / tile, 0], [2 * hw / tile, 2 * hd / tile], [0, 2 * hd / tile]], (0, 1, 0))
    def ring_mesh(name):
        if name not in rings:
            m = None
            try: m = load_mesh(name)
            except Exception as ex: log(f"  ring {name}: {type(ex).__name__}: {ex}")
            rings[name] = m
        return rings[name]
    def instance_rings(rec, side_tex, edge_tex):
        m = ring_mesh(rec["type"])
        if not m: return False
        y0, h = rec["pos"][1], rec["h"]; n = max(1, int(round(h / RING_H))); sy = h / (RING_H * n); W, Wn = place(rec)
        for sub in [sb for sec in m["sections"] for sb in sec["subs"]]:
            if not sub["nvert"] or not len(sub["tris"]): continue
            slot = str(sub["material"]).lower(); texname = (edge_tex or side_tex) if "edge" in slot else (side_tex or edge_tex)
            if not texname: continue
            mi = mat_for(texname); P = np.asarray(sub["pos"], dtype=np.float64); N = np.asarray(sub["nrm"], dtype=np.float64) if sub.get("nrm") is not None else None; UV = np.asarray(sub["uv"], dtype=np.float64)
            for k in range(n):
                g = groups[mi]; base = len(g["P"])
                for i in range(len(P)):
                    x, y, z = P[i]; g["P"].append(list(W(x, y0 + sy * (y + RING_H / 2 + RING_H * k), z)))
                    g["N"].append(list(Wn(*N[i])) if N is not None else [0, 1, 0]); g["UV"].append([float(UV[i][0]), float(UV[i][1])])
                for t in sub["tris"]:   # wind every triangle so its front faces OUT of the ring (geometric normal . (centroid - centre) > 0): the source winding is not trusted
                    a, b_, c = (P[int(t[0])], P[int(t[1])], P[int(t[2])]); nrm = np.cross(b_ - a, c - a); cen = (a + b_ + c) / 3; outward = float(nrm[0] * cen[0] + nrm[2] * cen[2])
                    if abs(outward) < 1e-9: outward = float(nrm[1])          # horizontal faces (none expected on rings): up
                    order = (int(t[0]), int(t[2]), int(t[1])) if outward < 0 else (int(t[0]), int(t[1]), int(t[2]))
                    g["I"] += [base + order[0], base + order[1], base + order[2]]   # W() mirrors z, which already flips the winding once: no extra swap (verified by raycast from inside/outside)
        return True
    n_seg = 0
    for rec in L["records"]:
        if not rec["lego"] or not rec["h"]: continue
        side = L["tex_by_id"].get(rec["tex_ids"][0]); edge = L["tex_by_id"].get(rec["tex_ids"][1])
        if not (side or edge): continue
        y0 = rec["pos"][1]; y1 = y0 + rec["h"]
        if not instance_rings(rec, side, edge): band(rec, y0, y1, side or edge)
        band(rec, y1, y1 + TRIM_H, TRIM_TEX[rec["b"] % 3] if rec["b"] < 3 else TRIM_TEX[0])
        cap(rec, y1 + TRIM_H, ROOF_TEX[rec["a"] % 2])
        if y0 > 0.01:   # pedestal under base segments
            bas = L["tex_by_id"].get(rec["ped_ids"][0]); top = L["tex_by_id"].get(rec["ped_ids"][1])
            if bas: band(rec, 0.0, min(5.0, y0), bas)
            if y0 > 5.0 and (top or bas): band(rec, 5.0, y0, top or bas)
        n_seg += 1
    if not groups: return None
    prims = []
    for mi, g in groups.items():
        attrs = {"POSITION": glb.accessor(np.array(g["P"], np.float32), 34962, minmax=True), "NORMAL": glb.accessor(np.array(g["N"], np.float32), 34962), "TEXCOORD_0": glb.accessor(np.array(g["UV"], np.float32), 34962)}
        prims.append({"attributes": attrs, "indices": glb.accessor(np.array(g["I"], np.uint32), 34963), "material": mi, "mode": 4})
    glb.j["meshes"].append({"name": f"{cell}_lego", "primitives": prims}); n = glb.node(name=f"{cell}_lego", mesh=0); glb.j["scenes"][0]["nodes"] = [n]
    glb.write(dst); return n_seg
