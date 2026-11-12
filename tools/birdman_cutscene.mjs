#!/usr/bin/env node
// Birdman cutscenes in one command: pick a cutscene, check it, render it with Birdman standing in for Spider-Man / Peter Parker.
//
//   node tools/birdman_cutscene.mjs --list            which cutscenes are worth making: hero on screen, clean geometry, dialogue
//   node tools/birdman_cutscene.mjs AC90 AC62         check + render each match  -> renders/birdman/xbox/<CUTSCENE>.mp4
//   node tools/birdman_cutscene.mjs --best 5          render the 5 best-ranked ones that are not rendered yet
//   node tools/birdman_cutscene.mjs AC90 --preview    no video: only the check + contact sheet (shots/verify/birdman/<CUTSCENE>.jpg), ~30 s
// options: --force      render even when the geometry check flags shots (default: skip and say why)
//          --hero NAME  stand-in set from xbscene.html STANDINS (default birdman; birdman1 = the earlier Spidey-rig one)
//          --frames N   only the first N frames (quick look)      --w 1280 --h 720 --fps 30
//
//   pipeline:  index.json ─▶ verify_cutscene.mjs (hero=birdman) ─▶ flags? ─no─▶ render_video.mjs (xbscene.html?hero=birdman&label=0) ─▶ mp4 + dialogue
//                                   │                               └yes─▶ skipped unless --force (sheet shows the bad shots)
//                                   └▶ shots/verify/birdman/<CUTSCENE>.jpg
// --list ranks from reports/cutscene_geometry.json (written by a full `node tools/verify_cutscene.mjs` run; re-run it after level changes).
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const HERE = dirname(fileURLToPath(import.meta.url)); const ROOT = join(HERE, '..'); process.chdir(ROOT);
const argv = process.argv.slice(2); const VALUED = new Set(['--hero', '--frames', '--w', '--h', '--fps', '--best']);
const flag = (n) => argv.includes(n); const val = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const names = argv.filter((a, i) => !a.startsWith('--') && !VALUED.has(argv[i - 1])).map((s) => s.toUpperCase());
const HERO = val('--hero', 'birdman'); const OUT = join('renders', 'birdman', 'xbox'); const SHEETS = join('shots', 'verify', 'birdman'); mkdirSync(OUT, { recursive: true });
const index = JSON.parse(readFileSync('public/xbox_cutscenes/index.json', 'utf8')).cutscenes;
const HERO_RIGS = new Set(['spiderman', 'peter_casual']);   // the rigs xbscene.html has Birdman stand-ins for

// ---- ranking: how much of the cutscene shows the hero, and how many of its shots pass the geometry check
function rank() {
  const rep = existsSync('reports/cutscene_geometry.json') ? JSON.parse(readFileSync('reports/cutscene_geometry.json', 'utf8')) : null;
  if (!rep) { console.error('no reports/cutscene_geometry.json yet: run  node tools/verify_cutscene.mjs  once (about 15 min)'); process.exit(2); }
  return rep.cutscenes.map((r) => { const c = index.find((x) => x.name === r.name) || {}; let n = 0, on = 0; const rigs = new Set();
    for (const s of r.shots) for (const f of s.samples) { n++; const h = f.actors.filter((a) => HERO_RIGS.has(a.skel)); h.forEach((a) => rigs.add(a.skel === 'spiderman' ? 'Spidey' : 'Peter')); if (h.some((a) => a.px >= 150 && a.vis >= 0.5)) on++; }
    const bad = r.shots.filter((s) => s.flags.length); const hero = n ? on / n : 0; const clean = 1 - bad.length / r.shots.length;
    return { name: r.name, dur: c.duration || 0, shots: r.shots.length, bad, hero, clean, rigs: [...rigs].join('+') || '—', audio: !!c.audio, done: existsSync(join(OUT, r.name + '.mp4')),
      score: hero * (bad.length ? 0.25 * clean : 1) * (c.audio ? 1 : 0.6) }; }).sort((a, b) => b.score - a.score);
}
if (flag('--list')) {
  const rows = rank(); const dot = (r) => (!r.bad.length && r.hero >= 0.4 ? '🟢' : r.hero < 0.15 || r.clean < 0.5 ? '🔴' : '🟡');
  console.log('   cutscene                  len  shots  hero on screen  stands in for  dialogue  geometry');
  for (const r of rows) console.log(`${dot(r)} ${r.name.padEnd(24)} ${String(Math.round(r.dur)).padStart(4)}s ${String(r.shots).padStart(5)}  ${(Math.round(r.hero * 100) + '%').padStart(13)}   ${r.rigs.padEnd(13)}  ${r.audio ? 'yes' : 'no '}       ${r.bad.length ? `${r.bad.length} flagged: ${[...new Set(r.bad.flatMap((s) => s.flags.map((f) => f.f)))].join(' ')}` : 'clean'}${r.done ? '   [rendered]' : ''}`);
  console.log('\n🟢 clean + hero in 40%+ of the frames   🟡 usable, look at the sheet first   🔴 hero barely on screen or mostly broken\nrender:  node tools/birdman_cutscene.mjs <NAME> [<NAME> ...]     or     --best 5');
  process.exit(0);
}
let todo = names.length ? index.filter((c) => names.some((n) => c.name.toUpperCase().includes(n))) : [];
if (flag('--best')) { const pick = rank().filter((r) => !r.bad.length && r.hero >= 0.4 && !r.done).slice(0, +val('--best', 5)).map((r) => r.name); todo = index.filter((c) => pick.includes(c.name)); }
if (!todo.length) { console.error('nothing to do: give cutscene names (substring match), --best N, or --list'); process.exit(2); }

let failed = 0;
for (const c of todo) {
  console.log(`\n━━ ${c.name}  (${c.duration.toFixed(1)} s, ${c.shots.length} shots, ${c.audio ? 'dialogue' : 'no dialogue'})`);
  if (!c.shots.some((s) => s.actors.some((a) => /^(hero|peter)/.test(a)))) console.log('   note: no Spider-Man / Peter in this cutscene, Birdman will not appear');
  const v = spawnSync('node', ['tools/verify_cutscene.mjs', c.name, '--query', `hero=${HERO}&label=0`, '--out', SHEETS], { encoding: 'utf8', maxBuffer: 1 << 26 });
  const mine = v.stdout.split('\n').filter((l) => l.startsWith('    ') || l.includes(c.name + ' '));   // a substring can match several cutscenes: keep this one's lines
  const lines = []; let on = false; for (const l of v.stdout.split('\n')) { if (/^[✓✗] /.test(l)) on = l.slice(2).split(' ')[0] === c.name; if (on && (/^[✓✗] /.test(l) || l.startsWith('    '))) lines.push(l); }
  console.log((lines.length ? lines : mine).join('\n') || v.stdout + v.stderr); console.log(`   sheet: ${join(SHEETS, c.name + '.jpg')}`);
  const flagged = lines.some((l) => l.startsWith('✗')) || !lines.length;
  if (flag('--preview')) continue;
  if (flagged && !flag('--force')) { console.log('   skipped: geometry check flagged shots (look at the sheet; --force renders anyway)'); failed++; continue; }
  const out = join(OUT, c.name + '.mp4'); const levels = (c.levels && c.levels.length ? c.levels : [c.level]).filter(Boolean).join('+') || 'none';
  const args = ['tools/render_video.mjs', levels, c.name, out, '--page', 'xbscene.html', '--gpu', '--query', `hero=${HERO}&label=0`];
  for (const k of ['--frames', '--w', '--h', '--fps']) if (val(k)) args.push(k, val(k));
  const r = spawnSync('node', args, { stdio: 'inherit' }); if (r.status !== 0 || !existsSync(out)) { console.log('   render failed'); failed++; }
}
process.exit(failed ? 1 : 0);
