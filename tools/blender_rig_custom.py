"""Rig a custom character mesh to an exported SM2 skeleton so it can play the original clips.

usage (headless):
  Blender -b --python tools/blender_rig_custom.py -- --skeleton public/models/characters/spideymesh.glb \
          --custom path/to/your_model.glb|.fbx|.obj --out public/models/characters/custom_hero.glb [--fit height]

What it does: imports the SM2 GLB (armature + clips), imports your mesh, optionally scales it to the SM2 character's
height and drops it so the feet match, deletes the original SM2 mesh, parents your mesh to the SM2 armature with
automatic weights, and exports a GLB carrying the armature, your mesh and all animation clips.
Your model should be roughly in an A/T-pose facing -Z (glTF forward) for the auto-weights to make sense.
"""
import bpy, sys, os, math
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default
skel_path = opt("--skeleton"); custom_path = opt("--custom"); out_path = opt("--out", "custom_rigged.glb"); fit = opt("--fit", "height")

bpy.ops.wm.read_factory_settings(use_empty=True)
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)   # Blender 5 may keep a default mesh
bpy.ops.import_scene.gltf(filepath=skel_path)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
arm.data.pose_position = "REST"                 # weight/bind against the rest pose, not whatever the NLA stack evaluates to
if arm.animation_data:
    for tr in arm.animation_data.nla_tracks: tr.mute = True
    arm.animation_data.action = None
bpy.context.view_layer.update()
orig_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
# original character bounds (world space) for fitting
def bounds(objs):
    import mathutils
    pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
    lo = [min(p[i] for p in pts) for i in range(3)]; hi = [max(p[i] for p in pts) for i in range(3)]
    return lo, hi
olo, ohi = bounds(orig_meshes)
before = set(bpy.data.objects)
ext = os.path.splitext(custom_path)[1].lower()
if ext in (".glb", ".gltf"): bpy.ops.import_scene.gltf(filepath=custom_path)
elif ext == ".fbx": bpy.ops.import_scene.fbx(filepath=custom_path)
elif ext == ".obj": bpy.ops.wm.obj_import(filepath=custom_path)
else: raise SystemExit("unsupported custom model format " + ext)
new = [o for o in bpy.data.objects if o not in before]
new_meshes = [o for o in new if o.type == "MESH"]
# drop any armature that came with the custom model (we re-rig to SM2 bones)
for o in new:
    if o.type == "ARMATURE":
        for m in new_meshes:
            if m.parent == o: m.parent = None; m.matrix_world = m.matrix_world
            for mod in list(m.modifiers):
                if mod.type == "ARMATURE": m.modifiers.remove(mod)
        bpy.data.objects.remove(o)
bpy.ops.object.select_all(action="DESELECT")
for m in new_meshes: m.select_set(True)
bpy.context.view_layer.objects.active = new_meshes[0]
if len(new_meshes) > 1: bpy.ops.object.join()
custom = bpy.context.view_layer.objects.active
custom.name = "CustomMesh"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if fit == "height":
    clo, chi = bounds([custom])
    s = (ohi[2] - olo[2]) / max(chi[2] - clo[2], 1e-6)
    custom.scale = (s, s, s); bpy.ops.object.transform_apply(scale=True)
    clo, chi = bounds([custom])
    custom.location.z += olo[2] - clo[2]
    custom.location.x += (olo[0] + ohi[0]) / 2 - (clo[0] + chi[0]) / 2
    custom.location.y += (olo[1] + ohi[1]) / 2 - (clo[1] + chi[1]) / 2
    bpy.ops.object.transform_apply(location=True)
for o in orig_meshes: bpy.data.objects.remove(o)
bpy.ops.object.select_all(action="DESELECT")
custom.select_set(True); arm.select_set(True); bpy.context.view_layer.objects.active = arm
try:
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
except Exception as ex:
    print("auto weights raised:", ex)
if not any(g for g in custom.vertex_groups if any(True for v in custom.data.vertices for ge in v.groups if ge.group == g.index and ge.weight > 0)):
    print("automatic weights failed -> nearest-bone fallback")
    import mathutils
    for g in list(custom.vertex_groups): custom.vertex_groups.remove(g)
    if custom.parent != arm:
        custom.parent = arm; custom.matrix_parent_inverse = arm.matrix_world.inverted()
    if not any(m.type == "ARMATURE" for m in custom.modifiers):
        mod = custom.modifiers.new("Armature", "ARMATURE"); mod.object = arm
    import re
    HELPER = re.compile(r"(_RF$|CONT|CONTROL|auto_sca|twist|conn|breather|RootParent|_ball|_toe|jaw|fingers|thumb|index|middle|ring|pinky)", re.I)
    bones = [b for b in arm.data.bones if b.use_deform and not HELPER.search(b.name)]
    segs = [(b.name, arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local) for b in bones]
    groups = {n: custom.vertex_groups.new(name=n) for n, _, _ in segs}
    def seg_dist(p, a, b):
        ab = b - a; L = ab.length_squared
        t = 0.0 if L < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / L))
        return (p - (a + ab * t)).length
    for v in custom.data.vertices:
        wp = custom.matrix_world @ v.co
        d = sorted(((seg_dist(wp, a, b), n) for n, a, b in segs), key=lambda x: x[0])[:2]
        if len(d) == 2 and d[1][0] > 0 and d[1][0] < d[0][0] * 1.5:
            w0 = 1.0 / max(d[0][0], 1e-4); w1 = 1.0 / max(d[1][0], 1e-4); t = w0 + w1
            groups[d[0][1]].add([v.index], w0 / t, "REPLACE"); groups[d[1][1]].add([v.index], w1 / t, "REPLACE")
        else:
            groups[d[0][1]].add([v.index], 1.0, "REPLACE")
if arm.animation_data:
    for tr in arm.animation_data.nla_tracks: tr.mute = False
arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB", use_selection=True, export_animations=True, export_skins=True, export_yup=True, export_apply=False)
print(f"RIGGED -> {out_path}: bones={len(arm.data.bones)} clips={len(bpy.data.actions)} verts={len(custom.data.vertices)}")
