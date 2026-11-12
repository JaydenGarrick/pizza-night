"""Export the game's COLL collision hulls (pack type 0x12) as GLBs: public/models/xbox/coll/<PACK>__<mesh>.glb (one per mesh, all its
000/001/... hulls merged, D3D -> glTF handedness like the render meshes) + public/models/xbox/coll/index.json {"<PACK>/<MESH>": url, ...}.
A level's stage.json placements reference meshes as "<PACK>.<MESH>"; the viewer looks up the hull by that key and applies the same transform."""
import sys, json, re, collections
from pathlib import Path
import numpy as np
sys.path.insert(0, "tools")
from xbpack import XBPack
from xbox.coll import parse
from ue2.gltf import GLB
index = json.load(open("intermediate/xbox/pack_index.json")); packs_dir = Path("intermediate/xbox/packs"); out_dir = Path("public/models/xbox/coll"); out_dir.mkdir(parents=True, exist_ok=True)
R = np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float64); cvt = lambda v: (R @ np.asarray(v, dtype=np.float64).T).T
groups = collections.defaultdict(list)
for pk, ents in index.items():
    for n, t, o, s in ents:
        if t == 0x12:
            m = re.match(r"^(.*?)(\d{3})$", n)
            groups[(pk, (m.group(1) if m else n).upper())].append(n)
out = {}; nverts = 0
for (pk, mesh), names in sorted(groups.items()):
    try: P = XBPack((packs_dir / f"{pk}.pack").read_bytes())
    except Exception: continue
    V, T, base = [], [], 0
    for n in sorted(names):
        c = parse(P.resource(n, 0x12))
        if not len(c["tris"]): continue
        V.append(cvt(c["verts"]).astype(np.float32)); T.append(c["tris"] + base); base += len(c["verts"])
    if not V: continue
    V = np.concatenate(V); T = np.concatenate(T); nverts += len(V)
    glb = GLB(); mi = glb.material("coll", None, None, True); glb.j["materials"][mi]["extras"] = {"collision": True, "hulls": len(names)}
    prim = {"attributes": {"POSITION": glb.accessor(V, 34962, minmax=True)}, "indices": glb.accessor(T[:, [0, 2, 1]].astype(np.uint32).flatten(), 34963), "material": mi, "mode": 4}
    glb.j["meshes"].append({"name": f"{mesh}_COLL", "primitives": [prim]}); nd = glb.node(name=f"{mesh}_COLL", mesh=0); glb.j["scenes"][0]["nodes"] = [nd]
    url = f"/public/models/xbox/coll/{pk}__{mesh.lower()}.glb"; glb.write(out_dir / f"{pk}__{mesh.lower()}.glb"); out[f"{pk}/{mesh}"] = url
json.dump(out, open(out_dir / "index.json", "w"), indent=0); print(len(out), "collision GLBs,", nverts, "vertices")
