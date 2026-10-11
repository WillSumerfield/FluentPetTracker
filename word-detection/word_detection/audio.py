"""Reading audio: Reference Clip files from disk, and decoded audio from FFmpeg."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from typing import Iterator, List, Optional

import numpy as np

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
CHUNK_SECONDS = 0.1
RTSP_TIMEOUT_MICROSECONDS = 10_000_000


class AudioError(Exception):
    """Raised when audio cannot be read or decoded."""


def read_wav(path: Path) -> np.ndarray:
    """Read a 16 kHz mono 16-bit WAV file as floats between -1 and 1."""
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            raw = wav.readframes(wav.getnframes())
    except (OSError, EOFError, wave.Error) as error:
        raise AudioError(f"cannot read {path}: {error}") from error

    if channels != 1 or sample_width != BYTES_PER_SAMPLE or sample_rate != SAMPLE_RATE:
        raise AudioError(
            f"{path} must be {SAMPLE_RATE} Hz mono 16-bit, "
            f"but is {sample_rate} Hz, {channels} channel(s), {sample_width * 8}-bit"
        )
    return _to_floats(raw)


def decode_command(source: str) -> List[str]:
    """Build the FFmpeg command that decodes a source to raw 16 kHz mono audio."""
    # Only fatal messages are shown: a sender that restarts its own clock (as the looping
    # stand-in does) otherwise fills the log with harmless timestamp warnings.
    command = ["ffmpeg", "-nostdin", "-loglevel", "fatal"]
    if source.startswith(("rtsp://", "rtsps://")):
        command += ["-rtsp_transport", "tcp", "-timeout", str(RTSP_TIMEOUT_MICROSECONDS)]
    command += ["-i", source, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    return command


class PcmStream:
    """Decoded audio from a file or stream, read in short chunks through FFmpeg."""

    def __init__(self, source: str) -> None:
        self._source = source
        self._process: Optional[subprocess.Popen] = None

    def __enter__(self) -> "PcmStream":
        try:
            self._process = subprocess.Popen(decode_command(self._source), stdout=subprocess.PIPE)
        except OSError as error:
            raise AudioError(f"cannot start ffmpeg: {error}") from error
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Stop FFmpeg. Safe to call more than once, and from a signal handler."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def chunks(self) -> Iterator[np.ndarray]:
        """Yield audio chunks until the source ends. Raises AudioError if FFmpeg fails."""
        if self._process is None or self._process.stdout is None:
            raise AudioError("the stream has not been opened")

        chunk_bytes = int(SAMPLE_RATE * CHUNK_SECONDS) * BYTES_PER_SAMPLE
        while True:
            raw = self._process.stdout.read(chunk_bytes)
            usable = len(raw) - (len(raw) % BYTES_PER_SAMPLE)
            if usable:
                yield _to_floats(raw[:usable])
            if len(raw) < chunk_bytes:
                break

        exit_code = self._process.wait()
        if exit_code not in (0, -15):  # -15: stopped by close()
            raise AudioError(f"ffmpeg exited with code {exit_code} while reading {self._source}")


def _to_floats(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
