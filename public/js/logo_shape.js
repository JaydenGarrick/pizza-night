// Traces a black-and-white logo image into an extruded, centred geometry: every pixel brighter than `threshold` is solid.  The outline is
// collected as oriented pixel edges chained into loops (so the staircase is exact), simplified (Douglas-Peucker, `simplify` px) and built into
// THREE.Shape(s) with holes; the result is `height` m tall and `depth` m thick, centred on the origin, facing +Z.
import * as THREE from 'three';

export async function logoGeometry(url, { height = 0.5, depth = 0.12, threshold = 128, simplify = 1.0, invert = false, smooth = 1, jitter = 0 } = {}) {   // jitter: px of deterministic vertex scatter after simplification (hand-cut look)
  const img = await new Promise((res, rej) => { const i = new Image(); i.crossOrigin = 'anonymous'; i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const w = img.naturalWidth, h = img.naturalHeight; const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d'); g.drawImage(img, 0, 0); const d = g.getImageData(0, 0, w, h).data;
  const on = new Uint8Array(w * h); for (let i = 0; i < w * h; i++) { const v = (d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2]) / 3; on[i] = ((v > threshold) !== invert) ? 1 : 0; }
  const fg = (x, y) => x >= 0 && y >= 0 && x < w && y < h && on[y * w + x] === 1;
  const segs = new Map(); const key = (x, y) => x * 65536 + y;
  const add = (x0, y0, x1, y1) => { const k = key(x0, y0); let a = segs.get(k); if (!a) { a = []; segs.set(k, a); } a.push([x1, y1]); };
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { if (!fg(x, y)) continue;   // clockwise in image space (y down) = counter-clockwise once y is flipped
    if (!fg(x, y - 1)) add(x, y, x + 1, y); if (!fg(x + 1, y)) add(x + 1, y, x + 1, y + 1); if (!fg(x, y + 1)) add(x + 1, y + 1, x, y + 1); if (!fg(x - 1, y)) add(x, y + 1, x, y); }
  const loops = [];
  for (const [k, outs] of segs) { while (outs.length) { const sx = Math.floor(k / 65536), sy = k % 65536; let [x, y] = outs.pop(); const pts = [[sx, sy]]; let guard = 0;
    while (!(x === sx && y === sy) && guard++ < 4e6) { pts.push([x, y]); const a = segs.get(key(x, y)); if (!a || !a.length) break; [x, y] = a.pop(); }
    if (pts.length > 8) loops.push(pts); } }
  const rdp = (pts, eps) => { if (pts.length < 3) return pts; let maxD = 0, idx = 0; const [ax, ay] = pts[0], [bx, by] = pts[pts.length - 1]; const len = Math.hypot(bx - ax, by - ay) || 1e-9;
    for (let i = 1; i < pts.length - 1; i++) { const [px, py] = pts[i]; const dd = len < 1e-6 ? Math.hypot(px - ax, py - ay) : Math.abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / len; if (dd > maxD) { maxD = dd; idx = i; } }   // a closed loop starts and ends on the same point: split it at the farthest point first
    if (maxD > eps) { const l = rdp(pts.slice(0, idx + 1), eps), r = rdp(pts.slice(idx), eps); return l.slice(0, -1).concat(r); } return [pts[0], pts[pts.length - 1]]; };
  const chaikin = (pts) => { const out = []; for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; out.push([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25], [a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75]); } return out; };
  const area = (pts) => { let s = 0; for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; s += a[0] * b[1] - b[0] * a[1]; } return s / 2; };
  const inside = (p, poly) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > p[1]) !== (yj > p[1]) && p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi) c = !c; } return c; };
  let seed = 7; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  let polys = loops.map((l) => { let p = rdp(l.concat([l[0]]), simplify); p = p.slice(0, -1); for (let i = 0; i < smooth; i++) p = chaikin(p); if (jitter) p = p.map(([x, y]) => [x + (rnd() - 0.5) * 2 * jitter, y + (rnd() - 0.5) * 2 * jitter]); return p.map(([x, y]) => [x, h - y]); });   // flip y: image down -> world up
  polys = polys.filter((p) => Math.abs(area(p)) > 4); const maxA = Math.max(...polys.map((p) => Math.abs(area(p)))); const sign = Math.sign(area(polys.reduce((b, p) => Math.abs(area(p)) > Math.abs(area(b)) ? p : b)));   // the biggest loop is an outline; loops wound the other way are holes
  const outers = polys.filter((p) => Math.sign(area(p)) === sign && Math.abs(area(p)) > maxA * 0.01).map((p) => sign > 0 ? p : p.slice().reverse()), holes = polys.filter((p) => Math.sign(area(p)) !== sign).map((p) => sign > 0 ? p : p.slice().reverse());
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity; for (const p of outers) for (const [x, y] of p) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
  const s = height / Math.max(1e-6, maxY - minY); const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2; const V = (p) => p.map(([x, y]) => new THREE.Vector2((x - cx) * s, (y - cy) * s));
  const shapes = outers.map((o) => { const sh = new THREE.Shape(V(o)); for (const hl of holes) if (inside(hl[0], o)) sh.holes.push(new THREE.Path(V(hl))); return sh; });
  const geo = new THREE.ExtrudeGeometry(shapes, { depth, bevelEnabled: false, curveSegments: 4 }); geo.translate(0, 0, -depth / 2); geo.computeVertexNormals(); geo.computeBoundingSphere();
  geo.userData.logo = { loops: loops.length, outers: outers.length, holes: holes.length, verts: outers.reduce((n, p) => n + p.length, 0), px: [maxX - minX, maxY - minY] };
  return geo;
}
