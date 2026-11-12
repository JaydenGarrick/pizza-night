#!/usr/bin/env node
// Geometry fingerprint for pizzanight.html: from ~45 fixed street / pavement / park points it casts 64 rays each (16 headings x 4 pitches, eye height)
// into the loaded city and records what every ray hits and how far away (sky = -1), plus a top-down hole scan of the playable patch.
// A saved fingerprint from a build that was checked by eye is the baseline; any later build (local, dist/, the live URL) is compared ray by ray:
// a missing wall, an open roof line, a piece that moved or vanished all show up as rays that now reach sky or land somewhere else.
//   node tools/verify_geometry.mjs --save                      fingerprint http://127.0.0.1:8790 into tools/geometry_baseline.json
//   node tools/verify_geometry.mjs                             check the local server against the baseline
//   node tools/verify_geometry.mjs --url https://host          check another build (dist server, live site)
// exit code 0 = within tolerance, 1 = geometry differs (prints the worst points), 2 = page failed to load
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const HERE = dirname(fileURLToPath(import.meta.url)); const BASE = join(HERE, 'geometry_baseline.json');
const args = process.argv.slice(2); const flag = (n) => args.includes(n); const val = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const url = val('--url', 'http://127.0.0.1:8790').replace(/\/$/, ''); const TOL = +val('--tol', 2.5);   // % of rays allowed to differ
const probe = () => {
  const { THREE, scene, camera, S } = window.__sm2; window.__sm2.setInput({ x: 0, y: 0, sprint: false, walk: false, jump: false }); window.__sm2.step(0.2);
  const skip = /thug|prison|super|puma|character|ped_|aziz|beacon|gem|glow|shadow|safety_floor|pizzab|itm_|hull:|cloud|sky|oceana/i;
  const meshes = []; scene.updateMatrixWorld(true);
  scene.traverse((o) => { if (!o.isMesh || o.isSkinnedMesh || !o.geometry || !o.visible) return; let p = o, bad = false; while (p) { if (skip.test(p.name || '')) { bad = true; break; } p = p.parent; } if (!bad) meshes.push(o); });
  const rc = new THREE.Raycaster(); rc.camera = camera; rc.far = 260; const dir = new THREE.Vector3(), org = new THREE.Vector3();
  const pts = [];
  for (let x = -370; x <= -130; x += 20) { pts.push([x, 722]); pts.push([x, 713]); }                 // main street + north pavement
  for (let z = 640; z <= 700; z += 20) { pts.push([-376, z]); pts.push([-172, z]); }               // cross streets
  for (let x = -300; x <= -200; x += 25) pts.push([x, 600]);                                        // back street
  for (let x = -230; x <= -150; x += 40) { pts.push([x, 750]); pts.push([x, 765]); }               // park / plaza
  const out = [];
  for (const [x, z] of pts) { const rays = [];
    for (const pitch of [0, 15, 35, 60]) for (let k = 0; k < 16; k++) { const a = k * Math.PI / 8, c = Math.cos(pitch * Math.PI / 180);
      dir.set(Math.sin(a) * c, Math.sin(pitch * Math.PI / 180), Math.cos(a) * c); org.set(x, 2.2, z); rc.set(org, dir);
      const h = rc.intersectObjects(meshes, false)[0]; rays.push(h ? Math.round(h.distance * 2) / 2 : -1); }
    out.push({ p: [x, z], r: rays }); }
  let holes = 0, n = 0; rc.far = 80; dir.set(0, -1, 0);
  for (let x = -370; x <= -130; x += 4) for (let z = 690; z <= 775; z += 4) { org.set(x, 40, z); rc.set(org, dir); n++; if (!rc.intersectObjects(meshes, false).length) holes++; }
  return JSON.stringify({ meshes: meshes.length, colliders: S.colliders.length, holes, groundRays: n, points: out });
};
const steps = JSON.stringify([{ eval: `(${probe.toString()})()`, settle: 100 }]);
const r = spawnSync('node', [join(HERE, 'shot.mjs'), `${url}/pizzanight.html?autostart=1&mute=1&seed=3&nocut=1`, '/dev/null', '--gpu', '--steps', steps], { encoding: 'utf8', maxBuffer: 1 << 26 });
const line = (r.stdout + '\n' + r.stderr).split('\n').find((l) => l.startsWith('eval → {'));
if (!line) { console.error('page did not return a fingerprint:\n' + (r.stdout + r.stderr).split('\n').filter((l) => !/skinning/.test(l)).slice(-6).join('\n')); process.exit(2); }
const fp = JSON.parse(line.slice('eval → '.length)); const nRays = fp.points.reduce((a, p) => a + p.r.length, 0); const sky = fp.points.reduce((a, p) => a + p.r.filter((d) => d < 0).length, 0);
console.log(`${url}: ${fp.meshes} meshes, ${fp.colliders} colliders, ${fp.points.length} points, ${nRays} rays (${(100 * sky / nRays).toFixed(1)}% sky), ground holes ${fp.holes}/${fp.groundRays}`);
if (flag('--save')) { writeFileSync(BASE, JSON.stringify(fp)); console.log('baseline saved to ' + BASE); process.exit(0); }
if (!existsSync(BASE)) { console.error('no baseline: run with --save on a build you have checked by eye'); process.exit(2); }
const base = JSON.parse(readFileSync(BASE, 'utf8')); let diff = 0, opened = 0; const worst = [];
fp.points.forEach((p, i) => { const b = base.points[i]; let d = 0, o = 0; p.r.forEach((v, k) => { const w = b.r[k]; if ((v < 0) !== (w < 0) || Math.abs(v - w) > 1.5) { d++; if (v < 0 || v > w + 1.5) o++; } }); diff += d; opened += o; if (d) worst.push({ at: p.p, changed: d, opened: o }); });
worst.sort((a, b) => b.changed - a.changed); const pct = 100 * diff / nRays;
console.log(`vs baseline: ${diff} of ${nRays} rays differ (${pct.toFixed(2)}%), ${opened} of them now see further or sky; mesh count ${base.meshes} -> ${fp.meshes}; holes ${base.holes} -> ${fp.holes}`);
for (const w of worst.slice(0, 8)) console.log(`  x ${w.at[0]} z ${w.at[1]}: ${w.changed}/64 rays changed (${w.opened} opened up)`);
const ok = pct <= TOL && fp.holes <= base.holes; console.log(ok ? 'GEOMETRY OK' : 'GEOMETRY DIFFERS');
process.exit(ok ? 0 : 1);
