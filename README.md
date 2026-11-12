# pizza-night: Pizza Night in America, Birdie's Adventure

A browser game built from Spider-Man 2 (2004) assets: a 90-second pizza delivery flight over the city (`pizzanight.html`).
The rest of this file covers the asset pipeline and the viewer pages it is built on.

```
 source/ (your game files) ─ tools/*.py ─▶ public/models, public/levels ─ server.py ─▶ pizzanight.html
                                                                              │
                              tools/bundle_pizzanight.py ─▶ dist/ ─ tools/verify_geometry.mjs ─▶ static host
```

**No game files are in this repository.** Models, textures, audio and video are gitignored; they come from your own copy of
Spider-Man 2 (2004, PC and Xbox) through the extraction tools in `tools/` (see "Re-run extraction" below). A fresh clone has the code and the
derived JSON (level layouts, animation, fonts) but will not run until those assets are extracted into `source/`, `intermediate/` and `public/`.

Split out of a larger working repository (`sm2-office`); the scene-filming tool built on the same pipeline lives in `dollhouse-director`.

```bash
npm install
python3 server.py                                              # http://127.0.0.1:8790/pizzanight.html
python3 tools/bundle_pizzanight.py                             # static build in dist/
node tools/verify_geometry.mjs --url http://127.0.0.1:8790     # geometry gate: run on dist and on the live site before and after a deploy
```

URL options: `?night=1`, `?seed=42`, `?nocut=1` (skip the films), `?touch=1`, `?debug=1`.


Everything is driven by a self-contained Python reader for the game's Unreal Engine 2 packages (version 126)
plus Three.js pages. Original game files and derived assets live in `source/`, `intermediate/`, `public/models`,
`public/levels` (all gitignored). Nothing here needs UModel or Windows.

```
┌──────────────┐   tools/ue2/*.py    ┌──────────────────────┐   server.py :8790   ┌──────────────────────────┐
│ source/pc    │ ──────────────────▶ │ public/models/*.glb  │ ──────────────────▶ │ index.html    viewer      │
│  .ukx .usx   │  export_*.py        │ public/levels/<Map>/ │                     │ cutscene.html replay+swap │
│  .utx .whr   │  extract_scenes.py  │ public/cutscenes/*.json                    │ pizzanight.html game      │
│  .uax .bik   │  export_sounds.py   │ intermediate/audio/vo/*.m4a                │ tools/render_video.mjs    │
└──────────────┘                     └──────────────────────┘                     └──────────────────────────┘
```

## Run

```bash
python3 server.py                      # http://127.0.0.1:8790/
```

| Page | Purpose |
|---|---|
| `/` | Model + clip viewer (all exported characters/props, 158 Spidey clips) |
| `/cutscene.html?map=Wharf_Warehouse&scene=StartAmbush` | Replays a real-time cutscene: camera path, fades, letterbox, dialog, scripted pawn actions. "Swap model" replaces any pawn with another GLB |

Keys: `h` hide UI · `space` play/pause.

## Render a video

```bash
node tools/render_video.mjs Wharf_Warehouse StartAmbush renders/ambush.mp4 --fps 30 --w 1280 --h 720
node tools/render_video.mjs Wharf_Warehouse StartAmbush renders/ambush_custom.mp4 --swap SuperThugAmbusher01=custom_hero
```
Frames are rendered deterministically in headless Chrome and muxed with the dialog lines by ffmpeg.

## Xbox version (Treyarch engine) — cutscenes

The Xbox disc is a different engine (NGL). Its assets are extracted and decoded by `tools/xbox/*` + `tools/xbox_*.py`
(see `intermediate/xbox/NOTES.md` for every format detail). The animation codec is run by emulating the game's own x86
code with Unicorn, so poses are bit-exact.

```
source/xbox ─ xiso_extract ─▶ amalgapak/xbpack ─▶ intermediate/xbox/packs/*.pack
   XBMESH/XBSKEL/XBSANIM ──▶ tools/xbox_export_cutscene.py ──▶ public/xbox_cutscenes/<SHOT>/{scene.json, <actor>.glb}
   ENS + lego buildings ───▶ tools/xbox_export_cell.py ───────▶ public/levels/XB_CITY, XB_B10, XB_LAB (Octavius lab) …
   STREAMS_SCENE_EN.WBK ──▶ vgmstream ───────────────────────▶ intermediate/xbox/audio/scene/*.m4a (one per cutscene)
```

| What | How |
|---|---|
| Play a whole cutscene with dialogue | `/xbscene.html?scene=AC87_CATFUN&level=XB_CITY` (pick from the "Cutscene" dropdown; shots run back to back, dialogue starts at 0) |
| Play one shot | `/xbscene.html?scene=SA04_MEETOCTAVIUS_21&level=XB_LAB` |
| Export one shot | `tools/.venv/bin/python -I tools/xbox_export_cutscene.py PK_STORY_06/SA04_MEETOCTAVIUS_21` |
| Export everything (366 shots, ~1 h) + rebuild `public/xbox_cutscenes/index.json` | `tools/.venv/bin/python -I tools/xbox_export_all_cutscenes.py --force` |
| Birdman as the hero | add `&hero=birdman` to the player URL or `--query hero=birdman` to the video renderer: the Birdie Survivors hero (`birdman_v2.glb`) retargeted onto the cutscene rigs (`birdman2_spiderman.glb` for Spider-Man, `birdman2_peter_casual.glb` for Peter) stands in, and the shot's own clip plays on him; the pigeon mask sits on the collar with the human neck hidden (`make_birdman.sh` OFFSET2/CLIP2/HIDE2) (`hero=birdman1` is the earlier Spidey-rig Birdman). Examples in `renders/birdman/xbox/` (AC62, AC63, AC68, AC89, AC90 as Spider-Man; AC96 as Peter); the PC equivalents (`cutscene.html` "Swap model" / `render_video.mjs --swap Tag=birdman_v2`, `birdman_peter` for PeterPawn) are in `renders/birdman/pc/`: only the bank stair scenes (`GoingDown`, `GoingUp`) and the warehouse `MJEscape` keep the hero pawn near the camera; the other PC scenes are gameplay triggers with the hero off screen or 100 m+ away, and the `MOV_*` scenes fade to black at once because the game plays a Bink animatic there |
| Generic buildings | the city's 'lego' buildings are the game's own unit ring meshes (`CITY blgNNx1`/`aptNNx1`, 5 units tall) instanced per record with its side (`*sid*`) and corner (`*edg*`) textures, trims and pedestals tiled by texture aspect (`tools/xbox/lego_mesh.py`; `tools/xbox_relego.py` rebuilds all 88 cells' `<CELL>__lego.glb` in seconds). All level textures use 8x anisotropic filtering. Ring orientation is checked against the game's own LOD city mesh (`tools/xbox_lego_orient.py`: a third of the non-square rings are stored 90° off and no record field says so), the records' yaw is applied left-handed (negated after the Z flip, for rings and props alike), and lego geometry is single-sided like the game's. The lego-prop fire escapes are snapped to the building face they hang on (`tools/xbox_fix_fireescapes.py`). Rebuild order after a city export: orient → `xbox_relego.py` → fire escapes |
| Video | `node tools/render_video.mjs XB_CITY AC87_CATFUN renders/catfun.mp4 --page xbscene.html --gpu` (`--gpu` = ANGLE/Metal instead of SwiftShader, ~20x faster on the city; `--frames N` for a quick test) |

### Lighting (how the Xbox game lights things, reproduced in `public/js/xblevel.js`)

| What | In the game | In the viewer |
|---|---|---|
| World geometry | pre-lit: texture × baked vertex colour (modulate ×1) × per-room shadow map (`*_SHDWMAP`, lighting in the DXT5 alpha) | unlit `MeshBasicMaterial` + linear vertex colours + `lightMap` on `TEXCOORD_1` |
| Characters | per-vertex Lambert ×2 from placed OMNI lights (+ ambient) — character textures are authored at half brightness | `MeshLambertMaterial` with colour 2.0; point lights from the cell's ENS light records (colour, radius, intensity); fitted sun outdoors |
| Light effects (`smtranslucent`: lamp cones, haze cards, glows) | additive | additive blending |
| Collision proxies (`*_COL`, `SCENECOL*`, `fx_placeholdera`), city LOD imposter, script-placed sun/cloud billboards | never drawn | hidden |

Each cutscene auto-loads every level its shots use (`public/xbox_cutscenes/levels.json`) and switches between the interior rig and the
sun/sky rig per shot: a shot counts as interior when its camera sits inside an interior level's bounds *and* a ray cast straight up hits that
level's geometry (a ceiling), so street shots in front of a building keep the sun.

- **Traffic & inspection:** `tools/xbox_export_vehicles.py` splits the city vehicle kits (`CITY/V_CITYCARA`, `V_CITYCARB`) into per-variant GLBs with wheels (`public/models/xbox/vehicles/`, `vehicles.json`); `pizza.html` drives the taxi and the box truck along the route (the only complete bodies: the other kit sections are hood/trunk/door/bed parts the game assembles on its vehicle rig) and hides the high-altitude traffic streak layer. `glbview.html?glb=/public/models/xbox/vehicles/v_citycara_000.glb,...` renders any GLBs on a grid for a quick look.

### Walk / run test area (`walk.html`)

A small playable patch of the city around the pizzeria (and its interior): WASD / arrows to move (Alt = walk), Shift to sprint, Space to jump (hold for higher), C to crouch, mouse drag or right stick for the camera, G to show the collision hulls, R to reset; gamepads work. The hero is **Birdman** (`public/models/xbox/anim/birdman_loco.glb`, the pigeon-headed civilian moved onto the Xbox Spider-Man rig with `tools/retarget_skin.py`, which keeps his original skin weights and maps bones by name); `?hero=spidey` plays Spider-Man. Spider-Man uses the real gameplay clips (`public/models/xbox/anim/spidey_loco.glb`, 42 clips) the way the game does: the walk/run/sprint loops share one foot phase advanced by distance (speeds measured from their root motion, `spidey_loco_speeds.json`: walk 2.0, run 6.4, sprint 11.1 m/s), starts and stops play the idle-to-run / run-to-idle clips and cover their root distance, standing reversals play the turn clips and rotate by their root yaw, tap = hop and hold = charged jump with the fall and landing clips. Collision is built from the game's own `COLL` hulls (pack type 0x12, decoded in `tools/xbox/coll.py`, exported by `tools/xbox_export_coll.py` to `public/models/xbox/coll/`) wherever a placed mesh has one, and from the rendered streets/buildings otherwise. Walking into the pizzeria's street door puts you inside at the dining aisle and pushing against the aisle's street-side wall takes you back out (the interior is a separate set that does not line up with the door, as in the game). `?x=&z=&radius=` picks another spot in the city; `?hulls=1` starts with the hulls visible. An invisible floor at street level (−0.22) backs the colliders: the city ground mesh is too big to be one and the street pieces leave gaps, so without it you could fall through (the same floor is in `survivors.html`).

### PC walk test (`walk_pc.html`)

The same controller on the PC (UE2) assets: `/walk_pc.html` drops Spider-Man (`public/models/characters/spideymesh.glb`) on the sidewalk at
`WallStreet_CityStreet`'s PlayerStart (`-43.5, 0, -5.1`, facing the street along +X; `?map=ParkAve_CityStreet` or any map with a `stage.json`
and a cutscene JSON works — maps without a PlayerStart spawn on the street-level PathNode nearest the middle of their pedestrian network —
and `?x=&z=&heading=` override the spot). WASD / arrows run, Shift or Alt walk, Space jumps (hold = higher), mouse drag
or the right stick steers the camera, G shows the collision cells, R resets; gamepad left stick at half deflection walks, A jumps.
`window.__sm2 = { scene, camera, renderer, S, ready, setInput, step, teleport }` drives it headless exactly like `walk.html`
(`S.probe(x,y,z,dx,dz,len)` casts a horizontal ray, `S.traceOn` records every tick into `S.trace`).

- **Clips.** The PC Spidey GLB carries 158 clips but none of them has root motion (the `RootParent` track barely moves), so there are no
  start/stop/turn clips to cover a distance: idle ↔ walk ↔ run is a plain blend by speed. Used: `IdleRest`, `Walk` (1.33 s), `RunForwards`
  (0.5 s), `JumpStandingTakeoff` → `JumpStandingMid` / `JumpRunningMid` → `Fall`, `JumpStandingLand` / `FromFallToRun`, `Fidget1` when idle.
- **Speeds.** Gameplay speeds are assumed: walk 2.0, run 6.4 m/s. The natural speed of each loop is measured at load from the clip itself
  (the planted foot — the lower toe bone — slides back under the hips at the ground speed; median of its stance-phase speed): `Walk` 1.27 m/s
  (cycle 1.69 m) and `RunForwards` 8.54 m/s (cycle 4.27 m), so the loops play at ×1.58 and ×0.75. As in `walk.html` the two loops share one
  foot phase advanced by distance travelled (phase-aligned on "left foot forward"), and the gait follows the distance actually covered, so
  pushing into a wall shows idle rather than running on the spot. The HUD prints the cycle / natural / rate numbers. The rig faces −Z;
  the foot sole is 0.094 m below the toe bone (measured from the skinned mesh on the idle pose) and every used clip gets a 30 fps
  foot-contact table so the hips sit at the right height in every pose.
- **Level + collision.** Every static of `stage.json` within 150 m of the spawn (789 of 1656, placed with the same pos/quat/scale as
  `cutscene.html`, same hemisphere + sun rig and PBR materials) plus the map's BSP (`bsp.glb`, 21.9 k triangles, the streets, kerbs and
  building shells). `public/js/pclevel.js` builds the colliders: the 93 map-wide BSP meshes are re-cut into 24 m grid cells (353 cells)
  so the capsule only raycasts what is near; opaque statics are used as they are (1087 meshes); alpha-blended / additive materials
  (glass, beacons, tree cards), water and backdrop surfaces are skipped (199). Kerbs are 0.32 m, so the wall rays start at 0.65 m
  (above the 0.55 m step height) and kerbs are stepped on and off instead of blocking.
- **Checked headless** (`tools/shot.mjs` + `__sm2.setInput/step`, `shots/pc_walk_*.png`): walk 2.0 m/s with the planted toe stationary in
  world space (0.00–0.01 m/s), run 6.4 m/s (stance-foot world speed 0.2–0.9 m/s), stop in 0.17 s / 0.5 m, jump 2.3 m high / 0.87 s air
  with `Fall` → `JumpStandingLand`, the feet stay on the probed ground (mean offset < 1 cm; 0.2–0.3 m transients while stepping a kerb or
  landing), running into the granite facade at x = −46.3 stops at a 0.43 m gap and pushing 45° into it slides 13.5 m along it with no
  tunnelling.

### F&F Pizzeria skin

Joe's Pizza is **F&F Pizzeria** by default on every page that loads Xbox levels (`pizza.html`, `walk.html`, `xbscene.html`, and any future page, because the default lives in `loadXboxLevel`: `public/ff/default.json` = variant v1). `?ff=none` shows the original, `?ff=v2` / `?ff=v3` the other variants. The skin: navy instead of red everywhere (awning, valances and lamp shades, counter diamonds, kitchen floor, seats, menu board, delivery bag), the old "Hans" neon removed, the **F&F pizza box** (white, crest centred on the lid, FRANKS.PIZZA on the long sides and F&F PIZZERIA on the short sides, in Birdman's hand in `pizza.html` and `survivors.html`), and a new sign: v1 (the default) is the painted board (crest, script F&F, PIZZERIA); v2 is the board with **3D extruded script letters, PIZZERIA and a raised crest plaque**, v3 a crest board plus a **hanging blade sign** at the door. Everything is a runtime overlay (`public/ff/skin_vN.json`: url remaps + extra placements + prop remaps) built by `tools/ff_recolor.py`, `tools/ff_sign.py`, `tools/ff_box.py` (the box meshes are re-UV'd by projection because the game's atlas shares one strip for all four edges) and `tools/ff_props.py`; the 3D letters are pixel-extruded from the logo images (`intermediate/ff/ff_script_logo.png`, `ff_crest.png`).

### UI / HUD assets (Xbox)

`public/ui/index.html` is a gallery of every HUD, icon, logo, loading-screen and web texture decoded from the Xbox packs (133 PNGs with alpha, `public/ui/*.png`, index in `public/ui/index.json`; click a tile to copy its URL). Bitmap fonts (`i_neue` Helvetica-style, `i_serpentine` sci-fi, `i_zeroes` HUD digits, `i_button_icons` controller glyphs, `i_arcade`) are exported as atlas PNG + glyph metrics JSON in `public/ui/fonts/` (per glyph: `char, x, y, advance, gx, gy, gw, gh`, plus `cellheight`/`ascent`), and the 1199 English game strings are in `public/ui/globaltext_english.json`. Re-export: `tools/.venv/bin/python -I tools/xbox_export_ui.py`.

### Pizza Time (procedural mission recreation)

The pizza delivery is a gameplay mission, not a cutscene, so `pizza.html` rebuilds it from the game's own parts:
1. **Joe's Pizza** (interior cell `F48I01` → `XB_PIZZERIA`): Peter (hero rig + `PETER` mesh, `SM2PPTALK*` clips) and Mr. Aziz
   (`PED_MALEFATJAKSIMPLE`, `CIVSTALK*`) at the counter, game-style text boxes, Aziz's briefing line (`VSSLM004`, best guess from the voice bank).
2. **Launch**: Spider-Man runs out of the door, leaps and web-zips to the first anchor.
3. **Swing**: a pendulum simulation along a road tour found on the city's own road mesh (`tools/pizza_roads.py` → `tools/pizza_route.py`),
   posed with the real swing set `SMSWGVERT000…315` blended by rope angle, `SMWEBJMPFLY` in flight, pizza box in hand, pizza theme
   (`MX_FINICULI`), HUD counter.
4. **Delivery** to a pedestrian playing `CIVSGRABPIZZA`.

`/pizza.html` (scripted / side / free camera, `h` hides the panel) and
`node tools/render_video.mjs XB_CITY pizza renders/pizza_time.mp4 --page pizza.html --gpu`. Birdman plays the whole thing: Peter in the intro (`public/models/xbox/anim/birdman_pizza.glb`, re-targeted onto the Peter intro rig) and the delivery hero (`birdman_moves.glb`, re-targeted onto the sprint/jump/swing rig), both made with `tools/retarget_skin.py`.

Shots whose camera block is empty use the game's gameplay camera in the original; the page substitutes a follow cam behind the first actor.
Doc Ock's tentacle rig (OCRIG) is exported rigid (bind pose) until its ENT part→bone table is parsed. Facial morphs are not applied.

## Use your own character model

1. Build your model in any tool in an A/T-pose, human proportions, **Y up, facing -Z, feet at y=0**. Export `.glb`.
2. Quick path (no Blender), binds to the original Spider-Man skeleton with nearest-bone weights and copies all 158 clips:
   ```bash
   tools/.venv/bin/python -I tools/rig_custom.py --skeleton public/models/characters/spideymesh.glb \
       --custom ~/my_model.glb --out public/models/characters/custom_hero.glb
   ```
   Options: `--fit none` to keep your scale, `--bones 3` for softer blending. Any `--skeleton` works (e.g. `maryjanemesh.glb`).
   For a model that is **already skinned** to one of the exported rigs (PC or Xbox), use `tools/retarget_skin.py --src model.glb --skeleton <other rig>.glb --out ...` instead: it keeps the model's own weights and maps bones by name (PC ↔ Xbox table built in, `--map a=b` for others).
3. Blender path (**experimental**: headless automatic weights currently mangles non-watertight test meshes; prefer step 2 or do it interactively as described below):
   ```bash
   /Applications/Blender.app/Contents/MacOS/Blender -b --python tools/blender_rig_custom.py -- \
     --skeleton public/models/characters/spideymesh.glb --custom ~/my_model.glb --out public/models/characters/custom_hero.glb
   ```
   For hand-painted weights: open Blender, import `spideymesh.glb`, delete its mesh, parent yours to the armature
   (Ctrl+P → Automatic Weights), paint, then File → Export glTF (GLB, include animations).
4. Reload any page: `custom_hero` appears in the model lists and the cutscene "Swap model" dropdown.
   A rigged example is included: `public/models/characters/custom_dummy.glb` (blocky green stand-in).


## Character customisation tools (no Blender)

| Tool | Purpose |
|---|---|
| `tools/retexture.py MODEL.glb --list / --set name=png` | Swap any texture inside an exported character |
| `tools/uv_layout.py MODEL.glb` | UV wireframe + body-region map (which texels are torso/arms/legs…) for painting |
| `tools/paint_outfit.py MODEL.glb --out tex.png` | Procedurally paint a texture by body region (skin-tight look; good for suits) |
| `tools/transfer_mesh.py --source A.glb --target B.glb` | Move a clothed body onto another skeleton by bone name (e.g. civilian Male02 onto Spider-Man → 158 clips) |
| `tools/attach_prop.py --model X.glb --prop head.glb --bone head --fit 1.6 --aim-tip -z --hide-regions head` | Rigid-attach any mesh (mask, hat, weapon) to a bone, auto-fitted |
| `tools/recolor_male02.py --shirt r,g,b --jeans r,g,b --shoes r,g,b` | Recolor the civilian body texture |
| `tools/make_birdman.sh` | Full rebuild of the Birdman example (pigeon-head scan + street clothes on the Spidey rig), then **Birdman v2** for the game: the civilian's own rig with the Spider-Man move clips merged in |
| `tools/merge_clips.py --into A.glb --from B.glb --clips X,Y --out C.glb` | Copy clips between rigs by bone name, rotations only (bones the target lacks are dropped, bone lengths stay) |
| `tools/bulk_mesh.py MODEL.glb --out X.glb [--inflate 'regex=metres']` | Push vertices out along their normals per bone region, blended by skin weight (a stockier build) |

Civilian bodies (`male02mesh`, `male03mesh`, `male05mesh`, `peterparkermesh`, `female0Xmesh`) share 40 bone names with Spider-Man,
so `transfer_mesh.py` keeps their artist-made clothing geometry while giving them every Spider-Man clip.

## Re-run extraction

```bash
PY=tools/.venv/bin/python
$PY -I tools/export_all_characters.py                                  # all .ukx -> public/models/characters
for m in source/pc/Maps/*.whr; do
  $PY -I tools/extract_scenes.py "$m"; $PY -I tools/export_stage.py "$m"; $PY -I tools/export_bsp.py "$m"
done
$PY -I tools/export_sounds.py source/pc/Sounds/VOAudio.uax intermediate/audio/vo_raw   # then ffmpeg -> m4a
$PY -I tools/dump_object.py source/pc/Maps/Wharf_Warehouse.whr --class SceneManager   # inspect any object
```

## Format notes (verified from the data)

- Packages: UE2 v126 / licensee 1. Maps `.whr`. Skeletal animation uses UE2.5 FlexTracks (types 1/3/4).
- Quaternions: conjugate every bone (uniform), bake MeshOrigin/RotOrigin/0.92 MeshScale + 0.02 m/uu into the GLB.
- Matinee: `PathStyle` default Linear; missing `Duration` = instant cut; `CamOrientation` = None/LookAtActor/FacePath/Interpolate/Dolly.
- ScriptedSequence `WaitForEvent` retags the sequence (so the event that triggers a sequence also satisfies its first wait).
- Dialog is Bink audio inside `VOAudio.uax`; no subtitles exist for cutscene lines (only tutorial/narrator).
- `.bik` movies are 512×512 animatics, converted to `intermediate/cutscenes/reference/videos/`.
- Xbox XBMESH vertex layout is decided by the material's **shader**, not by the stride: stride 28 `smlegosimple` = pos, normal, colour, uv but `smtranslucent/smfxenv/smglass` = pos, normal, uv, colour; stride 36 `smlego` = pos, normal, colour, uv, uv2 but `smshiny` = pos, normal, tangent, binormal, uv, colour (full table in `intermediate/xbox/NOTES.md`). Mis-reading these gives rainbow lamp shades and scrambled glass.
- Xbox cutscene props on the 2-bone `simple` skeleton are identified by their block name with trailing digits stripped (`ENT_E39I02_CHAIRA16` → `ENT_E39I02_CHAIRA`); web strands (`web` skeleton, spline controls) have no mesh and are skipped.
