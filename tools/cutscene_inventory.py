#!/usr/bin/env python3
"""Enumerate prospective PC cinematics and packages; no file mutation."""
from collections import Counter
from pathlib import Path
import json
import subprocess
import sys

root = Path(sys.argv[1]).expanduser().resolve()
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/cutscene-inventory.json")
if not root.is_dir():
    raise SystemExit(f"Not a directory: {root}")

candidate_exts = {".bik", ".whr", ".u", ".ukx", ".usx", ".utx", ".uax"}
items = []
for file in sorted(root.rglob("*")):
    if not file.is_file() or file.suffix.lower() not in candidate_exts:
        continue
    record = {
        "path": file.relative_to(root).as_posix(),
        "extension": file.suffix.lower(),
        "bytes": file.stat().st_size,
    }
    if file.suffix.lower() == ".bik":
        try:
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(file)],
                text=True, capture_output=True, timeout=30, check=True,
            )
            result = json.loads(proc.stdout)
            record["streams"] = [
                {key: s.get(key) for key in ("codec_type", "codec_name", "width", "height", "avg_frame_rate", "duration") if s.get(key) is not None}
                for s in result.get("streams", [])
            ]
            record["duration"] = result.get("format", {}).get("duration")
        except (FileNotFoundError, subprocess.SubprocessError, ValueError) as exc:
            record["probe_error"] = str(exc)
    items.append(record)

out.parent.mkdir(parents=True, exist_ok=True)
report = {
    "root": str(root),
    "counts": dict(Counter(item["extension"] for item in items)),
    "items": items,
}
out.write_text(json.dumps(report, indent=2))
print(f"Wrote {out}: {len(items)} candidates")
for it in items:
    if it["extension"] == ".bik":
        v = next((s for s in it.get("streams", []) if s.get("codec_type") == "video"), {})
        print(f"  {it['path']:45} {float(it.get('duration') or 0):7.1f}s  {v.get('width')}x{v.get('height')} @ {v.get('avg_frame_rate')}")
