// Xbox (Treyarch) level loader + lighting that mirrors the game's own model:
//   world geometry is PRE-LIT  -> unlit: texture x baked vertex colour (x1, linear) x interior shadow map (TEXCOORD_1, DXT5 alpha)
//   characters are lit at runtime -> placed OMNI point lights (ENS class 0x90: colour, inner/outer radius, intensity) + an
//   ambient term indoors; outdoors a sun whose direction was fitted from the baked shading of the city buildings + sky light.
import * as THREE from 'three';

export const SUN_DIR = new THREE.Vector3(0.236, 0.939, -0.25).normalize();   // toward the sun (three coords), fitted from vertex colours
export const SKY = { zenith: 0x2458c0, horizon: 0x9fbce4, haze: 0xb9cde6, ground: 0x9aa3ad, fogNear: 450, fogFar: 2200 };   // blue reaches down to a narrow pale horizon band; distance haze is a separate, bluer colour (the game's smsky dome is a procedural gradient)
export const LIGHT_SCALE = Math.PI;   // game OMNI adds intensity x colour to the vertex light (gamma space); three's lambert divides by pi

const cache = new Map();
export function makeLoader(gltfLoader) { return (u) => { if (!cache.has(u)) cache.set(u, gltfLoader.loadAsync(u)); return cache.get(u); }; }
async function loadUnique(loadGLTF, urls, limit = 12) {
  const list = [...new Set(urls)]; let i = 0; const failed = [];
  await Promise.all(Array.from({ length: limit }, async () => { while (i < list.length) { const u = list[i++]; try { await loadGLTF(u); } catch (e) { cache.delete(u); failed.push(u); } } }));
  return failed;
}

// ---- light rig -----------------------------------------------------------------------------------------------------
export function setLightRig(scene, { interior = false } = {}) {
  let rig = scene.getObjectByName('xb_rig');
  if (!rig) { rig = new THREE.Group(); rig.name = 'xb_rig'; scene.add(rig); }
  rig.clear();
  if (interior) {
    rig.add(new THREE.AmbientLight(0xffffff, 1.5));                      // ~0.5 base (three divides by pi): the game's indoor character ambient
    const h = new THREE.HemisphereLight(0xfff4e6, 0x55504a, 0.7); rig.add(h);
    scene.background = new THREE.Color(0x05060a); scene.fog = null;
    const sky = scene.getObjectByName('xb_sky'); if (sky) sky.visible = false;
  } else {
    const hemi = new THREE.HemisphereLight(0xcfe0ff, 0x8a7f6a, 1.15); rig.add(hemi);
    const sun = new THREE.DirectionalLight(0xfff0dc, 2.0); sun.name = 'sun'; sun.position.copy(SUN_DIR).multiplyScalar(300); rig.add(sun); rig.add(sun.target);
    scene.background = new THREE.Color(SKY.haze); scene.fog = new THREE.Fog(SKY.haze, SKY.fogNear, SKY.fogFar);
    let sky = scene.getObjectByName('xb_sky');
    if (!sky) {
      const geo = new THREE.SphereGeometry(9000, 32, 16); const col = new Float32Array(geo.attributes.position.count * 3); const z = new THREE.Color(SKY.zenith), h = new THREE.Color(SKY.horizon), g = new THREE.Color(SKY.ground);
      for (let i = 0; i < geo.attributes.position.count; i++) { const y = geo.attributes.position.getY(i) / 9000; const c = y >= 0 ? h.clone().lerp(z, Math.pow(Math.min(1, y * 2.4), 0.55)) : h.clone().lerp(g, Math.min(1, -y * 3)); col[3 * i] = c.r; col[3 * i + 1] = c.g; col[3 * i + 2] = c.b; }   // mostly blue by ~15 deg elevation
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
      sky = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false })); sky.name = 'xb_sky'; sky.renderOrder = -1000; sky.frustumCulled = false; scene.add(sky);
    }
    sky.visible = true;
  }
  return rig;
}

// ---- material conversion ----------------------------------------------------------------------------------------------
const FLAT = { 'ground (lit)': 0x8a8780, grass: 0x4f7a38, paths: 0x9a938a };
export function toUnlit(mesh, parser, url, cells) {
  const src = mesh.material; if (!src || src.userData.__xb) return;
  if (src.map && src.map.anisotropy < 8) src.map.anisotropy = 8;   // walls seen at grazing angles (street-level cameras) turned to mush with trilinear mips alone
  const ex = src.userData || {}; const mn = (src.name || '').toLowerCase();
  if (mn.includes('dcl_') || mn.includes('lamplite') || mn.includes('lightcone') || mn.includes('glow')) { mesh.visible = false; return; }   // night light decals
  if (!src.map && mesh.geometry.attributes.position.count <= 8) { mesh.visible = false; return; }
  const u = (url || '').toLowerCase();
  // collision proxies: '*_col', 'scenecol*', 'parkgroundcol*', 'col_*' meshes and anything textured with the fx_placeholder checker
  if (/(_col\.glb$|scenecol|groundcol|__col_|_col_)/.test(u) || (src.map && /placeholder/i.test(src.map.name || (src.map.image && src.map.image.name) || ''))) { mesh.visible = false; return; }
  if (u.includes('s_sunmoon')) { mesh.visible = false; return; }          // sun + moon billboard sheet (both in one mesh, placed by script)
  if (u.includes('s_animclouds')) {   // the game's cloud layer (15 km sheet at y=1000 with the tileable s_clouda alpha texture; scrolled by the engine)
    const cm = new THREE.MeshBasicMaterial({ map: src.map || null, transparent: true, depthWrite: false, side: THREE.DoubleSide, opacity: 0.8, color: 0xffffff, fog: true }); if (cm.map) { cm.map.wrapS = cm.map.wrapT = THREE.RepeatWrapping; cm.map.repeat.set(2.5, 2.5); cm.map.needsUpdate = true; } cm.userData.__xb = true; mesh.material = cm; mesh.renderOrder = -900; mesh.frustumCulled = false; return; }   // ~1.2 km cloud cells; fogged so the sheet fades into the haze at the horizon instead of dotting the whole sky   // the sheet's UVs span ~4.8 tiles over 15 km; the engine scrolls/tiles finer, 6x gives ~500 m clouds
  if (u.includes('s_citylod') || u.includes('s_cityshore') || u.includes('citylights')) { mesh.visible = false; return; }   // whole-city LOD imposter / night-lights overlay
  if (/__v_citycar[ab]\.glb$/.test(u)) { mesh.visible = false; return; }   // the traffic vehicle KIT (taxi + sedans + van + truck + wheel pairs all at one origin) placed as a static prop = a pile of superimposed cars
  { const lm = u.match(/__lod_([a-z]\d{2,3})_/); if (lm && cells && cells.has(lm[1].toUpperCase())) { mesh.visible = false; return; } }   // per-building LOD_* imposter whose detailed cell is loaded (z-fights it); far landmarks (Ellis, Liberty) keep theirs
  if (/__s_star\.glb$/.test(u) || u.includes('_spotlight') || u.includes('spotlite') || mn.includes('blbrdsmoke') || mn === 'star') { mesh.visible = false; return; }   // night-only: star dome, billboard searchlight beams
  if (u.includes('s_oceana') || u.includes('c_water')) { mesh.position.y -= 1.2; mesh.renderOrder = -5; }   // the ocean plane is coplanar with the low-LOD ground: keep it under the land (which is itself lowered below the cell ground)
  if (url && url.toLowerCase().includes('city_ground')) { mesh.position.y -= 0.6; mesh.renderOrder = -4; }   // whole-city low-LOD ground (flat grass, 2x2 road tiles) is coplanar with the cells' textured streets/parks: keep it under them so it only shows where no cell ground exists
  // always double-sided: the export's triangle winding is inconsistent (D27 streets, interior floors and even the pizzeria facade come out
  // inverted), so back-face culling hollows out buildings and drops the hero through floors.  Cost: a camera placed inside a shop front
  // (AC72_CATTHIEF_03) sees the wall's back faces instead of looking out.
  const m = new THREE.MeshBasicMaterial({ map: src.map || null, color: src.color ? src.color.clone() : 0xffffff, vertexColors: !!mesh.geometry.attributes.color, transparent: !!src.transparent, opacity: src.opacity ?? 1, side: ex.single_sided ? THREE.FrontSide : THREE.DoubleSide, alphaTest: src.alphaTest || 0 });
  if (url && url.toLowerCase().includes('city_ground') && FLAT[mn] !== undefined) { m.map = null; m.vertexColors = false; m.color.setHex(FLAT[mn]); }   // low-LOD ground subs without textures
  // 'smtranslucent' = light-emitting effects (lamp cones, horizon haze cards, glows): additive, so day-time black cones vanish
  if (ex.shader === 'smtranslucent') { m.transparent = true; m.depthWrite = false; m.blending = THREE.AdditiveBlending; m.vertexColors = !!mesh.geometry.attributes.color; mesh.renderOrder = 4; }
  else if (ex.shader === 'smglass') { m.transparent = true; m.depthWrite = false; m.opacity = 0.55; }
  else if (ex.shader === 'smfxenv') { m.transparent = false; }
  if (u.includes('city_traffic') || (ex.shader || '').includes('traffic')) { m.transparent = true; m.blending = THREE.AdditiveBlending; m.depthWrite = false; mesh.renderOrder = 5; }   // car-light streaks over the roads
  if (m.map && m.transparent === false && (mn.includes('fence') || mn.includes('rail') || mn.includes('tree') || mn.includes('leaf'))) m.alphaTest = 0.5;
  m.userData.__xb = true; m.name = src.name; mesh.material = m;
  if (ex.lightmap !== undefined && parser) {
    parser.getDependency('texture', ex.lightmap).then((t) => { t.colorSpace = THREE.SRGBColorSpace; t.flipY = false; m.lightMap = t; m.lightMapIntensity = Math.PI; m.needsUpdate = true; }).catch(() => {});
  }
}

// ---- level --------------------------------------------------------------------------------------------------------------
let _defaultSkin;   // public/ff/default.json (the F&F Pizzeria skin) is applied by every page unless a caller passes skin: null
export async function defaultSkin() { if (_defaultSkin === undefined) { try { _defaultSkin = await (await fetch('/public/ff/default.json')).json(); } catch { _defaultSkin = null; } } return _defaultSkin; }
export async function loadXboxLevel(scene, name, { loadGLTF, filter, adjust, onStatus, rig = true, skin } = {}) {   // skin: { remap: {url: url}, add: [placements], props: {url: url} } overlays a stage; undefined = the default skin, null = none
  // adjust(p): a placement patch, applied after the filter: return the placement (or a changed copy: pos / quat) or null to drop it (a stage's broken placements, fixed per page)
  if (skin === undefined) skin = await defaultSkin();
  const stage = await (await fetch(`/public/levels/${name}/stage.json`)).json();
  const group = new THREE.Group(); group.name = 'level:' + name; scene.add(group);
  // identical placements (same mesh, position, rotation) only z-fight: scripted props like Mysterio's XB02_FAKEFLOOR are stacked 4x
  const seen = new Set();
  const src = skin ? [...stage.statics.map((p) => (skin.remap && skin.remap[p.url]) ? { ...p, url: skin.remap[p.url] } : p), ...(skin.add || [])] : stage.statics;
  const statics = src.filter(filter || (() => true)).map((p) => adjust ? adjust(p) : p).filter(Boolean).filter((p) => { const k = p.url + '|' + p.pos.map((v) => v.toFixed(2)).join(',') + '|' + p.quat.map((v) => v.toFixed(3)).join(','); if (seen.has(k)) return false; seen.add(k); return true; });
  const cells = new Set(statics.map((p) => p.url.split('/').pop().split('__')[0].toUpperCase()));   // cells whose detailed geometry is in this level
  const failed = await loadUnique(loadGLTF, statics.map((p) => p.url)); if (failed.length) console.warn(name, 'failed GLBs', failed.length, failed.slice(0, 5));
  let n = 0;
  await Promise.all(statics.map(async (p) => { try {
    const gl = await loadGLTF(p.url); const o = gl.scene.clone(true); o.position.fromArray(p.pos); o.quaternion.fromArray(p.quat); o.scale.fromArray(p.scale || [1, 1, 1]);
    o.traverse((m) => { if (m.isMesh) toUnlit(m, gl.parser, p.url, cells); });
    o.userData.placement = p;                                                    // keeps the stage record (mesh key, cell, class) with the placed object: collision hulls are looked up by it
    group.add(o); n++; } catch {} }));
  // placed lights (interiors): point lights for the characters; the world itself is already baked
  const lights = new THREE.Group(); lights.name = 'lights'; group.add(lights);
  for (const l of stage.lights || []) {
    const c = new THREE.Color(l.color[0], l.color[1], l.color[2]); const pl = new THREE.PointLight(c, l.intensity * LIGHT_SCALE, l.outer, 0); pl.position.fromArray(l.pos); pl.name = l.name; lights.add(pl);   // decay 0: flat inside, smooth cutoff at the outer radius
  }
  // world box of the real geometry (ground plane and origin placeholders excluded) -> used to decide interior/exterior per shot
  const box = new THREE.Box3(); const tmp = new THREE.Box3(); const ctr = new THREE.Vector3(); const sz = new THREE.Vector3();
  for (const o of group.children) { if (o === lights) continue; tmp.setFromObject(o); if (tmp.isEmpty()) continue; tmp.getCenter(ctr); tmp.getSize(sz); if ((ctr.length() < 8 && Math.max(sz.x, sz.y, sz.z) < 12) || sz.x > 3000) continue; box.union(tmp); }
  // slack for the rig test (same as the level mapper): building interiors' cameras sit just outside the room mesh, underground arenas' hover 30 m out
  box.expandByScalar(!stage.interior || box.isEmpty() ? 2.5 : (box.max.y < -100 ? 30 : 8));
  if (rig) setLightRig(scene, { interior: !!stage.interior });
  if (onStatus) onStatus(`${name}: ${n} props, ${(stage.lights || []).length} lights${stage.interior ? ' (interior)' : ''}`);
  return { name, stage, group, lights, box, interior: !!stage.interior, dispose: () => { scene.remove(group); } };
}

// ---- characters -----------------------------------------------------------------------------------------------------------
// Character textures are authored at ~half brightness (means 30-60 vs 75-130 for world textures): the game lights them with a
// modulate-2x vertex lambert (ambient + lights, clamped, x2).  Lambert with a 2x colour reproduces that; Standard's sheen does not.
export function toCharacterMaterials(root) {
  root.traverse((o) => {
    if (!o.isMesh || !o.material || o.material.userData.__xbChar) return;
    const src = o.material; const shader = (src.userData && src.userData.shader) || '';
    if (shader === 'smtranslucent') {                                  // rotor blur, glows: additive effect geometry on props
      const fx = new THREE.MeshBasicMaterial({ map: src.map || null, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, opacity: 0.6 }); fx.userData.__xbChar = true; o.material = fx; o.renderOrder = 4; return; }
    if (shader === 'smshadowvol' || shader === 'dropshadow') { o.visible = false; return; }
    if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();     // rigid props (camera, briefcase, tentacle pieces) ship without normals: Lambert would light them black
    const m = new THREE.MeshLambertMaterial({ map: src.map || null, color: new THREE.Color(2, 2, 2), side: THREE.DoubleSide, transparent: shader === 'smglass' || shader === 'smfxenv', opacity: (shader === 'smglass' || shader === 'smfxenv') ? 0.6 : 1, alphaTest: src.alphaTest || 0, skinning: true });
    if (src.map) { src.map.colorSpace = THREE.SRGBColorSpace; }
    m.name = src.name; m.userData.__xbChar = true; o.material = m; o.frustumCulled = false;
  });
}
