"""Stage: deploy. Sync the top-100 manifest into the library tier.

Only ever reads from the archive tier and writes/removes within the
library tier -- the archive tier is never modified or deleted from here.
A rerun after the selection changes (a new override, a rescoring, etc.)
removes library-tier files that fell out of the current selection, not
just adds new ones -- otherwise a display displaced by a force_exclude or
a lower rank stays sitting in the "curated" tier indefinitely.
"""

import json
from pathlib import Path
from shutil import copy2


def deploy_top(top_100_path: Path, archive_dir: Path, library_dir: Path) -> dict[str, list[str]]:
    top = json.loads(top_100_path.read_text())
    library_dir.mkdir(parents=True, exist_ok=True)

    wanted_names = {Path(r["path"]).name for r in top if r.get("path")}

    copied = []
    for record in top:
        rel_path = record.get("path")
        if not rel_path:
            continue  # force_include override with no archive file to copy
        src = archive_dir / rel_path
        dest = library_dir / Path(rel_path).name
        if not src.exists():
            continue
        copy2(src, dest)
        copied.append(str(dest))

    removed = []
    for existing in library_dir.iterdir():
        if existing.is_file() and existing.name not in wanted_names:
            existing.unlink()
            removed.append(str(existing))

    return {"copied": copied, "removed": removed}
