"""The Reference Clip files: one folder per Word, numbered WAV files inside."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Optional

import numpy as np

from .audio import SAMPLE_RATE, AudioError, read_wav, write_wav

WORD_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 _-]*$")
CLIP_PATTERN = re.compile(r"^\d{3}\.wav$")
MAX_WORD_LENGTH = 40


class NotEnrolled(Exception):
    """Raised when a Word or Reference Clip that is asked for does not exist."""


def check_word(word: str) -> str:
    """Return the Word if it can name a folder. Raises AudioError otherwise."""
    if not isinstance(word, str) or len(word) > MAX_WORD_LENGTH or not WORD_PATTERN.match(word):
        raise AudioError(f"'{word}' is not a usable Word name: use lower-case letters, digits, spaces, - or _")
    return word


def next_clip_path(word_folder: Path) -> Path:
    """The first unused numbered file in a Word's folder."""
    number = 1
    while (word_folder / f"{number:03d}.wav").exists():
        number += 1
    return word_folder / f"{number:03d}.wav"


def list_words(directory: Path) -> List[dict]:
    """Every enrolled Word with its Reference Clips, in name order."""
    if not directory.is_dir():
        return []
    words = []
    for word_folder in sorted(path for path in directory.iterdir() if path.is_dir()):
        clips = []
        for clip in sorted(word_folder.glob("*.wav")):
            try:
                seconds: Optional[float] = round(read_wav(clip).size / SAMPLE_RATE, 2)
            except AudioError:
                seconds = None  # listed all the same, so that it can be removed
            clips.append({"name": clip.name, "seconds": seconds})
        if clips:
            words.append({"word": word_folder.name, "clips": clips})
    return words


def clip_path(directory: Path, word: str, name: str) -> Path:
    """Where one Reference Clip is kept. Raises NotEnrolled if it does not exist."""
    if not WORD_PATTERN.match(word) or not CLIP_PATTERN.match(name):
        raise NotEnrolled(f"there is no Reference Clip {word}/{name}")
    path = directory / word / name
    if not path.is_file():
        raise NotEnrolled(f"there is no Reference Clip {word}/{name}")
    return path


def replace_word(directory: Path, word: str, clips: List[np.ndarray]) -> int:
    """Give a Word these Reference Clips in place of the ones it had. Returns how many it had."""
    check_word(word)
    word_folder = directory / word
    try:
        word_folder.mkdir(parents=True, exist_ok=True)
        # The new ones are written in full before an old one is touched, so a failure loses nothing.
        waiting = []
        for number, samples in enumerate(clips, start=1):
            target = word_folder / f"{number:03d}.wav.new"
            write_wav(target, samples)
            waiting.append(target)
        old = list(word_folder.glob("*.wav"))
        for path in old:
            path.unlink()
        for path in waiting:
            path.rename(path.with_suffix(""))
    except OSError as error:
        raise AudioError(f"cannot save the Reference Clips of '{word}': {error}") from error
    return len(old)


def remove(directory: Path, word: str, name: Optional[str] = None) -> None:
    """Remove one Reference Clip, or the whole Word when no clip is named."""
    try:
        if name is None:
            if not WORD_PATTERN.match(word) or not (directory / word).is_dir():
                raise NotEnrolled(f"the Word '{word}' is not enrolled")
            shutil.rmtree(directory / word)
            return
        clip_path(directory, word, name).unlink()
        word_folder = directory / word
        if not any(word_folder.iterdir()):
            word_folder.rmdir()
    except OSError as error:
        raise AudioError(f"cannot remove it: {error}") from error
