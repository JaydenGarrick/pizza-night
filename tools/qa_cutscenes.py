#!/usr/bin/env python3
"""QA sweep for Xbox cutscenes: render every cutscene (xbscene.html, no level) at 25/50/75 % of its length, record which shot was
active and how many triangles were drawn (0 = nothing in view), write shots/qa/summary.json and contact sheets shots/qa/sheet_N.png.
usage: qa_cutscenes.py [--only SUBSTR] [--level XB_CITY] [--limit N]"""
import json, subprocess, sys, re
from pathlib import Path
from PIL import Image, ImageDraw
args = sys.argv[1:]; only = args[args.index("--only") + 1] if "--only" in args else None
level = args[args.index("--level") + 1] if "--level" in args else None; limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 999
idx = json.load(open("public/xbox_cutscenes/index.json")); out = Path("shots/qa"); out.mkdir(parents=True, exist_ok=True)
summary = []
for c in idx["cutscenes"][:limit]:
    if only and only.lower() not in c["name"].lower(): continue
    steps = []
    for k, f in enumerate((0.25, 0.5, 0.75)):
        t = round(c["duration"] * f, 2)
        # in-view test: project every visible actor's pelvis into clip space; count those inside the frustum
        js = ("(()=>{document.getElementById('ui').classList.add('hidden'); window.__sm2.frame(%s); const S=window.__sm2.S; const sh=S.tl.shots[S.active]; const cam=window.__sm2.camera; "
              "let vis=0, inview=0; window.__sm2.scene.traverse(o=>{ if(o.name==='trajectory' && o.visible){ let p=o; let ok=true; while(p){ if(!p.visible){ok=false;break;} p=p.parent;} if(!ok) return; vis++; "
              "const pts=[o]; const h=o.parent && o.parent.getObjectByName('bip01_head'); if(h) pts.push(h); let hit=false; for(const q of pts){ const v=new o.position.constructor(); q.getWorldPosition(v); v.project(cam); if(Math.abs(v.x)<1.1 && Math.abs(v.y)<1.1 && v.z<1) hit=true; } if(hit) inview++; } }); "
              "return JSON.stringify({t:%s, shot: sh.name, actors: sh.actors.length, vis, inview, cam: !!sh.camera});})()") % (t, t)
        steps.append({"eval": js, "settle": 700, "out": f"shots/qa/{c['name']}_{k}.png"})
    lvl = level or c.get("level") or ""                               # per-cutscene level from the index (interiors) unless overridden
    url = f"http://127.0.0.1:8790/xbscene.html?scene={c['name']}" + (f"&level={lvl}" if lvl else "&level=none")
    r = subprocess.run(["node", "tools/shot.mjs", url, f"shots/qa/{c['name']}_0.png", "--settle", "45000" if lvl == "XB_CITY" else "14000", "--steps", json.dumps(steps)], capture_output=True, text=True)
    evals = [json.loads(m.group(1)) for m in re.finditer(r"eval → (\{.*\})", r.stdout)]
    rec = {"name": c["name"], "duration": c["duration"], "shots": len(c["shots"]), "audio": bool(c["audio"]), "level": lvl, "samples": evals, "ok": r.returncode == 0 and len(evals) == 3}
    summary.append(rec); print(c["name"], "ok" if rec["ok"] else "FAIL", [(e["shot"], f"{e['inview']}/{e['vis']}", "cam" if e["cam"] else "follow") for e in evals], flush=True)
json.dump(summary, open(out / "summary.json", "w"), indent=1)
# contact sheets: one row per cutscene, 3 thumbs
rows = [s for s in summary if s["ok"]]; W, H = 320, 194; per = 10
for si in range(0, len(rows), per):
    chunk = rows[si:si + per]; sheet = Image.new("RGB", (3 * W + 260, len(chunk) * H), (20, 22, 28)); d = ImageDraw.Draw(sheet)
    for ri, s in enumerate(chunk):
        d.text((8, ri * H + 8), f"{s['name']}\n{s['duration']:.0f}s {s['shots']} shots\n{'audio' if s['audio'] else 'no audio'}\n{s.get('level','')}", fill=(230, 230, 230))
        for k in range(3):
            try: im = Image.open(out / f"{s['name']}_{k}.png").convert("RGB").resize((W, H)); sheet.paste(im, (260 + k * W, ri * H))
            except Exception: pass
            e = s["samples"][k]; d.text((260 + k * W + 6, ri * H + 4), f"{e['shot']} t={e['t']} in view {e['inview']}/{e['vis']} {'cam' if e['cam'] else 'follow'}", fill=(255, 220, 90))
    sheet.save(out / f"sheet_{si // per:02d}.png")
bad = [s["name"] for s in rows if all(e["inview"] == 0 and e["vis"] > 0 for e in s["samples"])]
print(f"{len(rows)}/{len(summary)} cutscenes rendered; no actor in view at any sample: {len(bad)} {bad}")
