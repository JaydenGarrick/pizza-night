"""Little-endian binary reader for Unreal Engine 2 package data (package version 126)."""
import struct

class BinReader:
    __slots__ = ("d", "p")

    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def tell(self): return self.p
    def seek(self, pos): self.p = pos
    def remaining(self): return len(self.d) - self.p

    def _unpack(self, fmt, size):
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return v

    def u8(self):  v = self.d[self.p]; self.p += 1; return v
    def i8(self):  return self._unpack("<b", 1)
    def u16(self): return self._unpack("<H", 2)
    def i16(self): return self._unpack("<h", 2)
    def u32(self): return self._unpack("<I", 4)
    def i32(self): return self._unpack("<i", 4)
    def i64(self): return self._unpack("<q", 8)
    def f32(self): return self._unpack("<f", 4)

    def bytes(self, n):
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def idx(self):
        """Unreal compact signed index."""
        b = self.u8()
        neg = b & 0x80
        v = b & 0x3F
        if b & 0x40:
            shift = 6
            while True:
                b = self.u8()
                v |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
        return -v if neg else v

    def fstr(self):
        n = self.idx()
        if n == 0:
            return ""
        if n < 0:
            raw = self.bytes(-2 * n)
            return raw.decode("utf-16-le", "replace").rstrip("\0")
        raw = self.bytes(n)
        return raw[:-1].decode("latin-1", "replace")

    def vec(self):  return struct.unpack_from("<3f", self.d, self._adv(12))
    def quat(self): return struct.unpack_from("<4f", self.d, self._adv(16))
    def rot(self):  return struct.unpack_from("<3i", self.d, self._adv(12))
    def color(self):  # FColor is stored B,G,R,A
        b, g, r, a = struct.unpack_from("<4B", self.d, self._adv(4))
        return (r, g, b, a)

    def _adv(self, n):
        p = self.p
        self.p += n
        return p

    def array(self, fn):
        n = self.idx()
        return [fn() for _ in range(n)]

    def lazy(self, fn):
        self.i32()  # SkipPos (package ver > 61)
        return self.array(fn)

    def packed(self, fmt, count):
        """Read `count` items of struct format `fmt` quickly."""
        size = struct.calcsize(fmt)
        out = list(struct.iter_unpack(fmt, self.d[self.p:self.p + size * count]))
        self.p += size * count
        return out

    def array_packed(self, fmt):
        n = self.idx()
        return self.packed(fmt, n)

    def lazy_packed(self, fmt):
        self.i32()
        return self.array_packed(fmt)
