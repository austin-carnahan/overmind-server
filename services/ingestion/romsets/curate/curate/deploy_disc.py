"""Stage: deploy-disc. Promote a disc-based platform's selectively
downloaded torrent files from the Inbox into the library tier.

The cartridge deploy stage (deploy.py) reads from the archive tier, which
holds the platform's entire curated pool. Disc-based platforms have no
archive tier -- queue-download only ever pulls the selected top-N (and
their sibling discs) into the Inbox, so this promotes from there instead.
Unlike deploy_top(), a wanted file missing from the source is a real
error, not a silent skip: queue-download already confirmed every so_id
selected mapped to a real file in the torrent, so a missing file here
means something went wrong, not an expected gap.
"""

import json
from pathlib import Path
from shutil import copy2


def _wanted_paths(top: list[dict]) -> set[str]:
    wanted = set()
    for record in top:
        if record.get("path"):
            wanted.add(record["path"])
        for disc in record.get("disc_files", []):
            if disc.get("path"):
                wanted.add(disc["path"])
    return wanted


def deploy_disc(top_100_path: Path, source_dir: Path, library_dir: Path) -> dict[str, list[str]]:
    top = json.loads(top_100_path.read_text())
    library_dir.mkdir(parents=True, exist_ok=True)

    wanted_paths = _wanted_paths(top)
    wanted_names = {Path(p).name for p in wanted_paths}

    copied = []
    missing = []
    for rel_path in sorted(wanted_paths):
        src = source_dir / rel_path
        dest = library_dir / Path(rel_path).name
        if not src.exists():
            missing.append(rel_path)
            continue
        copy2(src, dest)
        copied.append(str(dest))

    if missing:
        raise FileNotFoundError(
            f"{len(missing)} selected file(s) not found in {source_dir} -- "
            f"queue-download should have made every one of these available: {missing[:5]}"
            + (" ..." if len(missing) > 5 else "")
        )

    removed = []
    for existing in library_dir.iterdir():
        if existing.is_file() and existing.name not in wanted_names:
            existing.unlink()
            removed.append(str(existing))

    return {"copied": copied, "removed": removed}
