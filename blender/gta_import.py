# Stage 1, import: Sollumz import of <name>_hi.yft (or <name>.yft) with <name>.ytd, drop collision/damage/low-LOD/props, keep alpha only on
# glass and lights, bake every part to world space with its origin on its GTA bone. Runs inside rebuild_blender.py (globals: S, SOLLUMZ, fail).
import bpy, bmesh, collections, math, os, re, sys, time
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
    print("FIVEM WARNING: this Sollumz version could not be patched to skip damaged textures (%s); one bad texture may then stop all of them" % e)
yft = name + "_hi.yft" if os.path.exists(os.path.join(src, name + "_hi.yft")) else name + ".yft"
if not os.path.exists(os.path.join(src, yft)):
    fail("no %s.yft or %s_hi.yft in %s" % (name, name, src))
files = [{"name": yft}] + ([{"name": name + ".ytd"}] if os.path.exists(os.path.join(src, name + ".ytd")) else [])
if len(files) == 1:
    L("no %s.ytd next to the model: the car comes out without its own pictures" % name)
try:
    bpy.ops.sollumz.import_assets(directory=os.path.join(src, ""), files=files)
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
    fail(why)
import_err = [l for l in log if l.startswith("IMPORT_ERROR")]
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    finish_fail("skipped", "yft unreadable: " + (import_err[0] if import_err else "no armature"))
if any(".ytd" in l for l in import_err):
    finish_fail("skipped", "ytd unreadable: " + import_err[0])
bones = {b.name: Vector(arm.matrix_world @ b.head_local) for b in arm.data.bones}
BONE_PARENT = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
# A two-wheeler has only wheel_lf and wheel_lr bones. This script builds four-wheel cars only.
BIKE = all(n in bones for n in ("wheel_lf", "wheel_lr")) and not any(n in bones for n in ("wheel_rf", "wheel_rr", "wheel_lm1", "wheel_rm1"))
if BIKE:
    finish_fail("refused", "a two-wheeler (wheel_lf and wheel_lr bones only): motorcycles are not supported")


def drop_reason(o):
    ln = o.name.lower()
    if o.type != "MESH":
        return "not a mesh"
    if o.name == "Cube":
        return "default cube"
    st = getattr(o, "sollum_type", "")
    if ln.endswith(".col") or ".col." in ln or str(st).startswith("sollumz_bound"):
        return "collision"
    # some cars keep body panels of 5,000 to 70,000 triangles in "Dummy Helper" objects; only a small mesh named dummy is a placeholder
    if any(k in ln for k in ("shatter", "damage", "_dam", "lowlod", "_ng")) or ("dummy" in ln and len(o.data.polygons) < 1500):
        return "damage/low-LOD"
    if ln.startswith("prop_") or "drug_case" in ln or "cash_case" in ln or "bobble" in ln:  # a dashboard bobble head once got joined to the wheel and copied to every corner
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

# A model whose body ships as loose add-on files next to the main yft gets the named files merged in: setting extra_yfts
# {"file.yft": "partname", ...}. Each add-on mesh is unparented in place (same coordinates as the main model),
# its own skeleton and modifiers are removed, and it joins the parts under the given name (the part then gets its own bone like any other part).
for _yf, _pn in S["extra_yfts"].items():
    if not os.path.exists(os.path.join(src, _yf)):
        fail("setting extra_yfts names %s, which is not in %s" % (_yf, src))
    _before = set(bpy.data.objects)
    try:
        bpy.ops.sollumz.import_assets(directory=os.path.join(src, ""), files=[{"name": _yf}])
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
    """A part whose other-side twin is missing from the model (a car with no driver front door) is copied across the middle line: world x flipped, normals flipped, named for the missing twin (the bone is made later, at the part's origin)."""
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
for _n in S["copy_to_other_side"]:
    if _n not in _present:
        L("WARNING: copy_to_other_side names %s, which is not a part of this car" % _n)
    else:
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

def bone_of(o):
    base = o.name.split(".")[0]
    return base if base in bones else None


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
    # A skinned part (armature modifier, one vertex group) on a side bone can come out with its geometry offset by twice the bone's sideways
    # distance (seen on light bars and trims: their boxes are exactly symmetrical once moved back). Move it back.
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

# A piece on a turned side bone can also come out on the far side of its bone, well outside the car: one car's right sill trim sat
# 1.7 m out to the left, an exact copy of the left one. Mirrored across its bone it lands where it belongs, the mirror of its twin, and it rides what its bone hangs from (MIRROR_FIXED, used when the parts are grouped). Done only when the piece is clearly
# outside the car and the mirror brings it inside. Measured after every part is placed, so the car's width is the real one.
import numpy as _np
_xw = {}
for o in keep:
    if o.type == "MESH" and o.data.vertices:
        _co = _np.empty(len(o.data.vertices) * 3); o.data.vertices.foreach_get("co", _co)
        _xw[o.name] = _co.reshape(-1, 3)[:, 0] + o.location.x
HALF_W = float(_np.percentile(_np.abs(_np.concatenate(list(_xw.values()))), 99.5)) if _xw else 1.0
MIRROR_FIXED = {}
for o in keep:
    _bn = o.name.split(".")[0]
    if o.name not in _xw or _bn not in bones or _bn.startswith(("wheel_", "door_")) or abs(bones[_bn].x) <= 0.3: continue
    _lo, _hi = float(_xw[o.name].min()), float(_xw[o.name].max()); _bx = bones[_bn].x
    if max(abs(_lo), abs(_hi)) > HALF_W + 0.3 and max(abs(2 * _bx - _lo), abs(2 * _bx - _hi)) <= HALF_W + 0.05:
        o.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))      # the data sits on its bone, so this mirrors it across the bone
        _bmm = bmesh.new(); _bmm.from_mesh(o.data); bmesh.ops.reverse_faces(_bmm, faces=_bmm.faces[:]); _bmm.to_mesh(o.data); _bmm.free()
        _pb = arm.data.bones[_bn].parent
        MIRROR_FIXED[o.name] = _pb.name if _pb else None
        L("CLEANUP mirrored %s across its bone: it was out at x %.2f..%.2f, outside the car (half width %.2f), now %.2f..%.2f; it rides %s"
          % (o.name, _lo, _hi, HALF_W, 2 * _bx - _hi, 2 * _bx - _lo, MIRROR_FIXED[o.name]))
# A piece lying wholly outside the car (all of it more than 30 cm beyond the car's sides, nose or tail) and not put back above is loose junk:
# it is attached to nothing the car has, so it is dropped.
_yw = {}
for o in keep:
    if o.name in _xw:
        _co = _np.empty(len(o.data.vertices) * 3); o.data.vertices.foreach_get("co", _co)
        _yw[o.name] = _co.reshape(-1, 3)[:, 1] + o.location.y
if _yw:
    _ally = _np.concatenate(list(_yw.values())); _ylo, _yhi = float(_np.percentile(_ally, 0.5)), float(_np.percentile(_ally, 99.5))
    for o in list(keep):
        if o.name not in _xw or o.name in MIRROR_FIXED or o.name.startswith(("wheel_", "door_")): continue
        if (_np.abs(_xw[o.name]).min() > HALF_W + 0.3) or (_yw[o.name].min() > _yhi + 0.3) or (_yw[o.name].max() < _ylo - 0.3):
            L("DROP %s: loose piece outside the car (x %.2f..%.2f, y %.2f..%.2f; the car is %.2f wide, y %.2f..%.2f)"
              % (o.name, _xw[o.name].min(), _xw[o.name].max(), _yw[o.name].min(), _yw[o.name].max(), 2 * HALF_W, _ylo, _yhi))
            keep.remove(o)

# Small flat pieces lying just above the ground (door puddle-light logos the source projects onto the road) are not part of the car:
# in the game they float under it. A loose, flat, level island of at most 64 faces in a non-wheel part, within 8 cm of the tires' lowest
# point and under 60 cm across, is deleted (the logos are 8 to 32 faces, 2 to 6 cm up, under each door). Bigger low pieces, such as
# underglow strips and undertrays, are left alone.
_wz = [(_np.array([v.co.z for v in o.data.vertices]) + o.location.z).min() for o in keep
       if o.type == "MESH" and o.name.startswith("wheel_") and o.data.vertices]
if _wz:
    _ground = float(min(_wz))
    for o in keep:
        if o.type != "MESH" or o.name.startswith("wheel_") or not o.data.polygons: continue
        _bmg = bmesh.new(); _bmg.from_mesh(o.data); _bmg.faces.ensure_lookup_table()
        _seen, _gone = set(), []
        for _f in _bmg.faces:
            if _f.index in _seen: continue
            _st, _isl = [_f], []; _seen.add(_f.index)
            while _st:
                _g = _st.pop(); _isl.append(_g)
                for _e in _g.edges:
                    for _h in _e.link_faces:
                        if _h.index not in _seen: _seen.add(_h.index); _st.append(_h)
            _ps = [v.co + o.location for g in _isl for v in g.verts]
            _zs = [p.z for p in _ps]
            if (len(_isl) <= 64 and max(_zs) - min(_zs) < 0.01 and max(_zs) - _ground < 0.08
                    and max(max(p.x for p in _ps) - min(p.x for p in _ps), max(p.y for p in _ps) - min(p.y for p in _ps)) < 0.6):
                _gone += _isl
                L("DROP ground piece of %s: %d faces at %.0f cm above the ground, x %.2f y %.2f" % (o.name, len(_isl), (max(p.z for p in _ps) - _ground) * 100, _ps[0].x, _ps[0].y))
        if _gone:
            bmesh.ops.delete(_bmg, geom=list({f for f in _gone}), context="FACES_ONLY")
            bmesh.ops.delete(_bmg, geom=[v for v in _bmg.verts if not v.link_faces], context="VERTS")
            _bmg.to_mesh(o.data)
        _bmg.free()

