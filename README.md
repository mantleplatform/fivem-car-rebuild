# FiveM car rebuild for Mantle

This script takes a FiveM (GTA V) car and rebuilds it as if it had been made for [Mantle](https://mantleplatform.com). You get one clean, skinned `.glb` you can bring into Unreal with the Mantle Core plugin, plus pictures to check it before you upload.

It does this on its own:

- Imports the car with Sollumz and drops collision, damage, low-detail and prop meshes.
- Sorts every source material into one of about 16 jobs Mantle understands (body paint, second paint, glass, tire, rim, chrome, interior, lamp lenses, and so on), and gives each job the car's own picture.
- Finds the doors, hood, trunk and side mirrors by their position, and builds the four wheels (front and rear can differ) with the brake calipers on their own hubs.
- Removes faces nobody can see and thins the heaviest pieces until the car fits Mantle's triangle budget.
- Lays out the paint for liveries, sets smooth shading, builds the skeleton (hinges, wheel centers, steering wheel) and exports the GLB.
- Checks the rebuilt car against the source and tells you if anything went missing.

Your car's original files are only read, never changed.

## What you need

| | Version | Notes |
|---|---|---|
| Windows | 10 or 11 | macOS and Linux should work but are untested. |
| [Blender](https://www.blender.org/download/) | **5.2** (tested) | 4.2 or newer is required by Sollumz. Other versions may give slightly different results. |
| [Sollumz](https://docs.sollumz.org) | **2.9.0** (tested) | The Blender add-on that reads GTA files. |
| [Python](https://www.python.org/downloads/) | 3.9 or newer | Only runs `rebuild_car.py`; the real work happens inside Blender. |

## Install

1. Install Blender 5.2.
2. Install Sollumz in Blender: **Edit > Preferences > Get Extensions**, open the **Repositories** menu (top right), click **+**, choose **Add Remote Repository**, enter `https://repo.sollumz.org/`, then search for **Sollumz** and click **Install**. See the [Sollumz docs](https://docs.sollumz.org) if this changes.
3. Download this repository (green **Code** button, **Download ZIP**, or `git clone`).
4. Optional: copy `config.example.json` to `config.json` and set where Blender is and where results go. Without it, the script looks for Blender in `C:\Program Files\Blender Foundation\` and writes to an `output` folder in the folder you run it from.

## Run

Point the script at the car's own folder, the one that holds `<name>.yft` (and usually `<name>_hi.yft` and `<name>.ytd`). In a FiveM resource this is usually `stream\<name>`.

```
python rebuild_car.py "C:\FiveM\mycarpack\stream\mycar"
```

That is all most cars need. It takes about a minute, then about two minutes for the pictures. Blender runs in the background at low priority, so you can keep working (set `"low_priority": false` in `config.json` to run it at normal speed).

Options:

| Option | What it does |
|---|---|
| `name` (after the folder) | The car's file name without `.yft`, if the folder holds more than one car. |
| `--out DIR` | Where results go. The car goes into `DIR\<name>\`. |
| `--settings FILE` | This car's settings file (see [Settings](#settings)). By default the script uses `cars\<name>.json` if it exists. |
| `--blender PATH` | Path to `blender.exe`, if it was not found. You can also set the `BLENDER` environment variable. |
| `--before OLD.glb` | Also takes pictures of an older GLB of the same car with the same cameras, so you can compare. |
| `--no-pictures` | Skip the pictures. |
| `--pictures-only` | Only take the pictures again for a car you already rebuilt. |

## What comes out

Everything goes into `output\<name>\`:

| File | What it is |
|---|---|
| `<name>_skinned.glb` | The rebuilt car. This is the file you import into Unreal. |
| `<name>_check.json` | The result, the check numbers, the steps that ran, warnings and materials. |
| `<name>_paint.json` | Values for the upload step: the starting second paint color, and for a car with a livery, the livery file and the body's starting color. |
| `<name>_livery.png` | Only for a car whose paint carries a printed picture: its livery, made for the rebuilt car's paint layout. Add it in the vehicle builder's Liveries step. |
| `<name>_rebuild_log.txt` | Everything the script decided, step by step. Read this when something looks wrong. |
| `<name>_blender_stdout.txt` | Blender's own output, for errors. |
| `pictures\after_*.png` | Review pictures (see below). |

At the end the script prints a result:

| Result | Meaning | GLB name |
|---|---|---|
| **OK** | The car passed the check and fits the budget. Look at the pictures, then go on to the upload. | `<name>_skinned.glb` |
| **OVER_BUDGET** | The car passed the check but has more triangles than `tri_budget` (178,000). Cut it down in Blender before uploading. | `<name>_skinned.OVER_BUDGET.glb` |
| **REFUSED** | The rebuilt car differs from the source. The result lists where. Do not upload it. | `<name>_skinned.REFUSED.glb` |
| **FAILED** | The car could not be rebuilt (for example a missing wheel, an unreadable file, a mistake in the settings). The reason is printed. | none |

The exit code is 0 for OK, 2 for OVER_BUDGET, 3 for REFUSED and 1 for FAILED, so you can script it.

### The pictures

They are simple Blender pictures (flat lighting, body paint shown red) with the same cameras every time. Look at them before you upload:

- `after_plain_*`: the car from the front, side and back.
- `after_open_*`: doors, hood and trunk open. Check they swing from the right place and the window goes with its door.
- `after_rail_*` and `after_roofrails_left_vs_right`: left against right. Paint should look the same on both sides.
- `after_grid_*`: a test grid on the paint. This is how a livery will sit on the car. The grid should be even, not stretched or torn.
- `after_lights_*`: the lamps up close.
- `after_shade_*`: the shading on the door and hood. It should be smooth with crisp edges.
- `after_livery_*`: only for a car with a livery: the car wearing it over its starting paint color.

## What the check means

Every rebuilt car is compared with its source by shooting rays at both from 26 directions: once closed, and once with the doors, hood, trunk and glass taken away so the inside is compared too. A third pass looks out from the seats, so the cabin can't lose its walls. Each risky step (hidden-face removal, thinning) is kept only if the car still passes. The check line reads like this:

```
missing 0.001%, spikes 0.000%, holes/tears 0.110% (limits 0.15 / 0.15 / 0.40%); cabin ... holes 0.015% (limit 0.20%)
```

- **missing**: rays that hit the source but miss the rebuild. A piece is gone.
- **spikes**: rays that hit something in the rebuild that is not in the source. A stray or stretched piece.
- **holes/tears**: rays whose first hit moved more than 4 cm. A hole or a torn surface.
- **cabin holes**: rays from the seats that see farther in the rebuild than in the source.

The "largest remaining difference" lines say where the biggest differences are (part, material and position, in meters, nose toward +x). The check does not see color, and it does not see spikes smaller than about 3.5 cm, so always look at the pictures too.

## Settings

A car needs no settings file. Add one only when the log or the pictures show something the automatic rules got wrong. Put it in `cars\<name>.json` (the script finds it there) or pass it with `--settings`. Keys you leave out keep their defaults. Keys starting with `_` are notes and are ignored. A misspelled key stops the script with a list of the known keys.

Material and part names are the ones in the log (`job ... <-` lines list which source materials went to which job). Regexes are [Python regular expressions](https://docs.python.org/3/library/re.html), case-insensitive, and match anywhere in the name. Blender adds `.001`, `.002` to repeated material names; those numbers are stable for a given car.

| Key | Default | What it does |
|---|---|---|
| `drop_parts` | `[]` | Source parts to throw away, by name. |
| `join` | `{}` | `{"misc_b": "bonnet"}`: add a piece to an opening part (doors, `bonnet`, `boot`). |
| `no_auto_join` | `[]` | Pieces the automatic door/hood/mirror rules must leave alone. |
| `mirror_parts` | `[]` | Pieces that are side mirrors although the automatic rule missed them (they ride the front door). |
| `material_jobs` | `[]` | `[["regex", "job"], ...]`: send source materials to a job. First match wins, before the built-in rules. |
| `part_material_jobs` | `{}` | `{"headlight": [["regex", "job"], ...]}`: the same, only for parts whose name starts with the key. |
| `pictures` | `{}` | `{"interior": "leather_01"}`: which source picture a job uses. By default, the picture of the job's biggest readable source material. |
| `inner_material_regex` | `""` | Source materials that mark inner (unpainted) paint faces. Empty: decided by which way each face points. |
| `extra_materials` | `{}` | `{"decal_white": [0.85, 0.85, 0.85]}`: extra flat-color jobs that `material_jobs` can point at. Don't use words Mantle reads in the name (light, lamp, lens, glass, tire, rim, chrome, roof). |
| `protect_from_thinning` | `[]` | Parts the thinning step must leave whole (a bumper that tears when thinned). |
| `wheel` | `{}` | `{"tire": "regex", "rim": "regex", "brake": "regex"}`: override how the wheel's materials are told apart. |
| `wheel_tri_budget` | `7500` | Each wheel is reduced to this many triangles if it is heavier. |
| `tri_budget` | `178000` | The whole car. Wheels and dense pieces are reduced further when it is over. |
| `hidden_faces` | `"standard"` | `"careful"` removes fewer hidden faces. Use it when the car only just passes the hole check and then can't be thinned. |
| `secondary_paint` | `null` | The starting color of the second paint layer (players can change it): `{"match": "PRIMARY"}`, `{"finish": "chrome"}` or `{"color": [r, g, b], "finish": "gloss"}`. Written to `<name>_paint.json`. |
| `extra_yfts` | `{}` | `{"mycar_body_1.yft": "bodyshell"}`: extra `.yft` files next to the main one whose meshes join the car under that part name. |
| `copy_to_other_side` | `[]` | Parts whose twin on the other side is missing: copied across the middle as `<part>_m`. A missing door's twin is copied by itself. |
| `save_blend` | `false` | Also save the rebuilt car as `<name>_rebuild.blend`. |

Jobs for `material_jobs`, `part_material_jobs` and `pictures`: `PRIMARY` (body paint), `SECONDARY` (second paint), `tire`, `rim`, `chrome`, `glass`, `head_lens`, `tail_lens`, `reverse_lens`, `indicator_lens`, `interior`, `plastic_black`, `carbon`, `badge`, `grille`, `reflector`, plus any name from `extra_materials`.

Examples from three real cars are in [`examples/settings`](examples/settings):

- `2019m5.json`: drops a piece, names the inner paint material and the interior picture, and fixes lamp parts.
- `2022jeep.json`: extra flat colors for parts whose pictures are missing, an engine-bay color, careful hidden-face removal.
- `camaro68t.json`: one rule (the seat stitching is marked as paint in the source) and chrome as the second paint.

A good order for a new car: run it with no settings, read the log, look at the pictures, add a settings file for what you saw (usually 3 to 10 lines), and run it again.

## Limits

- Cars and other four-wheel vehicles only. Motorcycles are refused. Middle wheels of six-wheelers are not built (a warning says so).
- The car must have a front wheel mesh (`wheel_lf` or `wheel_rf`) and rear wheel bones (`wheel_lr` / `wheel_rr`) or a rear wheel mesh. A car with its own rear wheel or rear brake mesh gets those at the back; otherwise the front wheel is used at all four corners.
- Doors, hood and trunk are found by GTA's names (`door_dside_f`, `door_pside_f`, `door_dside_r`, `door_pside_r`, `bonnet`, `boot`). A car that names them differently (a `tailgate`) gets no opening part for it.
- Textures Sollumz can't read stay flat color. Decals, and materials whose picture is missing, become black plastic unless a setting says otherwise.
- A livery printed on the body paint (a paint material with its own picture in the car's files, at least 512 px) becomes a real Mantle livery: the body stays plain paint, and the picture is copied onto the rebuilt paint layout as `<name>_livery.png` (2048 px, see-through where the paint has no picture). Players can switch it off and recolor the paint under it. To keep a picture off the livery, send its material to `PRIMARY` with `material_jobs`.
- Where paint and livery can't be told apart (a picture on the second paint color), the picture stays on the car itself in materials named `print`, `print_2` and so on, at most 2048 px. Players can't recolor those parts.
- Some cars put their livery on GTA's lamp shader, so the body glows when the headlights are on. The script notes which light in `<name>_paint.json` as `livery_glow` (`head`, `rear` and so on). In the vehicle builder's Liveries step, set that livery's **Livery Glows** light to it, and the livery lights up with that light in Mantle.
- Pictures GTA draws on the lamp shader (not the livery) glow too: they stay on the car in materials named `print_glow_<light>`, `print_2_glow_<light>` and so on, which glow with that light.
- Paint layout uses 30 to 45% of the livery sheet; window frames and fender shapes leave gaps. The layout can come out packed a little differently from one run to the next.
- Thinning can tear thin parts, so thin bars and brackets are never thinned. Use `protect_from_thinning` for anything else that tears.
- The check does not see color or very small spikes. Always look at the pictures.

## After the script: getting the car into Mantle

The rebuilt GLB goes into Unreal Engine with the Mantle Core plugin, which turns it into a Mantle vehicle and uploads it. See [Bringing in a FiveM car](https://mantleplatform.com/docs/creators/vehicles/#fivem) in the Mantle docs for the steps.

Use `<name>_paint.json` there: `secondary` is the second paint color's starting finish or color (the material is named `SECONDARY`). The steering wheel needs nothing from you: the vehicle builder finds its `steering_wheel` bone and makes it turn.
