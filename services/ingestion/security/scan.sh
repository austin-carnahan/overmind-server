#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:?usage: scan.sh <path>}"
[[ -e "$TARGET" ]] || { echo "Target does not exist: $TARGET" >&2; exit 2; }
command -v clamscan >/dev/null 2>&1 || { echo "clamscan not installed" >&2; exit 3; }

printf 'Scanning: %s\n' "$TARGET"
clamscan --recursive --infected --alert-encrypted -- "$TARGET"
