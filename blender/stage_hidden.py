# Stage: remove faces nobody sees and thin the heaviest pieces, but only the parts of this that pass the before/after check on this car.
# A risky step is kept only when the rebuilt car still matches the source (check_fidelity.py); otherwise it is undone and said so in the log.
import bpy, bmesh, re, collections, os, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree
objs = [o for o in bpy.data.objects if o.type == "MESH"]
P = {o.name: o for o in objs}
GL = re.compile(r"glass|lens", re.I)
OPEN = re.compile(r"^(door_|bonnet|boot|wheel_|hub_|window_|steering_wheel)")
def glassy(o, mi):
    m = o.material_slots[mi].material if mi < len(o.material_slots) else None
    return bool(m and GL.search(m.name))
def tri_count():
    t = 0
    for n_, o_ in P.items():
        o_.data.calc_loop_triangles(); t += len(o_.data.loop_triangles)
    return t
def backup(): return {n: o.data.copy() for n, o in P.items()}
def restore(bk):
    for n, me_ in bk.items(): P[n].data = me_.copy()
def check(tag, tol):
    r = fid_compare(REF, fid_snapshot(list(P.values())), tol=tol)
    L("check after %s: %s" % (tag, r["text"]))
    for w in r["where"]: L("   " + w)
    return r

# Where people look from. Rays leaving a face at a few fixed angles miss the narrow view a footwell or kick panel has through a window, so a face
# also counts as seen when a straight line reaches it from an eye in the cabin (over each seat, from the source's seat bones) or from outside an
# open door. Without this the step removed the footwell walls and the wheel arch showed through (Camaro, BMW: daylight under the dash).
def cabin_eyes():
    eyes = []
    seats = sorted(n for n in BONES if re.match(r"^seat_[dp]side_[fr]$", n))
    for n in seats:
        p = BONES[n]; st = Vector((p.y, -p.x, p.z + GROUND_SHIFT))          # source frame -> Mantle frame (as stage_parts turned the car)
        eyes += [st + Vector((0, 0, 0.65)), st + Vector((0, 0, 0.35)), st + Vector((0.25, 0, 0.55))]   # head, chest, leaning forward
    if seats:
        fs = [BONES[n] for n in seats if n.endswith("_f")] or [BONES[n] for n in seats]
        mid = sum(fs, Vector()) / len(fs)
        eyes.append(Vector((mid.y, -mid.x, mid.z + GROUND_SHIFT + 0.6)))   # between the front seats
    else:   # no seat bones: the middle of the interior faces
        pts = [o.matrix_world @ pp.center for o in P.values() if not OPEN.match(o.name) for pp in o.data.polygons
               if pp.material_index < len(o.material_slots) and o.material_slots[pp.material_index].material and o.material_slots[pp.material_index].material.name.startswith("interior")]
        if pts:
            c = sum(pts, Vector()) / len(pts); eyes += [c + Vector((0, 0, 0.45)), c + Vector((0.4, 0, 0.45)), c + Vector((-0.4, 0, 0.45))]
    ncab = len(eyes)
    for n, o in P.items():   # outside each door opening, standing back a little
        if not n.startswith("door_"): continue
        vs = [o.matrix_world @ v.co for v in o.data.vertices]
        if not vs: continue
        lo = Vector([min(v[i] for v in vs) for i in range(3)]); hi = Vector([max(v[i] for v in vs) for i in range(3)])
        side = 1.0 if (lo.y + hi.y) > 0 else -1.0
        for fx in (0.25, 0.5, 0.75):
            eyes.append(Vector((lo.x + (hi.x - lo.x) * fx, (hi.y if side > 0 else lo.y) + 0.9 * side, (lo.z + hi.z) / 2 + 0.25)))
    return eyes, ncab
EYES, _ncab = cabin_eyes()
FID_EYES[:] = EYES[:_ncab]      # the before/after check also looks around the cabin from these (check_fidelity.py)
L("viewpoints: %d in the cabin, %d outside the door openings" % (_ncab, len(EYES) - _ncab))

def remove_hidden(careful):
    verts, polys = [], []
    for o in P.values():
        if OPEN.match(o.name): continue
        o.data.calc_loop_triangles()
        base = len(verts)
        verts.extend(v.co.copy() for v in o.data.vertices)
        for t in o.data.loop_triangles:
            if not glassy(o, t.material_index):
                polys.append((base + t.vertices[0], base + t.vertices[1], base + t.vertices[2]))
    bvh = BVHTree.FromPolygons(verts, polys)
    o = P["body"]
    bm = bmesh.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table()
    seen = set(); dele = []; dups = 0; nview = [0]
    for f in bm.faces:
        c = f.calc_center_median()
        key = (round(c.x, 3), round(c.y, 3), round(c.z, 3), len(f.verts))
        if key in seen:
            dele.append(f); dups += 1; continue
        seen.add(key)
        if glassy(o, f.material_index): continue
        n = f.normal.copy()
        t1 = n.cross(Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))).normalized()
        t2 = n.cross(t1).normalized()
        if careful:   # more directions, down to nearly flat to the surface: a face that can be seen from any outside angle stays
            dirs = [n] + [(n * k + t * (1 - k * k) ** 0.5).normalized() for k in (0.8, 0.5, 0.2, 0.05) for t in (t1, -t1, t2, -t2, (t1 + t2).normalized(), (t1 - t2).normalized(), (-t1 + t2).normalized(), (-t1 - t2).normalized())]
        else:
            dirs = [n] + [(n * 0.57 + t * 0.82).normalized() for t in (t1, -t1, t2, -t2)] + [(n * 0.57 + (a + b) * 0.58).normalized() for a in (t1, -t1) for b in (t2, -t2)]
        pts = [c] + [f.calc_center_median() * 0.4 + v.co * 0.6 for v in f.verts[:3]]
        vis = False
        for p in pts:
            for sgn in (1, -1):
                org = p + n * (0.003 * sgn)
                for d in dirs:
                    if bvh.ray_cast(org, d * sgn, 60.0)[0] is None:
                        vis = True; break
                if vis: break
            if vis: break
        if not vis:   # no fixed ray got out: is it seen from where a person can be? (a big face is sampled about every 5 cm: part of it may show)
            vpts = list(pts)
            _ar = f.calc_area()
            if _ar > 0.0025 and len(f.verts) >= 3:
                _k = min(8, int(math.ceil(math.sqrt(_ar) / 0.05)))
                _a, _b, _c = f.verts[0].co, f.verts[1].co, f.verts[2].co
                _tris = [(f.verts[0].co, f.verts[i].co, f.verts[i + 1].co) for i in range(1, len(f.verts) - 1)]
                for _a, _b, _c in _tris:
                    for i in range(_k + 1):
                        for j in range(_k + 1 - i):
                            u, v = (i + 1 / 3) / (_k + 1), (j + 1 / 3) / (_k + 1)
                            vpts.append(_a + (_b - _a) * u + (_c - _a) * v)
            for p in vpts:
                for e in EYES:
                    d = e - p; dist = d.length
                    if dist < 1e-4: continue
                    d /= dist
                    if bvh.ray_cast(p + d * 0.003, d, dist - 0.006)[0] is None:
                        vis = True; nview[0] += 1; break
                if vis: break
        if not vis: dele.append(f)
    nb = len(bm.faces)
    bmesh.ops.delete(bm, geom=dele, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(o.data); bm.free()
    L("body: removed %d hidden faces (%d duplicates) of %d%s; %d kept because a viewpoint sees them" % (len(dele), dups, nb, " [careful]" if careful else "", nview[0]))
    seen2 = set()   # the doors, hood and trunk: only exact duplicates go
    for n, o in P.items():
        if not OPEN.match(n) or n.startswith(("wheel_", "hub_")): continue
        bm = bmesh.new(); bm.from_mesh(o.data); d2 = []
        for f in bm.faces:
            c = f.calc_center_median()
            key = (round(c.x, 4), round(c.y, 4), round(c.z, 4), len(f.verts))
            if key in seen2: d2.append(f)
            seen2.add(key)
        if d2:
            bmesh.ops.delete(bm, geom=d2, context="FACES"); bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"); bm.to_mesh(o.data)
            L("%s: %d duplicate faces removed" % (n, len(d2)))
        bm.free()

STATUS = {"steps": [], "over_budget": False}
L("source: %d triangles" % tri_count())

def attempt(label, fn, tol):
    """run a risky step; keep it only if the rebuilt car still matches the source"""
    bk = backup(); before = tri_count()
    fn()
    after = tri_count()
    if after >= before:
        L("%s: nothing to do" % label); return False
    r = check("%s (%d -> %d triangles)" % (label, before, after), tol)
    if r["ok"]:
        STATUS["steps"].append("%s: kept (%d -> %d triangles)" % (label, before, after)); return True
    restore(bk)
    STATUS["steps"].append("%s: SKIPPED, it damaged the car (%d triangles would have gone)" % (label, before - after))
    L("%s: undone, it damaged the car" % label)
    return False

# 1. hidden faces (two versions; the first that passes stays)
if True:
    if S.get("hidden_faces") == "careful" or not attempt("hidden-face removal", lambda: remove_hidden(False), 0.02):
        attempt("hidden-face removal (careful version)", lambda: remove_hidden(True), 0.02)
L("triangles now: %d" % tri_count())
_mt = collections.Counter()
for n_, o_ in P.items():
    for t_ in o_.data.loop_triangles: _mt[o_.data.materials[t_.material_index].name if t_.material_index < len(o_.data.materials) else "?"] += 1
L("triangles by material: %s" % dict(_mt.most_common()))

# 2. the tires: stage_parts built the four wheels at full detail; reduce them to the wheel budget
_wpolys = {n_[6:]: len(o_.data.polygons) for n_, o_ in P.items() if n_.startswith("wheel_")}
_w0 = max(_wpolys.values())
def op_wheels(budget):
    hub_tris = {}
    for n_, o_ in P.items():
        if n_.startswith("hub_"):    # the caliper is reduced by the same share as its wheel, but never below 600 triangles
            o_.data.calc_loop_triangles()
            decimate_mesh(o_, max(600, int(len(o_.data.loop_triangles) * min(1.0, budget / float(_wpolys.get(n_[4:], _w0))))))
            o_.data.calc_loop_triangles(); hub_tris[n_[4:]] = len(o_.data.loop_triangles)
    for n_, o_ in P.items():
        if n_.startswith("wheel_"): decimate_mesh(o_, max(1500, budget - hub_tris.get(n_[6:], 0)))   # a wheel and its caliper together stay within the budget
_wb = S["wheel_tri_budget"]
if _w0 > _wb:
    for _b in (_wb, int(_wb * 1.7), int(_wb * 2.8)):
        if attempt("wheel reduction to %d triangles each" % _b, lambda: op_wheels(_b), 0.04): break

# 3. triangle budget: each step is tried only while the car is over budget and stays only if the check passes
THIN = {"plastic_black", "interior", "carbon_fiber", "chrome", "badge", "grille", "reflector"} | set(S["extra_materials"])   # extra flat materials count as trim and can be thinned
BIG_ISLAND = 100     # only whole, dense pieces (engine, seats, spare tire's carrier...) are thinned; thin bars, brackets and lamps are never touched
def tri_count():
    t = 0
    for n_, o_ in P.items():
        o_.data.calc_loop_triangles(); t += len(o_.data.loop_triangles)
    return t
def big_dense_islands(o_, mats=None):
    """islands (joined by position, so split seams do not count) of at least BIG_ISLAND triangles that are mostly THIN materials"""
    me_ = o_.data
    idx = {i for i, m in enumerate(me_.materials) if m and m.name in (mats or THIN)}
    if not idx: return [], me_
    kpa = me_.attributes.get("keepall")
    kv = collections.defaultdict(list)
    key = lambda co: (round(co.x * 2e4), round(co.y * 2e4), round(co.z * 2e4))
    vk = [key(v.co) for v in me_.vertices]
    for p in me_.polygons:
        for vi in p.vertices: kv[vk[vi]].append(p.index)
    seen = set(); out_ = []
    for p in me_.polygons:
        if p.index in seen: continue
        st = [p.index]; seen.add(p.index); cs = []
        while st:
            c_ = st.pop(); cs.append(c_)
            for vi in me_.polygons[c_].vertices:
                for q in kv[vk[vi]]:
                    if q not in seen: seen.add(q); st.append(q)
        if kpa is not None and any(kpa.data[c_].value for c_ in cs): continue
        if len(cs) >= BIG_ISLAND and sum(1 for c_ in cs if me_.polygons[c_].material_index in idx) > 0.5 * len(cs): out_.append(cs)
    return out_, me_
def thin_parts(keep_frac, mats=None):
    for n_, o_ in P.items():
        if n_.startswith(("wheel_", "hub_", "window_")): continue
        isl_, me_ = big_dense_islands(o_, mats)
        if not isl_: continue
        faces_ = {c_ for cs in isl_ for c_ in cs}
        bm_ = bmesh.new(); bm_.from_mesh(me_); bm_.faces.ensure_lookup_table()
        gv = sorted({v for c_ in faces_ for v in bm_.faces[c_].verts}, key=lambda v_: v_.index)
        bmesh.ops.remove_doubles(bm_, verts=gv, dist=1e-5)
        bm_.verts.ensure_lookup_table()
        gv_idx = [v.index for v in bm_.verts if v.is_valid and any(f.index in faces_ for f in v.link_faces) and all(f.index in faces_ for f in v.link_faces)] if False else None
        bm_.to_mesh(me_); bm_.free()
        isl_, me_ = big_dense_islands(o_, mats)
        faces_ = {c_ for cs in isl_ for c_ in cs}
        gvi = sorted({vi for c_ in faces_ for vi in me_.polygons[c_].vertices})
        if not gvi: continue
        vg = o_.vertex_groups.new(name="thin"); vg.add(gvi, 1.0, "REPLACE")
        n_all = len(me_.polygons)
        mod = o_.modifiers.new("Decimate", "DECIMATE"); mod.vertex_group = "thin"; mod.use_collapse_triangulate = True
        mod.ratio = max(0.03, 1 - (1 - keep_frac) * len(faces_) / max(1, n_all))
        with bpy.context.temp_override(object=o_, active_object=o_, selected_objects=[o_]):
            bpy.ops.object.modifier_apply(modifier=mod.name)
        if "thin" in o_.vertex_groups: o_.vertex_groups.remove(o_.vertex_groups["thin"])

def classes(o_):
    """position-joined islands of a part: [(tris, longest side, materials counter, faces)]"""
    me_ = o_.data
    kv = collections.defaultdict(list); key = lambda co: (round(co.x * 2e4), round(co.y * 2e4), round(co.z * 2e4))
    vk = [key(v.co) for v in me_.vertices]
    for p in me_.polygons:
        for vi in p.vertices: kv[vk[vi]].append(p.index)
    seen = set(); out_ = []
    for p in me_.polygons:
        if p.index in seen: continue
        st = [p.index]; seen.add(p.index); cs = []
        while st:
            c_ = st.pop(); cs.append(c_)
            for vi in me_.polygons[c_].vertices:
                for q in kv[vk[vi]]:
                    if q not in seen: seen.add(q); st.append(q)
        vs = [me_.vertices[vi].co for c_ in cs for vi in me_.polygons[c_].vertices]
        ext = max(max(v[i] for v in vs) - min(v[i] for v in vs) for i in range(3))
        out_.append((cs, ext))
    return out_
KEEPMATS = {"glass", "headlight_lens", "taillight_lens", "reverselight_lens", "indicator_lens", "tire", "rim"}
def op_drop_small(maxext):
    for n_, o_ in P.items():
        if n_.startswith(("wheel_", "hub_", "window_")): continue
        me_ = o_.data; gone = set()
        for cs, ext in classes(o_):
            if ext < maxext and sum(1 for c_ in cs if me_.materials[me_.polygons[c_].material_index].name in KEEPMATS) < 0.3 * len(cs): gone.update(cs)
        if not gone: continue
        bm_ = bmesh.new(); bm_.from_mesh(me_); bm_.faces.ensure_lookup_table()
        bmesh.ops.delete(bm_, geom=[bm_.faces[i] for i in gone], context="FACES")
        bmesh.ops.delete(bm_, geom=[v for v in bm_.verts if not v.link_faces], context="VERTS")
        bm_.to_mesh(me_); bm_.free()
def op_dissolve(deg):
    for n_, o_ in P.items():
        if n_.startswith(("wheel_", "hub_", "window_")): continue
        mod = o_.modifiers.new("Dissolve", "DECIMATE"); mod.decimate_type = "DISSOLVE"; mod.angle_limit = math.radians(deg); mod.delimit = {"MATERIAL"}
        with bpy.context.temp_override(object=o_, active_object=o_, selected_objects=[o_]):
            bpy.ops.object.modifier_apply(modifier=mod.name)
        bm_ = bmesh.new(); bm_.from_mesh(o_.data); bmesh.ops.triangulate(bm_, faces=bm_.faces[:]); bm_.to_mesh(o_.data); bm_.free()
def op_thin(mats, floor):
    tot = tri_count()
    T = sum(len(c) for n_, o_ in P.items() if not n_.startswith(("wheel_", "hub_", "window_")) for c in big_dense_islands(o_, mats)[0])
    if T == 0: return
    thin_parts(max(floor, 1 - (tot - S["tri_budget"]) * 1.05 / max(1, T)), mats)
BUDGET_STEPS = [
    ("drop pieces under 4 cm (bolts, screws)", lambda: op_drop_small(0.04), 0.04),
    ("merge flat triangles (3 degrees)", lambda: op_dissolve(3), 0.04),
    ("drop pieces under 8 cm", lambda: op_drop_small(0.08), 0.04),
    ("thin dense interior and engine pieces", lambda: op_thin(THIN, 0.3), 0.04),
    ("thin dense paint pieces too", lambda: op_thin(THIN | {"PRIMARY", "SECONDARY", "rim"}, 0.45), 0.04),
    ("wheels to 5000 triangles each", lambda: op_wheels(5000), 0.04),
]
for _label, _fn, _tol in BUDGET_STEPS:
    if tri_count() <= S["tri_budget"]: break
    attempt(_label, _fn, _tol)
tot = tri_count()
STATUS["over_budget"] = tot > S["tri_budget"]
if STATUS["over_budget"]: L("OVER BUDGET: %d triangles (limit %d). Every further cut damages the car, so it needs a hand cut." % (tot, S["tri_budget"]))
