#!/usr/bin/env python3
"""Build dist/ for the hosted site with Pizza Night in America (pizzanight.html) as the front page.

Starts from an empty dist/, copies what pizzanight.html fetches and points index.html at it.  The geometry gate (tools/verify_geometry.mjs)
loads /pizzanight.html from dist/ and from the live site.

The file list is tools/pizzanight_manifest.txt.  Re-collect it after adding assets, from the dev server's request log, NOT from the browser's
performance resource entries: that buffer stops at 250 entries and this game loads more, which silently drops the last models loaded (the first
attempt shipped a bundle with no vehicles).  Start server.py with its output going to a file, load /pizzanight.html once in a fresh browser profile
and start a run (tools/shot.mjs does both), then keep every path the log shows as "GET <path> ... 200".  Afterwards serve dist/ and load / to confirm
the game starts: a missing file stops the page from becoming ready.
"""
import re, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; DIST = ROOT / "dist"; MAN = Path(__file__).resolve().parent / "pizzanight_manifest.txt"
PAGE = "/pizzanight.html"; LOCK_SPOT = "joes"; VENDOR = ("/node_modules/", "/vendor/")   # Cloudflare Pages refuses node_modules/: served as /vendor/
if DIST.exists(): shutil.rmtree(DIST)
page = (ROOT / PAGE.lstrip("/")).read_text()
files = {l.strip().split("?")[0] for l in MAN.read_text().splitlines() if l.strip().startswith("/") and not l.strip().endswith("favicon.ico")} | {PAGE}
files |= {f"/public/ui/{n}.png" for n in re.findall(r"UI\('([^']+)'", page)}                 # HUD icons drawn as CSS backgrounds
files |= {u for u in re.findall(r"url\((/public/[^)'\"]+)\)", page) if "$" not in u}                                 # textures named in the style sheet
files |= set(re.findall(r"new Audio\('([^']+)'", page))
files |= set(re.findall(r'<script src="(/[^"]+)"', page))                                # classic scripts (the QR generator)
files |= set(re.findall(r"'(/public/video/[^']+\.mp4)'", page))                              # the intro and outro films: fetched when they play                                      # music
files |= {f"/intermediate/audio/sfx/{n}.wav" for n in re.findall(r"'([A-Za-z0-9_]+)'", re.search(r"const SFX_NAMES = \{(.*?)\};", page).group(1))}   # sound effects: fetched on the first key / touch
files |= {f"/public/ui/fonts/{p.stem}.json" for p in (ROOT / "public/ui/fonts").glob("FontNeuzeit*.json")} | {f"/public/ui/{p.stem}.png" for p in (ROOT / "public/ui/fonts").glob("FontNeuzeit*.json")}   # the body font: one size per device ratio
added = 0; tot = 0; missing = []
for u in sorted(files):
    src = ROOT / u.lstrip("/")
    if not src.is_file(): missing.append(u); continue
    dst = DIST / u.replace(*VENDOR).lstrip("/"); new = not dst.exists(); dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix in (".html", ".js", ".mjs", ".json") and VENDOR[0] in src.read_text(errors="ignore"):
        txt = src.read_text().replace(VENDOR[0], VENDOR[1])
        if u == PAGE and LOCK_SPOT:   # the hosted build ignores ?spot= and always plays the waterfront
            key = "const SPOT = SPOTS[q.get('spot')] || SPOTS.joes;"; assert key in txt, "spot line moved"; txt = txt.replace(key, f"const SPOT = SPOTS.{LOCK_SPOT};   /* hosted build: locked to the waterfront (tools/bundle_pizzanight.py LOCK_SPOT) */")
        dst.write_text(txt)
    else: shutil.copy2(src, dst)
    if new: added += 1; tot += src.stat().st_size
(DIST / "index.html").write_text(f'<!doctype html><meta http-equiv="refresh" content="0; url={PAGE}">')
(DIST / "_headers").write_text("/*\n  Cache-Control: public, max-age=3600\n/public/models/*\n  Cache-Control: public, max-age=604800, immutable\n")
if missing: print("MISSING:", missing); sys.exit(1)
size = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
print(f"dist/: + {len(files)} pizzanight files ({tot/1e6:.0f} MB); total {size/1e6:.0f} MB; index -> {PAGE}")
