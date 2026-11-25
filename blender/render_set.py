"""blender -b --python render_set.py -- <glb> <out prefix> <sets>   sets = plain,shade,open,lights,rail then (separately, it paints a test grid on the paint) grid
Workbench pictures of a skinned car GLB (nose +X). Same cameras for before and after."""
import bpy, math, sys
from mathutils import Vector, Matrix
a = sys.argv[sys.argv.index("--") + 1:]
glb, prefix, sets = a[0], a[1], a[2].split(",")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
sc = bpy.context.scene
meshes = [o for o in sc.objects if o.type == "MESH"]
arm = next((o for o in sc.objects if o.type == "ARMATURE"), None)

def base_color(m):
    pb = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m.node_tree else None
    if pb is None: return (0.5, 0.5, 0.5, 1)
    mix = next((n for n in m.node_tree.nodes if n.type == "MIX" and n.data_type == "RGBA"), None)
    if mix is not None and not pb.inputs["Base Color"].links: pass
    c = tuple(pb.inputs["Base Color"].default_value)
    if pb.inputs["Base Color"].links and mix is not None: c = tuple(mix.inputs[7].default_value)
    return (c[0], c[1], c[2], 1)
for m in bpy.data.materials:
    m.diffuse_color = base_color(m)
    if "PRIMARY" in m.name: m.diffuse_color = (0.72, 0.06, 0.06, 1)
    if "glass" in m.name.lower(): m.diffuse_color = (0.12, 0.2, 0.26, 1)

pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p[i] for p in pts) for i in range(3))); hi = Vector((max(p[i] for p in pts) for i in range(3)))
center = (lo + hi) / 2; size = (hi - lo).length
sc.render.engine = "BLENDER_WORKBENCH"
sc.render.resolution_x, sc.render.resolution_y = 1400, 800
sc.display.shading.show_cavity = False
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.55, 0.6, 0.65)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
def aim(loc, target, lens=36, ortho=None):
    cam.location = loc
    cam.rotation_euler = (target - loc).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    if ortho: cam.data.type = "ORTHO"; cam.data.ortho_scale = ortho
    else: cam.data.type = "PERSP"
def shot(path):
    sc.render.filepath = path; bpy.ops.render.render(write_still=True)
def standard(tag, dist=1.75):
    aim(Vector((center.x, center.y + size * dist, center.z)), center, ortho=(hi.x - lo.x) * 1.12); shot(prefix + "_%s_side.png" % tag)
    aim(center + Vector((size * 0.62, size * 0.8, size * 0.28)), center); shot(prefix + "_%s_34front.png" % tag)
    aim(center + Vector((-size * 0.62, -size * 0.8, size * 0.28)), center); shot(prefix + "_%s_34rear.png" % tag)

sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
if "plain" in sets:
    standard("plain")
if "livery" in sets and len(a) > 3:     # the car wearing its livery (a[3], made for UV 0) over its starting paint colour
    import numpy as np
    liv = bpy.data.images.load(a[3]); W_, H_ = liv.size
    px = np.empty(W_ * H_ * 4, np.float32); liv.pixels.foreach_get(px); px = px.reshape(H_, W_, 4)
    for m in bpy.data.materials:
        if "PRIMARY" not in m.name: continue
        nt = m.node_tree; pb = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        lin = list(pb.inputs["Base Color"].default_value)[:3]
        paint = np.array([(c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055) for c in lin], np.float32)
        al = px[:, :, 3:4]
        comp = np.concatenate([px[:, :, :3] * al + paint * (1 - al), np.ones_like(al)], axis=2)
        img = bpy.data.images.new("livery_on_paint", W_, H_); img.pixels.foreach_set(comp.ravel())
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
        for l in list(pb.inputs["Base Color"].links): nt.links.remove(l)
        nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"]); nt.nodes.active = tex
        m.diffuse_color = (*lin, 1)
    sc.display.shading.color_type = "TEXTURE"
    standard("livery")
if "grid" in sets:
    img = bpy.data.images.new("grid", 2048, 2048); img.generated_type = "COLOR_GRID"
    for m in bpy.data.materials:
        if "PRIMARY" in m.name:
            nt = m.node_tree; pb = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
            tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
            for l in list(pb.inputs["Base Color"].links): nt.links.remove(l)
            nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"]); nt.nodes.active = tex
    sc.display.shading.color_type = "TEXTURE"
    aim(Vector((center.x, center.y + size * 1.2, center.z)), center, ortho=(hi.x - lo.x) * 0.62); shot(prefix + "_grid_sideclose.png")
    standard("grid")
    sc.display.shading.color_type = "TEXTURE"
if "shade" in sets:
    for m in bpy.data.materials:
        if "PRIMARY" in m.name:
            m.diffuse_color = (0.75, 0.05, 0.05, 1)
    sc.display.shading.light = "MATCAP"
    try: sc.display.shading.studio_light = "ceramic_dark.exr"
    except Exception: pass
    tgt = Vector((center.x + 0.1, hi.y, 0.417 * hi.z))
    aim(tgt + Vector((0.8, 1.9, 0.25)), tgt, lens=55); shot(prefix + "_shade_door.png")
    tgt = Vector((hi.x - 0.9, 0.0, lo.z + (hi.z - lo.z) * 0.45))
    aim(tgt + Vector((1.3, size * 0.45, 0.8)), tgt, lens=55); shot(prefix + "_shade_hood.png")
    sc.display.shading.light = "STUDIO"
if "open" in sets and arm is not None:
    def hinge(name, axis, deg):
        pb = arm.pose.bones.get(name)
        if pb is None: print("NOBONE", name); return
        h = pb.head.copy()
        ax = (arm.matrix_world.to_3x3().inverted() @ Vector(axis)).normalized()
        R = Matrix.Rotation(math.radians(deg), 4, ax)
        pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ pb.bone.matrix_local
        bpy.context.view_layer.update()
    # left side is +Y, nose +X: doors hinge at their front edge and open outward; hood hinges at its rear edge, trunk at its front edge
    for n, d in (("door_dside_f", -60), ("door_dside_r", -60), ("door_pside_f", 60), ("door_pside_r", 60)): hinge(n, (0, 0, 1), d)
    hinge("bonnet", (0, 1, 0), -60); hinge("boot", (0, 1, 0), 60)
    bpy.context.view_layer.update()
    sc.display.shading.color_type = "TEXTURE"
    aim(center + Vector((size * 0.55, size * 0.75, size * 0.55)), center + Vector((0, 0, -0.1))); shot(prefix + "_open_34front_left.png")
    aim(center + Vector((-size * 0.55, -size * 0.75, size * 0.55)), center + Vector((0, 0, -0.1))); shot(prefix + "_open_34rear_right.png")
    aim(center + Vector((size * 0.55, -size * 0.75, size * 0.55)), center + Vector((0, 0, -0.1))); shot(prefix + "_open_34front_right.png")
    aim(Vector((center.x, center.y, hi.z + size * 1.6)), center, ortho=(hi.x - lo.x) * 1.2); shot(prefix + "_open_top.png")
    # back to rest
    for pb in arm.pose.bones: pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
if "lights" in sets:
    cols = {"headlight_lens": (1, 1, 0.85, 1), "taillight_lens": (1, 0.05, 0.02, 1), "reverselight_lens": (0.75, 0.9, 1, 1), "indicator_lens": (1, 0.55, 0.0, 1)}
    for m in bpy.data.materials:
        m.diffuse_color = cols.get(m.name, (0.06, 0.06, 0.07, 1))
    sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
    sc.world.color = (0.03, 0.03, 0.04)
    f = hi.x; r = lo.x
    aim(Vector((f + 1.6, 1.9, 0.64 * hi.z)), Vector((f - 0.3, 0.2, 0.37 * hi.z)), lens=32); shot(prefix + "_lights_front_left.png")
    aim(Vector((f + 1.6, -1.9, 0.64 * hi.z)), Vector((f - 0.3, -0.2, 0.37 * hi.z)), lens=32); shot(prefix + "_lights_front_right.png")
    aim(Vector((r - 1.6, 1.9, 0.64 * hi.z)), Vector((r + 0.3, 0.2, 0.4 * hi.z)), lens=32); shot(prefix + "_lights_rear_left.png")
    aim(Vector((r - 1.6, -1.9, 0.64 * hi.z)), Vector((r + 0.3, -0.2, 0.4 * hi.z)), lens=32); shot(prefix + "_lights_rear_right.png")
if "rail" in sets:
    import numpy as np
    for m in bpy.data.materials:
        if "PRIMARY" in m.name: m.diffuse_color = (0.72, 0.06, 0.06, 1)
    sc.display.shading.color_type = "TEXTURE"; sc.display.shading.light = "STUDIO"
    sc.render.resolution_x, sc.render.resolution_y = 1000, 640
    paths = []
    for nm, y in (("left", 1), ("right", -1)):
        t = Vector((center.x - 0.3, 0.74 * hi.y * y, 0.81 * hi.z))
        aim(t + Vector((0.5, 2.4 * hi.y * y, 0.8 * hi.z)), t, lens=45); shot(prefix + "_rail_%s.png" % nm); paths.append(prefix + "_rail_%s.png" % nm)
    ims = [bpy.data.images.load(p) for p in paths]
    arrs = []
    for im in ims:
        w, h = im.size; a = np.empty(w * h * 4, dtype=np.float32); im.pixels.foreach_get(a); arrs.append(a.reshape(h, w, 4))
    both = np.concatenate(arrs, axis=1)
    out = bpy.data.images.new("both", both.shape[1], both.shape[0], alpha=True); out.pixels.foreach_set(both.reshape(-1)); out.filepath_raw = prefix + "_roofrails_left_vs_right.png"; out.file_format = "PNG"; out.save()
