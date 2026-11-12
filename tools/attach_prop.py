#!/usr/bin/env python3
"""Attach a static prop GLB (hat, mask, weapon...) to a bone of a rigged character GLB, rigid-skinned to that bone.

usage: attach_prop.py --model spidey.glb --prop birdhead.glb --bone head --out out.glb
         [--fit 1.35]            scale prop so its bbox ~= (bone's vertex bbox) * fit   (omit or 0 = keep prop scale)
         [--offset x,y,z]        extra offset in meters (glTF space: x right, y up, z back) after fitting
         [--rot x,y,z]           rotate prop by these degrees (applied before fitting)
         [--hide-regions head]   drop the character's triangles dominated by these bone-name regions (so they don't poke through)
         [--texture-size 1024]   downscale prop textures
"""
import sys, io, re, json, math
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.glbread import GLBFile
from ue2.gltf import GLB

args = sys.argv[1:]
def opt(flag, default=None):
    if flag in args: i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
    return default
model_path = opt("--model"); prop_path = opt("--prop"); bone_q = (opt("--bone", "head") or "head").lower(); out_path = opt("--out", "attached.glb")
fit = float(opt("--fit", "0") or 0); offset = np.array([float(v) for v in (opt("--offset", "0,0,0")).split(",")]); rot = [math.radians(float(v)) for v in (opt("--rot", "0,0,0")).split(",")]
hide = [h for h in (opt("--hide-regions", "") or "").split(",") if h]; tex_size = int(opt("--texture-size", "0") or 0)
aim_tip = opt("--aim-tip")
skirt = float(opt("--skirt", "0") or 0)        # extrude the prop's open boundary straight down by this many meters (mask neck)
pixel_tex = int(opt("--pixel-tex", "0") or 0)
tex_gain = float(opt("--tex-gain", "1.0") or 1.0)   # brighten/darken prop textures
clip_below = opt("--clip-below")                   # dy: remove everything below y = head joint + dy, with a clean planar cut
sleeve = opt("--sleeve")                           # "r,depth": neck sleeve of radius r from inside the mask down to depth m below the head joint
neck = float(opt("--neck", "0") or 0)              # build a neck tube from the mask rim down to this far below the bone joint (m)
neck_color = [float(v) for v in (opt("--neck-color", "0.13,0.12,0.11")).split(",")]  # downscale + colour-quantise prop textures, nearest sampling (retro look)
flat = "--flat" in args                        # flat-shaded prop (one normal per triangle)   # e.g. "-z": rotate so the prop's most protruding point faces that axis (beak/nose forward)

cm = GLBFile(model_path); pr = GLBFile(prop_path)
J = cm.j; skin = J["skins"][0]; joints = skin["joints"]; nodes = J["nodes"]
bone_names = [nodes[n].get("name", "") for n in joints]
bi = next((i for i, n in enumerate(bone_names) if n.lower() == bone_q), None) or next((i for i, n in enumerate(bone_names) if bone_q in n.lower()), None)
if bi is None: sys.exit(f"bone '{bone_q}' not found; bones: {bone_names}")
W = cm.node_world(); bone_w = W[joints[bi]]
print(f"attaching to bone [{bi}] {bone_names[bi]} at {bone_w[:3, 3].round(3)}")

# character geometry (all primitives of the first mesh)
prims_src = J["meshes"][0]["primitives"]
def region_of(name):
    n = name.lower()
    for key, lab in [("head", "head"), ("jaw", "head"), ("neck", "neck"), ("spine", "torso"), ("hip", "hips"), ("clavicle", "shoulders"), ("upper_arm", "upper arm"), ("elbow", "elbow"), ("lower_arm", "forearm"), ("wrist", "hand"), ("hand", "hand"), ("thumb", "fingers"), ("index", "fingers"), ("middle", "fingers"), ("ring", "fingers"), ("pinky", "fingers"), ("fingers", "fingers"), ("upper_leg", "thigh"), ("lower_leg", "shin"), ("ankle", "foot"), ("foot", "foot"), ("ball", "foot"), ("toe", "foot")]:
        if key in n: return lab
    return "other"
char_parts = []; hv_all = []
for prim in prims_src:
    cpos = cm.accessor(prim["attributes"]["POSITION"]).astype(np.float64); cnrm = cm.accessor(prim["attributes"]["NORMAL"]); cuv = cm.accessor(prim["attributes"]["TEXCOORD_0"])
    cJ = cm.accessor(prim["attributes"]["JOINTS_0"]); cW = cm.accessor(prim["attributes"]["WEIGHTS_0"]); cidx = cm.accessor(prim["indices"]).reshape(-1, 3)
    dom_tri = np.array([int(np.bincount(cJ[t].flatten(), weights=cW[t].flatten()).argmax()) for t in cidx])
    vdom = np.array([int(np.argmax(w)) for w in cW]); vj = np.array([cJ[i][vdom[i]] for i in range(len(cJ))])
    hv_all.append(cpos[vj == bi])
    keep = np.ones(len(cidx), bool)
    if hide: keep = np.array([region_of(bone_names[d]) not in hide for d in dom_tri])
    char_parts.append((prim, cpos, cnrm, cuv, cJ, cW, cidx, keep))
hv = np.concatenate(hv_all) if hv_all else np.zeros((0, 3))
if len(hv) < 4: hv = np.concatenate([cp[1] for cp in char_parts])
hmin, hmax = hv.min(0), hv.max(0); hcen = (hmin + hmax) / 2; hsize = hmax - hmin
print(f"target region bbox size {hsize.round(3)} center {hcen.round(3)} ({len(hv)} verts)")
if hide: print(f"hiding {sum(int((~k).sum()) for *_, k in char_parts)} character triangles in {hide}")

# prop geometry (world space of its own file), rotate, fit, place
PW = pr.node_world(); ppos = []; pnrm = []; puv = []; pidx = []; pmats = []; base = 0
Rx = lambda a: np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
Ry = lambda a: np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
Rz = lambda a: np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
R = Rz(rot[2]) @ Ry(rot[1]) @ Rx(rot[0])
for ni, n in enumerate(pr.j["nodes"]):
    if "mesh" not in n: continue
    M = PW[ni]
    for p in pr.j["meshes"][n["mesh"]]["primitives"]:
        P = pr.accessor(p["attributes"]["POSITION"]).astype(np.float64); P = (M[:3, :3] @ P.T).T + M[:3, 3]; P = (R @ P.T).T
        N = pr.accessor(p["attributes"]["NORMAL"]).astype(np.float64) if "NORMAL" in p["attributes"] else np.zeros_like(P); N = (R @ (np.linalg.inv(M[:3, :3]).T @ N.T)).T
        UV = pr.accessor(p["attributes"]["TEXCOORD_0"]).astype(np.float32) if "TEXCOORD_0" in p["attributes"] else np.zeros((len(P), 2), np.float32)
        I = pr.accessor(p["indices"]).reshape(-1).astype(np.uint32) if "indices" in p else np.arange(len(P), dtype=np.uint32)
        ppos.append(P); pnrm.append(N); puv.append(UV); pidx.append(I + base); pmats.append((p.get("material"), len(I))); base += len(P)
ppos = np.concatenate(ppos); pnrm = np.concatenate(pnrm); puv = np.concatenate(puv); pidx = np.concatenate(pidx)
if aim_tip:
    cen = ppos.mean(0)
    ylo = ppos[:, 1].min() + 0.4 * (ppos[:, 1].max() - ppos[:, 1].min())   # ignore the neck opening when looking for the beak/nose
    cand = np.where(ppos[:, 1] > ylo)[0]
    tip = ppos[cand[np.argmax(np.linalg.norm(ppos[cand] - cen, axis=1))]]; d = (tip - cen) / np.linalg.norm(tip - cen)
    target = {"-z": [0, 0, -1], "+z": [0, 0, 1], "+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0]}[aim_tip.lower()]
    t = np.array(target, float)
    if "--aim-full" in args:   # minimal 3D rotation (may introduce roll)
        v = np.cross(d, t); c = float(np.dot(d, t)); k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        Ra = np.eye(3) + k + k @ k * (1 / (1 + c)) if c > -0.999 else -np.eye(3)
    else:                      # yaw only: keep the prop's own up axis, turn it about Y so the tip faces the target
        a0 = math.atan2(d[0], d[2]); a1 = math.atan2(t[0], t[2]); ang = a1 - a0
        Ra = np.array([[math.cos(ang), 0, math.sin(ang)], [0, 1, 0], [-math.sin(ang), 0, math.cos(ang)]])
        if "--level" in args:   # pitch about X so the tip direction has no vertical component
            dy = Ra @ d; pitch = -math.atan2(dy[1], -dy[2]) if t[2] < 0 else -math.atan2(dy[1], dy[2])
            Rp = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]]); Ra = Rp @ Ra
            print(f"level: pitch {math.degrees(pitch):.1f} deg")
    ppos = (Ra @ (ppos - cen).T).T + cen; pnrm = (Ra @ pnrm.T).T
    print(f"aim-tip: tip direction {d.round(2)} -> {target} (tip at {(tip - cen).round(3)} from centre)")
pmin, pmax = ppos.min(0), ppos.max(0); pcen = (pmin + pmax) / 2; psize = pmax - pmin
anchor = opt("--anchor", "center")
if fit > 0 and anchor == "opening":
    # scale by side-to-side width (beak length would inflate the bbox), anchor the neck-opening centroid on the bone joint
    s = fit * hsize[0] / psize[0]
    ylo = pmin[1] + 0.12 * psize[1]; ring = ppos[ppos[:, 1] < ylo]; rc = ring.mean(0) if len(ring) else np.array([pcen[0], pmin[1], pcen[2]])
    target_pt = bone_w[:3, 3] + offset
    ppos = (ppos - rc) * s + target_pt
    print(f"fit(width) scale {s:.3f}: prop size {(psize * s).round(3)}, opening anchored at bone {target_pt.round(3)}")
elif fit > 0 and anchor == "bottom":
    # mask-style: scale by height, bottom edge at the bone joint (collar), skull centre over the head centre
    s = fit * hsize[1] / psize[1]
    zcut = np.percentile(ppos[:, 2], 40); skull = ppos[ppos[:, 2] > zcut]       # rear part (tip faces -Z after aiming)
    sc = skull.mean(0)
    target = np.array([hcen[0], bone_w[1, 3], hcen[2]]) + offset
    ppos = (ppos - np.array([sc[0], pmin[1], sc[2]])) * s + target
    print(f"fit(height) scale {s:.3f}: prop size {(psize * s).round(3)}, bottom at y={target[1]:.3f}, skull centre over head")
elif fit > 0:
    s = fit * max(hsize) / max(psize); ppos = (ppos - pcen) * s + hcen + offset
    print(f"fit scale {s:.3f}: prop size {(psize * s).round(3)} placed at {(hcen + offset).round(3)}")
else:
    ppos = ppos + offset

if clip_below is not None:
    ycut = bone_w[1, 3] + float(clip_below)
    tri = pidx.reshape(-1, 3)
    NP, NN, NU, NI, newmats = [], [], [], [], []
    start = 0
    for mat_i, cnt in pmats:
        block = tri[start // 3:(start + cnt) // 3]; start += cnt; n_before = len(NI)
        for t in block:
            d = ppos[t, 1] - ycut
            if (d >= 0).all():
                poly = [(ppos[k], pnrm[k], puv[k]) for k in t]
            elif (d < 0).all():
                continue
            else:   # Sutherland-Hodgman against the plane, keep the upper side
                poly = []
                for a_, b_ in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                    da, db = ppos[a_, 1] - ycut, ppos[b_, 1] - ycut
                    if da >= 0: poly.append((ppos[a_], pnrm[a_], puv[a_]))
                    if (da >= 0) != (db >= 0):
                        u = da / (da - db)
                        poly.append((ppos[a_] + (ppos[b_] - ppos[a_]) * u, pnrm[a_] + (pnrm[b_] - pnrm[a_]) * u, puv[a_] + (puv[b_] - puv[a_]) * u))
            base_i = len(NP)
            for q in poly: NP.append(q[0]); NN.append(q[1]); NU.append(q[2])
            for k in range(1, len(poly) - 1): NI += [base_i, base_i + k, base_i + k + 1]
        newmats.append((mat_i, len(NI) - n_before))
    ppos = np.array(NP); pnrm = np.array(NN); puv = np.array(NU, dtype=np.float32); pidx = np.array(NI, dtype=np.uint32); pmats = newmats
    print(f"clip: removed everything below y={ycut:.3f}; {len(pidx)//3} triangles remain")
if skirt > 0:
    # boundary edges = edges used by exactly one triangle
    tri = pidx.reshape(-1, 3); edges = {}
    # weld by position so UV-seam duplicates don't count as open edges
    keys = {}; canon = np.zeros(len(ppos), dtype=np.int64)
    for vi, pv in enumerate(np.round(ppos, 5)):
        k = tuple(pv); canon[vi] = keys.setdefault(k, vi)
    for a_, b_, c_ in tri:
        for e in ((canon[a_], canon[b_]), (canon[b_], canon[c_]), (canon[c_], canon[a_])):
            if e[0] == e[1]: continue
            k = (min(e), max(e)); edges[k] = edges.get(k, 0) + 1
    ymin, ymax = ppos[:, 1].min(), ppos[:, 1].max()
    cut = ymin + 0.35 * (ymax - ymin)            # only the bottom opening, not eye holes / cracks higher up
    boundary = [e for e, n in edges.items() if n == 1 and ppos[e[0], 1] < cut and ppos[e[1], 1] < cut]
    bverts = sorted({v for e in boundary for v in e})
    ybottom = ppos[:, 1].min() - skirt
    newidx = {v: len(ppos) + i for i, v in enumerate(bverts)}
    extra = ppos[bverts].copy(); extra[:, 1] = ybottom
    ppos = np.concatenate([ppos, extra]); pnrm = np.concatenate([pnrm, pnrm[bverts]]); puv = np.concatenate([puv, puv[bverts]])
    quads = []
    for a_, b_ in boundary:
        a2, b2 = newidx[a_], newidx[b_]
        quads += [a_, b_, b2, a_, b2, a2]
    pidx = np.concatenate([pidx, np.array(quads, dtype=np.uint32)])
    pmats[-1] = (pmats[-1][0], pmats[-1][1] + len(quads))
    print(f"skirt: {len(boundary)} boundary edges extruded down to y={ybottom:.3f}")
if flat:
    tri = pidx.reshape(-1, 3)
    P2 = ppos[tri].reshape(-1, 3); UV2 = puv[tri].reshape(-1, 2)
    fn = np.cross(P2[1::3] - P2[0::3], P2[2::3] - P2[0::3]); fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
    ppos = P2; puv = UV2.astype(np.float32); pnrm = np.repeat(fn, 3, axis=0); pidx = np.arange(len(P2), dtype=np.uint32)
    pmats = [(pmats[0][0], len(pidx))] if pmats else pmats
if neck > 0:
    # rubber-mask neck: cone from the mask's rim ellipse down to a tight ring around the neck at collar height
    ylo, yhi = ppos[:, 1].min(), ppos[:, 1].max(); band = ppos[ppos[:, 1] < ylo + 0.18 * (yhi - ylo)]
    rcx, rcz = (band[:, 0].max() + band[:, 0].min()) / 2, (band[:, 2].max() + band[:, 2].min()) / 2
    rrx = (band[:, 0].max() - band[:, 0].min()) / 2 * 0.98; rrz = (band[:, 2].max() - band[:, 2].min()) / 2 * 0.98
    ncx, ncz = bone_w[0, 3], bone_w[2, 3]; nr = float(opt("--neck-radius", "0.075") or 0.075)
    ytop = ylo + 0.08 * (yhi - ylo); ybot = bone_w[1, 3] - neck
    segs_n = 24; ring = np.linspace(0, 2 * math.pi, segs_n, endpoint=False)
    top = np.stack([rcx + rrx * np.cos(ring), np.full(segs_n, ytop), rcz + rrz * np.sin(ring)], 1)
    bot = np.stack([ncx + nr * np.cos(ring), np.full(segs_n, ybot), ncz + nr * np.sin(ring)], 1)
    side = top - bot; nrm_ring = np.stack([np.cos(ring), np.zeros(segs_n), np.sin(ring)], 1)
    base_i = len(ppos)
    ppos = np.concatenate([ppos, top, bot]); pnrm = np.concatenate([pnrm, nrm_ring, nrm_ring]); puv = np.concatenate([puv, np.zeros((2 * segs_n, 2), np.float32)])
    quads = []
    for i in range(segs_n):
        j = (i + 1) % segs_n; a_, b_, c_, d_ = base_i + i, base_i + j, base_i + segs_n + j, base_i + segs_n + i
        quads += [a_, b_, c_, a_, c_, d_]
    pidx = np.concatenate([pidx, np.array(quads, dtype=np.uint32)]); pmats.append(("neck", len(quads)))
    if opt("--neck-color-auto", None) is None and neck_color == [0.13, 0.12, 0.11]:
        # match the mask: average of its (brightened) texture
        try:
            im0 = pr.j["images"][0]; pil0 = Image.open(io.BytesIO(pr.view_bytes(im0["bufferView"]))).convert("RGB").resize((32, 32))
            arr0 = np.asarray(pil0).astype(np.float32).reshape(-1, 3) / 255; m = np.percentile(arr0, 30, axis=0) * tex_gain * 0.9; neck_color = [float(min(1, v)) for v in m]
        except Exception: pass
    print(f"neck cone: rim {rrx*2:.3f}x{rrz*2:.3f} at y={ytop:.3f} -> ring r={nr} at y={ybot:.3f}, colour {np.round(neck_color, 2)}")
sleeve_data = None
if sleeve:
    sr, sdepth = [float(v) for v in sleeve.split(",")]
    neck_bi = next((i for i, n in enumerate(bone_names) if n.lower() == "neck"), bi)
    ylo, yhi = ppos[:, 1].min(), ppos[:, 1].max()
    cx, cz = bone_w[0, 3], bone_w[2, 3] + 0.01
    ytop = ylo + 0.35 * (yhi - ylo)          # start well inside the mask shell
    ybot = bone_w[1, 3] - sdepth
    segs_n = 20; ring = np.linspace(0, 2 * math.pi, segs_n, endpoint=False)
    top = np.stack([cx + sr * np.cos(ring), np.full(segs_n, ytop), cz + sr * 0.9 * np.sin(ring)], 1)
    bot = np.stack([cx + sr * 1.05 * np.cos(ring), np.full(segs_n, ybot), cz + sr * 0.95 * np.sin(ring)], 1)
    nrm_ring = np.stack([np.cos(ring), np.zeros(segs_n), np.sin(ring)], 1)
    quads = []
    for i in range(segs_n):
        j = (i + 1) % segs_n; a_, b_, c_, d_ = i, j, segs_n + j, segs_n + i
        quads += [a_, b_, c_, a_, c_, d_]
    sleeve_data = (np.concatenate([top, bot]), np.concatenate([nrm_ring, nrm_ring]), np.array(quads, dtype=np.uint32), neck_bi)
    if neck_color == [0.13, 0.12, 0.11]:
        try:
            im0 = pr.j["images"][0]; pil0 = Image.open(io.BytesIO(pr.view_bytes(im0["bufferView"]))).convert("RGB").resize((32, 32))
            arr0 = np.asarray(pil0).astype(np.float32).reshape(-1, 3) / 255; m = np.percentile(arr0, 30, axis=0) * tex_gain * 0.9; neck_color = [float(min(1, v)) for v in m]
        except Exception: pass
    print(f"neck sleeve: r={sr} from y={ytop:.3f} (inside mask) to y={ybot:.3f}, skinned head->{bone_names[neck_bi]}")
# ---- write combined GLB: copy nodes, skin, animations, character material/texture; add prop primitives as a second mesh skinned to the bone
glb = GLB()
for n in nodes: glb.j["nodes"].append({k: v for k, v in n.items() if k in ("name", "translation", "rotation", "scale", "matrix", "children")})
ibm = cm.accessor(skin["inverseBindMatrices"]).astype(np.float32)
glb.j["skins"].append({"joints": joints, "inverseBindMatrices": glb.accessor(ibm), "skeleton": skin.get("skeleton", joints[0]), "name": "skin"})
for a in J.get("animations", []):
    na = {"name": a.get("name"), "channels": [{"sampler": c["sampler"], "target": dict(c["target"])} for c in a["channels"]], "samplers": []}
    for smp in a["samplers"]: na["samplers"].append({"input": glb.accessor(cm.accessor(smp["input"]).astype(np.float32), minmax=True), "output": glb.accessor(cm.accessor(smp["output"]).astype(np.float32)), "interpolation": smp.get("interpolation", "LINEAR")})
    if "extras" in a: na["extras"] = a["extras"]
    glb.j["animations"].append(na)
def copy_material(src, mi):
    if mi == "neck":
        lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in neck_color]   # sRGB -> linear (glTF factors are linear)
        idx = glb.material("MaskNeck", None, None, True); glb.j["materials"][idx]["pbrMetallicRoughness"]["baseColorFactor"] = [lin[0], lin[1], lin[2], 1.0]; return idx
    if mi is None: return glb.material("prop")
    m = src.j["materials"][mi]; pbr = m.get("pbrMetallicRoughness", {}); tex = None
    bct = pbr.get("baseColorTexture")
    if bct is not None:
        im = src.j["images"][src.j["textures"][bct["index"]]["source"]]
        if "bufferView" in im:
            pil = Image.open(io.BytesIO(src.view_bytes(im["bufferView"]))).convert("RGBA")
            if tex_size and max(pil.size) > tex_size: pil = pil.resize((tex_size, tex_size), Image.LANCZOS)
            if src is pr and tex_gain != 1.0:
                from PIL import ImageEnhance
                pil = ImageEnhance.Brightness(pil).enhance(tex_gain)
            if src is pr and pixel_tex:
                pil = pil.resize((pixel_tex, pixel_tex), Image.LANCZOS).convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT).convert("RGBA")
            tex = glb.image_png(pil, im.get("name"))
            if src is pr and pixel_tex:
                glb.j["samplers"].append({"magFilter": 9728, "minFilter": 9728, "wrapS": 10497, "wrapT": 10497}); glb.j["textures"][tex]["sampler"] = len(glb.j["samplers"]) - 1
    idx = glb.material(m.get("name", f"mat{mi}"), tex, m.get("alphaMode"), m.get("doubleSided", False))
    if "baseColorFactor" in pbr: glb.j["materials"][idx]["pbrMetallicRoughness"]["baseColorFactor"] = pbr["baseColorFactor"]
    return idx
char_prims = []
for prim, cpos, cnrm, cuv, cJ, cW, cidx, keep in char_parts:
    kept = cidx[keep].flatten().astype(np.uint32)
    if len(kept) == 0: continue
    char_prims.append({"attributes": {"POSITION": glb.accessor(cpos.astype(np.float32), 34962, minmax=True), "NORMAL": glb.accessor(cnrm.astype(np.float32), 34962), "TEXCOORD_0": glb.accessor(cuv.astype(np.float32), 34962), "JOINTS_0": glb.accessor(cJ.astype(np.uint16), 34962), "WEIGHTS_0": glb.accessor(cW.astype(np.float32), 34962)}, "indices": glb.accessor(kept, 34963), "material": copy_material(cm, prim.get("material")), "mode": 4})
pj = np.zeros((len(ppos), 4), np.uint16); pj[:, 0] = bi; pw = np.zeros((len(ppos), 4), np.float32); pw[:, 0] = 1
prop_prims = []; start = 0
for mi, cnt in pmats:
    prop_prims.append({"attributes": {"POSITION": glb.accessor(ppos.astype(np.float32), 34962, minmax=True), "NORMAL": glb.accessor(pnrm.astype(np.float32), 34962), "TEXCOORD_0": glb.accessor(puv, 34962), "JOINTS_0": glb.accessor(pj, 34962), "WEIGHTS_0": glb.accessor(pw, 34962)}, "indices": glb.accessor(pidx[start:start + cnt], 34963), "material": copy_material(pr, mi), "mode": 4}); start += cnt
if sleeve_data is not None:
    sp, sn, si, nbi = sleeve_data; n2 = len(sp) // 2
    sj = np.zeros((len(sp), 4), np.uint16); sw = np.zeros((len(sp), 4), np.float32)
    sj[:n2, 0] = bi; sw[:n2, 0] = 1.0                       # top ring follows the head
    sj[n2:, 0] = nbi; sj[n2:, 1] = bi; sw[n2:, 0] = 0.7; sw[n2:, 1] = 0.3   # bottom ring mostly follows the neck
    prop_prims.append({"attributes": {"POSITION": glb.accessor(sp.astype(np.float32), 34962, minmax=True), "NORMAL": glb.accessor(sn.astype(np.float32), 34962), "TEXCOORD_0": glb.accessor(np.zeros((len(sp), 2), np.float32), 34962), "JOINTS_0": glb.accessor(sj, 34962), "WEIGHTS_0": glb.accessor(sw, 34962)}, "indices": glb.accessor(si, 34963), "material": copy_material(pr, "neck"), "mode": 4})
glb.j["meshes"].append({"name": "character", "primitives": char_prims + prop_prims})
mesh_node = next(i for i, n in enumerate(nodes) if "mesh" in n)
glb.j["nodes"][mesh_node]["mesh"] = 0; glb.j["nodes"][mesh_node]["skin"] = 0
glb.j["scenes"][0]["nodes"] = list(J["scenes"][J.get("scene", 0)]["nodes"])
size = glb.write(out_path); print(f"wrote {out_path} ({size/1e6:.2f} MB)")
