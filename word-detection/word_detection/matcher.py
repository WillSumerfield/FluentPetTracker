"""Matches incoming spectrogram frames against the Reference Clips."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .audio import AudioError, read_wav
from .features import FRAMES_PER_SECOND, extract_features

log = logging.getLogger(__name__)

MINIMUM_REFERENCE_SECONDS = 0.2
SETTLE_SECONDS = 0.3
FLAT_SIGNAL = 1e-6


@dataclass(frozen=True)
class Reference:
    """One Reference Clip, prepared for matching."""

    word: str
    name: str
    template: np.ndarray  # shape (frames, bands), each band zero mean, unit length overall

    @property
    def frame_count(self) -> int:
        return self.template.shape[0]


@dataclass(frozen=True)
class Match:
    """A Word heard in the audio. Frames count from the start of the stream."""

    word: str
    reference: str
    score: float
    start_frame: int
    end_frame: int
    uncertain: bool

    @property
    def start_seconds(self) -> float:
        return self.start_frame / FRAMES_PER_SECOND


def load_references(directory: Path) -> List[Reference]:
    """Load every Reference Clip. Each sub-folder is a Word; unusable clips are skipped."""
    if not directory.is_dir():
        log.warning("Reference folder %s does not exist.", directory)
        return []

    references: List[Reference] = []
    for word_folder in sorted(path for path in directory.iterdir() if path.is_dir()):
        for clip in sorted(word_folder.glob("*.wav")):
            name = f"{word_folder.name}/{clip.name}"
            try:
                features = extract_features(read_wav(clip))
            except AudioError as error:
                log.warning("Skipping Reference Clip %s: %s", name, error)
                continue

            if features.shape[0] < MINIMUM_REFERENCE_SECONDS * FRAMES_PER_SECOND:
                log.warning("Skipping Reference Clip %s: shorter than %.1f s.", name, MINIMUM_REFERENCE_SECONDS)
                continue

            # Centre each band on its own average, so the match follows how the sound
            # changes over time and not the overall tone shared by all audio.
            centred = features - features.mean(axis=0)
            length = float(np.linalg.norm(centred))
            if length < FLAT_SIGNAL:
                log.warning("Skipping Reference Clip %s: it contains no sound.", name)
                continue

            references.append(Reference(word_folder.name, name, centred / length))
    return references


class Matcher:
    """Finds Words in a stream of spectrogram frames.

    Each Reference Clip is slid along the audio and scored between -1 and 1 for how
    closely the audio follows it. A score peak above the uncertain threshold becomes
    a Match once no better score has turned up for a short settling time.
    """

    def __init__(self, references: List[Reference], confident_threshold: float, uncertain_threshold: float) -> None:
        if not references:
            raise ValueError("at least one Reference Clip is required")
        if not -1.0 <= uncertain_threshold <= confident_threshold <= 1.0:
            raise ValueError("thresholds must satisfy -1 <= uncertain <= confident <= 1")

        self._references = references
        self._confident_threshold = confident_threshold
        self._uncertain_threshold = uncertain_threshold
        self._settle_frames = int(SETTLE_SECONDS * FRAMES_PER_SECOND)
        self._tail_length = max(reference.frame_count for reference in references) - 1
        self._tail: Optional[np.ndarray] = None
        self._frames_seen = 0
        self._candidate: Optional[Match] = None
        self._last_end_by_word: Dict[str, int] = {}

    def push(self, frames: np.ndarray) -> List[Match]:
        """Add new frames and return the Matches that are now settled."""
        if frames.shape[0] == 0:
            return []

        history = frames if self._tail is None else np.concatenate([self._tail, frames])
        first_frame = self._frames_seen - (history.shape[0] - frames.shape[0])
        first_new = history.shape[0] - frames.shape[0]

        best_scores = np.full(frames.shape[0], -np.inf)
        best_references = np.zeros(frames.shape[0], dtype=int)
        for index, reference in enumerate(self._references):
            scores = self._score(history, reference)
            if scores is None:
                continue
            # scores[k] is for the window ending at history row k + frame_count - 1.
            first_end = reference.frame_count - 1
            skip = max(0, first_new - first_end)
            offset = max(0, first_end - first_new)
            usable = scores[skip:]
            better = usable > best_scores[offset:]
            best_scores[offset:][better] = usable[better]
            best_references[offset:][better] = index

        matches: List[Match] = []
        for position in range(frames.shape[0]):
            end_frame = first_frame + first_new + position
            score = float(best_scores[position])
            if score >= self._uncertain_threshold and (self._candidate is None or score > self._candidate.score):
                reference = self._references[best_references[position]]
                self._candidate = Match(
                    word=reference.word,
                    reference=reference.name,
                    score=score,
                    start_frame=end_frame - reference.frame_count + 1,
                    end_frame=end_frame,
                    uncertain=score < self._confident_threshold,
                )
            if self._candidate is not None and end_frame - self._candidate.end_frame >= self._settle_frames:
                self._settle(matches)

        self._frames_seen += frames.shape[0]
        self._tail = history[-self._tail_length :] if self._tail_length else history[:0]
        return matches

    def flush(self) -> List[Match]:
        """Return a Match still waiting to settle. Call when the audio has ended."""
        matches: List[Match] = []
        if self._candidate is not None:
            self._settle(matches)
        return matches

    def _settle(self, matches: List[Match]) -> None:
        candidate, self._candidate = self._candidate, None
        if candidate is None:
            return
        # A repeat that starts before the same Word finished playing is the same Press.
        if candidate.start_frame <= self._last_end_by_word.get(candidate.word, -1):
            log.debug("Ignored a repeat of '%s' inside the previous one.", candidate.word)
            return
        self._last_end_by_word[candidate.word] = candidate.end_frame
        matches.append(candidate)

    @staticmethod
    def _score(history: np.ndarray, reference: Reference) -> Optional[np.ndarray]:
        """Score the Reference Clip against every window of the history it fits in."""
        if history.shape[0] < reference.frame_count:
            return None
        windows = sliding_window_view(history, reference.frame_count, axis=0)  # (n, bands, frames)
        template = reference.template.T
        overlap = np.einsum("nbt,bt->n", windows, template)
        band_means = windows.mean(axis=2)
        squares = np.einsum("nbt,nbt->n", windows, windows)
        centred_squares = squares - reference.frame_count * np.einsum("nb,nb->n", band_means, band_means)
        spread = np.sqrt(np.maximum(centred_squares, FLAT_SIGNAL))
        return overlap / spread
