#!/usr/bin/env bash
set -euo pipefail

FILE="${1:?usage: validate-media.sh <media-file>}"
[[ -f "$FILE" ]] || { echo "Not a regular file: $FILE" >&2; exit 2; }
command -v ffprobe >/dev/null 2>&1 || { echo "ffprobe not installed" >&2; exit 3; }

ffprobe -v error -show_entries format=format_name,duration -show_streams -of json -i "$FILE" >/dev/null
printf 'Container probe succeeded: %s (not a complete import check)\n' "$FILE"
