from pathlib import Path
from collections import Counter
import json
import sys

root = Path(sys.argv[1]).expanduser().resolve()
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/inventory.json")
extensions = Counter()
files = []
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    with path.open("rb") as stream:
        header = stream.read(32)
    ext = path.suffix.lower() or "(none)"
    extensions[ext] += 1
    files.append({
        "path": str(path.relative_to(root)),
        "size": path.stat().st_size,
        "extension": ext,
        "header_hex": header.hex(),
        "header_ascii": "".join(chr(c) if 32 <= c < 127 else "." for c in header),
    })
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    "root": str(root),
    "count": len(files),
    "extensions": dict(extensions.most_common()),
    "files": files,
}, indent=2))
print(f"Indexed {len(files)} files to {out}")
for ext, count in extensions.most_common(25):
    print(f"{ext:12} {count}")
