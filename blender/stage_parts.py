# Stage: parts. Assemble the rebuilt car from the baked source parts (GTA frame in, Mantle frame out).
# Runs inside rebuild_blender.py after gta_import.py. Globals used: bpy, keep, bones, S (settings), L, math, re ...
import bpy, bmesh, re, math, collections, json
from mathutils import Vector, Matrix

for _ob in list(bpy.data.objects):
    if _ob not in keep:
        bpy.data.objects.remove(_ob, do_unlink=True)
P = {o.name: o for o in bpy.data.objects if o.type == "MESH"}
BONES = {k: Vector((round(v.x, 3), round(v.y, 3), round(v.z, 3))) for k, v in bones.items()}   # source frame, millimetre precision

# ---- 1. world-space meshes
bpy.context.view_layer.update()
for o in P.values():
    mw = o.matrix_world.copy()
    o.data = o.data.copy()
    o.data.transform(mw)
    o.parent = None; o.matrix_world = Matrix.Identity(4)
TOTAL_POLYS = sum(len(o.data.polygons) for o in P.values())

# ---- 2. materials: one per job
def mk(mname, col, alpha=1.0, rough=0.5, metal=0.0):
    m = bpy.data.materials.new(mname); m.use_nodes = True
    pb = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    pb.inputs["Base Color"].default_value = (*col, 1)
    pb.inputs["Roughness"].default_value = rough
    pb.inputs["Metallic"].default_value = metal
    if alpha < 1:
        pb.inputs["Alpha"].default_value = alpha
        try: m.blend_method = "BLEND"
        except Exception: pass
    m.diffuse_color = (*col, 1)
    return m
M = {
 "PRIMARY": mk("PRIMARY", (0.8, 0.8, 0.8), rough=0.25),
 "SECONDARY": mk("SECONDARY", (0.03, 0.03, 0.03), rough=0.3),
 "rim": mk("rim", (0.6, 0.6, 0.63), rough=0.3, metal=0.8),
 "tire": mk("tire", (0.015, 0.015, 0.015), rough=0.9),
 "chrome": mk("chrome", (0.85, 0.85, 0.88), rough=0.05, metal=1.0),
 "glass": mk("glass", (0.05, 0.08, 0.1), alpha=0.35, rough=0.05),
 # lamp lenses are named so Mantle's light finder knows them (a whole word starting headlight / taillight / reverse + light, or indicator)
 "head_lens": mk("headlight_lens", (0.9, 0.92, 0.95), alpha=0.7, rough=0.05),
 "tail_lens": mk("taillight_lens", (0.55, 0.02, 0.02), alpha=0.85, rough=0.05),
 "reverse_lens": mk("reverselight_lens", (0.9, 0.9, 0.9), alpha=0.85, rough=0.05),
 "indicator_lens": mk("indicator_lens", (0.9, 0.45, 0.05), alpha=0.85, rough=0.05),
 "interior": mk("interior", (0.10, 0.085, 0.075), rough=0.8),
 "plastic_black": mk("plastic_black", (0.012, 0.012, 0.012), rough=0.6),
 "carbon": mk("carbon_fiber", (0.02, 0.02, 0.025), rough=0.35),
 "badge": mk("badge", (0.8, 0.8, 0.8), rough=0.3),
 "grille": mk("grille", (0.8, 0.8, 0.8), rough=0.5),
 "reflector": mk("reflector", (0.8, 0.8, 0.8), rough=0.4),
}
for _k, _v in S["extra_materials"].items():   # flat materials a car needs besides the standard jobs (name, [r, g, b]); the name must not hold a word Mantle reads (light, lamp, lens, glass, tire, rim, chrome, roof ...)
    M[_k] = mk(_k, tuple(_v[:3]), rough=0.6)
_badjobs = sorted(({j_ for _rx, j_ in S["material_jobs"]} | {j_ for _r in S["part_material_jobs"].values() for _rx, j_ in _r} | set(S["pictures"])) - set(M))
if _badjobs:
    fail("settings name jobs that do not exist: %s. Jobs: %s (or a name from extra_materials)" % (_badjobs, ", ".join(M)))
# The tail and indicator lenses keep a flat red / amber base colour and no picture: a picture replaces the base colour (the GLB then says white),
# and Mantle keeps a lens's own colour only when its base colour is red to amber (otherwise it becomes the shared clear lens).
PICJOBS = ("interior", "carbon", "badge", "grille", "reflector", "head_lens", "reverse_lens")
# the car's own pictures: the source materials point at empty placeholders, the real pictures sit in the "<name>.dds" images
DDS = {i.name.lower(): i for i in bpy.data.images if i.name.lower().endswith(".dds") and i.size[0] > 0}
def diffuse_name(m):
    if not m or not m.node_tree: return None
    n = next((n for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image and "diffuse" in (n.label + n.name).lower()), None)
    return n.image.name.lower().replace(".dds", "") if n is not None else None

def base(mn): return re.sub(r"\.\d{3}$", "", mn)
# A printed livery: paint whose own picture is in the car's files is a picture printed on the body, not a colour players choose.
# - Body paint (PRIMARY): the faces stay plain paint and the picture becomes a real Mantle livery: stage_paint_uv copies it onto the new paint
#   layout as <name>_livery.png (see-through where the paint has no picture), to be added in the vehicle builder's Liveries step.
# - Anything else (second paint), where paint and livery can't be told apart in one layer: a "print" material that keeps its picture and its
#   own UVs (Mantle would make a paint section's picture a grey tint mask). Each picture gets its own (print, print_2 ...), at most 2048 px.
PRINTS = {}
PRINT_MIN = 512
LIVERY_SRC = {}       # source material -> its picture, for the livery
LIVERY_PAINT = {}     # written to <name>_paint.json by stage_rig_export
LIVERY_GLOW = collections.Counter()   # livery faces on GTA's lamp shader, by the Mantle light their ID names
def print_picture(mn):
    d = diffuse_name(bpy.data.materials.get(mn))
    # script_rt_* are GTA's placeholders for screens the game draws while playing (dials, displays): blank in the files, never a print
    if not d or (d + ".dds") not in DDS or re.match(r"vehicle_generic|blank|black|white|grey|script_rt", d): return None, None
    im = DDS[d + ".dds"]
    return (d, im) if max(im.size) >= PRINT_MIN else (None, None)
def livery_job(mn):
    d, im = print_picture(mn)
    if d is None: return None
    if mn not in LIVERY_SRC: L("livery <- %s picture %s (%dx%d): body paint with a printed picture; the faces stay paint" % (mn, im.name, im.size[0], im.size[1]))
    LIVERY_SRC[mn] = im
    return "PRIMARY"
def print_job(mn, kind=None):
    """the print material for this source material's picture; kind = a Mantle light kind makes it <print>_glow_<kind>: the same picture,
    also as its glow (the marker Mantle reads for "keeps its own picture and glows with that light")"""
    d, im = print_picture(mn)
    if d is None: return None
    if (d, kind) not in PRINTS:
        base_ = next((k_ for (p_, kk), k_ in PRINTS.items() if p_ == d and kk is None), None) or next((re.sub(r"_glow_\w+$", "", k_) for (p_, kk), k_ in PRINTS.items() if p_ == d), None)
        if base_ is None:
            n_ = len({p_ for p_, kk in PRINTS})
            base_ = "print" if n_ == 0 else "print_%d" % (n_ + 1)
        key = base_ + ("_glow_" + kind if kind else "")
        M[key] = mk(key, (0.8, 0.8, 0.8), rough=0.3)
        if max(im.size) > 2048:
            im2 = bpy.data.images.get(d + "_2048.png")
            if im2 is None:
                im2 = im.copy(); im2.name = d + "_2048.png"
                im2.scale(min(2048, im.size[0] * 2048 // max(im.size)), min(2048, im.size[1] * 2048 // max(im.size)))
            L("print %s: picture %s scaled %dx%d -> %dx%d" % (key, im.name, im.size[0], im.size[1], im2.size[0], im2.size[1])); im = im2
        nt = M[key].node_tree; pb = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = im; tex.label = "diffuse"
        nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"])
        _a = __import__("numpy").empty(im.size[0] * im.size[1] * 4, "float32"); im.pixels.foreach_get(_a)
        if _a[3::4].min() < 0.5:     # see-through parts in the picture (cut-out): kept cut out (glTF alpha mask)
            rnd = nt.nodes.new("ShaderNodeMath"); rnd.operation = "ROUND"
            nt.links.new(tex.outputs["Alpha"], rnd.inputs[0]); nt.links.new(rnd.outputs[0], pb.inputs["Alpha"])
        if kind:
            nt.links.new(tex.outputs["Color"], pb.inputs["Emission Color"]); pb.inputs["Emission Strength"].default_value = 1.0
        PRINTS[(d, kind)] = key
        L("print %s <- picture %s (%dx%d)%s" % (key, im.name, im.size[0], im.size[1], ", glows with the %s lights" % kind if kind else ""))
    return PRINTS[(d, kind)]

# GTA's lamp shader (vehicle_lightsemissive): a surface on it glows when its light is on, and which light is the light ID in its vertex colour's
# alpha. The car's own lamps tell which ID is which Mantle light (a headlight part's ID is a headlight); an ID no lamp of the car names stays
# unlit, never guessed. Pictures on this shader outside the lamps (a body livery, wheel covers, trim) glow with the light their ID names.
def lamp_shader(m):
    sp = getattr(m, "shader_properties", None) if m else None
    return "lightsemissive" in (getattr(sp, "name", "") or "")
def face_light_ids(o_):
    ca = o_.data.color_attributes[0] if len(o_.data.color_attributes) else None
    if ca is None: return None
    out_ = []
    for p_ in o_.data.polygons:
        li = p_.loop_indices[0]
        out_.append(int(round(ca.data[li if ca.domain == "CORNER" else o_.data.loops[li].vertex_index].color[3] * 255)))
    return out_
LAMP_KIND = (("headlight", "head"), ("taillight", "rear"), ("brakelight", "rear"), ("reversinglight", "reverse"), ("indicator_l", "left"), ("indicator_r", "right"))
ID_KIND = {}
_idk = collections.defaultdict(collections.Counter)
for n_, o_ in P.items():
    k_ = next((k for pre, k in LAMP_KIND if n_.startswith(pre)), None)
    ids_ = face_light_ids(o_) if k_ else None
    if not ids_: continue
    for p_, i_ in zip(o_.data.polygons, ids_):
        if lamp_shader(o_.material_slots[p_.material_index].material if p_.material_index < len(o_.material_slots) else None): _idk[i_][k_] += 1
for i_, c_ in _idk.items():
    if len(c_) == 1: ID_KIND[i_] = next(iter(c_))
    else: L("light ID %d is on lamps of several kinds %s: left unlit" % (i_, dict(c_)))
L("light IDs from the car's own lamps: %s" % ID_KIND)
def rx_first(rules, b):
    for rx, job in rules:
        if re.search(rx, b, re.I): return job
    return None
LAMP_BODY = re.compile(r"^light[a-z]?$|light_?set|reflect|chrome|bowl|bulb", re.I)   # GTA lamp-body pictures (lighta, light_seta_d ...), not glass or a glow
LIGHT_PARTS = (("headlight", "head_lens"), ("extralight", "head_lens"), ("taillight", "tail_lens"), ("brakelight", "tail_lens"), ("reversinglight", "reverse_lens"), ("indicator", "indicator_lens"))

# ---- 3. which source parts are dropped / opened / mirrors
# The wheels. GTA draws wheel_lf at every corner unless the model has its own rear wheel (wheel_lr / wheel_rr), and draws each hub (brake)
# where the model has one. Front wheel: wheel_lf, else wheel_rf. Rear wheel: wheel_lr, else wheel_rr, else the front one. The same for the hubs.
# A right-hand source is mirrored to the left first, so every wheel below is built from a left-hand wheel.
WCHECK_WARN = []
def _first(*names): return next((n_ for n_ in names if n_ in P), None)
FRONT_W = _first("wheel_lf", "wheel_rf"); REAR_W = _first("wheel_lr", "wheel_rr")
FRONT_H = _first("hub_lf", "hub_rf"); REAR_H = _first("hub_lr", "hub_rr")
if FRONT_W is None:
    fail("no front wheel mesh: the model has no part named wheel_lf or wheel_rf")
if REAR_W is None and not any(b_ in BONES for b_ in ("wheel_lr", "wheel_rr")):
    fail("no rear wheel bones: the model has no wheel_lr or wheel_rr bone, so the rear wheels have nowhere to go")
WHEEL_SRC = {n_ for n_ in (FRONT_W, REAR_W, FRONT_H, REAR_H) if n_}
_extra = sorted(b_ for b_ in BONES if re.match(r"^wheel_[lr]m\d", b_))
if _extra:
    WCHECK_WARN.append("middle wheels %s are not built: only four-wheel cars are supported" % _extra)
def _left_bone(axle_):   # the axle's left wheel bone, or its right one mirrored
    if "wheel_l" + axle_ in BONES: return BONES["wheel_l" + axle_]
    if "wheel_r" + axle_ in BONES: p_ = BONES["wheel_r" + axle_]; return Vector((-p_.x, p_.y, p_.z))
    return None
for n in sorted(WHEEL_SRC):
    if n[-2] == "r":     # wheel_rf, hub_rr ...: mirror across the car's middle, faces turned back out
        P[n].data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
        _bm = bmesh.new(); _bm.from_mesh(P[n].data); bmesh.ops.reverse_faces(_bm, faces=_bm.faces[:]); _bm.to_mesh(P[n].data); _bm.free()
        L("wheel source %s is on the right: mirrored to the left" % n)
L("wheel sources: front %s + %s, rear %s + %s" % (FRONT_W, FRONT_H, REAR_W or "(front wheel)", REAR_H or ("(front hub)" if REAR_W is None else "none")))
DROP = re.compile(r"^(suspension_|hub_|wheel_)")
for n in list(P):
    if DROP.match(n) and n not in WHEEL_SRC or n in S["drop_parts"]:
        if n in P: bpy.data.objects.remove(P.pop(n), do_unlink=True)
OPENERS = [n for n in P if re.match(r"^(door_[dp]side_[fr]|bonnet|boot)$", n)]
doorbox = {}
for n in OPENERS:
    if n.startswith("door_"):
        vs = [v.co for v in P[n].data.vertices]
        doorbox[n] = ([min(v[i] for v in vs) for i in range(3)], [max(v[i] for v in vs) for i in range(3)])
SKIPJOIN = re.compile(r"^(window_|wheel_|hub_|headlight|taillight|brakelight|reversinglight|indicator|extralight|steeringwheel|bodyshell|chassis|dials)")
JOIN = {}
for n, o in P.items():       # a piece that sits on an opener's bone origin belongs to that opener (the hood's outer skin)
    if n in OPENERS or SKIPJOIN.match(n) or n in S["no_auto_join"] or n not in BONES: continue
    for op in OPENERS:
        if op in BONES and (BONES[n] - BONES[op]).length < 0.01: JOIN[n] = op; break
for n, pb_ in MIRROR_FIXED.items():     # a piece put back by mirroring (gta_import) rides the opener its bone hangs from
    if n in P and pb_ in OPENERS and n not in S["no_auto_join"]: JOIN[n] = pb_
MIRRORS = set()
for n, o in P.items():       # a small piece beside a front door, out at its outer edge, is that door's mirror
    if n in OPENERS or n in JOIN or SKIPJOIN.match(n) or n in S["no_auto_join"]: continue
    if len(o.data.polygons) > 0.03 * TOTAL_POLYS: continue
    vs = [v.co for v in o.data.vertices]
    if not vs: continue
    c = Vector([(min(v[i] for v in vs) + max(v[i] for v in vs)) / 2 for i in range(3)])
    for dn, (lo_, hi_) in doorbox.items():
        if not dn.endswith("_f"): continue
        side = -1 if "dside" in dn else 1
        outer = max(abs(lo_[0]), abs(hi_[0]))
        # out at the door's outer edge, but no farther than a mirror reaches (a piece far beyond it is a stray, not a mirror)
        if c.x * side > 0 and outer - 0.08 <= abs(c.x) <= outer + 0.45 and lo_[1] - 0.15 <= c.y <= hi_[1] + 0.15:
            JOIN[n] = dn; MIRRORS.add(n); break
# A piece whose bone hangs from an opener in the source moves with it in GTA: a hatchback's rear glass, spoiler and struts, and the
# inner half of a split tail light, on the boot. Lamps count here (the outer half of a split lamp hangs from the body and stays).
# Only when the piece really sits on the opener (its middle inside the opener's box, 5 cm slack): modders also hang pieces far off
# the boot from it (a pickup's cab-roof brake light on the tailgate), and those stay on the body.
SKIPPARENT = re.compile(r"^(window_|wheel_|hub_|steeringwheel|bodyshell|chassis|dials)")
def _wbox(o_):
    ws_ = [v.co for v in o_.data.vertices]     # meshes are in world space here (step 1)
    return [min(p[i] for p in ws_) for i in range(3)], [max(p[i] for p in ws_) for i in range(3)]
for n in P:
    if n in OPENERS or n in JOIN or SKIPPARENT.match(n) or n in S["no_auto_join"]: continue
    op = BONE_PARENT.get(n)
    if op not in OPENERS or not P[n].data.vertices or not P[op].data.vertices: continue
    (lo_, hi_), (olo, ohi) = _wbox(P[n]), _wbox(P[op])
    mid = [(lo_[i] + hi_[i]) / 2 for i in range(3)]
    if all(olo[i] - 0.05 <= mid[i] <= ohi[i] + 0.05 for i in range(3)): JOIN[n] = op
    else: L("bone of %s hangs from %s, but the piece is not on it: left on the body" % (n, op))
for a, b in S["join"].items():
    if a in P and b in P: JOIN[a] = b
for a in S["mirror_parts"]: MIRRORS.add(a)
for a, b in JOIN.items(): L("auto-join: %s -> %s%s" % (a, b, " (mirror)" if a in MIRRORS else ""))

# ---- 4. wheel: tire / rim / brake by shape (the material that reaches farthest from the axle is the tire)
def wheel_jobs(wo):
    vs = [v.co for v in wo.data.vertices]
    wc_y = (min(v.y for v in vs) + max(v.y for v in vs)) / 2; wc_z = (min(v.z for v in vs) + max(v.z for v in vs)) / 2
    rad = collections.defaultdict(float)
    for p in wo.data.polygons:
        mn_ = wo.material_slots[p.material_index].material.name
        for vi in p.vertices:
            v = wo.data.vertices[vi].co; rad[mn_] = max(rad[mn_], math.hypot(v.y - wc_y, v.z - wc_z))
    WJOB = {}
    tire_name = max(rad, key=rad.get)
    if S["wheel"].get("tire"):
        tire_name = next((m for m in rad if re.search(S["wheel"]["tire"], m, re.I)), tire_name)
    for m_ in rad:
        b = base(m_)
        if m_ == tire_name: WJOB[m_] = "tire"
        elif S["wheel"].get("brake") and re.search(S["wheel"]["brake"], b, re.I) or re.search(r"brake|caliper|disc|rotor", b, re.I): WJOB[m_] = "plastic_black"
        elif S["wheel"].get("rim") and not re.search(S["wheel"]["rim"], b, re.I): WJOB[m_] = "plastic_black"
        else: WJOB[m_] = "rim"
    L("wheel materials %s: %s (radius m: %s)" % (wo.name, WJOB, {k: round(v, 3) for k, v in rad.items()}))
    return WJOB
WJOBS = {n_: wheel_jobs(P[n_]) for n_ in (FRONT_W, REAR_W) if n_}

# ---- 5. material -> job
MIRRORRULES = [(r"PRIMARY", "SECONDARY"), (r"turn|indic|signal|dials", "indicator_lens"), (r"salon|mirror|glass", "chrome")]
GENERIC = [(r"leather|carpet|seat|upholst|interior|headliner|cabin", "interior"), (r"PRIMARY", "PRIMARY"), (r"SECONDARY", "SECONDARY"),
           (r"glass|window|windscreen|windshield", "glass"), (r"carbon", "carbon"), (r"chrome|silver|satin|billet", "chrome"),
           (r"badge|logo|emblem", "badge"), (r"grille", "grille"), (r"reflector", "reflector")]
SRCLIST = []
JOBTRIS = collections.defaultdict(collections.Counter)
SRCMAT = {}
def job_of(mn, part):
    b = base(mn)
    if part in WJOBS: return WJOBS[part].get(mn, "rim")
    if part in WHEEL_SRC: return "plastic_black"     # a hub
    for key, rules in S["part_material_jobs"].items():
        if part.startswith(key):
            j = rx_first(rules, b) or rx_first(rules, mn)
            if j: return j
    j = rx_first(S["material_jobs"], b) or rx_first(S["material_jobs"], mn)   # the name without .001 first, then the full name (a variant such as [PRIMARY].004)
    if j: return j
    if part.startswith(("window_", "windscreen")): return "glass"
    for pref, job in LIGHT_PARTS:
        if part.startswith(pref):
            if re.search(r"black|housing|metal", b, re.I): return "plastic_black"
            if LAMP_BODY.search(b): return "reflector"     # the bowl and bulb behind the lens: drawn as the lamp's inside, not as lens
            return job
    if part in MIRRORS:
        return rx_first(MIRRORRULES, b) or "plastic_black"
    j = rx_first(GENERIC, b) or "plastic_black"
    if j == "PRIMARY": livery_job(mn)      # a settings rule (material_jobs comes first) can still keep a picture off the livery
    elif j == "SECONDARY" or lamp_shader(bpy.data.materials.get(mn)): j = print_job(mn) or j   # the lamp-shader faces then glow per face, below
    return j

INNER_RX = S["inner_material_regex"]
for n, o in P.items():
    me = o.data
    kp = me.attributes.new("keepall", "INT", "FACE")   # 1 = the thinning step must not touch this piece (settings: protect_from_thinning)
    for d_ in kp.data: d_.value = 1 if n in S["protect_from_thinning"] else 0
    att = me.attributes.new("inner", "INT", "FACE")
    slots = [s.material.name if s.material else "" for s in o.material_slots]
    for p in me.polygons:
        if INNER_RX:
            att.data[p.index].value = 1 if re.search(INNER_RX, slots[p.material_index]) else 0
        else:  # no marker in the source: a face looking toward the car's middle line is an inner face
            c = p.center
            att.data[p.index].value = 1 if (p.normal.x * c.x + p.normal.y * c.y) < -0.002 else 0
    newslots = {i: job_of(sn, n) for i, sn in enumerate(slots)}
    facejob = [newslots[p.material_index] for p in me.polygons]
    _ids = None
    for i, sn in enumerate(slots):     # a print on GTA's lamp shader: each face glows with the light its ID names (an unknown ID: no glow)
        if not lamp_shader(bpy.data.materials.get(sn)): continue
        if sn in LIVERY_SRC:     # the livery's own glow is Mantle's per-livery setting: only noted here (<name>_paint.json "livery_glow")
            _ids = _ids or face_light_ids(o) or []
            for p in me.polygons:
                if p.material_index == i and p.index < len(_ids) and _ids[p.index] in ID_KIND: LIVERY_GLOW[ID_KIND[_ids[p.index]]] += 1
            continue
        if not newslots[i].startswith("print"): continue
        _ids = _ids or face_light_ids(o)
        if not _ids: continue
        for p in me.polygons:
            if p.material_index == i and _ids[p.index] in ID_KIND: facejob[p.index] = print_job(sn, ID_KIND[_ids[p.index]])
    _sa = me.attributes.new("srcmat", "INT", "FACE")   # which source material each face came from (kept for the log and for fixing a car by hand)
    for p in me.polygons:
        _sn = slots[p.material_index]
        if _sn not in SRCLIST: SRCLIST.append(_sn)
        _sa.data[p.index].value = SRCLIST.index(_sn)
    for p in me.polygons:
        JOBTRIS[facejob[p.index]][slots[p.material_index]] += 1
    orig = [pp.material_index for pp in me.polygons]
    srcmats = {sn: bpy.data.materials.get(sn) for sn in slots}
    for sn, m_ in srcmats.items(): SRCMAT[sn] = m_
    me.materials.clear()
    names_ = []
    for tn in dict.fromkeys(facejob):
        me.materials.append(M[tn]); names_.append(tn)
    for p in me.polygons:
        p.material_index = names_.index(facejob[p.index])

for _k in M:
    if JOBTRIS[_k]:
        L("job %s <- %s" % (_k, ", ".join("%s (%d)" % (a_, b_) for a_, b_ in JOBTRIS[_k].most_common(12))))
# ---- 6. pictures: each job gets the picture of its biggest readable source material (settings can name one)
for k in PICJOBS:
    pn = S["pictures"].get(k)
    if pn is None:
        for sn, cnt in JOBTRIS[k].most_common():
            d = diffuse_name(SRCMAT.get(sn))
            if d and (d + ".dds") in DDS: pn = d; break
    if pn is None or (pn + ".dds") not in DDS:
        if JOBTRIS[k]: L("picture %s: none readable (flat colour)" % k)
        continue
    im = DDS[pn + ".dds"]
    nt = M[k].node_tree; pb = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = im; tex.label = "diffuse"
    nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"])
    L("picture %s <- %s (%dx%d)" % (k, im.name, im.size[0], im.size[1]))
UNREAD = sorted({diffuse_name(m_) for m_ in SRCMAT.values() if m_ and diffuse_name(m_) and (diffuse_name(m_) + ".dds") not in DDS and re.search(r"[a-z]", diffuse_name(m_)) and not re.search(r"^(black|blank|white|grey|spec|normal|vehicle_generic|blick)", diffuse_name(m_))})
L("pictures not readable (no image in the car's files): %s" % UNREAD)

# ---- 7. wheels: the front wheel (with its hub/brake) and the rear one (the model's own rear wheel and hub, or the front's), each built into
# two corners, level and mirrored. They are reduced later (stage_hidden) if heavy.
from mathutils.bvhtree import BVHTree
def _wk(v): return (round(v.co.x * 1e3), round(v.co.y * 1e3), round(v.co.z * 1e3))
def _crossings(a_data, b_data):
    """number of triangle pairs of two meshes that intersect"""
    def tree(d):
        d.calc_loop_triangles()
        return BVHTree.FromPolygons([v.co.copy() for v in d.vertices], [tuple(t.vertices) for t in d.loop_triangles])
    return len(tree(a_data).overlap(tree(b_data)))
def _spin_crossings(cal_data, rim_data, steps=24):
    """the most triangle pairs of the caliper and the rim that intersect at any point of a full turn of the rim about the axle (the source's
    X axis): the rim spins and the caliper does not, so the caliper must clear the rim at every angle, not only as it rests"""
    cal_data.calc_loop_triangles(); rim_data.calc_loop_triangles()
    ct = BVHTree.FromPolygons([v.co.copy() for v in cal_data.vertices], [tuple(t.vertices) for t in cal_data.loop_triangles])
    rt = [tuple(t.vertices) for t in rim_data.loop_triangles]; rv = [v.co.copy() for v in rim_data.vertices]
    worst = 0
    for k in range(steps):
        rot = Matrix.Rotation(2 * math.pi * k / steps, 3, "X")
        worst = max(worst, len(BVHTree.FromPolygons([rot @ p for p in rv], rt).overlap(ct)))
    return worst

def build_wheel(label, wheel_n, hub_n, hub_shift=None):
    """One wheel from its source meshes: a copy of the wheel joined with a copy of its hub (moved by hub_shift first), centred on its tire, and
    the brake caliper split off onto its own mesh. Returns {data: the wheel mesh centred on the axle, hub: the caliper mesh or None,
    c: the tire centre in the source, r: the tire radius, text, warn}."""
    W = P[wheel_n].copy(); W.data = P[wheel_n].data.copy(); bpy.context.scene.collection.objects.link(W)
    if hub_n:
        H = P[hub_n].copy(); H.data = P[hub_n].data.copy(); bpy.context.scene.collection.objects.link(H)
        if hub_shift is not None: H.data.transform(Matrix.Translation(hub_shift))
        bpy.ops.object.select_all(action="DESELECT")
        W.select_set(True); H.select_set(True)
        bpy.context.view_layer.objects.active = W
        bpy.ops.object.join()
    tire_idx = [i for i, s in enumerate(W.material_slots) if s.material and s.material.name == "tire"][0]
    tv = {v for p in W.data.polygons if p.material_index == tire_idx for v in p.vertices}
    tpts = [W.data.vertices[i].co for i in tv]
    c = Vector(((min(p.x for p in tpts) + max(p.x for p in tpts)) / 2, (min(p.y for p in tpts) + max(p.y for p in tpts)) / 2, (min(p.z for p in tpts) + max(p.z for p in tpts)) / 2))
    R = (max(p.z for p in tpts) - min(p.z for p in tpts)) / 2
    L("%s wheel (%s + %s): centre in source %s radius %.4f" % (label, wheel_n, hub_n, tuple(round(x, 4) for x in c), R))
    W.data.transform(Matrix.Translation(-c))

    # 7b. the brake caliper: brake pieces that are not round (a disc or a hub cap goes all the way round the axle, a caliper covers part of the
    # circle) hang on a hub that steers with the wheel but does not spin. It must sit inside the rim: no triangle of it may cross a triangle of the
    # rim at any angle of the rim's turn. Steering turns rim and caliper together about the same point, so it changes nothing between them; the
    # right-hand corners carry the same caliper mirrored and the same rim turned round, which is the same clearance as the left (the turn test
    # covers every angle of the rim).
    text = "no caliper"; warn = []
    HUBDATA = None
    _bmA = bmesh.new(); _bmA.from_mesh(W.data); _bmA.faces.ensure_lookup_table()
    _names = [m.name if m else "" for m in W.data.materials]
    _brake = [f for f in _bmA.faces if _names[f.material_index] not in ("tire", "rim")]
    _vmap = collections.defaultdict(list)
    for f in _brake:
        for v in f.verts: _vmap[_wk(v)].append(f)
    _seen = set(); _cal = set()
    for f in _brake:
        if f.index in _seen: continue
        _st = [f]; _seen.add(f.index); _comp = []
        while _st:
            g = _st.pop(); _comp.append(g)
            for v in g.verts:
                for h in _vmap[_wk(v)]:
                    if h.index not in _seen: _seen.add(h.index); _st.append(h)
        _ang = sorted(math.atan2(v.co.z, v.co.y) for g in _comp for v in g.verts)    # around the axle (the source's X axis)
        _gaps = [_ang[i + 1] - _ang[i] for i in range(len(_ang) - 1)] + [_ang[0] + 2 * math.pi - _ang[-1]]
        if 360 - math.degrees(max(_gaps)) <= 300: _cal.update(g.index for g in _comp)
    if _cal:
        _bmB = bmesh.new(); _bmB.from_mesh(W.data); _bmB.faces.ensure_lookup_table()
        bmesh.ops.delete(_bmA, geom=[f for f in _bmA.faces if f.index in _cal], context="FACES")
        bmesh.ops.delete(_bmA, geom=[v for v in _bmA.verts if not v.link_faces], context="VERTS")
        bmesh.ops.delete(_bmB, geom=[f for f in _bmB.faces if f.index not in _cal], context="FACES")
        bmesh.ops.delete(_bmB, geom=[v for v in _bmB.verts if not v.link_faces], context="VERTS")
        HUBDATA = W.data.copy()
        _bmB.to_mesh(HUBDATA); _bmB.free()
        _bmA.to_mesh(W.data); _bmA.free()
        # the rim (only the rim material) as its own mesh for the crossing test
        _rim_i = [i for i, n_ in enumerate(_names) if n_ == "rim"]
        _bmR = bmesh.new(); _bmR.from_mesh(W.data); _bmR.faces.ensure_lookup_table()
        bmesh.ops.delete(_bmR, geom=[f for f in _bmR.faces if f.material_index not in _rim_i], context="FACES")
        bmesh.ops.delete(_bmR, geom=[v for v in _bmR.verts if not v.link_faces], context="VERTS")
        _rim = bpy.data.meshes.new("rimtest"); _bmR.to_mesh(_rim); _bmR.free()
        _o = 1.0 if c.x > 0 else -1.0      # outward (away from the car) is +X for a wheel on the positive side
        _cv = [v.co for v in HUBDATA.vertices]
        _rmin = min(math.hypot(p.y, p.z) for p in _cv); _rmax = max(math.hypot(p.y, p.z) for p in _cv)
        _rimR = max(math.hypot(v.co.y, v.co.z) for v in _rim.vertices)
        _band = [v.co.x * _o for v in _rim.vertices if _rmin - 0.01 <= math.hypot(v.co.y, v.co.z) <= min(_rmax + 0.01, 0.85 * _rimR)]
        _calmax = max(p.x * _o for p in _cv)
        _n0 = _spin_crossings(HUBDATA, _rim)
        _CAP = 0.04     # a caliper is moved inboard by at most 4 cm (it hangs just behind the spokes); further than that is not the same car
        _shift = min(_CAP, max(0.0, _calmax - (min(_band) - 0.005))) if _band else 0.0
        if _n0 > 0:
            HUBDATA.transform(Matrix.Translation((-_o * _shift, 0, 0)))
            _n = _spin_crossings(HUBDATA, _rim)
            while _n > 0 and _shift < _CAP:
                HUBDATA.transform(Matrix.Translation((-_o * 0.004, 0, 0))); _shift += 0.004; _n = _spin_crossings(HUBDATA, _rim)
            _need = None
            if _n > 0:      # cannot be cleared within the cap: find how far it would take (up to 12 cm), then leave it where the source has it
                _try = _shift
                while _try < 0.12:
                    HUBDATA.transform(Matrix.Translation((-_o * 0.004, 0, 0))); _try += 0.004
                    if _spin_crossings(HUBDATA, _rim) == 0: _need = _try; break
                HUBDATA.transform(Matrix.Translation((_o * _try, 0, 0))); _shift = 0.0; _n = _n0
        else:
            _n = 0; _need = None
        bpy.data.meshes.remove(_rim)
        text = "caliper %d triangles on a hub: %d triangle pairs crossed the turning rim in the source, moved inboard %.1f cm, %d cross now" % (len(HUBDATA.polygons), _n0, _shift * 100, _n)
        if _n > 0: warn.append("caliper crosses the turning rim: %d triangle pairs, part hub_*, could not be cleared within 4 cm (%s), left as the source has it" % (
            _n, "moving it %.1f cm inboard would clear it, which is no longer the same car" % (_need * 100) if _need else "even 12 cm inboard would not clear it: the caliper needs a smaller shape or the rim a deeper dish"))
    else:
        _bmA.free()
    data = W.data
    bpy.data.objects.remove(W, do_unlink=True)
    return {"data": data, "hub": HUBDATA, "c": c, "r": R, "text": text, "warn": warn}

FW = build_wheel("front", FRONT_W, FRONT_H)
if REAR_W is None and REAR_H is None:
    RW = FW                                   # the front wheel and hub at all four corners
elif REAR_W is None:                          # the front wheel with the model's own rear hub, moved from the rear axle to the front one
    RW = build_wheel("rear", FRONT_W, REAR_H, hub_shift=_left_bone("f") - _left_bone("r"))
else:                                         # the model's own rear wheel (and its own hub, if it has one)
    RW = build_wheel("rear", REAR_W, REAR_H)
c = FW["c"]; WHEEL_R = FW["r"]
WCHECK_TEXT = FW["text"] if RW is FW else "front: %s; rear: %s" % (FW["text"], RW["text"])
WCHECK_WARN += FW["warn"] + ([] if RW is FW else ["rear wheel: " + w_ for w_ in RW["warn"]])
L("wheel check: %s" % WCHECK_TEXT)

def decimate_mesh(ob, target):
    ob.data.calc_loop_triangles(); n = len(ob.data.loop_triangles)
    if n <= target: return
    bm_ = bmesh.new(); bm_.from_mesh(ob.data); bmesh.ops.remove_doubles(bm_, verts=bm_.verts, dist=1e-5); bm_.to_mesh(ob.data); bm_.free()
    mod = ob.modifiers.new("Decimate", "DECIMATE"); mod.ratio = max(0.05, target / n); mod.use_collapse_triangulate = True
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    ob.data.calc_loop_triangles(); L("wheel reduced %d -> %d triangles" % (n, len(ob.data.loop_triangles)))
for n in WHEEL_SRC:
    bpy.data.objects.remove(P.pop(n), do_unlink=True)
def axle(a, b):
    ys = [BONES[n_].y for n_ in (a, b) if n_ in BONES]
    return sum(ys) / len(ys) if ys else None
fy = axle("wheel_lf", "wheel_rf"); ry = axle("wheel_lr", "wheel_rr")
ftx = abs(c.x)
if REAR_W is None:      # the front wheel at the rear bones, as far out from them as the front wheel sits from its own bone
    _rb = [abs(BONES[n_].x) for n_ in ("wheel_lr", "wheel_rr") if n_ in BONES]
    rtx = sum(_rb) / len(_rb) + (abs(c.x) - abs(_left_bone("f").x))
    rz = c.z
else:                   # its own wheel: its own track, the bottom of its tire level with the front tire's
    rtx = abs(RW["c"].x)
    rz = c.z - WHEEL_R + RW["r"]
WHEEL_RS = {"wheel_lf": WHEEL_R, "wheel_rf": WHEEL_R, "wheel_lr": RW["r"], "wheel_rr": RW["r"]}
L("axle y front %.3f rear %.3f; track half front %.3f rear %.3f; tire radius front %.4f rear %.4f" % (fy, ry, ftx, rtx, WHEEL_R, RW["r"]))
spots = {"wheel_lf": (-ftx, fy, c.z, FW), "wheel_rf": (ftx, fy, c.z, FW), "wheel_lr": (-rtx, ry, rz, RW), "wheel_rr": (rtx, ry, rz, RW)}
wheels = {}
for nm, (x, y, z, wh) in spots.items():
    o = bpy.data.objects.new(nm, wh["data"].copy())
    bpy.context.scene.collection.objects.link(o)
    if x > 0: o.data.transform(Matrix.Rotation(math.pi, 4, "Z"))
    o.data.transform(Matrix.Translation((x, y, z)))
    wheels[nm] = o
    if wh["hub"] is not None:
        h = bpy.data.objects.new("hub_" + nm[6:], wh["hub"].copy())
        bpy.context.scene.collection.objects.link(h)
        if x > 0:   # the wheel is turned round (its face looks out), but the caliper is mirrored across the car's middle so it stays on the same
                    # side of the axle as on the left (turning it put the passenger-side caliper behind the axle); then its faces are turned back out
            h.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
            _bmh = bmesh.new(); _bmh.from_mesh(h.data); bmesh.ops.reverse_faces(_bmh, faces=_bmh.faces[:]); _bmh.to_mesh(h.data); _bmh.free()
        h.data.transform(Matrix.Translation((x, y, z)))
        wheels[h.name] = h

# ---- 8. group parts: openers keep their own pieces, windows stay separate (they ride the door), the rest is the body
G = collections.defaultdict(list)
for n in P:
    if n in OPENERS or n.startswith("window_"): G[n].append(n)
STEER_SRC = next((n for n in P if re.match(r"^steering_?wheel", n, re.I)), None)
if STEER_SRC:
    G["steering_wheel"].append(STEER_SRC)
    if "steering_wheel" not in BONES:
        _sv = [v.co for v in P[STEER_SRC].data.vertices]
        BONES["steering_wheel"] = BONES.get(STEER_SRC) or Vector([(min(v[i] for v in _sv) + max(v[i] for v in _sv)) / 2 for i in range(3)])
    L("steering wheel: part steering_wheel <- %s (bone at %s)" % (STEER_SRC, tuple(round(x, 3) for x in BONES["steering_wheel"])))
else:
    L("steering wheel: none in the source (no steering_wheel bone)")
for a, b in JOIN.items():
    if a in P and b in G: G[b].append(a)
used = {x for v in G.values() for x in v}
G["body"] = [n for n in P if n not in used]
parts = {}
for gn, members in G.items():
    objs = [P[m] for m in members if m in P]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1: bpy.ops.object.join()
    objs[0].name = gn; objs[0].data.name = gn
    parts[gn] = objs[0]
    L("part %s <- %s" % (gn, members))
parts.update(wheels)

# ---- 9. nose to +X (source forward is +Y), then ground at z = 0
rot = Matrix.Rotation(-math.pi / 2, 4, "Z")
for o in parts.values(): o.data.transform(rot)
minz = min(v.co.z for o in parts.values() for v in o.data.vertices)
for o in parts.values(): o.data.transform(Matrix.Translation((0, 0, -minz)))
GROUND_SHIFT = -minz
L("ground shift %.4f" % GROUND_SHIFT)
for n, o in parts.items():
    o.data.update(); o.data.calc_loop_triangles()
    L("  %s: %d tris, mats %s" % (n, len(o.data.loop_triangles), [m.name for m in o.data.materials]))
for o in list(bpy.data.objects):
    if o not in parts.values(): bpy.data.objects.remove(o, do_unlink=True)

# ---- 10. glass shells. A window pane that the source models with two surfaces a millimetre or so apart (an outer one facing out and an inner one
# facing in) is drawn by the game as four stacked see-through layers where the surfaces overlap and two where they do not, which shows as dark
# triangles and blocks over the glass (the Camaro's and the Jeep's windshields). Keep the outer surface and drop the inner one, only where the outer
# one lies right behind all of it, so no gap opens. This is cleaning the source's duplicate surface, so it runs before the before/after check's
# reference is taken (the check then compares like with like).
from mathutils.bvhtree import BVHTree
def drop_glass_shells(gap=0.015):
    glass = {}
    allc = []
    for n_, o_ in parts.items():
        o_.data.calc_loop_triangles()
        mw = o_.matrix_world
        tris = []
        for t_ in o_.data.loop_triangles:
            mi = t_.material_index
            m_ = o_.material_slots[mi].material if mi < len(o_.material_slots) else None
            if not (m_ and "glass" in m_.name.lower()): continue
            vs = [mw @ o_.data.vertices[v_].co for v_ in t_.vertices]
            nrm = (vs[1] - vs[0]).cross(vs[2] - vs[0])
            if nrm.length < 1e-12: continue
            tris.append((t_, vs, nrm.normalized()))
            allc.append((vs[0] + vs[1] + vs[2]) / 3.0)
        if tris: glass[n_] = tris
    if not allc: return 0
    cabin = sum(allc, Vector()) / len(allc)
    removed = 0
    for n_, tris in glass.items():
        o_ = parts[n_]
        verts = [v for _, vs, _ in tris for v in vs]
        bvh = BVHTree.FromPolygons(verts, [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))], all_triangles=True, epsilon=0.0)
        kill = set()
        for i, (t_, vs, nrm) in enumerate(tris):
            c = (vs[0] + vs[1] + vs[2]) / 3.0
            if nrm.dot(cabin - c) <= 0: continue          # this surface faces away from the cabin: it is the outer one, keep it
            covered = True
            for s_ in (c, c + (vs[0] - c) * 0.6, c + (vs[1] - c) * 0.6, c + (vs[2] - c) * 0.6):
                hit = bvh.ray_cast(s_ - nrm * 2e-5, -nrm, gap)
                if hit[0] is None or hit[2] == i or tris[hit[2]][2].dot(nrm) > -0.7:
                    covered = False; break
            if covered: kill.add(t_.polygon_index)
        if kill:
            bm_ = bmesh.new(); bm_.from_mesh(o_.data); bm_.faces.ensure_lookup_table()
            bmesh.ops.delete(bm_, geom=[bm_.faces[k] for k in kill], context="FACES")
            bm_.to_mesh(o_.data); bm_.free(); o_.data.update()
            removed += len(kill)
    return removed
L("glass shells: %d inner glass faces dropped (the outer surface lies right behind them)" % drop_glass_shells())
