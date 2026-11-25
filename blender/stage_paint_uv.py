# Stage: join the parts into one mesh, tidy the paint pieces, lay out UV 0 (paint) island by island.
import bpy, bmesh, json, math, sys, collections, os
from mathutils import Vector
AMIN = 0.25         # a piece smaller than this (m2) that touches a bigger one belongs to it (source meshes split panels arbitrarily)
objs = [o for o in bpy.data.objects if o.type == "MESH"]
names = sorted(o.name for o in objs)
for o in objs:
    me = o.data
    me.attributes.new("part", "INT", "FACE")
    pi = names.index(o.name)
    for d in me.attributes["part"].data: d.value = pi
    while len(me.uv_layers) > 1: me.uv_layers.remove(me.uv_layers[-1])
    if len(me.uv_layers) == 0: me.uv_layers.new(name="UVMap")
    me.uv_layers[0].name = "UVMap"
    for k in list(me.color_attributes): me.color_attributes.remove(k)
bpy.ops.object.select_all(action="DESELECT")
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = bpy.data.objects["body"]
bpy.ops.object.join()
car = bpy.context.view_layer.objects.active
car.name = "car"; car.data.name = "car"
car["part_names"] = json.dumps(names)
car["src_names"] = json.dumps(SRCLIST)
me = car.data
mats = {m.name: i for i, m in enumerate(me.materials)}
pm = mats["PRIMARY"]; bk = mats["plastic_black"]

bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
whyL = bm.faces.layers.int.new('why')
partL = bm.faces.layers.int["part"]
_allv = [v.co for v in bm.verts]
HEIGHT = max(v.z for v in _allv); HALFW = max(abs(v.y) for v in _allv)
_dv = [v.co for f in bm.faces if names[f[partL]].startswith("door_") and f.material_index == pm for v in f.verts]
_bv = [v.co for f in bm.faces if names[f[partL]] == "bonnet" for v in f.verts]
DOOR = (min(v.x for v in _dv), max(v.x for v in _dv), min(v.z for v in _dv), max(v.z for v in _dv)) if _dv else None
HOODX = min(v.x for v in _bv) if _bv else None
L("paint geometry: height %.2f, half width %.2f, doors %s, hood starts at x %s" % (HEIGHT, HALFW, tuple(round(x, 2) for x in DOOR) if DOOR else None, round(HOODX, 2) if HOODX is not None else None))
def topo_islands(faceset):
    seen = {}; isl = []
    for f in bm.faces:
        if f.index not in faceset or f.index in seen: continue
        seen[f.index] = len(isl); st = [f]; cs = []
        while st:
            c = st.pop(); cs.append(c)
            for e in c.edges:
                for g in e.link_faces:
                    if g.index in faceset and g.index not in seen: seen[g.index] = len(isl); st.append(g)
        isl.append(cs)
    return isl, seen
def area(cs): return sum(f.calc_area() for f in cs)
pset = {f.index for f in bm.faces if f.material_index == pm}
isl, seen = topo_islands(pset)
L("paint faces %d, source pieces %d" % (len(pset), len(isl)))

# ---- Always the source's own materials: no rule here changes a face's material because of its shape or place (door edges, jambs, hinge arms,
# ---- thin strips, small pieces and engine-bay pieces all stay what the source made them). A piece that looks wrong is fixed in cars/<name>.json.
# ---- 1. A face's material comes from the source, never from its shape. Thin strips and small loose pieces (roof rails, scoops, cowl panels, hood
# ---- hinges) keep the material the source gave them; they are just small pieces in the layout below. (Earlier versions turned thin or small paint
# ---- pieces black; that took real paint off the M5's left roof rail and the Camaro's hood. Trim the source made black is black through its own material.)
pset = {f.index for f in bm.faces if f.material_index == pm}
isl, seen = topo_islands(pset)

# ---- 2. small pieces join the neighbour they share the most edge with (same part only), welded so they unwrap as one
def key(v): return (round(v.co.x * 2e3), round(v.co.y * 2e3), round(v.co.z * 2e3))
vk = collections.defaultdict(set)
for k, cs in enumerate(isl):
    for f in cs:
        for v in f.verts: vk[key(v)].add(k)
parent = list(range(len(isl)))
def find(x):
    while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
    return x
areas = [area(cs) for cs in isl]
part_of = [cs[0][partL] for cs in isl]
share = collections.defaultdict(collections.Counter)
for k, ks in vk.items():
    for a in ks:
        for b in ks:
            if a != b and part_of[a] == part_of[b]: share[a][b] += 1
order = sorted(range(len(isl)), key=lambda i: areas[i])
tot = {i: areas[i] for i in range(len(isl))}
merged = 0
for i in order:
    ri = find(i)
    if tot[ri] >= (99 if names[part_of[i]] in ('bonnet', 'boot') else AMIN): continue
    best = None
    for j, c in share[i].most_common():
        if find(j) != ri: best = j; break
    if best is None:
        for m in [x for x in range(len(isl)) if find(x) == ri]:
            for j, c in share[m].most_common():
                if find(j) != ri: best = j; break
            if best is not None: break
    if best is None: continue
    rb = find(best); parent[ri] = rb; tot[rb] += tot[ri]; merged += 1
groups = collections.defaultdict(list)
for i in range(len(isl)): groups[find(i)].append(i)
L("pieces %d -> blobs %d (merged %d)" % (len(isl), len(groups), merged))
nweld = 0
for g, members in groups.items():
    if len(members) < 2: continue
    vs = list({v for i in members for f in isl[i] for v in f.verts})
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=vs, dist=3e-4)
    nweld += before - len(bm.verts)
L("welded %d vertices" % nweld)
bm.faces.ensure_lookup_table()
pset = {f.index for f in bm.faces if f.material_index == pm}
isl, seen = topo_islands(pset)
L("paint blobs after weld %d" % len(isl))
bm.to_mesh(me); bm.free()

# ---- 3. unwrap in rounds; blobs that stay stretched get seams on their creases
def sig(bm, cs):
    c = sum((f.calc_center_median() for f in cs), Vector()) / len(cs)
    return (round(c.x, 2), round(c.y, 2), round(c.z, 2))
def measure(bm, cs, uvl):
    dens = []; tw = 0
    for f in cs:
        wa = f.calc_area(); us = [l[uvl].uv for l in f.loops]; ua = 0.0
        for k in range(1, len(us) - 1): ua += abs((us[k] - us[0]).cross(us[k + 1] - us[0])) / 2
        if wa > 1e-9: dens.append((ua / wa, wa)); tw += wa
    dens.sort(); cum = 0; ds = []
    for d, w in dens: cum += w; ds.append((cum / tw, d))
    q = lambda p: next((d for c, d in ds if c >= p), ds[-1][1])
    return q(0.05), q(0.5), q(0.95)
cut = {}   # blob signature -> degrees
for rnd in range(5):
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table(); bm.edges.ensure_lookup_table()
    pset = {f.index for f in bm.faces if f.material_index == pm}
    isl, seen = topo_islands(pset)
    innL = bm.faces.layers.int['inner']
    for e in bm.edges: e.seam = False
    for cs in isl:
        a = cut.get(sig(bm, cs))
        if a is None: continue
        iset = {f.index for f in cs}
        for f in cs:
            for e in f.edges:
                lf = [g for g in e.link_faces if g.index in iset]
                if len(e.link_faces) > 2 and len(lf) > 1: e.seam = True
                elif len(lf) == 2 and len(e.link_faces) == 2 and (e.calc_face_angle(0) > math.radians(a) or lf[0][innL] != lf[1][innL]): e.seam = True
    for f in bm.faces: f.select = f.index in pset
    bm.to_mesh(me); bm.free()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", fill_holes=True, margin=0.0)
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    uvl = bm.loops.layers.uv[0]
    pset = {f.index for f in bm.faces if f.material_index == pm}
    isl, seen = topo_islands(pset)
    bad = 0
    for cs in isl:
        # unwrap pieces (seams split a blob into UV islands, measure each blob as a whole)
        p5, p50, p95 = measure(bm, cs, uvl)
        if area(cs) > 0.05 and (p95 / max(p5, 1e-9) > 3.0):
            s = sig(bm, cs); cur = cut.get(s, 180)
            nxt = {180: 75, 75: 60, 60: 48, 48: 40, 40: 32}.get(cur)
            if nxt: cut[s] = nxt; bad += 1
            L("round %d blob %s area %.2f stretch p95/p5 %.1f -> seams at %s deg" % (rnd, s, area(cs), p95 / max(p5, 1e-9), nxt))
    bm.free()
    if not bad: break
L("unwrap rounds %d, blobs with seams: %d" % (rnd + 1, len(cut)))

# ---- 4. stand each island upright: world up (or nose, for roof/hood/trunk) points up the sheet, then pack
bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
uvl = bm.loops.layers.uv[0]
pset = {f.index for f in bm.faces if f.material_index == pm}
# UV islands = connected by shared edge AND shared UV (split by seams)
class UF:
    def __init__(s): s.p = {}
    def f(s, x):
        s.p.setdefault(x, x)
        while s.p[x] != x: s.p[x] = s.p[s.p[x]]; x = s.p[x]
        return x
    def u(s, a, b): s.p[s.f(a)] = s.f(b)
uf = UF()
for fi in pset:
    f = bm.faces[fi]
    for l in f.loops:
        uf.f(("f", fi))
        for lf in l.vert.link_loops:
            g = lf.face
            if g.index in pset and g.index != fi and (lf[uvl].uv - l[uvl].uv).length < 1e-6 and lf.edge is not None:
                # same vertex, same UV coordinate: the faces sit in one UV island if they also share an edge
                if any(e in g.edges for e in (l.edge, l.link_loop_prev.edge)): uf.u(("f", fi), ("f", g.index))
uis = collections.defaultdict(list)
for fi in pset: uis[uf.f(("f", fi))].append(fi)
L("UV islands %d" % len(uis))
for k, fis in uis.items():
    nrm = sum((bm.faces[i].normal * bm.faces[i].calc_area() for i in fis), Vector())
    nrm.normalize()
    axis = 2 if abs(nrm.z) < 0.7 else 0
    pts = {}
    for i in fis:
        for l in bm.faces[i].loops: pts[l.vert.index] = (l.vert.co[axis], l[uvl].uv.copy())
    # least squares: coord ~ a*u + b*v + c
    import numpy as np
    A = np.array([[p[1].x, p[1].y, 1.0] for p in pts.values()]); y = np.array([p[0] for p in pts.values()])
    if len(y) < 3: continue
    sol = np.linalg.lstsq(A, y, rcond=None)[0]
    g = Vector((sol[0], sol[1]))
    if g.length < 1e-9: continue
    ang = math.atan2(g.x, g.y)   # rotate so that gradient points to +V
    ca, sa = math.cos(ang), math.sin(ang)
    for i in fis:
        for l in bm.faces[i].loops:
            u, v = l[uvl].uv.x, l[uvl].uv.y
            l[uvl].uv = (u * ca - v * sa, u * sa + v * ca)
bm.to_mesh(me); bm.free()
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.uv.pack_islands(rotate=False, margin=0.003, margin_method="SCALED")
bpy.ops.object.mode_set(mode="OBJECT")

# ---- 5. report
bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
uvl = bm.loops.layers.uv[0]
pset = {f.index for f in bm.faces if f.material_index == pm}
isl, seen = topo_islands(pset)
partL = bm.faces.layers.int["part"]
rows = []
tua = 0
for cs in isl:
    p5, p50, p95 = measure(bm, cs, uvl)
    rows.append((area(cs), len(cs), p5, p50, p95, sig(bm, cs), names[cs[0][partL]]))
rows.sort(reverse=True)
for f in bm.faces:
    if f.index in pset:
        us = [l[uvl].uv for l in f.loops]
        for k in range(1, len(us) - 1): tua += abs((us[k] - us[0]).cross(us[k + 1] - us[0])) / 2
L("paint area %.2f m2 in %d blobs; sheet use %.1f%%" % (sum(r[0] for r in rows), len(rows), 100 * tua))
for r in rows[:40]:
    L("blob %-14s %s area %.3f tris %4d dens p5 %.4f p50 %.4f p95 %.4f (p95/p5 %.1f)" % (r[6], r[5], r[0], r[1], r[2], r[3], r[4], r[4] / max(r[2], 1e-9)))
us_ = [l[uvl].uv for f in bm.faces if f.index in pset for l in f.loops]
L("paint uv bounds x %.3f..%.3f y %.3f..%.3f" % (min(u.x for u in us_), max(u.x for u in us_), min(u.y for u in us_), max(u.y for u in us_)))
bm.free()
