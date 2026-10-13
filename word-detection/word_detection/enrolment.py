"""Enrolment from the mic feed: capture an Enrolment Recording, suggest its Spans, and save
them as Reference Clips.
"""

from __future__ import annotations

import logging
import threading
import wave
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import references
from .audio import BYTES_PER_SAMPLE, SAMPLE_RATE, AudioError, read_wav, to_pcm
from .matcher import MINIMUM_REFERENCE_SECONDS

log = logging.getLogger(__name__)

RECORDING_NAME = "enrolment-recording.wav"
LONGEST_SPAN_SECONDS = 10.0

# Finding the bursts of sound in an Enrolment Recording.
LEVEL_HOP = 160  # 10 ms
SMOOTHING_HOPS = 5
QUIETEST_LEVEL = 1e-5
ROOM_PERCENTILE = 20  # the level the room sits at when no button is sounding
LEAST_RISE_DB = 12.0  # a burst stands at least this far above the room
RISE_SHARE = 0.35  # and at least this share of the way from the room to the loudest moment
JOIN_GAP_SECONDS = 0.3  # a Word may have short silences inside it
EDGE_PADDING_SECONDS = 0.05
SHORTEST_BURST_SECONDS = 0.25


class EnrolmentError(Exception):
    """Raised when what was asked for cannot be done as things stand."""


class Enrolment:
    """The one Enrolment Recording there may be, and the Reference Clips cut from it.

    The listening loop feeds it audio while it is recording; the web side starts, stops and
    saves it. Both may call at once, so everything here is guarded by one lock.
    """

    def __init__(
        self,
        references_dir: Path,
        data_dir: Path,
        limit_seconds: float,
        on_recording_changed: Callable[[], None],
        on_references_changed: Callable[[], None],
    ) -> None:
        self._references_dir = references_dir
        self._recording_path = data_dir / RECORDING_NAME
        self._part_path = data_dir / f"{RECORDING_NAME}.part"
        self._limit_samples = int(limit_seconds * SAMPLE_RATE)
        self._limit_seconds = limit_seconds
        self._on_recording_changed = on_recording_changed
        self._on_references_changed = on_references_changed
        self._lock = threading.RLock()
        self._writer: Optional[wave.Wave_write] = None
        self._samples_written = 0
        self._level = 0.0
        self._hearing = False
        self._ended_because: Optional[str] = None

        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            # A recording cut short by a restart cannot be trusted.
            self._part_path.unlink(missing_ok=True)
        except OSError as error:
            log.warning("The Enrolment folder %s cannot be used: %s", data_dir, error)

    # ---- What the listening loop tells it -------------------------------------

    @property
    def recording(self) -> bool:
        return self._writer is not None

    def set_hearing(self, hearing: bool) -> None:
        """Told whether the mic feed is being heard. A recording ends when it is lost."""
        with self._lock:
            self._hearing = hearing
            if not hearing and self.recording:
                self._finish("the mic feed was lost")

    def feed(self, chunk: np.ndarray) -> None:
        """Add audio to the recording that is running."""
        with self._lock:
            if self._writer is None:
                return
            try:
                self._writer.writeframesraw(to_pcm(chunk))
            except OSError as error:
                log.error("The Enrolment Recording could not be written: %s", error)
                self._finish("the recording could not be written to disk")
                return
            self._samples_written += chunk.size
            self._level = float(np.max(np.abs(chunk))) if chunk.size else 0.0
            if self._samples_written >= self._limit_samples:
                self._finish(f"it reached the limit of {self._limit_seconds / 60:.0f} minutes")

    # ---- What the page asks of it ---------------------------------------------

    def state(self) -> dict:
        with self._lock:
            if self.recording:
                state, seconds = "recording", self._samples_written / SAMPLE_RATE
            elif self._recording_path.is_file():
                state, seconds = "ready", self._recording_seconds()
            else:
                state, seconds = "idle", 0.0
            return {
                "state": state,
                "hearing": self._hearing,
                "seconds": round(seconds, 2),
                "level": round(self._level, 3) if self.recording else 0.0,
                "limit_seconds": self._limit_seconds,
                "ended_because": self._ended_because,
            }

    def start(self) -> dict:
        """Begin a new Enrolment Recording, in place of any that was waiting."""
        with self._lock:
            if self.recording:
                raise EnrolmentError("an Enrolment Recording is already running")
            if not self._hearing:
                raise EnrolmentError("the mic feed is not being heard, so there is nothing to record")
            try:
                self._recording_path.unlink(missing_ok=True)
                writer = wave.open(str(self._part_path), "wb")
                writer.setnchannels(1)
                writer.setsampwidth(BYTES_PER_SAMPLE)
                writer.setframerate(SAMPLE_RATE)
            except (OSError, wave.Error) as error:
                raise EnrolmentError(f"the recording cannot be started: {error}") from error
            self._writer = writer
            self._samples_written = 0
            self._level = 0.0
            self._ended_because = None
            log.info("Enrolment Recording started. No Word is reported until it ends.")
        self._on_recording_changed()
        return self.state()

    def stop(self) -> dict:
        with self._lock:
            if not self.recording:
                raise EnrolmentError("no Enrolment Recording is running")
            self._finish(None)
        return self.state()

    def discard(self) -> dict:
        with self._lock:
            if self.recording:
                self._finish(None)
            try:
                self._recording_path.unlink(missing_ok=True)
            except OSError as error:
                raise EnrolmentError(f"the recording cannot be discarded: {error}") from error
            self._ended_because = None
            log.info("Enrolment Recording discarded.")
        return self.state()

    def recording_path(self) -> Path:
        with self._lock:
            if self.recording or not self._recording_path.is_file():
                raise EnrolmentError("there is no finished Enrolment Recording")
            return self._recording_path

    def suggested_spans(self) -> List[dict]:
        """The bursts of sound in the recording, each a likely button."""
        samples = self._read_recording()
        return [{"start": round(start, 3), "end": round(end, 3)} for start, end in find_bursts(samples)]

    def save(self, spans: object) -> dict:
        """Turn labelled Spans into Reference Clips, replacing those of each Word labelled."""
        with self._lock:
            samples = self._read_recording()
            length = samples.size / SAMPLE_RATE
            by_word: Dict[str, List[np.ndarray]] = defaultdict(list)
            for span in _checked(spans, length):
                by_word[span["word"]].append(samples[int(span["start"] * SAMPLE_RATE) : int(span["end"] * SAMPLE_RATE)])

            saved = []
            try:
                for word in sorted(by_word):
                    replaced = references.replace_word(self._references_dir, word, by_word[word])
                    saved.append({"word": word, "clips": len(by_word[word]), "replaced": replaced})
                    log.info(
                        "Enrolled '%s' with %d Reference Clip(s), in place of %d.", word, len(by_word[word]), replaced
                    )
            except AudioError as error:
                raise EnrolmentError(str(error)) from error
            finally:
                if saved:
                    self._on_references_changed()
            self._recording_path.unlink(missing_ok=True)
        return {"saved": saved}

    def words(self) -> List[dict]:
        return references.list_words(self._references_dir)

    def clip_path(self, word: str, name: str) -> Path:
        return references.clip_path(self._references_dir, word, name)

    def remove(self, word: str, name: Optional[str] = None) -> None:
        with self._lock:
            try:
                references.remove(self._references_dir, word, name)
            except AudioError as error:
                raise EnrolmentError(str(error)) from error
            log.info("Removed %s.", f"Reference Clip {word}/{name}" if name else f"the Word '{word}'")
        self._on_references_changed()

    # ---- Inside ---------------------------------------------------------------

    def _finish(self, because: Optional[str]) -> None:
        """Close the running recording and keep it. Called with the lock held."""
        writer, self._writer = self._writer, None
        if writer is None:
            return
        seconds = self._samples_written / SAMPLE_RATE
        self._ended_because = because
        try:
            writer.close()
            if self._samples_written:
                self._part_path.replace(self._recording_path)
            else:
                self._part_path.unlink(missing_ok=True)
        except (OSError, wave.Error) as error:
            log.error("The Enrolment Recording could not be kept: %s", error)
            self._ended_because = "the recording could not be written to disk"
        if because:
            log.warning("Enrolment Recording ended after %.0f s because %s.", seconds, because)
        else:
            log.info("Enrolment Recording stopped after %.0f s.", seconds)
        self._on_recording_changed()

    def _recording_seconds(self) -> float:
        try:
            with wave.open(str(self._recording_path), "rb") as wav:
                return wav.getnframes() / SAMPLE_RATE
        except (OSError, EOFError, wave.Error):
            return 0.0

    def _read_recording(self) -> np.ndarray:
        try:
            return read_wav(self.recording_path())
        except AudioError as error:
            raise EnrolmentError(f"the Enrolment Recording cannot be read: {error}") from error


def find_bursts(samples: np.ndarray) -> List[tuple]:
    """Where the recording rises clearly above the room, as (start, end) in seconds."""
    hops = samples.size // LEVEL_HOP
    if hops < SMOOTHING_HOPS:
        return []
    power = np.mean(np.square(samples[: hops * LEVEL_HOP].reshape(hops, LEVEL_HOP)), axis=1)
    power = np.convolve(power, np.ones(SMOOTHING_HOPS) / SMOOTHING_HOPS, mode="same")
    level = 10.0 * np.log10(np.maximum(power, QUIETEST_LEVEL**2))

    room = float(np.percentile(level, ROOM_PERCENTILE))
    loudest = float(level.max())
    if loudest - room < LEAST_RISE_DB:
        return []  # nothing stands out: a silent or evenly noisy recording
    loud = level > room + max(LEAST_RISE_DB, RISE_SHARE * (loudest - room))

    # Edges of each run of loud hops.
    padded = np.concatenate(([False], loud, [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    runs = [(int(start), int(end)) for start, end in zip(changes[::2], changes[1::2])]

    hop_seconds = LEVEL_HOP / SAMPLE_RATE
    joined: List[List[float]] = []
    for start, end in runs:
        if joined and start * hop_seconds - joined[-1][1] < JOIN_GAP_SECONDS:
            joined[-1][1] = end * hop_seconds
        else:
            joined.append([start * hop_seconds, end * hop_seconds])

    length = samples.size / SAMPLE_RATE
    return [
        (max(start - EDGE_PADDING_SECONDS, 0.0), min(end + EDGE_PADDING_SECONDS, length))
        for start, end in joined
        if end - start >= SHORTEST_BURST_SECONDS
    ]


def _checked(spans: object, length: float) -> List[dict]:
    """The Spans sent by the page, in time order. Raises EnrolmentError if any cannot be used."""
    if not isinstance(spans, list) or not spans:
        raise EnrolmentError("there are no Spans to save")
    checked = []
    for number, span in enumerate(spans, start=1):
        try:
            start, end, word = float(span["start"]), float(span["end"]), span["word"]
            references.check_word(word)
        except (KeyError, TypeError, ValueError) as error:
            raise EnrolmentError(f"Span {number} needs a start, an end and a Word") from error
        except AudioError as error:
            raise EnrolmentError(str(error)) from error
        if not 0.0 <= start < end <= length + 0.01:
            raise EnrolmentError(f"Span {number} ('{word}') does not lie inside the recording")
        if end - start < MINIMUM_REFERENCE_SECONDS:
            raise EnrolmentError(f"Span {number} ('{word}') is shorter than {MINIMUM_REFERENCE_SECONDS} s")
        if end - start > LONGEST_SPAN_SECONDS:
            raise EnrolmentError(f"Span {number} ('{word}') is longer than {LONGEST_SPAN_SECONDS:.0f} s")
        checked.append({"start": start, "end": min(end, length), "word": word})
    return sorted(checked, key=lambda span: span["start"])
