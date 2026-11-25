"""Runs inside Blender (started by rebuild_car.py):
   blender -b --python rebuild_blender.py -- <car folder> <car name> <out folder> [settings.json]
Import the FiveM car, rebuild it as if it had been made for Mantle, export one skinned GLB. The steps are the stage_*.py files, run in order
in this one process. Everything particular to one car belongs in that car's settings file, never in these scripts."""
import bpy, os, sys, json, math, re, time, collections
HERE = os.path.dirname(os.path.abspath(__file__))
_a = sys.argv[sys.argv.index("--") + 1:]
_name = _a[1]
DEFAULTS = {
    "drop_parts": [],             # source parts to throw away (names as in the yft)
    "join": {},                   # {"misc_b": "bonnet"}: pieces to add to an opening part (automatic rules run too)
    "no_auto_join": [],           # pieces the automatic join rules must leave alone
    "mirror_parts": [],           # pieces that are side mirrors although the automatic rule misses them (they ride the front door)
    "material_jobs": [],          # [[regex, job], ...] source material name (without .001) -> job; first match wins, before the built-in table
    "part_material_jobs": {},     # {"headlight": [[regex, job], ...]} the same, only for parts whose name starts with the key
    "pictures": {},               # {"interior": "leather_01"} picture to use for a job (default: biggest readable source material)
    "tint": {},                   # {"interior": [0.08, 0.08, 0.08]} colour a job's picture is multiplied by (GTA tints [INTERIOR TRIM] leather with the car's trim colour)
    "inner_material_regex": "",   # source material names that mark inner (unpolished) paint faces; empty = decide by face direction
    "extra_materials": {},        # {"decal_white": [0.85, 0.85, 0.85]} extra flat materials that material_jobs can point at
    "protect_from_thinning": [],  # source parts the triangle-budget thinning must leave whole (a bumper that tears when thinned)
    "wheel": {},                  # {"tire": regex, "rim": regex, "brake": regex} overrides for the wheel's materials
    "wheel_tri_budget": 7500,     # one wheel is reduced to this many triangles if heavier
    "tri_budget": 178000,         # whole car; wheels are reduced further when it is over
    "save_blend": False,          # also save the rebuilt car as <name>_rebuild.blend
    "hidden_faces": "standard",   # "careful": start hidden-face removal with the careful version (removes less, leaves room in the hole check for thinning)
    "secondary_paint": None,      # {"finish": "chrome"} or {"color": [r, g, b], "finish": "gloss"} or {"match": "PRIMARY"}: the starting colour of the second
                                  # paint layer (players can change it). Written to <name>_paint.json for the upload step; Mantle defaults it to white.
    "extra_yfts": {},             # {"body_1.yft": "bodyshell"}: extra .yft files next to the main one whose meshes join the car under that part name
    "copy_to_other_side": [],     # parts whose twin on the other side is missing: copied across the middle as <part>_m
}


def fail(why):
    print("FIVEM_FAILED " + why, flush=True)
    raise SystemExit(1)


S = dict(DEFAULTS)
_sp = _a[3] if len(_a) > 3 and _a[3] else ""
if _sp:
    try:
        _user = json.load(open(_sp, encoding="utf-8"))
    except Exception as e:
        fail("settings file %s could not be read: %s" % (_sp, e))
    _unknown = sorted(k for k in _user if not k.startswith("_") and k not in DEFAULTS)
    if _unknown:
        fail("settings file %s has unknown keys %s (known keys: %s)" % (_sp, _unknown, ", ".join(sorted(DEFAULTS))))
    S.update({k: v for k, v in _user.items() if not k.startswith("_")})
print("REBUILD settings", _sp or "(none, defaults only)", flush=True)

# Start from an empty file, whatever the user's startup file holds. Data left in the file changes the names Blender gives the car's
# materials (a second "[PRIMARY]" becomes ".001"), and settings files match those names.
for _coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.armatures, bpy.data.cameras, bpy.data.lights,
              bpy.data.curves, bpy.data.node_groups, bpy.data.textures, bpy.data.actions):
    for _d in list(_coll):
        _coll.remove(_d)
for _c in list(bpy.context.scene.collection.children):
    bpy.data.collections.remove(_c)

# Sollumz: installed from the Sollumz extension repository, from a zip, or as a legacy add-on. Use whichever is installed.
import addon_utils
SOLLUMZ = next((m.__name__ for m in addon_utils.modules() if m.__name__.split(".")[-1].lower() == "sollumz"), None)
if SOLLUMZ is None:
    fail("the Sollumz add-on is not installed in this Blender (see README: Install)")
try:
    bpy.ops.preferences.addon_enable(module=SOLLUMZ)
except Exception as e:
    fail("the Sollumz add-on (%s) could not be turned on: %s" % (SOLLUMZ, e))
print("REBUILD sollumz", SOLLUMZ, flush=True)

for _stage in ("gta_import", "check_fidelity", "stage_parts", "stage_hidden", "stage_paint_uv", "stage_rig_export"):
    _t = time.time()
    _f = os.path.join(HERE, _stage + ".py")
    exec(compile(open(_f, encoding="utf-8").read(), _f, "exec"), globals())
    if _stage == "stage_parts":
        REF = fid_snapshot([o for o in bpy.data.objects if o.type == "MESH"])   # the source, for the before/after check
    print("REBUILD stage %s done in %ds" % (_stage, time.time() - _t), flush=True)
