# Stage: shading, skeleton (hinge pivots, wheel centres), GLB.
import bpy, bmesh, json, math, re, collections
from mathutils import Vector, Matrix
OUT = out.replace("\\", "/").rstrip("/") + "/"
car = bpy.data.objects["car"]; me = car.data
names = json.loads(car["part_names"])

# ---- 0. no zero-area triangles: one whose corners lie on a line has no normal, and Mantle's cook refuses the whole car for it ("a normal or
# texture coordinate is not a finite number"). The mesh is cut into the triangles the GLB will hold, and every one under 1e-10 m2 is removed.
bm = bmesh.new(); bm.from_mesh(me)
bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method="BEAUTY", ngon_method="BEAUTY")
_deg = [f for f in bm.faces if f.calc_area() < 1e-10]
bmesh.ops.delete(bm, geom=_deg, context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bm.to_mesh(me); bm.free(); me.update()
L("zero-area triangles removed: %d" % len(_deg))

# ---- 1. surfaces: smooth panels, crisp creases (sharp edges over 35 deg), weighted normals
bm = bmesh.new(); bm.from_mesh(me)
sharp = 0
for f in bm.faces: f.smooth = True
for e in bm.edges:
    if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(35):
        e.smooth = False; sharp += 1
bm.to_mesh(me); bm.free()
mod = car.modifiers.new("WN", "WEIGHTED_NORMAL"); mod.keep_sharp = True; mod.weight = 50; mod.mode = "FACE_AREA"
with bpy.context.temp_override(object=car, active_object=car):
    bpy.ops.object.modifier_apply(modifier="WN")
L("sharp edges %d" % sharp)

# ---- 2. vertex groups by part (body -> chassis root)
bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
pl = bm.faces.layers.int["part"]
vpart = {}
for f in bm.faces:
    for v in f.verts: vpart[v.index] = names[f[pl]]
cen = collections.defaultdict(list)
for vi, pn in vpart.items(): cen[pn].append(bm.verts[vi].co.copy())
bm.free()
def bbc(pn):
    vs = cen[pn]
    return Vector(((min(v.x for v in vs) + max(v.x for v in vs)) / 2, (min(v.y for v in vs) + max(v.y for v in vs)) / 2, (min(v.z for v in vs) + max(v.z for v in vs)) / 2))

# ---- 3. skeleton
shift = GROUND_SHIFT
def gta(n):  # source (x right, y nose) -> Mantle (x nose, y left), on the ground
    p = BONES[n]; return Vector((p.y, -p.x, p.z + shift))
arm_data = bpy.data.armatures.new(name + "_skeleton")
skel = bpy.data.objects.new(name + "_skeleton", arm_data)
bpy.context.scene.collection.objects.link(skel)
bpy.context.view_layer.objects.active = skel
bpy.ops.object.mode_set(mode="EDIT")
root = arm_data.edit_bones.new("chassis"); root.head = Vector((0, 0, 0.47)); root.tail = Vector((0, -0.2, 0.47))
bone_of = {"body": "chassis"}
heads = {}
for pn in names:
    if pn == "body": continue
    if pn.startswith("wheel_"):
        c = bbc(pn); c.z = WHEEL_RS.get(pn, WHEEL_R); head = c
    elif pn.startswith("hub_") and ("wheel_" + pn[4:]) in cen:    # the caliper's hub sits at its wheel's centre (it follows the wheel's travel and steering, not its spin)
        c = bbc("wheel_" + pn[4:]); c.z = WHEEL_RS.get("wheel_" + pn[4:], WHEEL_R); head = c
    else:
        head = gta(pn)
    heads[pn] = head
    b = arm_data.edit_bones.new(pn); b.head = head
    b.tail = head + (Vector((0, 0.06, 0)) if pn.startswith(("wheel_", "hub_", "bonnet", "boot")) else Vector((0, 0, 0.06)))
    b.parent = root
    bone_of[pn] = pn
# Each window rides the door it sits in, found by place, not by name: models call the rear-door glass window_lr, window_lm or
# window_rm as they please. A window rides the door on its own side that holds most of its length (80% or more, 3 cm slack),
# the one it overlaps most; a window in no door (a two-door car's rear side glass, a quarter window) stays on the body.
def _xr(pn): xs = [v.x for v in cen[pn]]; return min(xs), max(xs)
_doors = [d for d in names if d.startswith("door_") and d in arm_data.edit_bones and cen[d]]
for ch in [w for w in names if w.startswith("window_") and w in arm_data.edit_bones and cen[w]]:
    wc_ = bbc(ch); w0, w1 = _xr(ch); best, bo = None, 0.0
    for d in _doors:
        if (bbc(d).y > 0) != (wc_.y > 0): continue
        d0, d1 = _xr(d)
        ov = (min(w1, d1 + 0.03) - max(w0, d0 - 0.03)) / max(w1 - w0, 1e-6)   # share of the window's length inside the door's
        if ov > bo: best, bo = d, ov
    if best is None or bo < 0.8:
        L("bone %s stays on the body (in no door%s)" % (ch, ", %.0f%% in %s" % (100 * bo, best) if best else "")); continue
    arm_data.edit_bones[ch].parent = arm_data.edit_bones[best]
    L("bone %s rides %s (%.0f%% inside it)" % (ch, best, 100 * bo))
bpy.ops.object.mode_set(mode="OBJECT")
for pn in names:
    L("bone %s head %s" % (pn, tuple(round(x, 3) for x in heads.get(pn, Vector((0, 0, 0.47))))))
groups = {bn: car.vertex_groups.new(name=bn) for bn in dict.fromkeys(bone_of.values())}
byb = collections.defaultdict(list)
for vi, pn in vpart.items(): byb[bone_of[pn]].append(vi)
for bn, vis in byb.items(): groups[bn].add(vis, 1.0, "REPLACE")
car.modifiers.new("Armature", "ARMATURE").object = skel
car.parent = skel

# ---- 4. wheels level and mirrored: check
wc = {n: bbc(n) for n in names if n.startswith("wheel_")}
L("wheel centres: %s" % {k: tuple(round(x, 4) for x in v) for k, v in wc.items()})
me.calc_loop_triangles()
L("triangles %d, materials %d: %s" % (len(me.loop_triangles), len(me.materials), [m.name for m in me.materials]))
mn = [min(v.co[i] for v in me.vertices) for i in range(3)]; mx = [max(v.co[i] for v in me.vertices) for i in range(3)]
L("size x %.3f..%.3f y %.3f..%.3f z %.3f..%.3f" % (mn[0], mx[0], mn[1], mx[1], mn[2], mx[2]))
if S.get("save_blend"): bpy.ops.wm.save_as_mainfile(filepath=OUT + name + "_rebuild.blend")
# ---- final check against the source, and the verdict
_final = fid_compare(REF, fid_snapshot([car]), tol=0.04)
L("FINAL check against the source: %s" % _final["text"])
for w in _final["where"]: L("   " + w)
_status = "ok"
_where = list(_final["where"])
if not _final["ok"]: _status = "refused"
elif STATUS["over_budget"]: _status = "over_budget"
L("WHEEL check: %s" % WCHECK_TEXT)
L("STATUS %s. Steps: %s" % (_status, "; ".join(STATUS["steps"]) or "none"))
_paint = {"secondary": S.get("secondary_paint"), "secondary_sections": [m.name for m in me.materials if m.name.startswith("SECONDARY")],
          "steering_wheel_bone": "steering_wheel" if "steering_wheel" in names else None}
_paint.update(LIVERY_PAINT)
json.dump(_paint, open(OUT + name + "_paint.json", "w"), indent=1)
L("paint defaults for the upload step: %s" % _paint)
json.dump({"status": _status, "paint_defaults": _paint, "triangles": len(me.loop_triangles), "check": _final["text"] + ". " + WCHECK_TEXT, "where": _where, "warnings": list(WCHECK_WARN), "steps": STATUS["steps"], "materials": [m.name for m in me.materials]},
          open(OUT + name + "_check.json", "w"), indent=1)
_glbname = name + "_skinned.glb" if _status == "ok" else name + "_skinned.%s.glb" % _status.upper()
bpy.ops.object.select_all(action="DESELECT")
car.select_set(True); skel.select_set(True)
bpy.context.view_layer.objects.active = car
import os
os.makedirs(OUT, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=OUT + _glbname, export_format="GLB", export_image_format="AUTO", export_yup=True, use_selection=True,
                          export_cameras=False, export_lights=False, export_skins=True, export_def_bones=False)
L("exported")
open(OUT + name + "_rebuild_log.txt", "w").write("\n".join(log))
