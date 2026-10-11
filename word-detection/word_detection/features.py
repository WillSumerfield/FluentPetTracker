"""Turns audio into a spectrogram: one row of band energies per 10 ms frame."""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .audio import SAMPLE_RATE

FRAME_LENGTH = 400  # 25 ms
HOP_LENGTH = 160  # 10 ms
FFT_LENGTH = 512
BAND_COUNT = 40
LOWEST_HZ = 100.0
HIGHEST_HZ = 7600.0
ENERGY_FLOOR = 1e-8

FRAMES_PER_SECOND = SAMPLE_RATE / HOP_LENGTH


def _hz_to_mel(hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _band_filters() -> np.ndarray:
    """Triangular filters, evenly spaced on the mel scale. Shape: (bands, FFT bins)."""
    edges = _mel_to_hz(
        np.linspace(_hz_to_mel(np.array(LOWEST_HZ)), _hz_to_mel(np.array(HIGHEST_HZ)), BAND_COUNT + 2)
    )
    bin_hz = np.fft.rfftfreq(FFT_LENGTH, d=1.0 / SAMPLE_RATE)
    filters = np.zeros((BAND_COUNT, bin_hz.size), dtype=np.float32)
    for band in range(BAND_COUNT):
        low, centre, high = edges[band], edges[band + 1], edges[band + 2]
        rising = (bin_hz - low) / (centre - low)
        falling = (high - bin_hz) / (high - centre)
        filters[band] = np.clip(np.minimum(rising, falling), 0.0, None)
    return filters


_FILTERS = _band_filters()
_WINDOW = np.hanning(FRAME_LENGTH).astype(np.float32)


class FeatureExtractor:
    """Computes spectrogram frames from audio that arrives a chunk at a time."""

    def __init__(self) -> None:
        self._pending = np.zeros(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> np.ndarray:
        """Add audio and return the frames it completes. Shape: (frames, bands)."""
        audio = np.concatenate([self._pending, samples.astype(np.float32, copy=False)])
        if audio.size < FRAME_LENGTH:
            self._pending = audio
            return np.zeros((0, BAND_COUNT), dtype=np.float32)

        frame_count = 1 + (audio.size - FRAME_LENGTH) // HOP_LENGTH
        frames = sliding_window_view(audio, FRAME_LENGTH)[::HOP_LENGTH][:frame_count]
        spectrum = np.fft.rfft(frames * _WINDOW, n=FFT_LENGTH, axis=1)
        power = (spectrum.real**2 + spectrum.imag**2).astype(np.float32)
        self._pending = audio[frame_count * HOP_LENGTH :]
        return np.log(power @ _FILTERS.T + ENERGY_FLOOR)


def extract_features(samples: np.ndarray) -> np.ndarray:
    """Compute the spectrogram of a whole recording at once."""
    return FeatureExtractor().push(samples)
