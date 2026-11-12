// usage: node tools/render_video.mjs <map|level> <sceneTag|xbox cutscene> <out.mp4> [--fps 30] [--w 1280] [--h 720] [--port 8790] [--swap Actor=mesh ...] [--page cutscene.html|dollhouse.html] [--query hero=birdman]
//        dollhouse: node tools/render_video.mjs x <savedSceneName> out.mp4 --page dollhouse.html
// Renders a cutscene deterministically frame by frame in headless Chrome, then muxes dialog audio with ffmpeg.
import { spawn, execFileSync } from 'node:child_process';
import { writeFileSync, mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const [map, sceneTag, out, ...rest] = process.argv.slice(2);
const opt = { fps: 30, w: 1280, h: 720, port: 8790, swaps: [], page: 'cutscene.html' };
for (let i = 0; i < rest.length; i++) { const k = rest[i]; if (k === '--swap') opt.swaps.push(rest[++i]); else if (k === '--page') opt.page = rest[++i]; else if (k === '--gpu') opt.gpu = true; else if (k === '--query') opt.query = rest[++i]; else if (k.startsWith('--')) opt[k.slice(2)] = Number(rest[++i]); }
// --gpu: real GPU (ANGLE/Metal) instead of SwiftShader — ~10x faster on scenes with thousands of draw calls; --frames N: render only the first N frames (test)
const port = 9300 + Math.floor(Math.random() * 500);
const prof = mkdtempSync(join(tmpdir(), 'sm2vid-')); const frames = mkdtempSync(join(tmpdir(), 'sm2frames-'));
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-sandbox', ...(opt.gpu ? ['--use-angle=metal', '--enable-gpu-rasterization'] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']), '--ignore-gpu-blocklist', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, `--window-size=${opt.w},${opt.h}`, '--hide-scrollbars', '--autoplay-policy=no-user-gesture-required', '--mute-audio', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const waiting = new Map();
const send = (method, params = {}) => new Promise((res, rej) => { const n = ++id; waiting.set(n, { res, rej }); ws.send(JSON.stringify({ id: n, method, params })); });
const evaluate = async (expression) => { const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value; };
try {
  let targets; for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (targets.length) break; } catch {} await sleep(250); }
  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { const w = waiting.get(d.id); waiting.delete(d.id); d.error ? w.rej(new Error(JSON.stringify(d.error))) : w.res(d.result); } else if (d.method === 'Runtime.exceptionThrown') console.error('PAGE EXCEPTION:', JSON.stringify(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 300)); });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: opt.w, height: opt.h, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: `http://127.0.0.1:${opt.port}/${opt.page}?map=${encodeURIComponent(map)}&scene=${encodeURIComponent(sceneTag)}${opt.query ? '&' + opt.query : ''}` });   // --query hero=birdman etc. is passed straight to the page
  const t0 = Date.now();
  while (Date.now() - t0 < 240000) { if (await evaluate('!!(window.__sm2 && window.__sm2.ready)')) break; await sleep(400); }
  for (const s of opt.swaps) { const [actor, mesh] = s.split('='); await evaluate(`window.__sm2.S.swaps[${JSON.stringify(actor)}] = ${JSON.stringify(mesh)}`); }
  if (opt.swaps.length) await evaluate('window.__sm2.reloadPawns ? window.__sm2.reloadPawns() : null');
  await evaluate(`document.getElementById('ui').classList.add('hidden'); document.getElementById('status').style.display='none'; window.__sm2.S.playing=false; window.__sm2.setSize(${opt.w}, ${opt.h}); true`);
  if (opt.page.startsWith('dollhouse')) await evaluate(`window.__sm2.scene.children.filter(o=>o.isGridHelper||o.type==='GridHelper').forEach(o=>o.visible=false); window.__sm2.scene.traverse(o=>{ if (o.isTransformControls || o.type==='TransformControlsGizmo' || o.name==='TransformControls') o.visible=false; }); true`);
  await sleep(500);
  const dur = await evaluate('window.__sm2.S.dur'); const events = await evaluate('JSON.stringify(((window.__sm2.S.tl && window.__sm2.S.tl.events) || window.__sm2.S.events || []).filter(e=>e.dialog))');   // Xbox page: S.tl.events; PC page: S.events (ActionTriggerDialog)
  const tracks = JSON.parse(await evaluate('JSON.stringify(window.__sm2.audioTracks || [])'));   // [{file:'/intermediate/...m4a', t}] (Xbox page)
  const n = Math.min(Math.ceil(dur * opt.fps) + 1, opt.frames || 1e9);
  console.log(`scene ${sceneTag}: ${dur.toFixed(2)}s -> ${n} frames @ ${opt.fps}fps`);
  await evaluate('window.__sm2.say = () => {}; true');   // no audio playback while rendering
  for (let i = 0; i < n; i++) {
    const t = i / opt.fps;
    await evaluate(`window.__sm2.frame(${t})`);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(frames, `f${String(i).padStart(6, '0')}.png`), Buffer.from(shot.data, 'base64'));
    if (i % 30 === 0) process.stdout.write(`\r  frame ${i}/${n}`);
  }
  process.stdout.write('\n');
  // mux: video from frames, audio = dialog lines delayed to their start times
  const ev = tracks.length ? tracks.map((tr) => ({ t: tr.t || 0, path: tr.file.replace(/^\//, '') })).filter((e) => existsSync(e.path))
    : JSON.parse(events).map((e) => ({ t: e.t, path: `intermediate/audio/vo/${e.dialog}.m4a` })).filter((e) => existsSync(e.path));
  const args = ['-y', '-framerate', String(opt.fps), '-i', join(frames, 'f%06d.png')];
  for (const e of ev) args.push('-i', e.path);
  let filter = '';
  if (ev.length) {
    filter = ev.map((e, i) => `[${i + 1}:a]adelay=${Math.round(e.t * 1000)}|${Math.round(e.t * 1000)}[a${i}]`).join(';') + ';' + ev.map((_, i) => `[a${i}]`).join('') + `amix=inputs=${ev.length}:normalize=0,apad[aout]`;
    args.push('-filter_complex', filter, '-map', '0:v', '-map', '[aout]', '-shortest');
  }
  args.push('-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'medium');
  if (ev.length) args.push('-c:a', 'aac', '-b:a', '128k');
  args.push(out);
  execFileSync('ffmpeg', args, { stdio: ['ignore', 'ignore', 'inherit'] });
  console.log(`wrote ${out} (${ev.length} audio tracks mixed)`);
} finally { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); await sleep(200); try { rmSync(prof, { recursive: true, force: true }); rmSync(frames, { recursive: true, force: true }); } catch {} }
