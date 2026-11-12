#!/usr/bin/env node
// Cutscene geometry check for xbscene.html (the cutscene counterpart of verify_geometry.mjs).
// verify_geometry.mjs fingerprints the city from fixed street points; this one looks through every SHOT CAMERA instead, because a cutscene
// is only right if the set, the actors and the camera agree with each other.  For each sampled frame it renders two extra passes into a
// 160x90 float target with ID materials (same side / alpha cut-out as the real materials, so it sees exactly what the frame shows):
//   level pass  -> per pixel: covered?, view depth, front or back face
//   actor pass  -> per actor: its pixels and their depth
// and derives, per shot:
//   OCCLUDED   set geometry stands between the camera and the actors (building in the wrong place, wall through the stage)
//   IN_SOLID   the camera sits inside a closed single-sided solid (a generated building): it looks out through culled walls
//   HOLE       nothing drawn below the horizon (missing ground / floor / cell)
//   VOID       an interior shot that is mostly empty background (wrong or missing set)
//   EMPTY      the shot has actors but none reaches the frame at any sample
//   FLOAT/SUNK an actor who stays in place has the feet above / below the floor (or a prop) in every sample: missing roof, set at the wrong height
//              (lower-case float / sunk = a note, under 3 m / 0.5 m or off screen: it does not fail the shot)
//   WALLFACE   a surface closer than 0.35 m fills the frame (camera pressed into a wall)
//   CAMJUMP    the camera path teleports inside a shot (bad track decode)     FOV  field of view outside 8..110 deg
//   BLACK      the real frame is black
// It also writes a contact sheet per cutscene: the real frame next to the diagnostic view
//   grey = set (darker = farther) · purple = set back faces · orange = nearer than 0.35 m · green = actor visible · red = actor hidden by the set
//   yellow = hole below the horizon · black = background
//
//   node tools/verify_cutscene.mjs                       every cutscene, 3 samples per shot  -> reports/cutscene_geometry.json + shots/verify/*.jpg
//   node tools/verify_cutscene.mjs AC62 SA24             only cutscenes whose name contains one of these
//   node tools/verify_cutscene.mjs --samples 6           more frames per shot       --all-frames  sheet shows every sample, not just flagged shots
//   node tools/verify_cutscene.mjs --notes               also print the notes (float / sunk)
//   node tools/verify_cutscene.mjs --save                accept the current result as tools/cutscene_baseline.json
//   node tools/verify_cutscene.mjs --url https://host    another build       --query hero=birdman   extra page parameters
// exit code 0 = no shot is worse than the baseline (or, without a baseline, nothing flagged), 1 = new / worse flags, 2 = a page failed to load
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync, mkdtempSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const HERE = dirname(fileURLToPath(import.meta.url)); const ROOT = join(HERE, '..'); const BASE = join(HERE, 'cutscene_baseline.json');
const argv = process.argv.slice(2); const VALUED = new Set(['--url', '--samples', '--query', '--chunk', '--out']);
const flag = (n) => argv.includes(n); const val = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const only = argv.filter((a, i) => !a.startsWith('--') && !VALUED.has(argv[i - 1])).map((s) => s.toUpperCase());
const url = val('--url', 'http://127.0.0.1:8790').replace(/\/$/, ''); const SAMPLES = +val('--samples', 3); const QUERY = val('--query', ''); const CHUNK = +val('--chunk', 6);
const OUT = val('--out', join(ROOT, 'shots', 'verify')); mkdirSync(OUT, { recursive: true }); mkdirSync(join(ROOT, 'reports'), { recursive: true });

// ---------------------------------------------------------------------------------------------------------------- in-page probe
const probe = async (name, SAMPLES, allFrames) => {
  const THREE = await import('/node_modules/three/build/three.module.js'); const sm = window.__sm2; const { scene, camera, renderer, S } = sm;
  const W = 160, H = 90, NEAR = 0.35, LEVEL = 5, ACTOR = 6;
  const P = window.__probe || (window.__probe = { rt: new THREE.WebGLRenderTarget(W, H, { type: THREE.FloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter }), mats: new Map(), levels: null, meshes: [] });
  if (S.tl?.name.toUpperCase() !== name.toUpperCase()) await sm.loadCutscene(name);
  document.getElementById('ui').classList.add('hidden'); S.playing = false;
  // ID material: writes (view depth, front-facing, 1, 1); keeps the source material's side and alpha cut-out
  const idMat = (src, skinned) => { const cut = src.alphaTest > 0 && src.map ? src.map : null; const k = [src.side, cut ? cut.uuid : '', src.alphaTest || 0].join('|');
    if (!P.mats.has(k)) P.mats.set(k, new THREE.ShaderMaterial({ side: src.side, uniforms: { map: { value: cut }, cut: { value: cut ? src.alphaTest : 0 } },
      vertexShader: '#include <common>\n#include <skinning_pars_vertex>\nvarying float vD; varying vec2 vU;\nvoid main(){ vU = uv;\n#include <skinbase_vertex>\n#include <begin_vertex>\n#include <skinning_vertex>\n#include <project_vertex>\n vD = -mvPosition.z; }',
      fragmentShader: 'uniform sampler2D map; uniform float cut; varying float vD; varying vec2 vU;\nvoid main(){ if (cut > 0.0 && texture2D(map, vU).a < cut) discard; gl_FragColor = vec4(vD, gl_FrontFacing ? 1.0 : 0.0, 1.0, 1.0); }' }));
    return P.mats.get(k); };
  const shown = (o) => { for (let p = o; p; p = p.parent) if (!p.visible && !p.userData.__culled) return false; return true; };   // xbscene hides off-screen placements per frame (__culled): they still belong to the set
  const solid = (m) => m && !Array.isArray(m) && (!m.transparent || m.alphaTest > 0) && m.blending === THREE.NormalBlending;   // glass, additive light cards and cloud sheets neither hide nor fill
  if (P.levels !== S.levels) {   // (re)index the set
    for (const e of P.meshes) e.o.layers.disable(LEVEL);
    P.levels = S.levels; P.meshes = []; scene.updateMatrixWorld(true);
    for (const lv of S.levels || []) lv.group.traverse((o) => { if (!o.isMesh || !shown(o) || !solid(o.material)) return; if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      o.layers.enable(LEVEL); P.meshes.push({ o, id: idMat(o.material, false), box: new THREE.Box3().copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld), single: o.material.side === THREE.FrontSide }); });
  }
  const interiorLevels = (S.levels || []).filter((l) => l.interior).length;
  const buf = new Float32Array(W * H * 4), lvl = new Float32Array(W * H * 4); const rc = new THREE.Raycaster(); const v = new THREE.Vector3(), d = new THREE.Vector3(), nrm = new THREE.Vector3();
  const pass = (layer, list) => {   // list: [{o, id}] -> swap in the ID materials, render that layer alone, read it back
    const keep = list.map((e) => e.o.material); list.forEach((e) => { e.o.material = e.id; });
    const bg = scene.background, fog = scene.fog, mask = camera.layers.mask, cc = renderer.getClearColor(new THREE.Color()), ca = renderer.getClearAlpha(); scene.background = null; scene.fog = null; camera.layers.set(layer);
    renderer.setRenderTarget(P.rt); renderer.setClearColor(0x000000, 0); renderer.clear(); renderer.render(scene, camera); renderer.readRenderTargetPixels(P.rt, 0, 0, W, H, buf);
    renderer.setRenderTarget(null); renderer.setClearColor(cc, ca); scene.background = bg; scene.fog = fog; camera.layers.mask = mask; list.forEach((e, i) => { e.o.material = keep[i]; });
  };
  const near = (x, y, z, r) => P.meshes.filter((e) => x > e.box.min.x - r && x < e.box.max.x + r && z > e.box.min.z - r && z < e.box.max.z + r && y > e.box.min.y - r && y < e.box.max.y + r);
  let props = [];   // the other actors' meshes (platforms, vehicles, furniture, a carrying villain): people stand on them too
  const floorGap = (p, own) => {   // foot height above the first surface under it (the ray starts 0.45 m higher, under table tops: negative = the floor is above the foot); 99 = nothing within 60 m
    const c = P.meshes.filter((e) => p.x > e.box.min.x && p.x < e.box.max.x && p.z > e.box.min.z && p.z < e.box.max.z && e.box.min.y < p.y + 0.45 && e.box.max.y > p.y - 60).map((e) => e.o);
    v.copy(p); v.y += 0.45; rc.set(v, d.set(0, -1, 0)); rc.near = 0; rc.far = 60.45; const h = rc.intersectObjects(c.concat(props.filter((o) => o.userData.__owner !== own)), false)[0]; return h ? +(h.distance - 0.45).toFixed(2) : 99; };
  const inSolid = (p) => {   // inside a closed single-sided solid: horizontal rays leave through back faces all around
    const c = near(p.x, p.y, p.z, 0.01).filter((e) => e.single); if (!c.length) return 0;
    const sides = c.map((e) => e.o.material); const uniq = [...new Set(sides)]; uniq.forEach((m) => { m.side = THREE.DoubleSide; }); let back = 0;
    for (let k = 0; k < 8; k++) { rc.set(p, d.set(Math.sin(k * Math.PI / 4), 0, Math.cos(k * Math.PI / 4))); rc.near = 0; rc.far = 120; const h = rc.intersectObjects(c.map((e) => e.o), false)[0];
      if (h && h.face && nrm.copy(h.face.normal).transformDirection(h.object.matrixWorld).dot(d) > 0) back++; }
    uniq.forEach((m) => { m.side = THREE.FrontSide; }); return back; };
  const thumbs = []; const tw = 320, th = 180; const grab = document.createElement('canvas'); grab.width = tw; grab.height = th; const g2 = grab.getContext('2d', { willReadFrequently: true });
  const diag = document.createElement('canvas'); diag.width = W; diag.height = H; const dctx = diag.getContext('2d'); const img = dctx.createImageData(W, H);
  const invP = new THREE.Matrix4(), dirW = new THREE.Vector3();
  const out = { name: S.tl.name, levels: (S.levels || []).map((l) => l.name), setMeshes: P.meshes.length, shots: [] };
  for (let si = 0; si < S.tl.shots.length; si++) {
    const sh = S.tl.shots[si]; const rec = { shot: sh.name, cam: !!sh.camera, actors: sh.actors.length, samples: [] };
    if (sh.camera) { const c = sh.camera; let step = 0, turn = 0, fmin = 9, fmax = 0; const a = new THREE.Vector3(), b = new THREE.Vector3(), qa = new THREE.Quaternion(), qb = new THREE.Quaternion();
      for (let f = 0; f < c.n; f++) { const fv = c.fov[f] > 0.05 ? c.fov[f] : 0.785; fmin = Math.min(fmin, fv); fmax = Math.max(fmax, fv); if (!f) continue; step = Math.max(step, a.fromArray(c.pos[f]).distanceTo(b.fromArray(c.pos[f - 1]))); turn = Math.max(turn, qa.fromArray(c.quat[f]).angleTo(qb.fromArray(c.quat[f - 1]))); }
      rec.camStep = +step.toFixed(2); rec.camTurn = +(turn * 57.3).toFixed(1); rec.fov = [+(fmin * 57.3).toFixed(1), +(fmax * 57.3).toFixed(1)]; }
    for (let k = 0; k < SAMPLES; k++) {
      const t = sh.start + sh.duration * (k + 0.5) / SAMPLES; sm.frame(t); scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      g2.drawImage(renderer.domElement, 0, 0, tw, th); const px = g2.getImageData(0, 0, tw, th).data; let luma = 0, dark = 0; for (let i = 0; i < px.length; i += 16) { const l = (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]) / 255; luma += l; if (l < 0.1) dark++; } const nl = px.length / 16;
      const frame = document.createElement('canvas'); frame.width = tw; frame.height = th; frame.getContext('2d').drawImage(grab, 0, 0);
      pass(LEVEL, P.meshes); lvl.set(buf);
      // actors on screen now: the shot's own plus frozen ones held over from earlier shots
      const acts = []; for (const s2 of S.tl.shots) for (const a of s2.actors) if (a.obj.visible) acts.push(a);
      const kind = new Uint8Array(W * H);   // 0 background, 1 set front, 2 set back, 3 set near, 4 actor visible, 5 actor hidden
      let cover = 0, back = 0, close = 0; for (let i = 0; i < W * H; i++) if (lvl[4 * i + 3] > 0) { cover++; kind[i] = 1; if (lvl[4 * i + 1] < 0.5) { back++; kind[i] = 2; } if (lvl[4 * i] < NEAR) { close++; kind[i] = 3; } }
      props = []; for (const a of acts) a.obj.traverse((o) => { if (o.isMesh && shown(o)) { if (o.isSkinnedMesh) o.computeBoundingSphere(); o.userData.__owner = a; props.push(o); } });
      const ares = []; let apx = 0, avis = 0;
      for (const a of acts) { const list = []; a.obj.traverse((o) => { if (o.isMesh && shown(o) && solid(o.material)) { o.layers.enable(ACTOR); list.push({ o, id: idMat(o.material, true) }); } });
        pass(ACTOR, list); list.forEach((e) => e.o.layers.disable(ACTOR));
        let n = 0, vis = 0; for (let i = 0; i < W * H; i++) if (buf[4 * i + 3] > 0) { n++; const hid = lvl[4 * i + 3] > 0 && lvl[4 * i] < buf[4 * i] - 0.05; if (!hid) vis++; if (kind[i] !== 4) kind[i] = hid ? 5 : 4; }
        const r = { name: a.name, skel: a.skeleton, px: n, vis: n ? +(vis / n).toFixed(2) : null };
        const feet = ['bip01_l_foot', 'bip01_r_foot'].map((b) => a.obj.getObjectByName(b)).filter(Boolean); const pel = a.obj.getObjectByName('bip01_pelvis') || a.obj.getObjectByName('trajectory');
        if (feet.length) { const lo = feet.map((f) => f.getWorldPosition(new THREE.Vector3())).sort((p, q) => p.y - q.y)[0]; r.gap = floorGap(lo, a); }
        if (pel) { pel.getWorldPosition(v); r.dist = +v.distanceTo(camera.position).toFixed(1); r.at = [+v.x.toFixed(1), +v.y.toFixed(1), +v.z.toFixed(1)]; }
        apx += n; avis += vis; ares.push(r); }
      // background below the horizon = a hole (sky above it is fine outdoors)
      invP.copy(camera.projectionMatrixInverse); let voidPx = 0, hole = 0;
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = y * W + x; if (kind[i]) continue; voidPx++; dirW.set((x + 0.5) / W * 2 - 1, (y + 0.5) / H * 2 - 1, 0.5).applyMatrix4(invP).transformDirection(camera.matrixWorld); if (dirW.y < -0.03) { hole++; kind[i] = 6; } }
      const N = W * H; const s = { t: +t.toFixed(2), interior: !!S.rigInterior, cover: +(cover / N).toFixed(3), void: +(voidPx / N).toFixed(3), hole: +(hole / N).toFixed(3), back: cover ? +(back / cover).toFixed(3) : 0, close: +(close / N).toFixed(3),
        actorPx: apx, actorVis: apx ? +(avis / apx).toFixed(2) : null, inSolid: inSolid(camera.position), luma: +(luma / nl).toFixed(3), dark: +(dark / nl).toFixed(2), actors: ares };
      rec.samples.push(s);
      const col = [[0, 0, 0], null, [150, 70, 200], [255, 150, 30], [60, 220, 90], [235, 50, 50], [250, 230, 40]];
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = (H - 1 - y) * W + x, o = (y * W + x) * 4; let c = col[kind[i]]; if (!c) { const g = Math.max(40, 215 - 38 * Math.log2(1 + lvl[4 * i])); c = [g, g, g]; } img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = 255; }
      dctx.putImageData(img, 0, 0); const dg = document.createElement('canvas'); dg.width = tw; dg.height = th; const dc = dg.getContext('2d'); dc.imageSmoothingEnabled = false; dc.drawImage(diag, 0, 0, tw, th);
      thumbs.push({ si, k, frame, dg, s });
    }
    // ---- verdict for the shot
    const ss = rec.samples; const med = (a) => { const b = a.filter((x) => x !== null && x !== undefined).sort((p, q) => p - q); return b.length ? b[b.length >> 1] : null; }; const frac = (f) => ss.filter(f).length / ss.length;
    const flags = []; const add = (f, why) => flags.push({ f, why });
    const framed = ss.filter((s) => s.actorPx >= 40); const tot = framed.reduce((a, s) => a + s.actorPx, 0), vis = framed.reduce((a, s) => a + s.actorPx * s.actorVis, 0);
    if (framed.length && vis / tot < 0.45) add('OCCLUDED', `${Math.round(100 * (1 - vis / tot))}% of the actors' pixels are behind the set`);
    if (frac((s) => s.inSolid >= 6 && !s.interior) >= 0.5) add('IN_SOLID', 'camera inside a closed single-sided building');
    const interior = frac((s) => s.interior) >= 0.5 || (interiorLevels && !out.levels.includes('XB_CITY'));
    if (med(ss.map((s) => s.hole)) > (interior ? 0.2 : 0.06)) add('HOLE', `${Math.round(100 * med(ss.map((s) => s.hole)))}% of the frame is background below the horizon`);
    if (interior && med(ss.map((s) => s.void)) > 0.6) add('VOID', `${Math.round(100 * med(ss.map((s) => s.void)))}% of an interior frame is background`);
    if (sh.actors.length && sh.camera && !ss.some((s) => s.actorPx >= 12)) add('EMPTY', 'no actor in frame at any sample');
    if (med(ss.map((s) => s.close)) > 0.3) add('WALLFACE', `${Math.round(100 * med(ss.map((s) => s.close)))}% of the frame is a surface closer than ${NEAR} m`);
    { const by = {}; for (const s of ss) for (const a of s.actors) if (a.gap !== undefined && a.at) (by[a.name] ||= []).push(a);
      // an actor who stays put (< 1.5 m between samples) with the lower foot off the floor in EVERY sample is standing on something that is not there
      // (or under a floor that should not be): jumps, swings and carried actors move, sitting actors keep a foot down
      const still = Object.entries(by).filter(([, a]) => a.length === ss.length && Math.max(...a.map((x) => Math.hypot(x.at[0] - a[0].at[0], x.at[1] - a[0].at[1], x.at[2] - a[0].at[2]))) < 1.5);
      const up = still.filter(([, a]) => a.every((x) => x.gap > 0.6)), down = still.filter(([, a]) => a.every((x) => x.gap < -0.2));
      // FLOAT / SUNK stop a render only when it is gross and on screen (a missing roof, a set 3 m off); smaller ones are notes: tentacle-borne Doc Ock, ledges, bar stools
      const seen = (n) => ss.some((s) => s.actors.some((x) => x.name === n && x.px >= 60 && x.vis > 0.3)); const lo = (a) => Math.min(...a.map((x) => x.gap)), hi = (a) => Math.max(...a.map((x) => x.gap));
      const txt = (l) => l.map(([n, a]) => `${n} ${lo(a) > 60 ? 'has no floor under the feet' : lo(a) + ' m above the floor'}`).join(', ');
      const gross = up.filter(([n, a]) => lo(a) > 3 && seen(n)), mild = up.filter((u) => !gross.includes(u));
      if (gross.length) add('FLOAT', txt(gross)); if (mild.length) add('float', txt(mild));
      const dtxt = (l) => l.map(([n, a]) => `${n} ${(-hi(a)).toFixed(2)} m under the floor`).join(', '); const deep = down.filter(([n, a]) => hi(a) < -0.5 && seen(n)), shallow = down.filter((u) => !deep.includes(u));
      if (deep.length) add('SUNK', dtxt(deep)); if (shallow.length) add('sunk', dtxt(shallow)); }
    if (rec.camStep > 6 && rec.camStep > 40 * (med([rec.camStep]) || 1) / 40) { const c = sh.camera; const steps = []; for (let f = 1; f < c.n; f++) steps.push(Math.hypot(c.pos[f][0] - c.pos[f - 1][0], c.pos[f][1] - c.pos[f - 1][1], c.pos[f][2] - c.pos[f - 1][2])); const m = med(steps); if (rec.camStep > Math.max(6, 25 * m)) add('CAMJUMP', `camera moves ${rec.camStep} m in one frame (median ${m.toFixed(2)})`); }
    if (rec.fov && (rec.fov[0] < 8 || rec.fov[1] > 110)) add('FOV', `fov ${rec.fov[0]}..${rec.fov[1]} deg`);
    if (frac((s) => s.dark > 0.97) >= 0.5) add('BLACK', 'frame is black');
    rec.notes = flags.filter((x) => x.f === x.f.toLowerCase()); rec.flags = flags.filter((x) => x.f !== x.f.toLowerCase()); out.shots.push(rec);
  }
  // ---- contact sheet: real frame | diagnostic, one row per sample (flagged shots only unless allFrames)
  const rows = thumbs.filter((t) => allFrames || out.shots[t.si].flags.length || t.k === (SAMPLES >> 1)); const per = 3; const cw = 2 * tw + 6, ch = th + 30;
  const sheet = document.createElement('canvas'); sheet.width = per * cw + 6; sheet.height = Math.ceil(rows.length / per) * ch + 6; const c = sheet.getContext('2d'); c.fillStyle = '#14161c'; c.fillRect(0, 0, sheet.width, sheet.height); c.font = '11px Menlo, monospace'; c.textBaseline = 'top';
  rows.forEach((t, i) => { const x = 6 + (i % per) * cw, y = 6 + Math.floor(i / per) * ch; const sh = out.shots[t.si]; c.drawImage(t.frame, x, y); c.drawImage(t.dg, x + tw, y);
    c.fillStyle = sh.flags.length ? '#ff6b5e' : '#9fe0a8'; c.fillText(`${sh.shot.replace(out.name + '_', '#')} t=${t.s.t} ${sh.flags.map((f) => f.f).join(' ') || 'ok'}`.slice(0, 46), x + 2, y + th + 2);
    c.fillStyle = '#aab2c0'; c.fillText(`act ${t.s.actorVis === null ? '-' : Math.round(t.s.actorVis * 100) + '%'} vis  hole ${Math.round(t.s.hole * 100)}%  back ${Math.round(t.s.back * 100)}%  near ${Math.round(t.s.close * 100)}%${t.s.interior ? '  int' : ''}`, x + 2, y + th + 15); });
  out.sheet = sheet.toDataURL('image/jpeg', 0.82);
  return JSON.stringify(out);
};

// ---------------------------------------------------------------------------------------------------------------- driver
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const index = await (await fetch(`${url}/public/xbox_cutscenes/index.json`)).json();
const todo = index.cutscenes.filter((c) => !only.length || only.some((o) => c.name.toUpperCase().includes(o)));
if (!todo.length) { console.error('no cutscene matches ' + only.join(' ')); process.exit(2); }
// cutscenes that share a set load it once: group by level list, then cut into pages of CHUNK so a page never holds too many actor GLBs
const groups = new Map(); for (const c of todo) { const k = (c.levels && c.levels.length ? c.levels : [c.level || 'none']).join('+'); (groups.get(k) || groups.set(k, []).get(k)).push(c); }
const pages = []; for (const g of groups.values()) for (let i = 0; i < g.length; i += CHUNK) pages.push(g.slice(i, i + CHUNK));
const port = 9300 + Math.floor(Math.random() * 500); const prof = mkdtempSync(join(tmpdir(), 'cutverify-'));
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', ...(flag('--cpu') ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : ['--use-angle=metal', '--enable-gpu-rasterization']), '--ignore-gpu-blocklist', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, '--window-size=1280,720', '--hide-scrollbars', '--mute-audio', 'about:blank'], { stdio: 'ignore' });
let ws, id = 0; const waiting = new Map(); const results = []; let failed = 0;
const send = (method, params = {}) => new Promise((res, rej) => { const n = ++id; waiting.set(n, { res, rej }); ws.send(JSON.stringify({ id: n, method, params })); });
const evaluate = async (expression) => { const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value; };
try {
  let targets; for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (targets.length) break; } catch {} await sleep(250); }
  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl); await new Promise((r) => ws.addEventListener('open', r));
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { const w = waiting.get(d.id); waiting.delete(d.id); d.error ? w.rej(new Error(JSON.stringify(d.error))) : w.res(d.result); } });
  await send('Page.enable'); await send('Runtime.enable'); await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
  for (const page of pages) {
    await send('Page.navigate', { url: 'about:blank' }); await sleep(300);
    await send('Page.navigate', { url: `${url}/xbscene.html?scene=${page[0].name}${QUERY ? '&' + QUERY : ''}` });
    const t0 = Date.now(); let ready = false; while (Date.now() - t0 < 300000) { try { if (await evaluate('!!(window.__sm2 && window.__sm2.ready)')) { ready = true; break; } } catch {} await sleep(500); }
    if (!ready) { console.error(`FAILED TO LOAD ${page.map((c) => c.name).join(' ')}`); failed += page.length; continue; }
    for (const c of page) {
      try { const r = JSON.parse(await evaluate(`(${probe.toString()})(${JSON.stringify(c.name)}, ${SAMPLES}, ${flag('--all-frames')})`));
        writeFileSync(join(OUT, `${r.name}.jpg`), Buffer.from(r.sheet.split(',')[1], 'base64')); delete r.sheet; results.push(r);
        const bad = r.shots.filter((s) => s.flags.length);
        console.log(`${bad.length ? '✗' : '✓'} ${r.name.padEnd(24)} ${String(r.shots.length).padStart(2)} shots  ${r.levels.join('+').slice(0, 40)}${r.shots.filter((s) => s.flags.length || (flag('--notes') && s.notes.length)).map((s) => `\n    ${s.shot}: ${[...s.flags, ...(flag('--notes') ? s.notes : [])].map((f) => `${f.f} (${f.why})`).join('; ')}`).join('')}`);
      } catch (e) { failed++; console.error(`✗ ${c.name}: probe failed: ${String(e.message).slice(0, 300)}`); }
    }
  }
} finally { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); await sleep(200); try { rmSync(prof, { recursive: true, force: true }); } catch {} }

// ---------------------------------------------------------------------------------------------------------------- report + baseline
const flat = {}; for (const r of results) for (const s of r.shots) flat[s.shot] = s.flags.map((f) => f.f).sort();
const nShots = Object.keys(flat).length, nBad = Object.values(flat).filter((f) => f.length).length; const tally = {}; for (const f of Object.values(flat).flat()) tally[f] = (tally[f] || 0) + 1;
if (!only.length && !QUERY) writeFileSync(join(ROOT, 'reports', 'cutscene_geometry.json'), JSON.stringify({ url, samples: SAMPLES, when: new Date().toISOString(), cutscenes: results }, null, 1));
console.log(`\n${results.length} cutscenes, ${nShots} shots: ${nShots - nBad} clean, ${nBad} flagged ${JSON.stringify(tally)}   sheets: ${OUT}/<CUTSCENE>.jpg`);
if (flag('--save')) { const prev = existsSync(BASE) && only.length ? JSON.parse(readFileSync(BASE, 'utf8')) : {}; writeFileSync(BASE, JSON.stringify({ ...prev, ...flat }, null, 0).replace(/],/g, '],\n')); console.log('baseline saved to ' + BASE); process.exit(failed ? 2 : 0); }
if (failed) process.exit(2);
if (!existsSync(BASE)) { console.log(nBad ? 'CUTSCENES FLAGGED (no baseline: fix them, or accept what is known with --save)' : 'CUTSCENES OK'); process.exit(nBad ? 1 : 0); }
const base = JSON.parse(readFileSync(BASE, 'utf8')); const worse = [], better = [];
for (const [shot, f] of Object.entries(flat)) { const b = base[shot] || []; const add = f.filter((x) => !b.includes(x)), gone = b.filter((x) => !f.includes(x)); if (add.length) worse.push(`${shot}: +${add.join(' +')}`); if (gone.length) better.push(`${shot}: -${gone.join(' -')}`); }
if (better.length) console.log(`fixed since the baseline (${better.length}):\n  ` + better.join('\n  '));
if (worse.length) console.log(`NEW since the baseline (${worse.length}):\n  ` + worse.join('\n  '));
console.log(worse.length ? 'CUTSCENES DIFFER' : 'CUTSCENES OK (nothing new vs the baseline)'); process.exit(worse.length ? 1 : 0);
