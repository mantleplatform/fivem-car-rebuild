#!/usr/bin/env python
r"""Rebuild one FiveM car for Mantle: import it, rebuild it as if made for Mantle, export one skinned GLB, render the review pictures.

   python rebuild_car.py <stream folder> <car name> [--glb-dir DIR] [--renders-dir DIR] [--settings FILE] [--before OLD.glb] [--no-render] [--render-only]

Defaults: GLB to car-prep\glb-rebuild\<name>\, pictures to car-prep\renders-rebuild\<name>\, settings cars\<name>.json if it exists.
Runs Blender at BelowNormal priority, one Blender at a time (a lock file makes a second run wait). Nothing is uploaded.
Needs Blender 5.2 with the Sollumz add-on (D:\FiveMVehicles\_blender_bootstrap.blend is the start file used for imports)."""
import argparse, glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PREP = os.path.dirname(HERE)
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
BOOT = r"D:\FiveMVehicles\_blender_bootstrap.blend"
BELOW_NORMAL = 0x4000

ap = argparse.ArgumentParser()
ap.add_argument("stream")
ap.add_argument("name")
ap.add_argument("--glb-dir")
ap.add_argument("--renders-dir")
ap.add_argument("--settings")
ap.add_argument("--before")
ap.add_argument("--no-render", action="store_true")
ap.add_argument("--render-only", action="store_true")
a = ap.parse_args()

glb_dir = a.glb_dir or os.path.join(PREP, "glb-rebuild", a.name)
ren_dir = a.renders_dir or os.path.join(PREP, "renders-rebuild", a.name)
os.makedirs(glb_dir, exist_ok=True)
os.makedirs(ren_dir, exist_ok=True)
LOCK = os.path.join(HERE, ".blender.lock")
while os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 3600:
    print("another rebuild is using Blender, waiting...")
    time.sleep(20)
open(LOCK, "w").write(a.name)


def blender(blend, script, args):
    cmd = [BLENDER, "-b"] + ([blend] if blend else []) + ["--python", script, "--"] + args
    return subprocess.run(cmd, creationflags=BELOW_NORMAL, capture_output=True, text=True)


try:
    t0 = time.time()
    glb = os.path.join(glb_dir, a.name + "_skinned.glb")
    tail = ""
    if not a.render_only:
        for old in glob.glob(os.path.join(glb_dir, a.name + "_skinned*.glb")):
            os.remove(old)
        args = [a.stream, a.name, glb_dir] + ([a.settings] if a.settings else [])
        p = blender(BOOT, os.path.join(HERE, "rebuild_blender.py"), args)
        open(os.path.join(glb_dir, a.name + "_blender_stdout.txt"), "w").write(p.stdout + "\n" + p.stderr)
        for line in p.stdout.splitlines():
            if line.startswith(("REBUILD", "FIVEM_FAILED")):
                print(line)
        tail = "\n".join((p.stdout + p.stderr).splitlines()[-25:])
    if not os.path.exists(glb):
        alt = sorted(glob.glob(os.path.join(glb_dir, a.name + "_skinned.*.glb")))
        if not alt:
            print("FAILED: no GLB. Last lines of Blender:\n" + tail)
            sys.exit(1)
        glb = alt[0]
    ck = os.path.join(glb_dir, a.name + "_check.json")
    if os.path.exists(ck):
        import json
        c = json.load(open(ck))
        print("STATUS: %s | %d triangles | %s" % (c["status"].upper(), c["triangles"], c["check"]))
        for s_ in c["steps"]:
            print("  step:", s_)
        for w in c.get("warnings", []):
            print("  WARNING:", w)
        for w in c["where"]:
            print("  %s: %s" % ("PROBLEM" if c["status"] != "ok" else "largest remaining difference", w))
    print("GLB %s  (%.0fs)" % (glb, time.time() - t0))
    if not a.no_render:
        rs = os.path.join(HERE, "render_set.py")
        for tag, g in (("after", glb),) + ((("before", a.before),) if a.before else ()):
            blender(None, rs, [g, os.path.join(ren_dir, tag), "plain,shade,open,lights,rail"])
            blender(None, rs, [g, os.path.join(ren_dir, tag), "grid"])
        print("pictures in", ren_dir)
finally:
    try:
        os.remove(LOCK)
    except OSError:
        pass
