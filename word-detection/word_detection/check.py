"""Run the matcher over a recording and list the Words it hears. For tuning, not for live use.

Run with: python -m word_detection.check recording.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from .audio import AudioError, PcmStream
from .features import FeatureExtractor
from .matcher import Match, Matcher, load_references


def find_matches(source: str, references_dir: Path, confident: float, uncertain: float) -> List[Match]:
    references = load_references(references_dir)
    if not references:
        raise AudioError(f"no usable Reference Clips in {references_dir}")

    extractor = FeatureExtractor()
    matcher = Matcher(references, confident, uncertain)
    matches: List[Match] = []
    with PcmStream(source) as stream:
        for chunk in stream.chunks():
            matches += matcher.push(extractor.push(chunk))
    return matches + matcher.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="List the Words heard in a recording.")
    parser.add_argument("source", help="the recording to check (any audio or video file)")
    parser.add_argument("--references-dir", type=Path, default=Path("references"), help="default: ./references")
    parser.add_argument("--confident", type=float, default=0.75, help="score for a confident match (default 0.75)")
    parser.add_argument("--uncertain", type=float, default=0.55, help="score for an Uncertain Match (default 0.55)")
    arguments = parser.parse_args()

    try:
        matches = find_matches(arguments.source, arguments.references_dir, arguments.confident, arguments.uncertain)
    except (AudioError, ValueError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        return 1

    if not matches:
        print("No Words heard.")
        return 0

    print(f"{'Start':>8}  {'Word':<16}  {'Score':>5}  {'Match':<9}  Reference Clip")
    for match in matches:
        kind = "uncertain" if match.uncertain else "confident"
        print(f"{match.start_seconds:>7.2f}s  {match.word:<16}  {match.score:>5.2f}  {kind:<9}  {match.reference}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
