# Before/after check: the rebuilt car is compared with its source (the parts as they were right after stage_parts) by shooting rays at both from
# 26 directions. Two passes: (closed) everything is solid; (open) doors, hood, trunk and glass are taken away from both, so the inside, the engine
# bay and the openings are compared too. A ray that hits the source but misses the rebuild = a piece is missing; a ray that hits the rebuild first
# but nothing (or something far) in the source = a spike or a stray piece; a ray whose first hit moves by more than the tolerance = a hole or a tear.
# Defines: fid_snapshot(), fid_compare(ref, cand, tol), FID_LIMITS.  Used by stage_hidden.py (to keep or skip a risky step) and stage_rig_export.py (final).
import bpy, math, re, collections, itertools, json
from mathutils import Vector
from mathutils.bvhtree import BVHTree

FID_OPEN = re.compile(r"^(door_|bonnet|boot|window_)")
FID_GLASS = re.compile(r"glass|window", re.I)
FID_CELL = 0.035
# share of the rays (of the ones that hit either car) that may differ. Calibrated on the approved 2019m5 (all steps passing) and the damaged 2022jeep.
FID_LIMITS = {"lost": 0.0015, "extra": 0.0015, "moved": 0.004, "cabin": 0.002}
# Cabin view: rays from eyes over the seats (stage_hidden.py fills FID_EYES) out in every direction, glass taken away, doors kept.
# A ray that hits the source but goes farther (or out) in the rebuild is a hole in the cabin: the outside passes cannot see these, and a step
# that opened the footwells to the wheel arches once passed. Limit: share of the cabin rays that hit the source.
FID_EYES = []
FID_CABIN_DIRS = 600


def fid_snapshot(objs, part_of=None):
    """triangles of the given mesh objects in world space: dict(verts, tris, info=[(part, material)])"""
    verts, tris, info = [], [], []
    for o in objs:
        me = o.data
        me.calc_loop_triangles()
        mw = o.matrix_world
        base = len(verts)
        verts.extend(mw @ v.co for v in me.vertices)
        att = me.attributes.get("part")
        pn = json.loads(o["part_names"]) if att is not None and "part_names" in o else None
        for t in me.loop_triangles:
            tris.append((base + t.vertices[0], base + t.vertices[1], base + t.vertices[2]))
            mat = me.materials[t.material_index].name if t.material_index < len(me.materials) and me.materials[t.material_index] else "?"
            part = pn[att.data[t.polygon_index].value] if pn is not None else o.name
            info.append((part, mat))
    return {"verts": verts, "tris": tris, "info": info}


def _bvh(snap, closed):
    keep = [i for i, (part, mat) in enumerate(snap["info"]) if closed or not (FID_OPEN.match(part) or FID_GLASS.search(mat))]
    return BVHTree.FromPolygons(snap["verts"], [snap["tris"][i] for i in keep]), keep


def _dirs():
    out = []
    for v in itertools.product((-1, 0, 1), repeat=3):
        if v != (0, 0, 0):
            out.append(Vector(v).normalized())
    return out


def _sphere(n):
    g = math.pi * (3 - math.sqrt(5))
    return [Vector((math.cos(g * i) * math.sqrt(1 - (1 - 2 * (i + 0.5) / n) ** 2), math.sin(g * i) * math.sqrt(1 - (1 - 2 * (i + 0.5) / n) ** 2), 1 - 2 * (i + 0.5) / n)) for i in range(n)]


def _cabin(ref, cand, tol, where):
    def bvh(snap):
        keep = [i for i, (part, mat) in enumerate(snap["info"]) if not FID_GLASS.search(mat)]
        return BVHTree.FromPolygons(snap["verts"], [snap["tris"][i] for i in keep]), keep
    rb, rkeep = bvh(ref); cb, ckeep = bvh(cand)
    n = bad = 0
    for e in FID_EYES:
        if rb.find_nearest(e)[3] is not None and rb.find_nearest(e)[3] < 0.05: continue   # an eye inside a seat sees nothing useful
        for d in _sphere(FID_CABIN_DIRS):
            h1 = rb.ray_cast(e, d, 4.0)
            if h1[0] is None: continue
            n += 1
            h2 = cb.ray_cast(e, d, 4.0)
            if h2[0] is None or h2[3] - h1[3] > max(tol, 0.06):
                bad += 1
                part, mat = ref["info"][rkeep[h1[2]]]; p = h1[0]
                key = ("cabin", part, mat, round(p.x / 0.4), round(p.y / 0.4), round(p.z / 0.4))
                where[key][0] += 1; where[key][1] += p
    return n, bad


def fid_compare(ref, cand, tol=0.025, log=None):
    """returns dict(ok, rates, text, where) ; where is a list of readable places"""
    allv = ref["verts"]
    lo = Vector([min(v[i] for v in allv) for i in range(3)]); hi = Vector([max(v[i] for v in allv) for i in range(3)])
    cen = (lo + hi) / 2; R = (hi - lo).length
    tot = collections.Counter(); bad = collections.defaultdict(collections.Counter); where = collections.defaultdict(lambda: [0, Vector()])
    for closed in (True, False):
        rb, rkeep = _bvh(ref, closed)
        cb, ckeep = _bvh(cand, closed)
        for d in _dirs():
            a = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized(); b = d.cross(a).normalized()
            cs = [(Vector(c) - cen) for c in itertools.product((lo.x, hi.x), (lo.y, hi.y), (lo.z, hi.z))]
            ua = [c.dot(a) for c in cs]; ub = [c.dot(b) for c in cs]
            na = int((max(ua) - min(ua)) / FID_CELL) + 1; nb = int((max(ub) - min(ub)) / FID_CELL) + 1
            for i in range(na):
                for j in range(nb):
                    org = cen - d * R + a * (min(ua) + (i + 0.5) * FID_CELL) + b * (min(ub) + (j + 0.5) * FID_CELL)
                    h1 = rb.ray_cast(org, d)
                    h2 = cb.ray_cast(org, d)
                    if h1[0] is None and h2[0] is None: continue
                    tot[closed] += 1
                    kind = None
                    if h1[0] is not None and h2[0] is None: kind = "lost"
                    elif h1[0] is None: kind = "extra"
                    elif h2[3] - h1[3] > tol: kind = "moved"      # the rebuild's first hit is farther: the front was cut away
                    elif h1[3] - h2[3] > tol: kind = "extra"      # the rebuild sticks out in front
                    if kind:
                        if kind in ("lost", "moved"):
                            part, mat = ref["info"][rkeep[h1[2]]]; p = h1[0]
                        else:
                            part, mat = cand["info"][ckeep[h2[2]]]; p = h2[0]
                        bad[closed][kind] += 1
                        key = (kind, part, mat, round(p.x / 0.4), round(p.y / 0.4), round(p.z / 0.4))
                        where[key][0] += 1; where[key][1] += p
    n = max(1, tot[True] + tot[False])
    rates = {k: (bad[True][k] + bad[False][k]) / n for k in ("lost", "extra", "moved")}
    ncab, bcab = _cabin(ref, cand, tol, where) if FID_EYES else (0, 0)
    rates["cabin"] = bcab / max(1, ncab)
    ok = all(rates[k] <= FID_LIMITS[k] for k in rates)
    places = []
    for key, (cnt, ssum) in sorted(where.items(), key=lambda kv: -kv[1][0])[:8]:
        if cnt < 3: continue
        p = ssum / cnt
        places.append("%s: %d rays, part %s, material %s, near x %.2f y %.2f z %.2f" % ({"lost": "piece missing", "extra": "spike or stray piece", "moved": "hole or tear", "cabin": "hole in the cabin"}[key[0]], cnt, key[1], key[2], p.x, p.y, p.z))
    text = "rays %d (closed %d, open %d): missing %.3f%%, spikes %.3f%%, holes/tears %.3f%% (limits %.2f / %.2f / %.2f%%)" % (n, tot[True], tot[False], 100 * rates["lost"], 100 * rates["extra"], 100 * rates["moved"], 100 * FID_LIMITS["lost"], 100 * FID_LIMITS["extra"], 100 * FID_LIMITS["moved"])
    if FID_EYES:
        text += "; cabin %d rays from %d eyes: holes %.3f%% (limit %.2f%%)" % (ncab, len(FID_EYES), 100 * rates["cabin"], 100 * FID_LIMITS["cabin"])
    return {"ok": ok, "rates": rates, "text": text, "where": places}
