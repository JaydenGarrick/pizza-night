"""Treyarch ENS (entity set / placements) parser.
Records start with class hash 0x7ace5bad followed (at +0x10) by the instance name. A record holds one or more 4x4
row-vector matrices; the world placement is the one with the world-scale translation (children have local offsets).
Mesh reference tokens: '<MESH>000' (uppercase + 3 digits), or a bare type name in the first record of a group."""
import struct, re
import numpy as np

MAGIC = bytes.fromhex("ad5bce7a")
UP_RE = re.compile(rb"[A-Z][A-Z0-9_]{2,30}")
LO_RE = re.compile(rb"[a-z][a-z0-9_]{2,30}")
SKIP = ("SIMPLE", "SPAWNPOINT", "MARK_", "TRIG_", "ROOFACCESS", "DOOR", "FRAME", "_ENTID", "WEB_", "ENT_")

def cstr(b): return b.split(b"\0")[0].decode("latin-1", "replace")

def _mat(ens, o):
    if o + 64 > len(ens): return None
    M = np.frombuffer(ens[o:o + 64], "<f4").reshape(4, 4)
    if M[3, 3] != 1.0 or M[0, 3] != 0 or M[1, 3] != 0 or M[2, 3] != 0 or not np.all(np.isfinite(M)): return None
    n = np.linalg.norm(M[:3, :3], axis=1)
    if not np.all(np.abs(n - 1) < 0.05) or not np.all(np.abs(M[3, :3]) < 1e5): return None
    return M.copy()

def parse_ens(ens, known_meshes=None):
    km = {k.lower() for k in known_meshes} if known_meshes else None
    starts = []
    i = ens.find(MAGIC, 0x20)
    while i != -1:
        nm = ens[i + 0x10: i + 0x30]
        if nm[:1].isalpha() and nm[0] < 0x80 and b"\0" in nm and all(32 <= c < 127 for c in nm.split(b"\0")[0]): starts.append(i)
        i = ens.find(MAGIC, i + 4)
    recs = []; cur_type = None; cur_skel = ""
    for k, r in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(ens)
        name = cstr(ens[r + 0x10: r + 0x30])
        mats = []
        for o in range(r + 0x30, end - 64, 4):
            M = _mat(ens, o)
            if M is not None: mats.append((o, M))
        if not mats: continue
        world = max(mats, key=lambda om: float(np.linalg.norm(om[1][3, :3])))[1]
        seg = ens[r + 0x30: end]
        ups = [t.decode() for t in UP_RE.findall(seg)]; los = [t.decode() for t in LO_RE.findall(seg)]
        typ = None; skel = "SIMPLE" if "SIMPLE" in ups else ""
        def strip_num(t):
            m = re.search(r"\d{2,3}$", t); return t[:m.start()] if m and len(t) - (len(t) - m.start()) > 3 else t
        if km is not None:                                   # an instance named after its own mesh (B10_I01FRONT, B10_SHEARSON)
            ent = name[4:] if name.upper().startswith("ENT_") else None       # ENT_F48I01_CHAIR02 -> F48I01_CHAIR
            for cand in (name, strip_num(name)) + ((ent, strip_num(ent)) if ent else ()):
                if cand and cand.lower() in km: typ = cand; break
        for t in (ups if typ is None else []):
            if t == name or t.startswith(SKIP): continue
            base = strip_num(t)
            if km is None or base.lower() in km: typ = base; break
        if typ is None and (ens[r + 0x0b] & 0x02):          # lowercase 'name000' tokens are the trailing instance table: never a light's type
            for t in los:
                base = t[:-3] if re.search(r"\d{3}$", t) and len(t) > 4 else t
                if km is not None and base.lower() in km: typ = base.upper(); break
        has_tokens = any(t != name for t in ups) or bool(los)
        if typ: cur_type, cur_skel = typ, skel
        # token-less records inherit the group's type only when they are numbered instances of it (B10_S_STRTLAMPB39 after S_STRTLAMPB);
        # lights, triggers, markers and other helper records (XB02_OMNI03 after XB02_FAKEFLOOR) must not become copies of the last mesh
        # class byte @+0x0b: bit 0x02 = mesh-bearing instance (0x92 props, 0x82 ENT_* pieces, 0xd2 script props); 0x90/0x80/0xd0 = lights,
        # spawn points, triggers.  Instance names are generic (B10_S_TRFFLITEA06 under a S_TRFFLITEC header), so the bit is the only safe test.
        inherit = cur_type if (not has_tokens and cur_type and (ens[r + 0x0b] & 0x02)) else None
        recs.append({"name": name, "type": typ if typ else inherit, "skel": skel or cur_skel, "M": world, "start": r, "end": end, "n_mats": len(mats)})
    return struct.unpack_from("<8I", ens, 0), recs


def parse_lights(ens):
    """class-0x90 records = placed omni lights: row-vector matrix @+0xa0 (position in row 3), RGBA colour @+0xe4,
    (inner radius, outer radius, intensity) @+0x104.  Returns D3D-space dicts."""
    out = []; i = ens.find(MAGIC, 0x20)
    while i != -1:
        if ens[i + 0x0b] == 0x90 and i + 0x114 <= len(ens):
            nm = cstr(ens[i + 0x10: i + 0x30]); M = np.frombuffer(ens[i + 0xa0: i + 0xe0], "<f4").reshape(4, 4); col = np.frombuffer(ens[i + 0xe4: i + 0xf4], "<f4"); f = np.frombuffer(ens[i + 0x104: i + 0x110], "<f4")
            if np.all(np.isfinite(M)) and np.all(np.isfinite(f)) and 0 < f[1] < 500 and 0 <= f[2] < 50:
                out.append({"name": nm, "pos": [float(x) for x in M[3, :3]], "color": [float(x) for x in col[:3]], "inner": float(f[0]), "outer": float(f[1]), "intensity": float(f[2])})
        i = ens.find(MAGIC, i + 4)
    return out
