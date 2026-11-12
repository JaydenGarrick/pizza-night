// PC (Unreal Engine 2) level helpers shared by walk_pc.html: the same stage.json placement and light rig that cutscene.html uses,
// plus a collider builder that splits map-sized meshes (the BSP) into grid cells so a capsule controller can raycast only what is near.
import * as THREE from 'three';

const cache = new Map();
export function makeLoader(gltfLoader) { return (u) => { if (!cache.has(u)) cache.set(u, gltfLoader.loadAsync(u)); return cache.get(u); }; }

// cutscene.html's rig: a cool hemisphere + one warm-white sun on the exported PBR materials (PC levels are lit at runtime, unlike the Xbox's pre-lit sets)
export function setPCLightRig(scene, { background = 0x0b0d10, fog = null } = {}) {
  let rig = scene.getObjectByName('pc_rig');
  if (!rig) { rig = new THREE.Group(); rig.name = 'pc_rig'; scene.add(rig); }
  rig.clear();
  rig.add(new THREE.HemisphereLight(0xcfd8ff, 0x3a3328, 1.3));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.name = 'sun'; sun.position.set(30, 60, 40); rig.add(sun);
  scene.background = new THREE.Color(background); scene.fog = fog;
  return rig;
}

// Places every static of public/levels/<Map>/stage.json (pos/quat/scale are already in three.js metres) and the BSP when the stage has one.
// filter(p) keeps a placement; each placed object remembers its record in userData.placement.  Returns { group, stage, placed, bsp }.
export async function loadPCLevel(scene, mapName, { loadGLTF, filter = null, onStatus = null, bsp = true, limit = 10 } = {}) {
  const stage = await (await fetch(`/public/levels/${mapName}/stage.json`)).json();
  const group = new THREE.Group(); group.name = 'pc_level:' + mapName; scene.add(group);
  const wanted = stage.statics.filter((p) => !filter || filter(p));
  const byUrl = new Map(); for (const p of wanted) { if (!byUrl.has(p.url)) byUrl.set(p.url, []); byUrl.get(p.url).push(p); }
  const urls = [...byUrl.keys()]; let i = 0, done = 0; const placed = []; const failed = [];
  await Promise.all(Array.from({ length: limit }, async () => {
    while (i < urls.length) {
      const url = urls[i++]; let g;
      try { g = await loadGLTF(url); } catch (e) { cache.delete(url); failed.push(url); continue; }
      for (const p of byUrl.get(url)) {
        const o = g.scene.clone(); o.position.fromArray(p.pos); o.quaternion.fromArray(p.quat); o.scale.fromArray(p.scale);
        o.name = p.mesh; o.userData.placement = p; group.add(o); placed.push(o);
      }
      done++; if (onStatus && done % 10 === 0) onStatus(`${mapName}: ${done}/${urls.length} meshes (${placed.length} placed)`);
    }
  }));
  let bspObj = null;
  if (bsp && stage.bsp) {
    if (onStatus) onStatus(`${mapName}: loading BSP…`);
    try { const g = await loadGLTF(stage.bsp); bspObj = g.scene; bspObj.name = 'bsp'; bspObj.traverse((m) => { if (m.isMesh) m.userData.bsp = true; }); group.add(bspObj); } catch (e) { console.warn('bsp failed', stage.bsp, e); }
  }
  group.updateMatrixWorld(true);
  if (onStatus) onStatus(`${mapName}: ${placed.length} statics` + (bspObj ? ' + BSP' : '') + (failed.length ? `, ${failed.length} missing` : ''));
  return { group, stage, placed, bsp: bspObj, failed };
}

// Materials that never block the player: alpha-blended / additive (glass, beacons, tree cards), water, sky backdrops.
export function isSolidMaterial(mat, name = '') {
  if (!mat) return false; const mats = Array.isArray(mat) ? mat : [mat];
  for (const m of mats) { if (m.transparent || m.blending === THREE.AdditiveBlending) return false; const n = ((m.name || '') + ' ' + name).toLowerCase(); if (/water|backdrop|skydome|skybox|\bsky\b/.test(n)) return false; }
  return true;
}

// Splits a mesh's triangles (in world space) into cell-sized pieces so the near-set of a capsule controller stays small even for the BSP,
// which is exported as one map-wide mesh per material.  The pieces are plain non-indexed meshes with an identity world matrix; they are
// never added to the scene (raycasts do not need that) unless a debug view wants them.
const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _c = new THREE.Vector3();
const chunkMat = new THREE.MeshBasicMaterial({ color: 0x3cff6a, wireframe: true, transparent: true, opacity: 0.6 });
export function chunkMeshes(meshes, cell = 24, kind = 'chunk') {
  const cells = new Map();
  for (const mesh of meshes) {
    const geo = mesh.geometry; const pos = geo.attributes.position; const idx = geo.index; const n = idx ? idx.count : pos.count; const M = mesh.matrixWorld;
    for (let t = 0; t + 2 < n; t += 3) {
      const i0 = idx ? idx.getX(t) : t, i1 = idx ? idx.getX(t + 1) : t + 1, i2 = idx ? idx.getX(t + 2) : t + 2;
      _a.fromBufferAttribute(pos, i0).applyMatrix4(M); _b.fromBufferAttribute(pos, i1).applyMatrix4(M); _c.fromBufferAttribute(pos, i2).applyMatrix4(M);
      const cx = Math.floor((_a.x + _b.x + _c.x) / 3 / cell), cz = Math.floor((_a.z + _b.z + _c.z) / 3 / cell); const key = cx + ',' + cz;
      let arr = cells.get(key); if (!arr) { arr = []; cells.set(key, arr); }
      arr.push(_a.x, _a.y, _a.z, _b.x, _b.y, _b.z, _c.x, _c.y, _c.z);
    }
  }
  const out = [];
  for (const [key, arr] of cells) {
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3)); g.computeBoundingSphere(); g.computeBoundingBox();
    const m = new THREE.Mesh(g, chunkMat); m.name = kind + '#' + key; m.userData.chunk = kind; m.userData.bsp = kind === 'bsp'; m.matrixAutoUpdate = false; m.visible = false; m.updateMatrixWorld(true); out.push(m);
  }
  return out;
}
export const chunkMesh = (mesh, cell = 24) => chunkMeshes([mesh], cell, mesh.userData.bsp ? 'bsp' : (mesh.name || 'mesh'));

// Builds { o, c, r, kind } collider records from the meshes under root.  Small meshes are used as they are (raycasts go through their
// world matrix); everything wider than splitAbove metres (the BSP's map-wide per-material meshes) is merged into one mesh per grid
// cell.  skip(mesh) can veto a mesh.
export function buildColliders(root, { cell = 24, splitAbove = 40, skip = null, maxRadius = 3000 } = {}) {
  const list = []; const sph = new THREE.Sphere(); let nMesh = 0, nSkip = 0; const big = [];
  root.updateMatrixWorld(true);
  root.traverse((m) => {
    if (!m.isMesh || m.isSkinnedMesh || !m.visible || !m.material) return;
    if ((skip && skip(m)) || !isSolidMaterial(m.material, (m.parent && m.parent.name) || m.name)) { nSkip++; return; }
    if (!m.geometry.boundingSphere) m.geometry.computeBoundingSphere();
    sph.copy(m.geometry.boundingSphere).applyMatrix4(m.matrixWorld); if (sph.radius > maxRadius) { nSkip++; return; }
    if (sph.radius > splitAbove) big.push(m); else { list.push({ o: m, c: sph.center.clone(), r: sph.radius, kind: m.userData.bsp ? 'bsp' : 'static' }); nMesh++; }
  });
  const chunks = chunkMeshes(big, cell, big.some((m) => m.userData.bsp) ? 'bsp' : 'chunk');
  for (const ch of chunks) list.push({ o: ch, c: ch.geometry.boundingSphere.center.clone(), r: ch.geometry.boundingSphere.radius, kind: ch.userData.chunk });
  return { list, chunks, nChunk: chunks.length, nBig: big.length, nMesh, nSkip };
}
