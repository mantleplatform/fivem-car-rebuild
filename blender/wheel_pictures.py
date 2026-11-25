"""blender -b --python wheel_pictures.py -- <car_skinned.glb> <out prefix> [calipers=steer|fixed]
Close pictures of a rebuilt car's four wheels: the front wheels steered 30 degrees each way, seen from outside and from in front, and the
rear wheels from outside. The brake calipers (bones hub_xx) steer with their wheel, as Mantle's vehicle builder rigs them ("Hubs and brakes
... steers with its wheel and does not spin"); calipers=fixed leaves them where they are, to show what a caliper that does not steer looks like.
Workbench, one-sided faces like the game, magenta background."""
import bpy, sys, math
from mathutils import Vector, Matrix
a = sys.argv[sys.argv.index("--") + 1:]
glb, prefix = a[0], a[1]
opts = dict(x.split("=") for x in a[2:])
steer_cal = opts.get("calipers", "steer") == "steer"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
car = next(o for o in sc.objects if o.type == "MESH")
cols = {"PRIMARY": (0.75, 0.75, 0.75, 1), "SECONDARY": (0.2, 0.2, 0.2, 1), "plastic_black": (0.08, 0.08, 0.08, 1), "rim": (0.6, 0.6, 0.6, 1),
        "tire": (0.03, 0.03, 0.03, 1), "chrome": (0.85, 0.85, 0.9, 1), "interior": (0.35, 0.25, 0.2, 1)}
for m in bpy.data.materials:
    m.diffuse_color = cols.get(m.name.split(".")[0], (0.5, 0.5, 0.5, 1))
# unskinned copy of the body we can move part by part (rest pose = the model as built)
for md in list(car.modifiers): car.modifiers.remove(md)
car.parent = None; me = car.data; mw = car.matrix_world.copy()
me.transform(mw); car.matrix_world = Matrix.Identity(4)
gi = {g.index: g.name for g in car.vertex_groups}
part = {}
for v in me.vertices:
    b = max(v.groups, key=lambda g: g.weight, default=None)
    part[v.index] = gi[b.group] if b else None
head = {b.name: arm.matrix_world @ b.head_local for b in arm.data.bones}
rest = [v.co.copy() for v in me.vertices]
def pose(steer):
    for v in me.vertices:
        p = part[v.index]; v.co = rest[v.index]
        if steer and p in ("wheel_lf", "wheel_rf") or (steer and steer_cal and p in ("hub_lf", "hub_rf")):
            c = head["wheel_" + p.split("_")[1]]
            v.co = c + Matrix.Rotation(math.radians(steer), 3, "Z") @ (rest[v.index] - c)
    me.update()
sc.render.engine = "BLENDER_WORKBENCH"; sc.render.resolution_x, sc.render.resolution_y = 1400, 1000
sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "MATERIAL"; sc.display.shading.show_backface_culling = True
sc.world = bpy.data.worlds.new("w"); sc.world.color = (1.0, 0.0, 1.0)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam; cam.data.lens = 35
def shot(name, c, off):
    cam.location = c + off
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = "%s_%s.png" % (prefix, name); bpy.ops.render.render(write_still=True)
for steer in (30, -30):
    pose(steer)
    for corner in ("lf", "rf"):
        c = head["wheel_" + corner]; side = 1 if c.y > 0 else -1
        shot("steer%+d_%s_out" % (steer, corner), c, Vector((0.0, 1.5 * side, 0.15)))
        shot("steer%+d_%s_front" % (steer, corner), c, Vector((1.4, 0.9 * side, 0.2)))
pose(0)
for corner in ("lr", "rr"):
    c = head["wheel_" + corner]; side = 1 if c.y > 0 else -1
    shot("rest_%s_out" % corner, c, Vector((0.0, 1.5 * side, 0.15)))
print("WHEELPICS done", prefix)
