"""Decimate a mesh GLB/OBJ to a target triangle count (keeps UVs + textures).
usage: Blender -b --python tools/blender_decimate.py -- --in model.glb --out low.glb --tris 600 [--flat]"""
import bpy, sys, os
argv = sys.argv[sys.argv.index("--") + 1:]
def opt(f, d=None): return argv[argv.index(f) + 1] if f in argv else d
src = opt("--in"); dst = opt("--out", "lowpoly.glb"); tris = int(opt("--tris", "600")); flat = "--flat" in argv
bpy.ops.wm.read_factory_settings(use_empty=True)
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
if src.lower().endswith(".obj"): bpy.ops.wm.obj_import(filepath=src)
else: bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
bpy.ops.object.select_all(action="DESELECT")
for m in meshes: m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1: bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
before = len(obj.data.polygons)
weld = float(opt("--weld", "0.0005"))
if weld > 0:   # merge seam-split vertices so decimation keeps the surface connected (UVs are per-corner, preserved)
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=weld); bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    print("welded verts:", len(obj.data.vertices))
skirt = float(opt("--skirt", "0"))
if skirt > 0:
    # extrude the bottom opening straight down (Blender Z-up after glTF import) and give it a plain dark material
    import bmesh, mathutils
    bpy.ops.object.mode_set(mode="EDIT"); bm = bmesh.from_edit_mesh(obj.data)
    zs = [v.co.z for v in bm.verts]; cut = min(zs) + 0.35 * (max(zs) - min(zs))
    for e in bm.edges: e.select = e.is_boundary and all(v.co.z < cut for v in e.verts)
    for v in bm.verts: v.select = False
    for e in bm.edges:
        if e.select:
            for v in e.verts: v.select = True
    bm.select_flush_mode(); bmesh.update_edit_mesh(obj.data)
    nsel = sum(1 for e in bm.edges if e.select); print("skirt boundary edges:", nsel)
    if nsel:
        bpy.ops.mesh.extrude_edges_move(TRANSFORM_OT_translate={"value": (0, 0, -skirt)})
        flare = float(opt("--skirt-flare", "1.0"))
        if flare != 1.0:   # widen the new bottom ring so the mask sits over the collar like a rubber mask
            bm = bmesh.from_edit_mesh(obj.data); sel = [v for v in bm.verts if v.select]
            cx = sum(v.co.x for v in sel) / len(sel); cy = sum(v.co.y for v in sel) / len(sel)
            for v in sel: v.co.x = cx + (v.co.x - cx) * flare; v.co.y = cy + (v.co.y - cy) * flare
            bmesh.update_edit_mesh(obj.data)
        bm = bmesh.from_edit_mesh(obj.data)
        mat = bpy.data.materials.new("MaskNeck"); mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.09, 0.08, 0.08, 1)
        obj.data.materials.append(mat); obj.active_material_index = len(obj.data.materials) - 1
        bpy.ops.object.material_slot_assign()
    bpy.ops.object.mode_set(mode="OBJECT")
mod = obj.modifiers.new("dec", "DECIMATE"); mod.ratio = max(0.001, min(1.0, tris / max(before, 1))); mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier="dec")
if flat:
    for p in obj.data.polygons: p.use_smooth = False
else:
    bpy.ops.object.shade_smooth()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_yup=True)
print(f"DECIMATED {before} -> {len(obj.data.polygons)} faces -> {dst}")
