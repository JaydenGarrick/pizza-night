"""Decode Treyarch NAL animation blocks by emulating the game's own codec routines (x86) with Unicorn.
Layout knowledge: see intermediate/xbox/NOTES.md. Usage: from xbox.nal_emu import NalEmu; e = NalEmu(); e.decode(skel_bytes, block_bytes)"""
import struct, re
from pathlib import Path
import numpy as np
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_PROT_ALL, UC_HOOK_MEM_UNMAPPED, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_ECX, UC_X86_REG_EAX

IMG_PATH = Path(__file__).resolve().parents[2] / "intermediate/xbox/default_flat.bin"
BASE = 0x10000
STACK = 0x7f000000; STACK_SIZE = 0x100000
HEAP = 0x20000000; HEAP_SIZE = 0x4000000
SENTINEL = 0x7e000000
REGISTRY_FIRST = 0x4dba44

def align(v, a): return (v + a - 1) // a * a
def cstr(b): return b.split(b"\0")[0].decode("latin-1")

def parse_skeleton(d):
    """XBSKEL: header counts at fixed offsets; regions follow each other (verified on GAME/SPIDERMAN)."""
    n_bones = struct.unpack_from("<I", d, 0x74)[0]; n_ch = struct.unpack_from("<I", d, 0x7c)[0]; n_channels_anim = struct.unpack_from("<I", d, 0x80)[0]
    n_groups = struct.unpack_from("<I", d, 0x88)[0]; quat_bytes = struct.unpack_from("<I", d, 0x90)[0]; qa = struct.unpack_from("<I", d, 0x94)[0] or 4
    g_bytes = struct.unpack_from("<I", d, 0x9c)[0]; n_groups2 = struct.unpack_from("<I", d, 0xa4)[0]; trans_bytes = struct.unpack_from("<I", d, 0xac)[0]; ta = struct.unpack_from("<I", d, 0xb0)[0] or 4
    size_a = struct.unpack_from("<I", d, 0x64)[0]; size_b = struct.unpack_from("<I", d, 0x6c)[0]
    bones_off = align(0xe0 + size_a + size_b, 4)
    ch_off = bones_off + n_bones * 0x30; groups_off = ch_off + n_ch * 0x28
    quats_off = align(groups_off + n_groups * 0x30, qa); g_off = align(quats_off + quat_bytes, 4)
    groups2_off = align(g_off + g_bytes, 4); trans_off = align(groups2_off + n_groups2 * 0x30, ta); params_off = align(trans_off + trans_bytes, 4)
    bones = []
    for i in range(n_bones):
        o = bones_off + 0x30 * i; h, = struct.unpack_from("<I", d, o); nm = cstr(d[o+4:o+0x24]); a, b, par = struct.unpack_from("<IIi", d, o + 0x24)
        bones.append({"name": nm, "hash": h, "a": a, "b": b, "parent": par})
    channels = []
    for i in range(n_ch):
        o = ch_off + 0x28 * i; h, = struct.unpack_from("<I", d, o); typ = cstr(d[o+4:o+0x20]); bone, u2 = struct.unpack_from("<2I", d, o + 0x20)
        channels.append({"type": typ, "bone": bone, "u2": u2, "hash": h})
    groups = []
    for i in range(n_groups):
        o = groups_off + 0x30 * i; h, = struct.unpack_from("<I", d, o); nm = cstr(d[o+4:o+0x20]); first, cnt, off = struct.unpack_from("<3I", d, o + 0x24)
        groups.append({"name": nm, "hash": h, "first": first, "count": cnt, "out_off": off, "rec_off": o})
    return {"n_bones": n_bones, "n_channels": n_ch, "n_anim_channels": n_channels_anim, "bones": bones, "channels": channels, "groups": groups,
            "offsets": {"bones": bones_off, "channels": ch_off, "groups": groups_off, "quats": quats_off, "groups2": groups2_off, "trans": trans_off, "params": params_off}, "raw": d}

def parse_block(d, off, n_anim_channels):
    """One tag-0x00b5b728 block at offset off (object base = tag)."""
    g = lambda o, f="<I": struct.unpack_from(f, d, off + o)[0]
    assert g(0) == 0x00b5b728 and g(0x2c) == 0x10200, "not a v0x10200 nal block"
    size = g(4); name = cstr(d[off+0xc:off+0x28]); skel_idx = g(0x28)
    blk = {"off": off, "size": size, "name": name, "skel_idx": skel_idx, "hash2": g(0x30), "duration": g(0x38, "<f"), "fps": g(0x40, "<f"), "n_frames": g(0x44),
           "page": g(0x48), "state_bytes": g(0x4c), "scales_bytes": g(0x54), "n_chunks": g(0x64), "frames_per_chunk": g(0x68), "stride": g(0x70)}
    n_words = (n_anim_channels + 31) // 32
    mask_off = off + 0x80; mask_end = mask_off + 4 * n_words
    scales_off = align(mask_end, g(0x58) or 16); table_off = align(scales_off + blk["scales_bytes"], 4)
    offs = [struct.unpack_from("<I", d, table_off + 4 * i)[0] for i in range(blk["n_chunks"])]
    data_base = table_off + 4 * blk["n_chunks"]
    blk.update({"mask": [struct.unpack_from("<I", d, mask_off + 4 * i)[0] for i in range(n_words)], "mask_off": mask_off, "scales_off": scales_off, "chunks": [data_base + o for o in offs], "end": off + size})
    return blk

class NalEmu:
    def __init__(self):
        img = IMG_PATH.read_bytes(); self.img = img
        uc = Uc(UC_ARCH_X86, UC_MODE_32); self.uc = uc
        uc.mem_map(0, align(BASE + len(img), 0x1000), UC_PROT_ALL); uc.mem_write(BASE, img)
        uc.mem_map(STACK, STACK_SIZE, UC_PROT_ALL); uc.mem_map(HEAP, HEAP_SIZE, UC_PROT_ALL); uc.mem_map(SENTINEL, 0x1000, UC_PROT_ALL)
        uc.mem_write(SENTINEL, b"\xf4" * 16)  # hlt
        self.heap_top = HEAP
        self.registry = self._read_registry()
        # stub the engine allocator/free (they take the Xbox kernel heap path): FUN_0032a940(size, align, flags), FUN_0032a990(ptr)
        # (handler, bytes of stack args the callee pops): alloc/free are cdecl, chunk alloc stdcall 0xc, class lookup stdcall 4
        self.stubs = {0x32a940: (self._stub_alloc, 0), 0x32a990: (lambda uc, args: 0, 0), 0x33cb80: (self._stub_chunk_alloc, 0xc), 0x32af20: (self._stub_class_lookup, 4)}
        uc.hook_add(UC_HOOK_CODE, self._on_code, begin=0x32a940, end=0x33cb81)
        # dummy vtable for codec classes we don't have (e.g. game-specific 'spidey_signal'): every slot returns immediately
        self._make_dummy_vtable(); self.class_desc = {}
    SLOT_ARGBYTES = {0: 0, 1: 0, 2: 0x14, 3: 0x14, 4: 0xc, 5: 0x10, 6: 0x1c, 7: 0x14, 8: 0x14, 9: 0x10, 10: 0x18, 11: 8, 12: 8, 13: 0xc, 14: 8, 15: 4, 16: 4, 17: 4, 18: 4, 19: 0, 20: 0, 21: 0, 22: 0x14, 23: 0x14}
    def _make_dummy_vtable(self):
        """codec slots are stdcall (callee pops); build 'xor eax,eax; ret N' stubs per slot for unknown codec classes"""
        code = b""; addrs = []
        for k in range(24):
            n = self.SLOT_ARGBYTES.get(k, 0); addrs.append(len(code)); code += b"\x31\xc0" + (b"\xc2" + struct.pack("<H", n) if n else b"\xc3")
        base = self.put(code, 16); self.ret_stub = base; self.dummy_vt = self.put(struct.pack("<24I", *[base + a for a in addrs]), 16)
    def _stub_chunk_alloc(self, uc, args):
        p = self._stub_alloc(uc, args)
        if args[2]: self.set_u32(args[2], p)
        return p
    def _stub_class_lookup(self, uc, args):
        """FUN_0032af20(group_record) -> class descriptor whose +0x20 is the codec vtable."""
        rec = args[0]; name = cstr(bytes(uc.mem_read(rec + 4, 28))).lower()
        if name not in self.class_desc:
            vt = self.dummy_vt
            for k, v in self.registry.items():
                if k == name or k.startswith(name): vt = v; break
            inst = self.alloc(0x80); uc.mem_write(inst, b"\0" * 0x80); self.set_u32(inst, vt)      # prototype instance: vtable at +0
            d = self.alloc(0x40); uc.mem_write(d, b"\0" * 0x40); self.set_u32(d + 0x20, inst); self.class_desc[name] = (d, vt)
        return self.class_desc[name][0]
    def _stub_alloc(self, uc, args):
        size = args[0] if args[0] else 16; al = args[1] if len(args) > 1 and 0 < args[1] <= 4096 else 16
        p = self.alloc(size + 16, max(al, 16)); uc.mem_write(p, b"\0" * (size + 16)); return p
    def _on_code(self, uc, addr, size, ud):
        st = self.stubs.get(addr)
        if st is None: return
        fn, pop = st
        esp = uc.reg_read(UC_X86_REG_ESP); ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        args = list(struct.unpack("<6I", uc.mem_read(esp + 4, 24)))
        uc.reg_write(UC_X86_REG_EAX, fn(uc, args) & 0xffffffff); uc.reg_write(UC_X86_REG_ESP, esp + 4 + pop); uc.reg_write(UC_X86_REG_EIP, ret)
    def _read_registry(self):
        """NAL class nodes: 20 B {vtable 0x479b58, next, name_ptr, &instance, ...} at 0x4dba3c + 20k; the prototype instance is the
        dword just before each node and holds that class's codec vtable."""
        reg = {}; node = REGISTRY_FIRST - 8
        while True:
            nvt, nxt, name_p, inst_p, y = struct.unpack_from("<5I", self.img, node - BASE)
            if nvt != 0x479b58 or not (0x44c2e0 <= name_p < 0x4af4a0): break
            o = name_p - BASE; name = self.img[o:self.img.find(b"\0", o)].decode()
            reg[name.lower()] = struct.unpack_from("<I", self.img, inst_p - BASE)[0]; node += 20
        return reg
    def alloc(self, n, a=16):
        p = align(self.heap_top, a); self.heap_top = p + n; return p
    def put(self, data, a=16):
        p = self.alloc(len(data), a); self.uc.mem_write(p, bytes(data)); return p
    def u32(self, addr): return struct.unpack("<I", self.uc.mem_read(addr, 4))[0]
    def set_u32(self, addr, v): self.uc.mem_write(addr, struct.pack("<I", v & 0xffffffff))
    def call(self, fn, args, ecx=0, max_insns=50_000_000):
        uc = self.uc; sp = STACK + STACK_SIZE - 0x1000 - 4 * (len(args) + 1)
        uc.mem_write(sp, struct.pack("<I", SENTINEL) + b"".join(struct.pack("<I", a & 0xffffffff) for a in args))
        uc.reg_write(UC_X86_REG_ESP, sp); uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.emu_start(fn, SENTINEL, count=max_insns)
        return uc.reg_read(UC_X86_REG_EAX)
    def vtable(self, group_name):
        key = group_name.lower()
        for k, v in self.registry.items():
            if k == key or k.startswith(key): return v, k
        raise KeyError(group_name)
    def decode(self, skel, blk_bytes, blk, verbose=False):
        """Returns dict(groups=[{name, codec, out_start}], frames=np.uint8[n_frames, stride], out_cursor_end)."""
        uc = self.uc; self.heap_top = HEAP
        blk_base = self.put(blk_bytes); skel_base = self.put(skel["raw"])
        off = blk["off"]; anim = blk_base + off                                   # the block itself is the anim object
        mask_ptr = anim + 0x80; self.set_u32(anim + 0x60, mask_ptr)             # +0x60 -> mask words
        # group records (copy from skeleton, patch vtable at +0x20)
        grecs = []
        for g in skel["groups"]:
            rec = bytearray(skel["raw"][g["rec_off"]: g["rec_off"] + 0x30])
            try: vt, cname = self.vtable(g["name"])
            except KeyError:
                if verbose: print("  skipping group with unknown codec:", g["name"]); break   # only safe when trailing (stream is sequential)
            struct.pack_into("<I", rec, 0x20, vt); p = self.put(bytes(rec)); grecs.append((g, p, vt, cname))
        n_frames = blk["n_frames"]; stride = blk["stride"]; fpc = blk["frames_per_chunk"]
        out_all = np.zeros((n_frames, stride), np.uint8); group_out = None
        for ci, chunk_ptr_off in enumerate(blk["chunks"]):
            f0 = ci * fpc; count = min(fpc, n_frames - f0)
            states = self.alloc(0x40000, 16); out = self.alloc(stride * count + 0x1000, 16)
            cur_states = self.alloc(4); cur_stream = self.alloc(4); cur_out = self.alloc(4); cur_scales = self.alloc(4); cur_params = self.alloc(4)
            self.set_u32(cur_states, states); self.set_u32(cur_stream, blk_base + chunk_ptr_off); self.set_u32(cur_out, out)
            self.set_u32(cur_scales, blk_base + blk["scales_off"]); self.set_u32(cur_params, skel_base + skel["offsets"]["params"])
            ctx = self.alloc(16); gouts = []
            for g, grec, vt, cname in grecs:
                uc.mem_write(ctx, struct.pack("<4I", anim, grec, cur_scales, cur_params))
                self.call(self.u32(vt + 0x14), [ctx, cur_states, cur_stream, count])
            # reset cursors that slot 6 walks (states) — slot 6 re-walks states from the start
            self.set_u32(cur_states, states); self.set_u32(cur_scales, blk_base + blk["scales_off"]); self.set_u32(cur_params, skel_base + skel["offsets"]["params"])
            for g, grec, vt, cname in grecs:
                uc.mem_write(ctx, struct.pack("<4I", anim, grec, cur_scales, cur_params))
                start = self.u32(cur_out)
                self.call(self.u32(vt + 0x18), [ctx, cur_out, cur_states, states + 0x40000, f0, count, stride])
                gouts.append({"name": g["name"], "codec": cname, "out_start": start - out, "out_end": self.u32(cur_out) - out, "first": g["first"], "count": g["count"]})
            out_all[f0:f0 + count] = np.frombuffer(uc.mem_read(out, stride * count), np.uint8).reshape(count, stride)
            if group_out is None: group_out = gouts
            if verbose: print(f"chunk {ci}: frames {f0}..{f0+count}, stream @+{chunk_ptr_off:#x}, out cursor end {self.u32(cur_out) - out:#x}, states used {self.u32(cur_states) - states:#x}")
        return {"groups": group_out, "frames": out_all}

    def decode_native(self, skel_raw, file_bytes, blk, verbose=False):
        """Run the game's own setup + chunk decoder. Returns np.uint8[n_frames, stride] of the raw decoded pose rows."""
        uc = self.uc; self.heap_top = HEAP; self.class_desc = {}; self._make_dummy_vtable()
        skel_base = self.put(bytes(skel_raw) + b"\0" * 0x40000, 16)          # codecs construct per-channel objects in the region after the file data
        self.call(0x3374b0, [], ecx=skel_base)                           # skeleton layout: region pointers + codec vtables
        file_base = self.put(file_bytes, 16); anim = file_base + blk["off"]
        self.set_u32(anim + 0x30, skel_base)                              # DATA pointer (file holds the skeleton hash)
        self.call(0x3376c0, [], ecx=anim)                                 # block init: mask ptr, scales ptr, chunk table fixup, chunk buffer array
        player = self.alloc(0x100); uc.mem_write(player, b"\0" * 0x100); self.set_u32(player + 0x10, anim); self.set_u32(player + 0x0c, skel_base)
        self._skel_base, self._anim, self._player = skel_base, anim, player
        n_frames, stride, fpc = blk["n_frames"], blk["stride"], blk["frames_per_chunk"]
        out = np.zeros((n_frames, stride), np.uint8)
        for ci in range(blk["n_chunks"]):
            self.call(0x337940, [ci], ecx=player)
            buf = self.u32(self.u32(anim + 0x78) + 4 * ci); f0 = ci * fpc; count = min(fpc, n_frames - f0)
            out[f0:f0 + count] = np.frombuffer(uc.mem_read(buf, stride * count), np.uint8).reshape(count, stride)
            if verbose: print(f"chunk {ci}: {count} frames decoded from buffer {buf:#x}")
        return out

    POSE_SIZES = {"posori": 0x20, "quat16": 0x10, "quat8": 0x10, "quatf": 0x10, "ikspin": 0x50, "float1": 4, "float3": 12, "signal": 1}
    def decode_matrices(self, skel, file_bytes, blk, verbose=False):
        """Full engine path per frame: chunk decode -> pose evaluation (codec slot 8) -> skeleton bytecode (FK + IK) -> bone matrices.
        Returns (rows, mats) with mats float32[n_frames, n_bones, 4, 4] (row-vector D3D, translation in row 3)."""
        from .anim_decode import layout_for
        uc = self.uc; skel_raw = skel["raw"]
        rows = self.decode_native(skel_raw, file_bytes, blk, verbose=verbose)       # sets self._skel_base/_anim/_player
        skel_base, anim, player = self._skel_base, self._anim, self._player
        n_frames, stride = blk["n_frames"], blk["stride"]; nb = self.u32(skel_base + 0x60)
        # channel -> pose offset table (or -1) from the skeleton groups
        n_ch = skel["n_channels"]; offs = [-1] * n_ch
        for g in skel["groups"]:
            try: al, size, kind = layout_for(g["name"])
            except KeyError: continue
            for k in range(g["count"]):
                ch = g["first"] + k
                if ch < n_ch: offs[ch] = g["out_off"] + k * self.POSE_SIZES[kind]
        offs_p = self.put(struct.pack(f"<{n_ch}i", *offs), 16)
        pose_size = max(0x1000, max(o for o in offs if o >= 0) + 0x100)
        pose_buf = self.alloc(pose_size, 16); uc.mem_write(pose_buf, b"\0" * pose_size)
        pose_obj = self.alloc(0x40, 16); uc.mem_write(pose_obj, b"\0" * 0x40); self.set_u32(pose_obj + 4, pose_buf)
        rest_buf = skel_base + skel["offsets"]["quats"]                                 # region F = rest pose in pose layout
        mats_buf = self.alloc(64 * (nb + 2), 16)
        chunk_bufs = self.u32(anim + 0x78); fpc = blk["frames_per_chunk"]
        mats = np.zeros((n_frames, nb, 4, 4), np.float32)
        for f in range(n_frames):
            row = self.u32(chunk_bufs + 4 * (f // fpc)) + stride * (f % fpc)
            uc.mem_write(pose_buf, bytes(uc.mem_read(rest_buf, min(pose_size, 0x420))))   # start from rest (unmasked channels)
            self.call(0x337bd0, [pose_buf, row, rest_buf, offs_p], ecx=player)        # evaluate frame -> pose buffer
            uc.mem_write(mats_buf, b"\0" * (64 * (nb + 2)))
            self.call(0x338980, [pose_obj, mats_buf], ecx=skel_base)                    # pose -> bone matrices (FK + IK)
            mats[f] = np.frombuffer(uc.mem_read(mats_buf, 64 * nb), "<f4").reshape(nb, 4, 4)
        return rows, mats

def find_blocks(d):
    out = []; i = d.find(b"\x28\xb7\xb5\x00")
    while i != -1:
        if struct.unpack_from("<I", d, i + 0x2c)[0] == 0x10200: out.append(i)
        i = d.find(b"\x28\xb7\xb5\x00", i + 4)
    return out

