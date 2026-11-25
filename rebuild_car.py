#!/usr/bin/env python3
"""Rebuild one FiveM car for Mantle: import it, rebuild it as if it had been made for Mantle, export one skinned GLB, and render review pictures.

    python rebuild_car.py <car folder> [car name] [options]

The car folder is the one that holds <name>.yft (and usually <name>_hi.yft and <name>.ytd). Nothing in it is changed.
Run with --help for the options. See README.md."""
import argparse, glob, json, os, re, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
BLENDER_DIR = os.path.join(HERE, "blender")
TESTED_BLENDER = (5, 2)
MIN_BLENDER = (4, 2)
EXIT = {"ok": 0, "failed": 1, "over_budget": 2, "refused": 3}


def die(msg):
    print("ERROR: " + msg)
    sys.exit(EXIT["failed"])


def find_blender(given):
    if given:
        if not os.path.isfile(given):
            die("Blender not found at %s" % given)
        return given
    env = os.environ.get("BLENDER")
    if env and os.path.isfile(env):
        return env
    cands = []
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            cands += glob.glob(os.path.join(root, "Blender Foundation", "Blender *", "blender.exe"))
    elif sys.platform == "darwin":
        cands += glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender")
    def ver(p):
        m = re.search(r"(\d+)\.(\d+)", p)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    cands.sort(key=ver, reverse=True)
    if cands:
        return cands[0]
    for name in ("blender", "blender.exe"):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    die("Blender not found. Install Blender %d.%d, or pass --blender <path to blender.exe>, or set \"blender\" in config.json." % TESTED_BLENDER)


def low_priority():
    """Blender runs at below-normal priority so the computer stays usable."""
    if os.name == "nt":
        return {"creationflags": 0x4000}   # BELOW_NORMAL_PRIORITY_CLASS
    return {"preexec_fn": lambda: os.nice(10)}


def blender_version(exe):
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        die("Blender at %s did not start: %s" % (exe, e))
    m = re.search(r"Blender (\d+)\.(\d+)", out)
    if not m:
        die("Blender at %s did not report a version" % exe)
    return (int(m.group(1)), int(m.group(2)))


def car_name(folder, given):
    if given:
        if not glob.glob(os.path.join(folder, given + ".yft")) + glob.glob(os.path.join(folder, given + "_hi.yft")):
            die("no %s.yft or %s_hi.yft in %s" % (given, given, folder))
        return given
    names = sorted({re.sub(r"_hi$", "", os.path.splitext(os.path.basename(p))[0]) for p in glob.glob(os.path.join(folder, "*.yft"))})
    base = os.path.basename(os.path.normpath(folder))
    if base in names:
        return base
    if len(names) == 1:
        return names[0]
    if not names:
        die("no .yft file in %s. Point to the car's own folder (the one that holds <name>.yft)." % folder)
    die("%s holds several cars (%s). Name the one to rebuild: rebuild_car.py <folder> <name>" % (folder, ", ".join(names)))


def main():
    ap = argparse.ArgumentParser(description="Rebuild one FiveM car for Mantle (one skinned GLB plus review pictures).")
    ap.add_argument("folder", help="the car's own folder, holding <name>.yft / <name>_hi.yft / <name>.ytd")
    ap.add_argument("name", nargs="?", help="the car's file name without .yft (default: found in the folder)")
    ap.add_argument("--out", help="output folder; the car goes into <out>/<name>/ (default: config.json \"output\", else ./output)")
    ap.add_argument("--settings", help="this car's settings file (default: cars/<name>.json if it exists, else none)")
    ap.add_argument("--blender", help="path to blender.exe (default: config.json \"blender\", the BLENDER variable, else searched for)")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"), help="config file (default: config.json next to this script)")
    ap.add_argument("--before", help="an older GLB of the same car: pictures of it are taken with the same cameras, for comparison")
    ap.add_argument("--no-pictures", action="store_true", help="skip the review pictures")
    ap.add_argument("--pictures-only", action="store_true", help="only take the pictures of an existing rebuild")
    a = ap.parse_args()

    cfg = {}
    if os.path.exists(a.config):
        try:
            cfg = json.load(open(a.config, encoding="utf-8"))
        except Exception as e:
            die("config file %s could not be read: %s" % (a.config, e))
    folder = os.path.abspath(a.folder)
    if not os.path.isdir(folder):
        die("car folder not found: %s" % folder)
    name = car_name(folder, a.name)
    exe = find_blender(a.blender or cfg.get("blender"))
    v = blender_version(exe)
    if v < MIN_BLENDER:
        die("Blender %d.%d is too old (Sollumz needs %d.%d or newer; tested with %d.%d)" % (v + MIN_BLENDER + TESTED_BLENDER))
    if v != TESTED_BLENDER:
        print("NOTE: Blender %d.%d; this script was tested with %d.%d" % (v + TESTED_BLENDER))
    settings = a.settings or (os.path.join(HERE, "cars", name + ".json") if os.path.exists(os.path.join(HERE, "cars", name + ".json")) else "")
    if settings and not os.path.isfile(settings):
        die("settings file not found: %s" % settings)
    out_root = os.path.abspath(a.out or cfg.get("output") or os.path.join(os.getcwd(), "output"))
    out = os.path.join(out_root, name)
    pics = os.path.join(out, "pictures")
    try:
        inside = os.path.commonpath([out, folder]) == folder
    except ValueError:      # different drives
        inside = False
    if inside:
        die("the output folder must not be inside the car folder (%s)" % folder)
    os.makedirs(pics, exist_ok=True)
    print("car      %s (%s)" % (name, folder))
    print("settings %s" % (os.path.abspath(settings) if settings else "none (defaults)"))
    print("blender  %s (%d.%d)" % ((exe,) + v))
    print("output   %s" % out)

    lock = os.path.join(tempfile.gettempdir(), "fivem-car-rebuild.lock")
    while os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 3600:
        print("another rebuild is using Blender, waiting...")
        time.sleep(20)
    open(lock, "w").write(name)

    def blender(script, args):
        cmd = [exe, "-b", "--python", os.path.join(BLENDER_DIR, script), "--"] + args
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **low_priority())

    try:
        t0 = time.time()
        glb = os.path.join(out, name + "_skinned.glb")
        if not a.pictures_only:
            for old in glob.glob(os.path.join(out, name + "_skinned*.glb")) + glob.glob(os.path.join(out, name + "_check.json")):
                os.remove(old)
            print("rebuilding (about a minute)...")
            p = blender("rebuild_blender.py", [folder, name, out, os.path.abspath(settings) if settings else ""])
            stdout_file = os.path.join(out, name + "_blender_stdout.txt")
            open(stdout_file, "w", encoding="utf-8").write(p.stdout + "\n" + p.stderr)
            failed = [l[len("FIVEM_FAILED "):] for l in p.stdout.splitlines() if l.startswith("FIVEM_FAILED")]
            if failed:
                print("\nRESULT: FAILED\n  why: %s\n  Blender output: %s" % (failed[0], stdout_file))
                return EXIT["failed"]
        ck = os.path.join(out, name + "_check.json")
        if not os.path.exists(ck):
            tail = "\n    ".join(open(os.path.join(out, name + "_blender_stdout.txt"), encoding="utf-8").read().strip().splitlines()[-15:]) \
                if os.path.exists(os.path.join(out, name + "_blender_stdout.txt")) else "(no Blender output)"
            print("\nRESULT: FAILED\n  why: Blender stopped before the car was exported. Last lines of its output:\n    " + tail)
            return EXIT["failed"]
        c = json.load(open(ck, encoding="utf-8"))
        status = c["status"]
        if status != "ok":
            glb = os.path.join(out, "%s_skinned.%s.glb" % (name, status.upper()))
        took = time.time() - t0
        if not a.no_pictures:
            print("taking review pictures (about two minutes)...")
            rs = "render_set.py"
            for tag, g in (("after", glb),) + ((("before", os.path.abspath(a.before)),) if a.before else ()):
                if not os.path.isfile(g):
                    print("WARNING: no GLB for the %s pictures at %s" % (tag, g))
                    continue
                liv = os.path.join(os.path.dirname(g), name + "_livery.png")
                for sets in ("plain,shade,open,lights,rail", "grid") + (("livery",) if os.path.isfile(liv) else ()):
                    r = blender(rs, [g, os.path.join(pics, tag), sets] + ([liv] if sets == "livery" else []))
                    if r.returncode != 0 or "Traceback" in r.stderr:
                        print("WARNING: pictures (%s, %s) failed:\n    %s" % (tag, sets, "\n    ".join((r.stdout + r.stderr).strip().splitlines()[-8:])))
        print("\nRESULT: %s" % status.upper())
        print("  GLB:        %s" % glb)
        print("  triangles:  {:,}".format(c["triangles"]))
        print("  check:      %s" % c["check"])
        for s_ in c["steps"]:
            print("  step:       %s" % s_)
        for w in c.get("warnings", []):
            print("  WARNING:    %s" % w)
        for w in c["where"]:
            print("  %s %s" % ("PROBLEM:   " if status != "ok" else "largest remaining difference:", w))
        print("  pictures:   %s" % (pics if not a.no_pictures else "(skipped)"))
        print("  log:        %s" % os.path.join(out, name + "_rebuild_log.txt"))
        print("  for upload: %s" % os.path.join(out, name + "_paint.json"))
        if status == "over_budget":
            print("  The car is over the triangle budget: cut it down by hand (or raise tri_budget in its settings) before uploading.")
        elif status == "refused":
            print("  The rebuilt car differs from the source in the places above. Do not upload it; see README: When a car is refused.")
        print("  (%.0f s for the rebuild)" % took)
        return EXIT.get(status, EXIT["failed"])
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
