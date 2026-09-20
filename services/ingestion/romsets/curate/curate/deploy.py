"""Stage: deploy. Promote the top-100 manifest into the library tier.

Copies only -- the archive tier is never modified or deleted from here.
"""

import json
import shutil
from pathlib import Path


def deploy_top(top_100_path: Path, archive_dir: Path, library_dir: Path) -> list[str]:
    top = json.loads(top_100_path.read_text())
    library_dir.mkdir(parents=True, exist_ok=True)
    deployed = []
    for record in top:
        rel_path = record.get("path")
        if not rel_path:
            continue  # force_include override with no archive file to copy
        src = archive_dir / rel_path
        dest = library_dir / Path(rel_path).name
        if not src.exists():
            continue
        shutil.copy2(src, dest)
        deployed.append(str(dest))
    return deployed
