// usage: node shot.mjs <url> <out.png> [--eval "js"] [--settle ms] [--steps json] [--gpu]
// Launches headless Chrome with remote debugging, waits for window.__office.ready, optionally evaluates JS, settles, screenshots.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const [url, out, ...rest] = process.argv.slice(2);
const opt = { eval: null, settle: 1500, steps: null, gpu: false };
for (let i = 0; i < rest.length; i++) { if (rest[i] === '--eval') opt.eval = rest[++i]; else if (rest[i] === '--settle') opt.settle = Number(rest[++i]); else if (rest[i] === '--steps') opt.steps = rest[++i]; else if (rest[i] === '--gpu') opt.gpu = true; else if (rest[i] === '--scale') opt.scale = Number(rest[++i]); else if (rest[i] === '--mobile') { opt.mobile = true; opt.scale = opt.scale || 2; opt.size = [844, 390]; } else if (rest[i] === '--size') opt.size = rest[++i].split('x').map(Number); }   // --mobile: a landscape phone (844x390 @2x, touch)   // --scale 2: a retina-like device pixel ratio   // --gpu: ANGLE/Metal instead of SwiftShader (fast on big scenes)
const port = 9300 + Math.floor(Math.random() * 500);
const prof = mkdtempSync(join(tmpdir(), 'shotprof-'));
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-sandbox', '--disable-gpu-sandbox', ...(opt.gpu ? ['--use-angle=metal', '--enable-gpu-rasterization'] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']), '--ignore-gpu-blocklist', ...(opt.scale ? [`--force-device-scale-factor=${opt.scale}`] : []), `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, `--window-size=${(opt.size || [1400, 850]).join(',')}`, '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws; let id = 0; const waiting = new Map();
function send(method, params = {}) { return new Promise((res, rej) => { const n = ++id; waiting.set(n, { res, rej }); ws.send(JSON.stringify({ id: n, method, params })); }); }
try {
  let targets;
  for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (targets.length) break; } catch {} await sleep(250); }
  const page = targets.find((t) => t.type === 'page');
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { const w = waiting.get(d.id); waiting.delete(d.id); d.error ? w.rej(new Error(JSON.stringify(d.error))) : w.res(d.result); }
    else if (d.method === 'Runtime.exceptionThrown') console.error('PAGE EXCEPTION:', JSON.stringify(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 400));
    else if (d.method === 'Runtime.consoleAPICalled' && (d.params.type === 'error' || d.params.type === 'warning')) console.error('PAGE ' + d.params.type.toUpperCase() + ':', d.params.args.map((a) => a.value || a.description).join(' ').slice(0, 300)); });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: (opt.size || [1400, 850])[0], height: (opt.size || [1400, 850])[1], deviceScaleFactor: opt.scale || 1, mobile: !!opt.mobile }); if (opt.mobile) await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  await send('Page.navigate', { url });
  const t0 = Date.now(); let ready = false, status = '';
  while (Date.now() - t0 < 240000) {
    const r = await send('Runtime.evaluate', { expression: 'JSON.stringify({ready: !!(window.__sm2 && window.__sm2.ready), progress: (document.getElementById("progress")||{}).textContent})', returnByValue: true });
    const v = JSON.parse(r.result.value); status = v.progress; if (v.ready) { ready = true; break; }
    await sleep(500);
  }
  if (!ready) { console.error('page never became ready; last status:', status); process.exitCode = 2; }
  const steps = opt.steps ? JSON.parse(opt.steps) : [{ eval: opt.eval, settle: opt.settle, out }];
  for (const st of steps) {
    if (st.eval) { const r = await send('Runtime.evaluate', { expression: st.eval, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) console.error('eval error:', JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails.text).slice(0, 300)); else if (r.result && r.result.value !== undefined) console.log('eval →', String(r.result.value).slice(0, 400000)); }
    await sleep(st.settle ?? 1500);
    if (st.out) { const shot = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(st.out, Buffer.from(shot.data, 'base64')); console.log(`wrote ${st.out} (t+${((Date.now() - t0) / 1000).toFixed(1)}s)`); }
  }
} finally { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); await sleep(200); try { rmSync(prof, { recursive: true, force: true }); } catch {} }
