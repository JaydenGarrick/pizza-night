#!/usr/bin/env python3
"""Dump UE2 package name/import/export tables. Read-only. Usage: ue2_tables.py PKG [--classes] [--filter Class1,Class2] [--json out]"""
import struct, sys, json
from collections import Counter
from pathlib import Path

class R:
    def __init__(s, data): s.d=data; s.p=0
    def u8(s): v=s.d[s.p]; s.p+=1; return v
    def u16(s): v=struct.unpack_from("<H",s.d,s.p)[0]; s.p+=2; return v
    def i32(s): v=struct.unpack_from("<i",s.d,s.p)[0]; s.p+=4; return v
    def u32(s): v=struct.unpack_from("<I",s.d,s.p)[0]; s.p+=4; return v
    def idx(s):  # compact index
        b=s.u8(); neg=b&0x80; v=b&0x3f
        if b&0x40:
            sh=6
            while True:
                b=s.u8(); v|=(b&0x7f)<<sh; sh+=7
                if not b&0x80: break
        return -v if neg else v
    def fstr(s):
        n=s.idx()
        if n==0: return ""
        if n<0:
            raw=s.d[s.p:s.p-2*n]; s.p+=-2*n; return raw.decode("utf-16-le","replace").rstrip("\0")
        raw=s.d[s.p:s.p+n]; s.p+=n; return raw[:-1].decode("latin-1","replace")

def parse(path):
    d=Path(path).read_bytes(); r=R(d)
    magic=r.u32(); assert magic==0x9E2A83C1, f"bad magic {magic:x}"
    ver=r.u16(); lic=r.u16(); flags=r.u32()
    nc,no,ec,eo,ic,io=r.u32(),r.u32(),r.u32(),r.u32(),r.u32(),r.u32()
    r.p=no; names=[]
    for _ in range(nc): names.append(r.fstr()); r.u32()
    r.p=io; imports=[]
    for _ in range(ic):
        cp=names[r.idx()]; cn=names[r.idx()]; pk=r.i32(); on=names[r.idx()]
        imports.append({"class_pkg":cp,"class":cn,"pkg":pk,"name":on})
    r.p=eo; exports=[]
    for _ in range(ec):
        ci=r.idx(); si=r.idx(); pk=r.i32(); on=names[r.idx()]; fl=r.u32(); sz=r.idx(); off=r.idx() if sz>0 else 0
        exports.append({"class_idx":ci,"super_idx":si,"pkg":pk,"name":on,"flags":fl,"size":sz,"offset":off})
    def refname(i):
        if i>0: return exports[i-1]["name"]
        if i<0: return imports[-i-1]["name"]
        return "Class"
    def fullname(i):
        parts=[]
        while i:
            e=exports[i-1] if i>0 else imports[-i-1]
            parts.append(e["name"]); i=e["pkg"]
        return ".".join(reversed(parts))
    for e in exports:
        e["class"]=refname(e["class_idx"]); e["full"]=fullname(exports.index(e)+1) if False else None
    # fullname by position
    for n,e in enumerate(exports): e["full"]=fullname(n+1)
    return {"path":str(path),"version":ver,"licensee":lic,"flags":flags,"names":names,"imports":imports,"exports":exports}

if __name__=="__main__":
    args=sys.argv[1:]; flt=None; out=None; classes="--classes" in args
    if "--filter" in args: flt=set(args[args.index("--filter")+1].split(","))
    if "--json" in args: out=args[args.index("--json")+1]
    pkg=[a for a in args if not a.startswith("--") and a not in (flt and ",".join(flt) or "", out or "")][0]
    p=parse(pkg)
    print(f"{pkg}: ver={p['version']} lic={p['licensee']} names={len(p['names'])} imports={len(p['imports'])} exports={len(p['exports'])}")
    if classes:
        c=Counter(e["class"] for e in p["exports"])
        for k,v in c.most_common(): print(f"  {v:6}  {k}")
    if flt:
        for e in p["exports"]:
            if e["class"] in flt: print(f"  {e['class']:20} {e['full']:60} size={e['size']}")
    if out: Path(out).write_text(json.dumps(p,indent=1))
