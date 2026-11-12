#!/bin/bash
# Rebuild "Birdman": civilian body (Male02) re-skinned onto Spider-Man's skeleton, recolored to cream shirt /
# jeans / olive sneakers, pigeon-head scan decimated to retro poly count and attached to the head bone.
set -e
cd "$(dirname "$0")/.."
PY=tools/.venv/bin/python; BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
HEAD_SRC=${HEAD_SRC:-intermediate/birdhead.glb}   # from ~/Downloads/11_2_2026/11_2_2026.obj (Blender obj->glb)
TRIS=${TRIS:-900}        # retro poly budget for the head (N64-ish: 500-1000)
PIX=${PIX:-128}          # head texture size (64 = crunchier)
FIT=${FIT:-0.95}; OFFSET=${OFFSET:-0,-0.08,0.01}; ROT=${ROT:--4,0,0}
CLIP=${CLIP:--0.02}      # planar cut just below the head joint: mask rim overlaps the top of the (visible) human neck
# v2 (below) sits the mask 3.5 cm lower so its rim meets the collar and hides the human neck polygons too: no hairline / skin showed from behind in cutscenes
OFFSET2=${OFFSET2:-0,-0.115,0.01}; CLIP2=${CLIP2:--0.055}; HIDE2=${HIDE2:-head,neck}
BODY=${BODY:-male02mesh}; TEX=${TEX:-intermediate/retex/male02_street.png}
STYLE=${STYLE:-}         # set STYLE=--flat for PS1-style faceted shading
[ -f "$TEX" ] || $PY -I tools/recolor_male02.py --out "$TEX"
$BLENDER -b --python tools/blender_decimate.py -- --in "$HEAD_SRC" --out intermediate/birdhead_low.glb --tris $TRIS 2>&1 | grep -E 'DECIMATED|rror'
$PY -I tools/transfer_mesh.py --source public/models/characters/$BODY.glb --target public/models/characters/spideymesh.glb \
    --texture MaleBodyVersion02a="$TEX" --out public/models/characters/street_body.glb
$PY -I tools/attach_prop.py --model public/models/characters/street_body.glb --prop intermediate/birdhead_low.glb --bone head \
    --fit $FIT --anchor bottom --aim-tip -z --rot $ROT --offset $OFFSET --clip-below $CLIP --pixel-tex $PIX --tex-gain 1.25 $STYLE --hide-regions head --out public/models/characters/birdman.glb
echo "done -> public/models/characters/birdman.glb  (view: http://127.0.0.1:8790/?model=/public/models/characters/birdman.glb)"

# ---- Birdman v2 (survivors.html): the civilian's OWN rig instead of the Spider-Man skeleton — natural hands and shoulders, upright idle/walk/run —
# with the Spider-Man move clips merged in by rotation (tools/merge_clips.py), bulked up (tools/bulk_mesh.py) and the same pigeon head.
$PY -I tools/retexture.py public/models/characters/$BODY.glb --set GenericMaleTextures.MaleBodyVersion02a="$TEX" --out intermediate/bm2_body.glb
$PY -I tools/merge_clips.py --into intermediate/bm2_body.glb --from public/models/characters/spideymesh.glb \
    --clips JumpStandingTakeoff,JumpStandingMid,JumpRunningMid,Fall,JumpStandingLand,FromFallToRun,LightPickupThrow,HitFromFront,Dieforwards,Fidget1 --out intermediate/bm2_c1.glb
$PY -I tools/merge_clips.py --into intermediate/bm2_c1.glb --from public/models/characters/spideymesh.glb --clips RunForwards,Walk,IdleRest --suffix _sm --out intermediate/bm2_c2.glb
$PY -I tools/merge_clips.py --into intermediate/bm2_c2.glb --from public/models/characters/thug01mesh.glb --clips RunForwards,RunCombat,Walk,IdleRest --suffix _thug --out intermediate/bm2_clips.glb   # same skeleton as the civilian: the thug run is the one the game uses
$PY -I tools/bulk_mesh.py intermediate/bm2_clips.glb --out intermediate/bm2_bulk.glb --inflate '^spine_01$=0.012' --inflate '^spine_0[234]$=0.022' --inflate '^neck=0.006' --inflate '_shoulder$=0.02' \
    --inflate '_upper_arm$=0.018' --inflate '_lower_arm$=0.012' --inflate '_hand$=0.004' --inflate '^hip$=0.012' --inflate '_upper_leg$=0.01' --inflate '_lower_leg$=0.006'   # half the tool's default: a little stockier, not a linebacker
$PY -I tools/attach_prop.py --model intermediate/bm2_bulk.glb --prop intermediate/birdhead_low.glb --bone head \
    --fit $FIT --anchor bottom --aim-tip -z --rot $ROT --offset $OFFSET2 --clip-below $CLIP2 --pixel-tex $PIX --tex-gain 1.25 $STYLE --hide-regions $HIDE2 --out public/models/characters/birdman_v2.glb
echo "done -> public/models/characters/birdman_v2.glb"
# cutscene stand-ins (xbscene.html ?hero=birdman): v2 on the Xbox Spider-Man and Peter rigs
$PY -I tools/retarget_skin.py --src public/models/characters/birdman_v2.glb --skeleton public/xbox_cutscenes/SA04_MEETOCTAVIUS_01/hero.glb --out public/models/xbox/anim/birdman2_spiderman.glb
$PY -I tools/retarget_skin.py --src public/models/characters/birdman_v2.glb --skeleton public/xbox_cutscenes/SA04_MEETOCTAVIUS_01/peter.glb --out public/models/xbox/anim/birdman2_peter_casual.glb
