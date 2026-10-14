#!/usr/bin/env python3
"""Gives every Clip without a thumbnail one, cut from the Clip file itself.

New Clips get their thumbnail from Frigate as they are cut. Frigate keeps only an hour of
footage, so older Clips (and any whose thumbnail could not be had then) are done here instead,
with ffmpeg from the relay's image. Run on this PC:  ./fluentpet.sh thumbnails
"""

from __future__ import annotations

import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_ENV = ROOT / "frigate" / ".env"
FFMPEG_IMAGE = "bluenviron/mediamtx:latest-ffmpeg"
THUMBNAIL_HEIGHT = 360  # as the recording service saves them

# Reads "<name> <seconds>" lines and writes <name>.jpg beside <name>.mp4, the frame that many
# seconds in. Each is written under another name first, so a half-written one is never shown.
CUT = f"""
made=0; failed=0
while read -r name offset; do
  if ffmpeg -nostdin -loglevel error -ss "$offset" -i "/clips/$name.mp4" -frames:v 1 \\
       -vf scale=-2:{THUMBNAIL_HEIGHT} -q:v 4 -f image2 -y "/clips/$name.jpg.partial" \\
     && mv "/clips/$name.jpg.partial" "/clips/$name.jpg"; then
    made=$((made + 1))
  else
    rm -f "/clips/$name.jpg.partial"; failed=$((failed + 1)); echo "  ✗ $name.mp4" >&2
  fi
done
echo "$made $failed"
"""


def read_env(path: Path) -> dict:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = shlex.split(value)[0] if value.strip() else ""
    return values


def main() -> int:
    if not COMPOSE_ENV.is_file():
        print("✗ frigate/.env was not found. Run ./fluentpet.sh configure first.", file=sys.stderr)
        return 1
    env = read_env(COMPOSE_ENV)
    clips_dir = Path(env.get("FP_CLIPS_DIR", ""))
    database = Path(env.get("FP_DATA_DIR", "")) / "correlator.db"
    if not clips_dir.is_dir():
        print(f"✗ The Clip folder {clips_dir} does not exist. Is the drive connected?", file=sys.stderr)
        return 1
    if not database.is_file():
        print(f"✗ The study's database was not found at {database}.", file=sys.stderr)
        return 1

    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=10.0)
        rows = connection.execute(
            "SELECT clip_path, started_at - clip_started_at FROM utterances"
            " WHERE clip_status = 'ready' AND clip_path IS NOT NULL ORDER BY id"
        ).fetchall()
        connection.close()
    except sqlite3.Error as error:
        print(f"✗ The study's database could not be read: {error}", file=sys.stderr)
        return 1

    wanted = []
    for clip_path, offset in rows:
        clip = clips_dir / clip_path
        if clip.suffix == ".mp4" and clip.is_file() and not clip.with_suffix(".jpg").is_file():
            wanted.append(f"{clip.stem} {max(offset or 0.0, 0.0):.3f}")
    if not wanted:
        print(f"✓ Every one of the {len(rows)} Clips already has a thumbnail.")
        return 0

    print(f"Cutting thumbnails for {len(wanted)} of {len(rows)} Clips…")
    command = ["docker", "run", "--rm", "-i", "--entrypoint", "sh", "-v", f"{clips_dir}:/clips", FFMPEG_IMAGE, "-c", CUT]
    try:
        result = subprocess.run(command, input="\n".join(wanted) + "\n", capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("✗ docker was not found. Is Docker Desktop running, with WSL integration on?", file=sys.stderr)
        return 1
    sys.stderr.write(result.stderr)
    try:
        made, failed = (int(part) for part in result.stdout.split()[-2:])
    except ValueError:
        print(f"✗ ffmpeg could not be run (docker exited with {result.returncode}).", file=sys.stderr)
        return 1
    if failed:
        print(f"✗ {made} thumbnails made; {failed} Clips could not be read (listed above).")
        return 1
    print(f"✓ {made} thumbnails made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
