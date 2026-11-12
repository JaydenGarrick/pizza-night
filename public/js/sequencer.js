// Deterministic simulation of UE2 ScriptedSequence/ScriptedTrigger action lists + SceneManager triggering.
// Produces per-pawn keyframe tracks and a global event list that the player evaluates with frame(t).
export const DEFAULT_SPEED = 300;         // unreal units / second (Pawn.GroundSpeed default-ish)

export function simulate(data, sceneTag, ctx, opts = {}) {
  const UNIT = ctx.unit; const dt = opts.dt ?? 1 / 30; const preroll = opts.preroll ?? 40; const tail = opts.tail ?? 6;
  const log = []; const events = []; const camScenes = [];
  // --- pawns
  const pawns = new Map();   // tag -> state
  const defs = new Map();
  for (const p of data.pawns) { const tag = p.Tag || p.name; defs.set(tag, p); defs.set(p.name, p); }
  function ensurePawn(tag) {
    if (pawns.has(tag)) return pawns.get(tag);
    const def = defs.get(tag); if (!def && !ctx.canSpawn(tag)) return null;
    const pos = def?.Location ? ctx.toWorld(def.Location) : ctx.spawnPos(tag);
    const st = { tag, def, pos, yaw: def?.Rotation ? def.Rotation[1] : 0, visible: true, clip: null, clipStart: 0, loop: true, rate: 1, speed: (def?.GroundSpeed || DEFAULT_SPEED) * UNIT, gait: 'run', keys: [], move: null };
    pawns.set(tag, st); key(st, -preroll - 1); return st;
  }
  function key(st, t) { st.keys.push({ t, pos: st.pos.slice(), yaw: st.yaw, visible: st.visible, clip: st.clip, clipStart: st.clipStart, loop: st.loop, rate: st.rate, moveTo: st.move ? st.move.to.slice() : null, moveEnd: st.move ? st.move.end : null }); }
  // --- sequences
  const seqs = data.sequences.map((s) => ({ def: s, pc: 0, block: null, active: false, runs: 0 }));
  const byTag = new Map();
  for (const s of seqs) { const tg = s.def.Tag; if (tg) { if (!byTag.has(tg)) byTag.set(tg, []); byTag.get(tg).push(s); } }
  const sceneByTag = new Map(); for (const sc of data.scenes) if (sc.Tag) sceneByTag.set(sc.Tag, sc);
  const hiddenStatics = new Map();  // tag -> [{t, visible}]
  let now = -preroll;
  const pending = [];  // events fired this tick
  function fire(name, src) {
    if (!name || name === 'None') return;
    log.push({ t: +now.toFixed(3), event: name, src });
    pending.push(name);
    if (sceneByTag.has(name) && now >= 0) camScenes.push({ t: now, scene: sceneByTag.get(name) });
  }
  function deliver() {
    while (pending.length) {
      const ev = pending.shift();
      for (const s of seqs) {
        if (s.block && s.block.type === 'event' && s.block.name === ev) { s.block = null; s.lastEvent = null; }
        else if (s.def.Tag === ev && !s.active) { s.active = true; s.pc = 0; s.block = null; s.runs++; s.lastEvent = ev; }
      }
    }
  }
  function targetPos(tag) {
    const p = pawns.get(tag) || (defs.has(tag) ? ensurePawn(tag) : null);
    if (p) return p.pos;
    const pt = ctx.pointPos(tag); return pt;
  }
  function yawTo(from, to) { // glTF coords: forward -Z; UE yaw (65536) with our conversion: pos' = (y, z, -x)
    const dx = to[0] - from[0], dz = to[2] - from[2];        // glTF x = ue y, glTF z = -ue x
    const uex = -dz, uey = dx; return Math.atan2(uey, uex) / (2 * Math.PI) * 65536;
  }
  function step(s) {   // run actions until blocked or done; returns true if progressed
    const acts = s.def.actions; let progressed = false; let guard = 0;
    while (s.active && !s.block && s.pc < acts.length && guard++ < 500) {
      const a = acts[s.pc]; const c = a.class || '?'; const pawnTag = s.def.PawnTag; const P = pawnTag ? ensurePawn(pawnTag) : null;
      progressed = true; s.pc++;
      switch (c) {
        case 'ACTION_WaitForEvent': if (s.lastEvent && s.lastEvent === a.ExternalEvent) { s.lastEvent = null; } else s.block = { type: 'event', name: a.ExternalEvent }; break;
        case 'ACTION_TriggerEvent': fire(a.Event, s.def.name); break;
        case 'ACTION_WaitForTimer': s.block = { type: 'time', until: now + (a.PauseTime ?? 1) }; break;
        case 'ACTION_WaitForPlayer': s.block = { type: 'time', until: now + 0.5 }; break;
        case 'ACTION_WaitForMovieEnded': s.block = { type: 'time', until: now + (ctx.movieDur || 8) }; break;
        case 'ACTION_EndSection': s.active = false; break;
        case 'ACTION_LeaveSequence': s.active = false; break;
        case 'ACTION_GotoAction': s.pc = Math.min(a.ActionNumber ?? 0, acts.length); break;
        case 'ACTION_IfCondition': case 'ACTION_IfRandomPct': case 'ACTION_IfLevelIsAvailable': case 'ACTION_IfReplayLevel': break; // assume true
        case 'ACTION_ChangeScript': { const t = byTag.get(a.NextScriptTag); if (t) for (const x of t) { x.active = true; x.pc = 0; x.block = null; } s.active = false; break; }
        case 'Action_PLAYANIM': if (P) { P.clip = a.BaseAnim; P.loop = !!a.bLoopAnim; P.rate = a.AnimRate || 1; P.clipStart = now; key(P, now); } break;
        case 'ACTION_FreezeOnAnimEnd': if (P) { P.clip = a.BaseAnim; P.loop = false; P.clipStart = now; key(P, now); } break;
        case 'ACTION_SetIdleAnim': if (P) { P.idle = a.IdleAnim; } break;
        case 'ACTION_StopAnimation': if (P) { P.clip = null; key(P, now); } break;
        case 'ACTION_WaitForAnimEnd': if (P && P.clip) { const d = ctx.clipDuration(P, P.clip) / (P.rate || 1); s.block = { type: 'time', until: Math.max(now, P.clipStart + d) }; } break;
        case 'ACTION_Say': { const d = ctx.audioDuration(a.dlgName) || 2.5; events.push({ t: now, dialog: a.dlgName, subtitle: a.dlgSubtitle || a.subtitle || null, dur: d, who: pawnTag }); if (P && !P.clip) { P.clip = null; } s.block = { type: 'time', until: now + d }; break; }
        case 'ACTION_TeleportToPoint': case 'ACTION_TeleportActor': { const T = c === 'ACTION_TeleportActor' ? ensurePawn(a.ActorTag) : P; const pt = ctx.pointPos(a.DestinationTag); if (T && pt) { T.pos = pt.slice(); T.move = null; const r = ctx.pointRot(a.DestinationTag); if (r && a.bRotate !== false) T.yaw = r[1]; key(T, now); } break; }
        case 'ACTION_MoveToPoint': case 'ACTION_JumpToPoint': { const tp = targetPos(a.DestinationTag || a.NavNodeTag); if (P && tp) { const d = Math.hypot(tp[0] - P.pos[0], tp[2] - P.pos[2]); const dur = d / Math.max(P.speed * (P.gait === 'walk' ? 0.4 : 1), 0.01); P.move = { from: P.pos.slice(), to: [tp[0], tp[1], tp[2]], start: now, end: now + dur }; P.yaw = yawTo(P.pos, tp); if (!P.clip || /idle|dialogue/i.test(P.clip)) { P.clip = P.gait === 'walk' ? 'Walk' : 'RunForwards'; P.loop = true; P.clipStart = now; P.moveClip = true; } key(P, now); s.block = { type: 'move', pawn: P }; } break; }
        case 'ACTION_MoveToPlayer': { const tp = targetPos('SpideyPawn'); if (P && tp) { const dur = Math.hypot(tp[0] - P.pos[0], tp[2] - P.pos[2]) / Math.max(P.speed, 0.01); P.move = { from: P.pos.slice(), to: tp.slice(), start: now, end: now + dur }; P.yaw = yawTo(P.pos, tp); key(P, now); s.block = { type: 'move', pawn: P }; } break; }
        case 'ACTION_Face': case 'ACTION_TurnTowardPlayer': { const tp = targetPos(c === 'ACTION_Face' ? a.DestinationTag : 'SpideyPawn'); if (P && tp) { P.yaw = yawTo(P.pos, tp); key(P, now); } break; }
        case 'ACTION_Walk': if (P) P.gait = 'walk'; break;
        case 'ACTION_Run': if (P) P.gait = 'run'; break;
        case 'ACTION_SetGroundSpeed': { const T = a.ActorTag ? ensurePawn(a.ActorTag) : P; if (T) T.speed = (a.Speed ?? DEFAULT_SPEED) * UNIT; break; }
        case 'ACTION_ShowActor': { const vis = a.Visible !== false && a.Visible !== 0; setVisible(a.ActorTag, vis); break; }
        case 'ACTION_SetHidden': setVisible(a.HideActorTag, !(a.bHidden ?? true)); break;
        case 'ACTION_DestroyActor': setVisible(a.DestroyTag, false); break;
        case 'ACTION_DestroyPawn': if (P) { P.visible = false; key(P, now); } break;
        case 'ACTION_PlayMovie': events.push({ t: now, movie: (a.Movie || '').split('.').pop() }); break;
        case 'ACTION_PlaySound': case 'ACTION_PlayLocalSound': events.push({ t: now, sound: a.Sound }); break;
        case 'ACTION_PlayMusic': events.push({ t: now, music: a.Song }); break;
        case 'ACTION_DisplayMessage': case 'ACTION_DisplayTutorialMessage': if (a.Message) events.push({ t: now, caption: a.Message, dur: 3 }); break;
        case 'ACTION_TimerStart': events.push({ t: now + (a.seconds || 1), fireEvent: a.TimeUpEvent }); break;
        default: break;
      }
    }
    return progressed;
  }
  function setVisible(tag, vis) {
    if (!tag) return;
    const p = pawns.get(tag) || (defs.has(tag) ? ensurePawn(tag) : null);
    if (p) { p.visible = vis; key(p, now); }
    if (ctx.hasStatic(tag)) { if (!hiddenStatics.has(tag)) hiddenStatics.set(tag, []); hiddenStatics.get(tag).push({ t: now, visible: vis }); }
  }
  // --- run
  for (const p of data.pawns) ensurePawn(p.Tag || p.name);
  for (const s of seqs) if (s.def.class === 'ScriptedTrigger' || s.def.class === 'ScriptedSequence') { s.active = true; }
  { let any = true, loops = 0; while (any && loops++ < 50) { any = false; for (const s of seqs) if (s.active && !s.block && step(s)) any = true; deliver(); } }
  fire('LevelLoad', 'init'); deliver();
  let endT = tail; let fired = false; const maxT = opts.maxT ?? 120;
  while (now < endT && now < maxT) {
    if (!fired && now >= 0) { fire(sceneTag, 'player'); fired = true; endT = (ctx.sceneDuration(sceneByTag.get(sceneTag)) || 0) + tail; }
    // timed events
    for (const ev of events) if (ev.fireEvent && !ev.done && ev.t <= now) { ev.done = true; fire(ev.fireEvent, 'timer'); }
    deliver();
    // unblock
    for (const s of seqs) {
      if (!s.block) continue;
      if (s.block.type === 'time' && now >= s.block.until) s.block = null;
      else if (s.block.type === 'move') { const P = s.block.pawn; if (!P.move || now >= P.move.end) { if (P.move) { P.pos = P.move.to.slice(); P.move = null; if (P.moveClip) { P.clip = P.idle || null; P.moveClip = false; P.clipStart = now; } key(P, now); } s.block = null; } }
    }
    let any = true; let loops = 0;
    while (any && loops++ < 50) { any = false; for (const s of seqs) if (s.active && !s.block && step(s)) any = true; deliver(); }
    for (const sc of camScenes) if (!sc.chained && now >= sc.t + ctx.sceneDuration(sc.scene)) { sc.chained = true; if (sc.scene.NextSceneTag) fire(sc.scene.NextSceneTag, 'scene-end'); if (sc.scene.Event) fire(sc.scene.Event, 'scene-end'); deliver(); const last = camScenes[camScenes.length - 1]; endT = Math.max(endT, last.t + ctx.sceneDuration(last.scene) + tail); }
    now += dt;
  }
  for (const p of pawns.values()) key(p, now);
  return { pawns: [...pawns.values()], events: events.filter((e) => !e.fireEvent && e.t >= 0), log, camScenes, hiddenStatics, duration: endT };
}

export function pawnStateAt(p, t) {
  const keys = p.keys; let k = keys[0];
  for (let i = 0; i < keys.length; i++) { if (keys[i].t <= t) k = keys[i]; else break; }
  if (!k) return null;
  let pos = k.pos;
  if (k.moveTo && k.moveEnd != null && k.moveEnd > k.t) { const u = Math.min(1, Math.max(0, (t - k.t) / (k.moveEnd - k.t))); pos = [k.pos[0] + (k.moveTo[0] - k.pos[0]) * u, k.pos[1] + (k.moveTo[1] - k.pos[1]) * u, k.pos[2] + (k.moveTo[2] - k.pos[2]) * u]; }
  return { pos, yaw: k.yaw, visible: k.visible, clip: k.clip, clipTime: Math.max(0, t - k.clipStart), loop: k.loop, rate: k.rate };
}
