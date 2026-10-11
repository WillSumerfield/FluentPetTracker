"""Enrolment: cut a Reference Clip for a Word out of a recording.

Run with: python -m word_detection.enrol --word happy --source press.mp4 --start 16.9 --length 1.5
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from .audio import SAMPLE_RATE, AudioError, read_wav

WORD_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 _-]*$")


def enrol(word: str, source: str, start: float, length: float, references_dir: Path) -> Path:
    """Cut one Reference Clip and return the file it was saved to."""
    if not WORD_PATTERN.match(word):
        raise AudioError(f"'{word}' is not a usable Word name: use lower-case letters, digits, spaces, - or _")
    if start < 0 or length <= 0:
        raise AudioError("the start must not be negative and the length must be greater than 0")

    word_folder = references_dir / word
    try:
        word_folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AudioError(f"cannot create {word_folder}: {error}") from error

    number = 1
    while (word_folder / f"{number:03d}.wav").exists():
        number += 1
    target = word_folder / f"{number:03d}.wav"

    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-ss", str(start), "-t", str(length), "-i", source,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(target),
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise AudioError(f"cannot start ffmpeg: {error}") from error
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise AudioError(f"ffmpeg could not cut the clip: {result.stderr.strip() or 'no details given'}")

    seconds = read_wav(target).size / SAMPLE_RATE
    if seconds < length * 0.9:
        target.unlink(missing_ok=True)
        raise AudioError(f"the recording ends too early: only {seconds:.2f} s of the {length:.2f} s asked for")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Cut a Reference Clip for a Word out of a recording.")
    parser.add_argument("--word", required=True, help="the Word this button says, e.g. happy")
    parser.add_argument("--source", required=True, help="the recording to cut from (any audio or video file)")
    parser.add_argument("--start", required=True, type=float, help="where the Word starts, in seconds")
    parser.add_argument("--length", required=True, type=float, help="how long the Word lasts, in seconds")
    parser.add_argument("--references-dir", type=Path, default=Path("references"), help="default: ./references")
    arguments = parser.parse_args()

    try:
        target = enrol(arguments.word, arguments.source, arguments.start, arguments.length, arguments.references_dir)
    except AudioError as error:
        print(f"Enrolment failed: {error}", file=sys.stderr)
        return 1

    print(f"Saved a Reference Clip for '{arguments.word}': {target} ({arguments.length:.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
