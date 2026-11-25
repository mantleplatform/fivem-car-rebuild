# FiveM (GTA .yft/.ytd) car -> one skinned .glb the vehicle builder takes, the way the X7 was made (clean.py + skin.py "gta"
# variant), made general: Sollumz import of <name>_hi.yft (or <name>.yft) with <name>.ytd, drop collision/damage/low-LOD/props,
# keep alpha only on glass and lights, bake every part to world space with its origin on its GTA bone, give missing wheels
# copies of wheel_lf (right side turned 180 degrees), decimate heavy parts, nose to +X, ground at z=0, one bone per part
# (GTA names), join and export. Also follows vehicle-model-guide.md: materials renamed by what they are (env RENAME_MATERIALS
# "old=new;old2=new2": the tire, the rim, the brake), duplicate materials merged, and each wheel's pivot at the middle of the
# wheel itself.
#   blender -b <bootstrap.blend> --python fivem_to_glb.py -- <stream folder> <name> <out dir>
import bpy, collections, math, os, re, sys, time
_T0 = time.time()
from mathutils import Matrix, Vector

src, name, out = sys.argv[sys.argv.index("--") + 1:][:3]
os.makedirs(out, exist_ok=True)
log = []


def L(s):
    print("FIVEM [%ds]" % (time.time() - _T0), s, flush=True)
    log.append(s)


for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
bpy.ops.preferences.addon_enable(module="bl_ext.repo_sollumz_org.sollumz")
# One damaged texture makes Sollumz refuse the whole .ytd ("Mip 0 has invalid layer size"). Load every texture on its own and skip
# only the bad one(s); their names are reported as unreadable.
BAD_TEXTURES = []
try:
    import szio.gta5.native.adapters.texture as _T
    def _load_each(txd):
        if txd is None:
            return {}
        res = {}
        for t in txd.textures.values():
            try:
                tex_data = _T.DataSource.create(_T._extract_embedded_texture_dds_g8(t), t.name + ".dds")
                res[t.name] = _T.EmbeddedTexture(t.name, t.width, t.height, tex_data)
            except Exception as e:
                BAD_TEXTURES.append(t.name)
        return res
    _T.load_textures_from_native_g8 = _load_each
except Exception as e:
    print("FIVEM texture patch failed", e)
yft = name + "_hi.yft" if os.path.exists(os.path.join(src, name + "_hi.yft")) else name + ".yft"
files = [{"name": yft}] + ([{"name": name + ".ytd"}] if os.path.exists(os.path.join(src, name + ".ytd")) else [])
try:
    bpy.ops.sollumz.import_assets(directory=src + "\\", files=files)
except Exception as e:
    # Sollumz reports a file it could not read after importing the others (a bad .ytd still leaves the model).
    L("IMPORT_ERROR %s" % str(e).strip().splitlines()[0][:200])
bpy.context.view_layer.update()
L("imported %s: %d objects, %d images" % (yft, len(bpy.data.objects), len(bpy.data.images)))

import json
RESULT = {"name": name, "problems": []}
def finish_fail(status, why):
    RESULT.update(status=status, reason=why)
    open(os.path.join(out, name + "_result.json"), "w").write(json.dumps(RESULT))
    open(os.path.join(out, name + "_blender_log.txt"), "w").write("\n".join(log))
    raise SystemExit("FIVEM_%s %s" % (status, why))
import_err = [l for l in log if l.startswith("IMPORT_ERROR")]
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    finish_fail("skipped", "yft unreadable: " + (import_err[0] if import_err else "no armature"))
if any(".ytd" in l for l in import_err):
    finish_fail("skipped", "ytd unreadable: " + import_err[0])
bones = {b.name: Vector(arm.matrix_world @ b.head_local) for b in arm.data.bones}
# cleanup-fix: a two-wheeler (GODz13HDSG32...) has only wheel_lf and wheel_lr bones. Mantle's motorcycle has one wheel per axle on the center line,
# named wheel_f and wheel_r, and a fork (a bone named fork...) that steers; so no wheel copies, no mirroring, no floating-part drop (its frame is its parts)
BIKE = all(n in bones for n in ("wheel_lf", "wheel_lr")) and not any(n in bones for n in ("wheel_rf", "wheel_rr", "wheel_lm1", "wheel_rm1"))
if BIKE:
    L("BIKE: two wheel bones, no right-hand wheels: motorcycle path (wheel_f / wheel_r on the center line)")


def drop_reason(o):
    ln = o.name.lower()
    if o.type != "MESH":
        return "not a mesh"
    if o.name == "Cube":
        return "default cube"
    st = getattr(o, "sollum_type", "")
    if ln.endswith(".col") or ".col." in ln or str(st).startswith("sollumz_bound"):
        return "collision"
    # "Dummy Helper" objects of 5,000 to 70,000 triangles are dzdaytona's body panels; only a small mesh named dummy is a placeholder
    if any(k in ln for k in ("shatter", "damage", "_dam", "lowlod", "_ng")) or ("dummy" in ln and len(o.data.polygons) < 1500):
        return "damage/low-LOD"
    if ln.startswith("prop_") or "drug_case" in ln or "cash_case" in ln or "bobble" in ln:  # hycadesti's bobble_head (21,840 triangles) was joined to the wheel and copied to every corner
        return "prop"
    if len(o.data.polygons) == 0:
        return "empty"
    return None


keep = []
for o in list(bpy.data.objects):
    r = drop_reason(o)
    if r is None:
        keep.append(o)
    elif o.type == "MESH":
        L("DROP %s: %s" % (o.name, r))

# cleanup-fix: a model whose body ships as loose add-on files next to the main yft (gstspc1's gst_spc1_body_1..8, nirohybrid's variant files) gets the named files
# merged in: env ADDON_YFTS "file.yft=partname;file2.yft=partname2". Each add-on mesh is unparented in place (same coordinates as the main model),
# its own skeleton and modifiers are removed, and it joins the parts under the given name (the part then gets its own bone like any other part).
for _pair in [p for p in os.environ.get("ADDON_YFTS", "").split(";") if "=" in p]:
    _yf, _pn = _pair.split("=", 1)
    _before = set(bpy.data.objects)
    try:
        bpy.ops.sollumz.import_assets(directory=src + "\\", files=[{"name": _yf}])
    except Exception as e:
        L("IMPORT_NOTE add-on %s: %s" % (_yf, str(e).strip().splitlines()[0][:150]))
    bpy.context.view_layer.update()
    _new = [o for o in bpy.data.objects if o not in _before]
    _n = 0
    for o in _new:
        if o.type == "MESH" and drop_reason(o) is None:
            _mw = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = _mw
            for _md in list(o.modifiers):
                o.modifiers.remove(_md)
            o.vertex_groups.clear()
            o.name = _pn if _n == 0 else "%s_%d" % (_pn, _n)
            _n += 1
            keep.append(o)
    for o in _new:
        if o.type != "MESH" or o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    _ms = [o for o in _new if o in keep and o.name in bpy.data.objects]
    if len(_ms) > 1:  # one part per add-on file: one bone, and "boot" or "bodyshell" stays one named part
        for _o in bpy.data.objects:
            _o.select_set(False)
        for _o in _ms:
            _o.select_set(True)
        bpy.context.view_layer.objects.active = _ms[0]
        bpy.ops.object.join()
        for _o in _ms[1:]:
            if _o in keep:
                keep.remove(_o)
        _ms[0].name = _pn
    L("CLEANUP add-on %s merged as %s (%d mesh%s)" % (_yf, _pn, _n, "" if _n == 1 else "es"))


def mirror_part(src, new_name):
    """cleanup-fix: a part whose other-side twin is missing from the model (gle21 has no driver front door, and its right front panel 'cee' has no left twin) is
    copied across the middle line: world x flipped, normals flipped, named for the missing twin (the bone is made later, at the part's origin)."""
    W = src.matrix_world.copy()
    t = W.translation
    M2 = Matrix.Translation((-t.x, t.y, t.z))
    new = src.copy()
    new.data = src.data.copy()
    bpy.context.scene.collection.objects.link(new)
    new.parent = None
    new.matrix_world = M2
    inv = M2.inverted()
    for v in new.data.vertices:
        w = W @ v.co
        w.x = -w.x
        v.co = inv @ w
    new.data.flip_normals()
    new.data.update()
    new.name = new_name
    return new


_present = {o.name for o in keep if o.type == "MESH"}
_mirrors = []
for _a, _b in (("door_dside_f", "door_pside_f"), ("door_dside_r", "door_pside_r")):
    if _a in _present and _b not in _present:
        _mirrors.append((_a, _b))
    elif _b in _present and _a not in _present:
        _mirrors.append((_b, _a))
for _n in [x for x in os.environ.get("MIRROR_PARTS", "").split(",") if x]:
    if _n in _present:
        _mirrors.append((_n, _n + "_m"))
for _srcn, _newn in _mirrors:
    _src = next(o for o in keep if o.name == _srcn)
    keep.append(mirror_part(_src, _newn))
    L("CLEANUP part %s has no twin on the other side: copied across the middle as %s" % (_srcn, _newn))
bpy.context.view_layer.update()

KEEP_ALPHA = re.compile(r"glass|window|light|lens|signal|lamp|dials|decal|sign", re.I)
for m in bpy.data.materials:
    if not m.users or not m.node_tree or KEEP_ALPHA.search(m.name):
        continue
    pb = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if pb is None:
        continue
    a = pb.inputs["Alpha"]
    if a.links or a.default_value < 1.0:
        for l in list(a.links):
            m.node_tree.links.remove(l)
        a.default_value = 1.0


# GTA materials list the game's shared pictures (a blank normal map, a dirt map, a spec map) that are not in a car's own files. When
# any of them is missing the glTF export drops the material's color picture too and leaves flat light gray (mirrors, trunk lip and
# splitter came out white on the Camaro). Wire the material's own diffuse picture straight into Base Color, and make a material
# whose diffuse is the game's missing plain "black" picture black. Paint, glass and light materials keep what they have.
TINT_OR_GLASS = re.compile(r"PRIMARY|SECONDARY|WHEEL|glass|window|light|lens|signal|lamp|dials|decal|sign", re.I)
fixed_diffuse, fixed_black = [], []
for m in bpy.data.materials:
    if not m.users or not m.node_tree or TINT_OR_GLASS.search(m.name):
        continue
    pb = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    diffuse = next((n for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image and "diffuse" in (n.label + n.name).lower()), None)
    if pb is None or diffuse is None:
        continue
    if diffuse.image.size[0] > 0:
        for link in list(pb.inputs["Base Color"].links):
            m.node_tree.links.remove(link)
        m.node_tree.links.new(diffuse.outputs["Color"], pb.inputs["Base Color"])
        fixed_diffuse.append(m.name)
    elif "black" in diffuse.image.name.lower():
        for link in list(pb.inputs["Base Color"].links):
            m.node_tree.links.remove(link)
        pb.inputs["Base Color"].default_value = (0.012, 0.012, 0.012, 1.0)
        fixed_black.append(m.name)
L("diffuse wired to base color: %d materials %s" % (len(fixed_diffuse), fixed_diffuse[:12]))
L("black pictures replaced by black: %s" % fixed_black)

# Materials renamed by what they are, so Mantle recognizes them (tire -> its rubber, rim -> wheel swaps).
for pair in [p for p in os.environ.get("RENAME_MATERIALS", "").split(";") if "=" in p]:
    old, new = pair.split("=", 1)
    m = bpy.data.materials.get(old)
    if m:
        m.name = new
        L("renamed material %s -> %s" % (old, new))
    else:
        L("RENAME_MISSING %s" % old)


def merge_duplicate_materials(objs):
    """Materials that differ only by a '.001' suffix and have the same pictures and color become one."""
    def key(m):
        base = re.sub(r"\.\d{3}$", "", m.name)
        imgs, col = (), None
        if m.node_tree:
            imgs = tuple(sorted(n.image.name for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image))
            pb = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if pb is not None and not pb.inputs["Base Color"].links:
                col = tuple(round(x, 3) for x in pb.inputs["Base Color"].default_value)
        return (base, imgs, col)
    keep = {}
    before = {s.material.name for o in objs for s in o.material_slots if s.material}
    for o in objs:
        for slot in o.material_slots:
            if slot.material:
                slot.material = keep.setdefault(key(slot.material), slot.material)
    after = {s.material.name for o in objs for s in o.material_slots if s.material}
    L("merged duplicate materials: %d -> %d" % (len(before), len(after)))


def apply_roles(objs):
    """Rebuild the car out of Mantle's parts: every material goes to the one that does its job, and parts nobody sees are removed.
    MANTLE_ROLES is a JSON list of [regex, target material name, optional [r,g,b] to make it flat] in priority order (the first
    regex that matches a material wins); MANTLE_DROP is ';'-separated regexes of materials whose faces are deleted."""
    import json, bmesh
    roles = json.loads(os.environ.get("MANTLE_ROLES", "[]"))
    drops = [d for d in os.environ.get("MANTLE_DROP", "").split(";") if d]
    for o in objs:
        gone = [i for i, sl in enumerate(o.material_slots) if sl.material and any(re.search(d, sl.material.name) for d in drops)]
        if gone:
            bm = bmesh.new(); bm.from_mesh(o.data)
            n = len(bm.faces)
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in gone], context="FACES")
            L("removed %d hidden triangles from %s" % (n - len(bm.faces), o.name))
            bm.to_mesh(o.data); bm.free()
    targets = {}
    for pattern, target, *flat in roles:
        m = bpy.data.materials.get(target)
        if m is None:
            m = bpy.data.materials.new(target)
            m.use_nodes = True
            pb = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            pb.inputs["Base Color"].default_value = tuple(flat[0]) + (1.0,) if flat else (0.8, 0.8, 0.8, 1.0)
        targets[pattern] = m
    moved = collections.Counter()
    for o in objs:
        for sl in o.material_slots:
            if not sl.material:
                continue
            for pattern, _t, *_f in roles:
                if re.search(pattern, sl.material.name):
                    if sl.material is not targets[pattern]:
                        moved[(sl.material.name, targets[pattern].name)] += 1
                        sl.material = targets[pattern]
                    break
    L("materials merged by role: %s" % sorted({"%s -> %s" % k for k in moved}))




def bone_of(o):
    base = o.name.split(".")[0]
    return base if base in bones else None


def decimate(ob, ratio):
    before = len(ob.data.polygons)
    if os.environ.get("NO_DECIMATE") and re.search(os.environ["NO_DECIMATE"], ob.name):
        return
    # cleanup-fix: weld doubled vertices first and keep the result in triangles (quads collapsed unevenly leave shards: GODzHYCADEMK4V2, purosangue)
    import bmesh
    _bm = bmesh.new()
    _bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(_bm, verts=_bm.verts, dist=1e-5)
    _bm.to_mesh(ob.data)
    _bm.free()
    mod = ob.modifiers.new("Decimate", "DECIMATE")
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    L("DECIMATE %s %d -> %d" % (ob.name, before, len(ob.data.polygons)))


# bake each part into world space (matrix_world already includes Sollumz's bone constraints), origin on its bone
for o in keep:
    mw = o.matrix_world.copy()
    for m in list(o.modifiers):
        if m.type == "ARMATURE":
            o.modifiers.remove(m)
    o.vertex_groups.clear()
    if o.data.users > 1:
        o.data = o.data.copy()
    o.data.transform(mw)
    # cleanup-fix: a skinned part (armature modifier, one vertex group) on a side bone can come out with its geometry offset by twice the bone's sideways
    # distance (mi8's LED bars, police lights and front trims: their boxes are exactly symmetrical once moved back). Move it back.
    _bn = o.name.split(".")[0]
    if _bn in bones and not _bn.startswith("wheel_") and not _bn.startswith("door_") and abs(bones[_bn].x) > 0.3 and o.data.vertices:
        _xs = [v.co.x for v in o.data.vertices]
        _cx = (min(_xs) + max(_xs)) / 2
        if abs(_cx - 2 * bones[_bn].x) < 0.15:
            o.data.transform(Matrix.Translation((-2 * bones[_bn].x, 0, 0)))
            L("CLEANUP put %s back: its geometry was %.2f m to the side (twice its bone's offset)" % (o.name, 2 * bones[_bn].x))
    o.parent = None
    for c in list(o.constraints):
        o.constraints.remove(c)
    o.matrix_world = Matrix.Identity(4)
    bn = bone_of(o)
    if bn:
        o.data.transform(Matrix.Translation(-bones[bn]))
        o.location = bones[bn]
        o.name = bn
        o.data.name = bn

