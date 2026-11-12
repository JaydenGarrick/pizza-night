#!/usr/bin/env python3
"""Snap the city's fire escapes to the building they hang on.  The lego block stores each fire escape with a position and a yaw, but ~25 % of the
yaws are 90 deg off (the 11 m length pointing out of the wall instead of along it), a few are 20 deg off and some sit metres from any wall or
have a 0xCDCD yaw: in the game the engine evidently derives the attached prop's transform from the wall it hangs on.  For every fire escape
placement in public/levels/XB_CITY/stage.json this finds the nearest generic-building face (all 88 cells, lateral overlap required, -3..9 m off
the face), sets the yaw so the mesh's depth axis (local x, 4 m) is along the face normal (keeping the stored mirror where it is readable), puts the
centre 2 m off the face (flush, the value 60 % of the records already have) and drops the ones with no wall.  Backs up stage.json first.
usage: xbox_fix_fireescapes.py [--dry]   (run on a stage whose lego_prop quats are already mirrored: see NOTES 'LEGO YAW SIGN')"""
import sys, math, json, shutil, re
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
from xbox.lego import parse_lego
from xbox.lego_mesh import ring_frame, ring_axes
ORIENT = json.load(open("intermediate/xbox/lego_orient.json")) if Path("intermediate/xbox/lego_orient.json").exists() else {}
DRY = "--dry" in sys.argv
R = np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float64); cvt = lambda v: (R @ np.asarray(v, dtype=np.float64).T).T
def yaw_matrix(pos, yaw_deg):
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)); M = np.eye(4); M[0, :3] = [c, 0, -s]; M[2, :3] = [s, 0, c]; M[3, :3] = pos; return M
def mat_to_pos_quat(M):
    Rm = M[:3, :3].T.astype(np.float64); Rg = R @ Rm @ R.T; sx, sy, sz = [np.linalg.norm(Rg[:, i]) for i in range(3)]; Rn = Rg / np.array([sx, sy, sz])
    if np.linalg.det(Rn) < 0: Rn[:, 2] *= -1; sz = -sz
    t = np.trace(Rn)
    if t > 0: s = math.sqrt(t + 1) * 2; q = [(Rn[2,1]-Rn[1,2])/s, (Rn[0,2]-Rn[2,0])/s, (Rn[1,0]-Rn[0,1])/s, 0.25*s]
    elif Rn[0,0] > Rn[1,1] and Rn[0,0] > Rn[2,2]: s = math.sqrt(1+Rn[0,0]-Rn[1,1]-Rn[2,2])*2; q = [0.25*s, (Rn[0,1]+Rn[1,0])/s, (Rn[0,2]+Rn[2,0])/s, (Rn[2,1]-Rn[1,2])/s]
    elif Rn[1,1] > Rn[2,2]: s = math.sqrt(1+Rn[1,1]-Rn[0,0]-Rn[2,2])*2; q = [(Rn[0,1]+Rn[1,0])/s, 0.25*s, (Rn[1,2]+Rn[2,1])/s, (Rn[0,2]-Rn[2,0])/s]
    else: s = math.sqrt(1+Rn[2,2]-Rn[0,0]-Rn[1,1])*2; q = [(Rn[0,2]+Rn[2,0])/s, (Rn[1,2]+Rn[2,1])/s, 0.25*s, (Rn[1,0]-Rn[0,1])/s]
    return [float(x) for x in cvt(M[3, :3])], [float(x) for x in q], [float(sx), float(sy), float(sz)]
stage_path = Path("public/levels/XB_CITY/stage.json"); stage = json.load(open(stage_path)); statics = stage["statics"]
cells = sorted({p["mesh"].split(".")[0] for p in statics if p.get("class") == "lego"})
rings, fes = [], []
for cell in cells:
    ens = XBPack((Path("intermediate/xbox/packs") / f"{cell}.pack").read_bytes()).resource(cell, 8); L = parse_lego(ens) if ens else None
    if not L: continue
    for r in L["records"]:
        if r["lego"] and r["h"]: rings.append((cell, r))
        elif not r["lego"] and "fireescape" in r["type"].lower(): fes.append((cell, r))
faces = []
for cell_, r in rings:   # faces in glTF xz from the corrected ring frame (negated yaw + per-ring +90), then back to D3D z for the matching below
    (gx, gz), ax, az = ring_frame(r, ORIENT, cell_, r["i"]); cx, cz = gx, -gz; xd = (ax[0], -ax[1]); zd = (az[0], -az[1]); hw, hd = r["w"] / 2, r["d"] / 2
    for n, half, lat, lat_half in ((xd, hw, zd, hd), ((-xd[0], -xd[1]), hw, zd, hd), (zd, hd, xd, hw), ((-zd[0], -zd[1]), hd, xd, hw)):
        faces.append((n, (cx + n[0] * half, cz + n[1] * half), lat, lat_half, r["pos"][1], r["pos"][1] + r["h"]))
def best_face(px, py, pz):
    best = None
    for n, c, lat, lat_half, y0, y1 in faces:
        dx, dz = px - c[0], pz - c[1]; dist = dx * n[0] + dz * n[1]; l = dx * lat[0] + dz * lat[1]
        if abs(l) > lat_half + 1.5 or dist < -3 or dist > 9 or py < y0 - 6 or py > y1 + 6: continue
        score = abs(dist - 2.0) + 0.05 * max(0, abs(l) - lat_half)
        if best is None or score < best[0]: best = (score, dist, l, n, c, lat)
    return best
by_key = {}
for i, p in enumerate(statics):
    if p.get("class") == "lego_prop" and "fireescape" in p["url"].lower(): by_key.setdefault((p["cell"], p["tag"]), []).append(i)
moved = dropped = kept = unmatched = 0; drop_idx = set()
for cell, r in fes:
    x, y, z = r["pos"]; pos0, _, _ = mat_to_pos_quat(yaw_matrix(r["pos"], r["yaw"]))
    cands = [i for i in by_key.get((cell, r["inst"]), []) if np.linalg.norm(np.array(statics[i]["pos"]) - np.array(pos0)) < 0.5]
    if not cands: unmatched += 1; continue
    i = cands[0]; b = best_face(x, y, z)
    if not b: dropped += 1; drop_idx.add(i); continue
    score, dist, l, n, c, lat = b
    # the prop's own x axis under the (negated) record yaw, in D3D xz: ring_axes gives glTF (x, z) -> D3D (x, -z)
    axg = ring_axes(r["yaw"])[0]; sx = (axg[0], -axg[1]); phi1 = math.degrees(math.atan2(-n[1], n[0]))
    yaw = phi1 if sx[0] * n[0] + sx[1] * n[1] >= 0 else phi1 + 180           # keep the record's mirror (which way the stairs run)
    npos = (c[0] + n[0] * 2.0 + lat[0] * l, y, c[1] + n[1] * 2.0 + lat[1] * l)
    if abs(dist - 2.0) < 0.05 and (yaw - r["yaw"]) % 360 < 0.5: kept += 1; continue
    pos, quat, scale = mat_to_pos_quat(yaw_matrix(npos, yaw)); statics[i]["pos"] = pos; statics[i]["quat"] = quat; statics[i]["scale"] = scale; statics[i]["fixed"] = "fireescape-snap"; moved += 1   # yaw here is a D3D face angle, applied with the D3D row-vector matrix: no extra sign
print(f"fire escapes: {len(fes)} records, {kept} already flush, {moved} snapped, {dropped} dropped (no wall within 9 m), {unmatched} not in stage.json")
if not DRY:
    shutil.copy2(stage_path, stage_path.with_suffix(".json.bak")); stage["statics"] = [p for i, p in enumerate(statics) if i not in drop_idx]; json.dump(stage, open(stage_path, "w")); print("stage.json updated (backup .json.bak)")
