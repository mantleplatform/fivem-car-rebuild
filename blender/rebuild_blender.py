"""Runs inside Blender (started by rebuild_car.py):
   blender -b _blender_bootstrap.blend --python rebuild_blender.py -- <stream folder> <car name> <out folder> [settings.json]
Import the FiveM car, rebuild it as if it had been made for Mantle, export one skinned GLB. The steps are the stage_*.py files, run in order
in this one process; everything particular to one car is in cars/<name>.json."""
import bpy, os, sys, json, math, re, time, collections
HERE = os.path.dirname(os.path.abspath(__file__))
_a = sys.argv[sys.argv.index("--") + 1:]
_name = _a[1]
DEFAULTS = {
    "drop_parts": [],             # source parts to throw away (names as in the yft)
    "join": {},                   # {"misc_b": "bonnet"}: pieces to add to an opening part (automatic rules run too)
    "no_auto_join": [],           # pieces the automatic join rules must leave alone
    "mirror_parts": [],           # pieces that are mirrors although the automatic rule misses them (they ride the front door)
    "material_jobs": [],          # [[regex, job], ...] source material name (without .001) -> job; first match wins, before the built-in table
    "part_material_jobs": {},     # {"headlight": [[regex, job], ...]} the same, only for parts whose name starts with the key
    "pictures": {},               # {"interior": "leather_01"} picture to use for a job (default: biggest readable source material)
    "inner_material_regex": "",   # source material names that mark inner (unpolished) paint faces; empty = decide by face direction
    "extra_materials": {},        # {"decal_white": [0.85, 0.85, 0.85]} extra flat materials that material_jobs can point at
    "protect_from_thinning": [],  # source parts the triangle-budget thinning must leave whole (a bumper that tears when thinned)
    "wheel": {},                  # {"tire": regex, "rim": regex, "brake": regex} overrides for the wheel's materials
    "wheel_tri_budget": 7500,     # one wheel is reduced to this many triangles if heavier
    "tri_budget": 178000,         # whole car; wheels are reduced further when it is over
    "save_blend": False,
    "hidden_faces": "standard",   # "careful": start hidden-face removal with the careful version (removes less, leaves room in the hole check for thinning)
    "secondary_paint": None,      # {"finish": "chrome"} or {"color": [r, g, b], "finish": "gloss"} or {"match": "PRIMARY"}: the starting colour of the second
                                  # paint layer (players can change it). Written to <name>_paint.json for the upload step; Mantle defaults it to white.
}
S = dict(DEFAULTS)
_sp = _a[3] if len(_a) > 3 else os.path.join(HERE, "cars", _name + ".json")
if os.path.exists(_sp):
    S.update({k: v for k, v in json.load(open(_sp)).items() if not k.startswith("_")})
print("REBUILD settings", _sp if os.path.exists(_sp) else "(defaults)", flush=True)
for _stage in ("gta_import", "check_fidelity", "stage_parts", "stage_hidden", "stage_paint_uv", "stage_rig_export"):
    _t = time.time()
    _f = os.path.join(HERE, _stage + ".py")
    exec(compile(open(_f, encoding="utf-8").read(), _f, "exec"), globals())
    if _stage == "stage_parts":
        REF = fid_snapshot([o for o in bpy.data.objects if o.type == "MESH"])   # the source, for the before/after check
    print("REBUILD stage %s done in %ds" % (_stage, time.time() - _t), flush=True)
