"""UE2 UMeshAnimation (with UE2.5 FlexTrack compressed tracks)."""
import math
from .props import object_props


def _restore_w(x, y, z):
    w2 = 1.0 - (x * x + y * y + z * z)
    return math.sqrt(w2) if w2 > 0 else 0.0


def _q48(v):
    x = (v[0] - 32767) / 32767.0; y = (v[1] - 32767) / 32767.0; z = (v[2] - 32767) / 32767.0
    return (x, y, z, _restore_w(x, y, z))


def _track(r):
    flags = r.u32()
    kq = r.array_packed("<4f"); kp = r.array_packed("<3f"); kt = r.array_packed("<f")
    return {"flags": flags, "quat": kq, "pos": kp, "time": [t[0] for t in kt]}


def _flex_track(r):
    ttype = r.i32()
    if ttype == 0:
        return {"flags": 0, "quat": [], "pos": [], "time": [], "flex": 0}
    if ttype == 1:    # FlexTrackStatic: one quat (96 no W) + one pos
        x, y, z = r.f32(), r.f32(), r.f32()
        q = (x, y, z, _restore_w(x, y, z)); p = r.vec()
        return {"flags": 0, "quat": [q], "pos": [p], "time": [], "flex": 1}
    if ttype == 3:    # FlexTrack48: quats, positions, times(int16)
        kq = [_q48(v) for v in r.array_packed("<3H")]; kp = r.array_packed("<3f"); kt = [t[0] for t in r.array_packed("<h")]
        return {"flags": 0, "quat": kq, "pos": kp, "time": kt, "flex": 3}
    if ttype == 4:    # FlexTrack48RotOnly: quats, times, single pos
        kq = [_q48(v) for v in r.array_packed("<3H")]; kt = [t[0] for t in r.array_packed("<h")]; p = r.vec()
        return {"flags": 0, "quat": kq, "pos": [p], "time": kt, "flex": 4}
    raise ValueError(f"unknown FlexTrack type {ttype}")


def load_anim(pkg, export):
    props, r, end = object_props(pkg, export)
    a = {"name": export.name, "props": props}
    a["version"] = r.i32()
    a["bones"] = [(pkg.names[r.idx()], r.u32(), r.i32()) for _ in range(r.idx())]
    moves = []
    for _ in range(r.idx()):
        mc = {"root_speed": r.vec(), "track_time": r.f32(), "start_bone": r.i32(), "flags": r.u32()}
        mc["bone_indices"] = [x[0] for x in r.array_packed("<i")]
        mc["tracks"] = [_track(r) for _ in range(r.idx())]
        mc["root_track"] = _track(r)
        if mc["flags"] >= 3:
            flex = [_flex_track(r) for _ in range(r.idx())]
            if flex:
                mc["tracks"] = flex
        moves.append(mc)
    a["moves"] = moves
    seqs = []
    for _ in range(r.idx()):
        s = {}
        if pkg.version >= 115: s["f28"] = r.f32()
        s["name"] = pkg.names[r.idx()]
        s["groups"] = [pkg.names[r.idx()] for _ in range(r.idx())]
        s["start_frame"] = r.i32(); s["num_frames"] = r.i32()
        notifies = []
        for _ in range(r.idx()):
            t = r.f32(); fn = pkg.names[r.idx()]
            obj = pkg.ref(r.idx()) if pkg.version >= 112 else None
            notifies.append((t, fn, obj))
        s["notifies"] = notifies
        s["rate"] = r.f32()
        seqs.append(s)
    a["sequences"] = seqs
    a["tail_bytes"] = end - r.tell()
    return a
