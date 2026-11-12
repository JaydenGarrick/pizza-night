#!/usr/bin/env python3
"""Batch-export every Xbox cutscene shot (XBSANIM, type 0x14) via xbox_export_cutscene.py and build
public/xbox_cutscenes/index.json: cutscenes = shots grouped by base name (AC87_CATFUN_03 -> AC87_CATFUN), in shot order,
with cumulative start times and the matching dialogue stream from intermediate/xbox/audio/scene/index.json.
usage: xbox_export_all_cutscenes.py [--force] [--only NAME_SUBSTR] [--index-only]"""
import sys, json, struct, subprocess, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xbpack import XBPack
args = sys.argv[1:]; force = "--force" in args; only = args[args.index("--only") + 1] if "--only" in args else None
index = json.load(open("intermediate/xbox/pack_index.json")); packs_dir = Path("intermediate/xbox/packs"); out_root = Path("public/xbox_cutscenes")
shots = sorted({(n, p) for p, ents in index.items() for n, t, o, s in ents if t == 0x14})
seen = set(); todo = []
for n, p in shots:
    if n in seen: continue
    seen.add(n); todo.append((p, n))
print(f"{len(todo)} shots in {len({n for n, p in shots})} unique names")
if "--index-only" not in args:
    t0 = time.time()
    for i, (p, n) in enumerate(todo):
        if only and only.lower() not in n.lower(): continue
        if not force and (out_root / n / "scene.json").exists(): continue
        r = subprocess.run([sys.executable, "-I", "tools/xbox_export_cutscene.py", f"{p}/{n}"], capture_output=True, text=True)
        tail = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "Warning" not in l and "conj()" not in l)
        print(f"[{i+1}/{len(todo)} {time.time()-t0:5.0f}s] {p}/{n} rc={r.returncode}\n{tail}", flush=True)
# ---- index
audio = {}
try: audio = {k.upper(): v for k, v in json.load(open("intermediate/xbox/audio/scene/index.json")).items()}
except Exception: pass
cuts = {}
for d in sorted(out_root.glob("*/scene.json")):
    sc = json.load(open(d)); name = sc["name"]
    m = re.fullmatch(r"(.+?)_(\d{1,3})", name); base, num = (m.group(1), int(m.group(2))) if m else (name, 0)
    cuts.setdefault(base, []).append({"name": name, "num": num, "pack": sc["pack"], "duration": sc["duration"], "actors": [a["name"] for a in sc["actors"]], "camera": bool(sc.get("camera"))})
lvl_map = {}
try: lvl_map = json.load(open(out_root / "levels.json"))
except Exception: pass
out = []
for base, lst in sorted(cuts.items()):
    lst.sort(key=lambda x: x["num"]); t = 0.0
    for s in lst: s["start"] = round(t, 4); t += s["duration"]
    a = audio.get(base.upper()); out.append({"name": base, "duration": round(t, 3), "shots": lst, "audio": a["file"] if a else None, "audio_seconds": a["seconds"] if a else None, "level": (lvl_map.get(base) or [None])[0], "levels": lvl_map.get(base) or []})
json.dump({"cutscenes": out}, open(out_root / "index.json", "w"), indent=1)
print(f"index: {len(out)} cutscenes, {sum(len(c['shots']) for c in out)} shots, {sum(1 for c in out if c['audio'])} with audio")
