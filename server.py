#!/usr/bin/env python3
"""sm2-office local server: serves the viewer, /public, /node_modules and a tiny model index. Binds 127.0.0.1 only."""
import json, os, sys, mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("SM2_PORT", "8790"))
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def do_GET(self):
        if self.path.startswith("/api/models"):
            models = sorted(str(p.relative_to(HERE / "public")) for p in (HERE / "public" / "models").rglob("*.glb"))
            scenes = sorted(str(p.relative_to(HERE / "public")) for p in (HERE / "public" / "cutscenes").rglob("*.json")) if (HERE / "public" / "cutscenes").exists() else []
            doll = sorted(str(p.relative_to(HERE / "public")) for p in (HERE / "public" / "dollhouse").rglob("*.json")) if (HERE / "public" / "dollhouse").exists() else []
            levels = sorted(p.parent.name for p in (HERE / "public" / "levels").glob("*/stage.json")) if (HERE / "public" / "levels").exists() else []
            xbox_cutscenes = sorted(str(p.relative_to(HERE / "public")) for p in (HERE / "public" / "xbox_cutscenes").glob("*/scene.json")) if (HERE / "public" / "xbox_cutscenes").exists() else []
            body = json.dumps({"models": ["/public/" + m for m in models], "cutscenes": ["/public/" + s for s in scenes], "dollhouse": ["/public/" + d for d in doll], "levels": levels, "xbox_cutscenes": xbox_cutscenes}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); return
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/save/"):
            name = "".join(c for c in self.path.split("/api/save/", 1)[1] if c.isalnum() or c in "-_")[:64] or "scene"
            n = int(self.headers.get("Content-Length", "0")); body = self.rfile.read(n)
            try: json.loads(body)
            except Exception: self.send_response(400); self.end_headers(); return
            d = HERE / "public" / "dollhouse"; d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.json").write_bytes(body)
            out = json.dumps({"saved": f"/public/dollhouse/{name}.json"}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
        self.send_response(404); self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "--quiet" not in sys.argv: super().log_message(fmt, *args)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"sm2-office → http://127.0.0.1:{PORT}/")
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
