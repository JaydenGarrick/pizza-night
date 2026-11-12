#!/usr/bin/env python3
"""Rasterise the XB_CITY low-LOD road network (CITY_GROUND road sub-meshes) to a grid and score straight routes from Joe's Pizza."""
import json, struct, numpy as np
G = open("public/models/xbox/static/CITY__city_ground.glb", "rb").read(); jl = struct.unpack_from("<I", G, 12)[0]; J = json.loads(G[20:20 + jl]); bin0 = 20 + jl + 8
def acc(i):
    a = J["accessors"][i]; bv = J["bufferViews"][a["bufferView"]]; off = bin0 + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    ct = {5126: ("<f4", 4), 5125: ("<u4", 4), 5123: ("<u2", 2)}[a["componentType"]]; n = {"VEC3": 3, "SCALAR": 1, "VEC2": 2}[a["type"]]
    return np.frombuffer(G, dtype=ct[0], count=a["count"] * n, offset=off).reshape(a["count"], n)
cells = set(); CS = 4.0
for m in J["meshes"]:
    for pr in m["primitives"]:
        mat = J["materials"][pr["material"]]["name"]
        if not any(k in mat for k in ("straight", "tee", "corner", "inter", "end_")): continue
        P = acc(pr["attributes"]["POSITION"]); I = acc(pr["indices"]).reshape(-1, 3) if "indices" in pr else np.arange(len(P)).reshape(-1, 3)
        for tri in I:
            a, b, c = P[tri[0]], P[tri[1]], P[tri[2]]
            n = int(max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b)) / 2.0) + 2      # ~2 m sampling, whatever the triangle size
            for u in np.linspace(0, 1, n):
                for v in np.linspace(0, 1 - u, max(2, int(n * (1 - u)) + 1)): q = a + u * (b - a) + v * (c - a); cells.add((int(np.floor(q[0] / CS)), int(np.floor(q[2] / CS))))
print(len(cells), "road cells of", CS, "m")
def is_road(x, z): return (int(np.floor(x / CS)), int(np.floor(z / CS))) in cells
door = (-250.5, 745.0)
runs = []
for x in range(-460, -40, 4):
    for z0 in (734, 730, 726, 722, 718, 714):
        if not is_road(x, z0): continue
        L = 0
        while L < 1500 and is_road(x, z0 - L): L += 4
        runs.append((L, x, z0)); break
runs.sort(reverse=True); print("northbound runs from the avenue (length m, x, z0):", runs[:10])
for z in (734, 730, 726, 722, 718):
    Lw = 0
    while Lw < 2200 and is_road(-250 - Lw, z): Lw += 4
    Le = 0
    while Le < 2200 and is_road(-250 + Le, z): Le += 4
    print(f"avenue z={z}: west {Lw} m, east {Le} m")
for L, x, z0 in runs[:4]:
    for z in (z0 - 100, z0 - 400, z0 - 700):
        xs = [xx for xx in range(x - 60, x + 61, 4) if is_road(xx, z)]; print(f"  street x={x}: at z={z} road x-range {min(xs) if xs else None}..{max(xs) if xs else None}")
json.dump({"cells": sorted(cells), "cs": CS}, open("public/pizza/roads.json", "w"))
