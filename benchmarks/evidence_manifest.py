"""Hash all generated artifacts, excluding the manifest itself."""

import hashlib
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "outputs"
manifest = {
    "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
    "artifacts": {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    },
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("evidence_manifest.json: " + json.dumps({
    "source_commit": manifest["source_commit"],
    "artifact_count": len(manifest["artifacts"]),
}))
