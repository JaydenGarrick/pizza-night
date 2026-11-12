"""Measure forward speed (m/s) of each gameplay clip from a root-motion export of spidey_loco (trajectory node translation over the clip),
plus the net yaw of turn clips -> public/models/xbox/anim/spidey_loco_speeds.json.  usage: measure_loco_speeds.py <root-motion.glb>"""
import sys, json, struct, math
import numpy as np
d = open(sys.argv[1], "rb").read(); ln = struct.unpack_from("<I", d, 12)[0]; j = json.loads(d[20:20 + ln]); off = 20 + ln; cl = struct.unpack_from("<I", d, off)[0]; b = d[off + 8: off + 8 + cl]
def acc(i):
    a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]; ct = {5126: "f4", 5121: "u1", 5123: "u2", 5125: "u4"}[a["componentType"]]; n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    return np.frombuffer(b, dtype=ct, count=a["count"] * n, offset=bv.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(a["count"], n)
nodes = j["nodes"]; out = {}
for an in j["animations"]:
    tr = rot = tm = None
    for ch in an["channels"]:
        if nodes[ch["target"]["node"]].get("name") != "trajectory": continue
        s = an["samplers"][ch["sampler"]]; t = acc(s["input"])[:, 0]; v = acc(s["output"])
        if ch["target"]["path"] == "translation": tr, tm = v, t
        elif ch["target"]["path"] == "rotation": rot = v
    if tr is None: continue
    dur = float(tm[-1] - tm[0]) if len(tm) > 1 else 0.0; dp = tr[-1] - tr[0]
    def yaw(q):  # rotation of +Z about Y
        x, y, z, w = q; fx = 2 * (x * z + w * y); fz = 1 - 2 * (x * x + y * y); return math.degrees(math.atan2(fx, fz))
    dyaw = (yaw(rot[-1]) - yaw(rot[0]) + 540) % 360 - 180 if rot is not None else 0.0
    horiz = float(math.hypot(dp[0], dp[2]))
    out[an["name"]] = {"duration": round(dur, 3), "dist": round(horiz, 3), "speed": round(horiz / dur, 3) if dur > 0 else 0.0, "rise": round(float(dp[1]), 3), "yaw": round(dyaw, 1)}
json.dump(out, open("public/models/xbox/anim/spidey_loco_speeds.json", "w"), indent=1)
for k, v in out.items(): print(f"{k:24s} {v['duration']:5.2f}s  {v['dist']:6.2f} m  {v['speed']:6.2f} m/s  rise {v['rise']:6.2f}  yaw {v['yaw']:7.1f}")
