#!/usr/bin/env python3
"""Extract real-time cutscene data (SceneManager camera paths, scripted sequences, pawns) from a .whr map to JSON.
usage: extract_scenes.py MAP.whr [--out public/cutscenes/<map>.json]"""
import sys, json, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue2.package import PackageSet, ObjRef
from ue2.props import object_props, RawArray

args = sys.argv[1:]
out = None
if "--out" in args: i = args.index("--out"); out = args[i + 1]; del args[i:i + 2]
map_path = Path(args[0]).resolve(); root = map_path.parents[1]
pset = PackageSet([root]); pkg = pset.open(map_path)

OBJ_ARRAYS = {"actions", "subactions", "skins", "touching", "attachments"}
def clean(v, key=""):
    if isinstance(v, ObjRef): return v.full if v else None
    if isinstance(v, RawArray):
        if key.lower() in OBJ_ARRAYS: return [o.full if o else None for o in v.objs()]
        return {"_array": v.count}
    if isinstance(v, (tuple, list)): return [clean(x) for x in v]
    if isinstance(v, dict): return {k: clean(x, k) for k, x in v.items()}
    if isinstance(v, bytes): return v.hex()
    return v

SKIP = ("Level", "Region", "PhysicsVolume", "HeadVolume", "ColLocation")
def props_of(export):
    p, _, _ = object_props(pkg, export)
    return {k: clean(v, k) for k, v in p.items() if k not in SKIP}

def obj(ref_name):
    if not ref_name: return None
    return pkg.export_by_name(str(ref_name).split(".")[-1])

subs = {}
sub_file = root / "System" / "Subtitles.int"
if sub_file.exists():
    for line in sub_file.read_text("latin-1").splitlines():
        if "=" in line and not line.startswith("["):
            k, _, v = line.partition("="); subs[k.strip().lower()] = v.strip()

def decode_action(name):
    e = obj(name)
    if not e: return {"name": name}
    d = {"class": e.cls, "name": e.name}; d.update(props_of(e))
    ip = d.get("IntPoint")
    if ip:
        ipe = obj(ip)
        if ipe:
            ipp = props_of(ipe)
            d["IntPointData"] = {"name": ipe.name, **{k: v for k, v in ipp.items() if k != "Tag"}}
    if d.get("SubActions"):
        d["SubActions"] = [({"class": obj(s).cls, **props_of(obj(s))} if obj(s) else {"name": s}) for s in d["SubActions"]]
    dlg = d.get("dlgName")
    if dlg: d["subtitle"] = subs.get(str(dlg).lower())
    return d

scenes = []
for e in pkg.exports_of_class("SceneManager"):
    d = {"name": e.name}; d.update(props_of(e))
    d["actions"] = [decode_action(a) for a in (d.pop("Actions", None) or [])]
    scenes.append(d)

sequences = []
for e in pkg.exports_of_class("TriggeredScriptedSequence", "ScriptedSequence", "ScriptedTrigger", "WebheadScriptedSequence"):
    d = {"class": e.cls, "name": e.name}; d.update(props_of(e))
    d["actions"] = [decode_action(a) for a in (d.pop("Actions", None) or [])]
    sequences.append(d)

pawns = []
for e in pkg.exports:
    if e.cls.lower().endswith("pawn") and not e.cls.lower().startswith("action"):
        d = {"class": e.cls, "name": e.name}; d.update(props_of(e)); pawns.append(d)

points = {e.name: {"class": e.cls, **props_of(e)} for e in pkg.exports_of_class("InterpolationPoint", "LookTarget", "PathNode", "Teleporter", "PlayerStart", "Trigger", "Counter", "Spawner", "HostageSpawner", "AIMarker", "WebSwingPoint")}
movies = [{"name": e.name, **props_of(e)} for e in pkg.exports_of_class("ACTION_PlayMovie")]

report = {"map": pkg.name, "scenes": scenes, "sequences": sequences, "pawns": pawns, "points": points, "movies": movies}
out = Path(out) if out else Path("public/cutscenes") / f"{pkg.name}.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=1, default=str))
print(f"{pkg.name}: {len(scenes)} scenes, {len(sequences)} sequences, {len(pawns)} pawns, {len(points)} points -> {out}")

def dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
for s in scenes:
    prev = None; line = []
    for a in s["actions"]:
        ipd = a.get("IntPointData")
        if not ipd or "Location" not in ipd: continue
        loc = ipd["Location"]
        if prev and a.get("PathLength") is not None and a["class"] == "ActionMoveCamera":
            sd = dist(prev, loc); pl = a["PathLength"]
            line.append(f"{a['name']}: PathLength={pl:.0f} straight={sd:.0f} ratio={pl / sd if sd else 0:.2f} dur={a.get('Duration')} style={a.get('PathStyle')}")
        prev = loc
    if line: print(f"  [{s['name']} tag={s.get('Tag')}] " + " ; ".join(line[:3]))
