"""Stage: convert-chd. Normalize disc-platform ZIP archives (PSX, Dreamcast)
into a CHD-based playable library, with M3U playlists for multi-disc games.

Per-disc pipeline, matching the spec exactly:
    hash zip -> test zip integrity -> extract to an isolated temp dir ->
    locate the .cue -> verify every FILE it references exists (handles both
    PSX single-BIN and Dreamcast multi-BIN/track layouts) -> chdman createcd
    -> chdman verify -> hash the CHD -> atomically promote into the library
    -> only then delete the source ZIP and temp extraction.

On any error the source ZIP is preserved, incomplete output is removed, the
failure is logged, and the batch continues with the next disc -- one bad
disc must never take down the rest of a platform's conversion run.

BIN/track filenames are never renamed -- chdman reads the extracted .cue
exactly as shipped. Only the final .chd/.m3u filenames are normalized.
"""

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .titles import clean_title, disc_number

FIRST_TAG_RE = re.compile(r"^([^(]*)\(([^)]*)\)")
CUE_FILE_RE = re.compile(r'^\s*FILE\s+"([^"]+)"', re.IGNORECASE | re.MULTILINE)
CUE_FILE_UNQUOTED_RE = re.compile(r"^\s*FILE\s+(\S+)", re.IGNORECASE | re.MULTILINE)


class ConversionError(Exception):
    pass


def normalized_base_name(raw: str) -> str:
    """'Final Fantasy IX (USA) (Disc 1) (Rev 1)' -> 'Final Fantasy IX (USA)'.
    Keeps the title and the first parenthetical tag (always region/language
    per No-Intro/Redump convention) and drops everything else -- revision,
    disc number, language lists, edition notes. Disc number is re-added
    separately per-CHD by the caller, never baked in here."""
    m = FIRST_TAG_RE.match(raw)
    if not m:
        return raw.strip()
    title, region = m.group(1).strip(), m.group(2).strip()
    return f"{title} ({region})"


def _sha256(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _cue_referenced_files(cue_path: Path) -> list[str]:
    text = cue_path.read_text(errors="replace")
    quoted = CUE_FILE_RE.findall(text)
    if quoted:
        return quoted
    return CUE_FILE_UNQUOTED_RE.findall(text)


def _group_discs(source_dir: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for zip_path in sorted(source_dir.glob("*.zip")):
        raw = zip_path.stem
        key = clean_title(raw) if disc_number(raw) is not None else raw
        groups.setdefault(key, []).append(zip_path)
    return groups


@dataclass
class DiscResult:
    source_zip: Path
    ok: bool
    zip_sha256: str | None = None
    chd_sha256: str | None = None
    chd_path: Path | None = None
    error: str | None = None


def _convert_one(zip_path: Path, final_chd_path: Path, scratch_root: Path) -> DiscResult:
    """Runs the full per-disc pipeline. final_chd_path's parent directory
    must already exist and be on the same filesystem as final_chd_path's
    eventual home, so the closing promotion is a same-filesystem, atomic
    os.replace rather than a cross-filesystem copy."""
    extract_dir = None
    tmp_chd = final_chd_path.with_suffix(".chd.tmp")
    try:
        zip_sha256 = _sha256(zip_path)

        with zipfile.ZipFile(zip_path) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise ConversionError(f"corrupt member in zip: {bad_member}")

        extract_dir = Path(tempfile.mkdtemp(dir=scratch_root, prefix=f"{zip_path.stem}-"))
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        cue_candidates = list(extract_dir.glob("*.cue"))
        if len(cue_candidates) != 1:
            raise ConversionError(f"expected exactly one .cue, found {len(cue_candidates)}")
        cue_path = cue_candidates[0]

        referenced = _cue_referenced_files(cue_path)
        if not referenced:
            raise ConversionError(f"could not parse any FILE references from {cue_path.name}")
        missing = [name for name in referenced if not (extract_dir / name).exists()]
        if missing:
            raise ConversionError(f"cue references missing file(s): {missing}")

        tmp_chd.parent.mkdir(parents=True, exist_ok=True)
        create = subprocess.run(
            ["chdman", "createcd", "-i", str(cue_path), "-o", str(tmp_chd)],
            capture_output=True, text=True,
        )
        if create.returncode != 0:
            raise ConversionError(f"chdman createcd failed: {create.stderr or create.stdout}")

        verify = subprocess.run(
            ["chdman", "verify", "-i", str(tmp_chd)],
            capture_output=True, text=True,
        )
        if verify.returncode != 0:
            raise ConversionError(f"chdman verify failed: {verify.stderr or verify.stdout}")

        chd_sha256 = _sha256(tmp_chd)

        tmp_chd.replace(final_chd_path)  # atomic, same filesystem

        return DiscResult(zip_path, ok=True, zip_sha256=zip_sha256, chd_sha256=chd_sha256, chd_path=final_chd_path)

    except Exception as exc:  # noqa: BLE001 -- one bad disc must not stop the batch
        tmp_chd.unlink(missing_ok=True)
        return DiscResult(zip_path, ok=False, error=str(exc))

    finally:
        if extract_dir is not None:
            shutil.rmtree(extract_dir, ignore_errors=True)


def convert_platform(platform_dir: Path, log_path: Path) -> dict:
    """platform_dir is both source and destination -- converts the flat
    .zip archives in place into the CHD/M3U library structure, deleting
    each source zip only after its own conversion is verified and
    promoted. Never touches a zip whose conversion failed."""
    scratch_root = Path(tempfile.mkdtemp(prefix="chd-convert-"))
    results: list[DiscResult] = []

    try:
        groups = _group_discs(platform_dir)

        for key, zips in groups.items():
            multi_disc = len(zips) > 1
            base_name = normalized_base_name(zips[0].stem)

            if multi_disc:
                zips_in_order = sorted(zips, key=lambda p: disc_number(p.stem) or 0)
                game_dir = platform_dir / base_name
                game_dir.mkdir(parents=True, exist_ok=True)
                disc_results = []
                for zp in zips_in_order:
                    n = disc_number(zp.stem)
                    final_chd = game_dir / f"{base_name} (Disc {n}).chd"
                    result = _convert_one(zp, final_chd, scratch_root)
                    results.append(result)
                    disc_results.append((n, result))
                    if result.ok:
                        zp.unlink()

                if all(r.ok for _, r in disc_results):
                    m3u_path = game_dir / f"{base_name}.m3u"
                    m3u_path.write_text(
                        "\n".join(f"{base_name} (Disc {n}).chd" for n, _ in sorted(disc_results, key=lambda t: t[0]))
                        + "\n"
                    )
                else:
                    print(f"skipping .m3u for {base_name!r} -- not every disc converted cleanly")

            else:
                zp = zips[0]
                final_chd = platform_dir / f"{base_name}.chd"
                result = _convert_one(zp, final_chd, scratch_root)
                results.append(result)
                if result.ok:
                    zp.unlink()

    finally:
        shutil.rmtree(scratch_root, ignore_errors=True)

    log_entries = [
        {
            "source_zip": str(r.source_zip),
            "ok": r.ok,
            "zip_sha256": r.zip_sha256,
            "chd_sha256": r.chd_sha256,
            "chd_path": str(r.chd_path) if r.chd_path else None,
            "error": r.error,
        }
        for r in results
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log_entries, indent=2))

    succeeded = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]
    return {"total": len(results), "succeeded": succeeded, "failed": failed}
