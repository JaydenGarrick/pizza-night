#!/usr/bin/env python3
"""Build public/pizza/route.json: a multi-leg swing route through XB_CITY (three.js coords) that follows real roads from Joe's Pizza.
Legs: east along the waterfront avenue to the first long cross street, north up that street, then along the longest road at its end.
Anchors every 34 m (alternating sides), heights from the roofs beside the road, ground from the kerb street lamps (lamp origin is 6.73 m up)."""
import json, math
from pathlib import Path
import numpy as np
st = json.load(open("public/levels/XB_CITY/stage.json"))["statics"]
roads = json.load(open("public/pizza/roads.json")); CS = roads["cs"]; cells = set(map(tuple, roads["cells"]))
def road(x, z): return (int(math.floor(x / CS)), int(math.floor(z / CS))) in cells
def run(x, z, dx, dz, cap=1500):
    L = 0
    while L < cap and road(x + dx * L, z + dz * L): L += 4
    return L
DOOR = [-247.5, 0.0, 733.0]   # sidewalk 2 m outside the south-face entrance (door quad x -248.5..-246.5, z 735.3)
# greedy road tour: start east along the avenue; at each cross street with a long perpendicular run, turn (never back), until ~1000 m
heading = (1, 0); total = 0.0; TARGET = 1100.0
# avenue centreline in front of the pizzeria: contiguous road span across z at x = -200
lo = 0
while lo > -60 and road(-200, 726 + lo - 4): lo -= 4
hi = 0
while hi < 60 and road(-200, 726 + hi + 4): hi += 4
Z_AVE = 726 + (lo + hi) / 2.0; W = [(-238.0, Z_AVE)]; print("avenue centre z", Z_AVE, "span", 726 + lo, 726 + hi)
def centre_of_cross(x, z, d):          # centre line of the perpendicular street through (x,z) heading d: scan sideways for road extent
    px, pz = -d[1], d[0]; lo = 0
    while lo > -40 and road(x + px * (lo - 4), z + pz * (lo - 4)): lo -= 4
    hi = 0
    while hi < 40 and road(x + px * (hi + 4), z + pz * (hi + 4)): hi += 4
    return (lo + hi) / 2.0
for leg in range(6):
    x0, z0 = W[-1]; dx, dz = heading
    straight = run(x0, z0, dx, dz); minLeg = 120 if leg == 0 else 320
    cands = []
    for sdist in range(minLeg, min(int(straight) - 20, 520), 4):            # cross streets along the current heading
        x, z = x0 + dx * sdist, z0 + dz * sdist
        for turn in ((-dz, dx), (dz, -dx)):
            L = run(x, z, turn[0], turn[1])
            if L >= 350: cands.append((L, sdist, turn))
    if not cands or total + minLeg >= TARGET:
        Lend = min(straight - 20, max(60, TARGET - total)); W.append((x0 + dx * Lend, z0 + dz * Lend)); total += Lend; break
    L, sdist, turn = max(cands)
    cx, cz = x0 + dx * sdist, z0 + dz * sdist
    # centre the corner on the cross street: 60 m down the new heading, scan along the old heading for the contiguous road span
    px, pz = cx + turn[0] * 60, cz + turn[1] * 60; lo = 0
    while lo > -60 and road(px + dx * (lo - 4), pz + dz * (lo - 4)): lo -= 4
    hi = 0
    while hi < 60 and road(px + dx * (hi + 4), pz + dz * (hi + 4)): hi += 4
    off = (lo + hi) / 2.0; cx, cz = cx + dx * off, cz + dz * off
    W.append((cx, cz)); total += sdist; heading = turn
    if total >= TARGET: break
print("waypoints:", [(round(a), round(b)) for a, b in W], "total", round(total))
lamps = [p["pos"] for p in st if "strtlamp" in p["url"]]
def ground_at(x, z):
    near = sorted(lamps, key=lambda l: (l[0] - x) ** 2 + (l[2] - z) ** 2)[:3]
    return (sum(l[1] for l in near) / 3 - 6.73) if near and (near[0][0] - x) ** 2 + (near[0][2] - z) ** 2 < 60 ** 2 else 0.0
def roof(x, z, nrm, side):
    best = None
    for p in st:
        px, py, pz = p["pos"]; lat = ((px - x) * nrm[0] + (pz - z) * nrm[1]) * side; d2 = (px - x) ** 2 + (pz - z) ** 2
        if d2 < 45 ** 2 and 10 < lat < 50 and py > (best or -1e9): best = py
    return best
legs = []
for i in range(len(W) - 1):
    (x0, z0), (x1, z1) = W[i], W[i + 1]; L = math.hypot(x1 - x0, z1 - z0); d = ((x1 - x0) / L, (z1 - z0) / L); n = (-d[1], d[0])
    legs.append({"c0": [x0, z0], "dir": [round(d[0], 4), round(d[1], 4)], "nrm": [round(n[0], 4), round(n[1], 4)], "length": round(L, 1)})
anchors = []; s_total = 0.0; side = 1; s = 18.0
cum = [0.0]
for lg in legs: cum.append(cum[-1] + lg["length"])
total = cum[-1]
while s < total - 10:
    li = max(i for i in range(len(legs)) if cum[i] <= s); lg = legs[li]; sl = s - cum[li]
    x = lg["c0"][0] + lg["dir"][0] * sl + lg["nrm"][0] * side * 4; z = lg["c0"][1] + lg["dir"][1] * sl + lg["nrm"][1] * side * 4
    g = ground_at(x, z); r = roof(x, z, lg["nrm"], side); h = max(g + 22, min(g + 26, (r if r is not None else g + 24)))
    anchors.append({"anchor": [round(x, 2), round(h, 2), round(z, 2)], "ground": round(g, 2), "leg": li}); s += 34; side = -side
end = legs[-1]; ex = end["c0"][0] + end["dir"][0] * end["length"]; ez = end["c0"][1] + end["dir"][1] * end["length"]
deliver = [round(ex + end["nrm"][0] * 9, 2), round(ground_at(ex, ez), 2), round(ez + end["nrm"][1] * 9, 2)]
customer = [round(ex + end["nrm"][0] * 10.5 + end["dir"][0] * 2, 2), deliver[1], round(ez + end["nrm"][1] * 10.5 + end["dir"][1] * 2, 2)]
route = {"level": "XB_CITY", "door": [DOOR[0], round(ground_at(DOOR[0], DOOR[2]), 2), DOOR[2]], "waypoints": W, "legs": legs, "anchors": anchors, "deliver": deliver, "customer": customer,
         "pizzeria": {"level": "XB_PIZZERIA", "peter": [-260.5, 0.0, 740.3], "aziz": [-260.5, 0.0, 744.0], "counter": [-260.5, 1.0, 742.2]}}
Path("public/pizza").mkdir(exist_ok=True); json.dump(route, open("public/pizza/route.json", "w"), indent=1)
print(len(anchors), "anchors over", round(total), "m;", len(legs), "legs; ground door", route["door"][1], "deliver", deliver, "heights", [a["anchor"][1] - a["ground"] for a in anchors][:6])
