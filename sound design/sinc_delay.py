"""The fractional delay line (G1 decision 2), in the structure Source/dsp/SincDelay.h will mirror.

Two taps, read from one ring, crossfaded amplitude-complementary over `FADE_MS` whenever the delay
changes (G1: both taps carry the same signal, so an equal-power law would overshoot by up to 3 dB
where they are in phase; an amplitude-complementary one cannot overshoot at all).

Fractional part: a table of Kaiser-windowed sinc kernels, `PHASES` fractional positions by `TAPS`
taps, built in `prepare`. A kernel's nominal group delay is `TAPS/2 - 1` samples, so the table can
only be used from `MIN_SINC_SAMPLES` of delay upward; below that - reachable only in the "0 (live)"
window, where the reported latency is zero and the internal delay is the Delay knob alone - the
read falls back to the nearest whole sample. The fallback is exactly flat in magnitude and exactly
linear in phase; its only error is a delay quantisation of half a sample (0.0104 ms at 48 kHz,
0.0026 ms at 192 kHz), inside the brief's 0.02 ms accuracy target at every supported rate except
44.1 kHz, where it is 0.0113 ms. A delay of exactly zero is a wire: `ring[w]` is the sample just
written, so Delay 0 nulls bit-for-bit.

Every length here is in seconds or in samples derived from `fs` in `prepare` (rule 12).
"""

from __future__ import annotations

import numpy as np

TAPS = 32          # kernel length; the constant the G3 kernel search settled on
PHASES = 512       # fractional positions in the table: quantisation 1/1024 sample
KAISER_BETA = 9.0  # window shape; set by the G2 kernel search
CUTOFF = 1.0       # kernel cutoff as a fraction of Nyquist; set by the G2 kernel search
FADE_MS = 10.0     # delay-change crossfade (sketch 4.1, rule 2)

CENTRE = TAPS // 2 - 1              # a kernel's nominal group delay, in samples
MIN_SINC_SAMPLES = float(TAPS // 2)  # below this the read is nearest-sample


def design_kernels(taps: int = TAPS, phases: int = PHASES, beta: float = KAISER_BETA,
                   cutoff: float = CUTOFF) -> np.ndarray:
    """(phases + 1, taps) float64 table. Row p is the kernel for a fractional offset p / phases.

    Each row is normalised to sum 1, so the DC gain is exactly one and no setting shifts the level.
    """
    centre = taps // 2 - 1
    window = np.kaiser(taps, beta)
    k = np.arange(taps)
    table = np.empty((phases + 1, taps), dtype=np.float64)
    for p in range(phases + 1):
        frac = p / phases
        x = k - centre - frac
        table[p] = np.sinc(cutoff * x) * cutoff * window
        table[p] /= table[p].sum()
    return table


def kernel_response(table: np.ndarray, fs: float, freqs: np.ndarray) -> np.ndarray:
    """(phases + 1, len(freqs)) complex response of every kernel, for the flatness check."""
    k = np.arange(table.shape[1])
    phase = np.exp(-2j * np.pi * np.outer(freqs / fs, k))
    return table @ phase.T


class SincDelay:
    """prepare / reset / set_delay_samples / process_block, the module shape of F.9."""

    def __init__(self) -> None:
        self.table = design_kernels()
        self._fs = 48000.0
        self._size = 1
        self._ring = np.zeros((2, 1))
        self._w = 0
        self._chunk = 512
        self._cur = 0.0
        self._target = 0.0
        self._old = 0.0
        self._fade_len = 0
        self._fade_pos = 0
        self._fading = False

    # -- lifecycle -----------------------------------------------------------------
    def prepare(self, fs: float, max_delay_samples: float, max_block: int = 512,
                channels: int = 2) -> None:
        self._fs = float(fs)
        # Prototype-era detail, listed here so G4 can decide it again (F.8): the read is vectorised
        # over a whole chunk, so the chunk is written into the ring before it is read and the ring
        # has to hold the chunk *and* the deepest delay. The C++ port reads per sample and needs
        # only the delay. `_chunk` keeps the result independent of the block size the caller uses,
        # including a block larger than the one announced to prepare.
        self._chunk = max(1, int(max_block))
        self._size = int(np.ceil(max_delay_samples)) + TAPS + 2 + self._chunk
        self._ring = np.zeros((channels, self._size), dtype=np.float64)
        self._fade_len = max(1, int(round(FADE_MS * 1e-3 * fs)))
        self.reset()

    def reset(self) -> None:
        self._ring[:] = 0.0
        self._w = 0
        self._cur = self._target
        self._old = self._target
        self._fade_pos = 0
        self._fading = False

    def set_delay_samples(self, d: float) -> None:
        self._target = float(max(0.0, d))

    @property
    def latency_samples(self) -> float:
        return self._cur

    # -- audio ---------------------------------------------------------------------
    def _read(self, ch: int, positions: np.ndarray, delay: float) -> np.ndarray:
        """Read `len(positions)` samples at a constant `delay`, positions being ring write indices."""
        if delay < MIN_SINC_SAMPLES:
            j = int(round(delay))
            return self._ring[ch][(positions - j) % self._size]
        i_d = int(np.floor(delay))
        frac = delay - i_d
        if frac == 0.0:
            # A whole number of samples is read straight from the ring. At CUTOFF 1.0 the frac = 0
            # kernel already is a delta, so this is only cheaper - but it also makes the identity
            # exact by construction rather than by a property of the window, and the brief's null
            # test lands exactly here: every Window is a whole number of samples by definition.
            return self._ring[ch][(positions - i_d) % self._size]
        row = self.table[int(round(frac * PHASES))]
        base = positions - (i_d - CENTRE)
        idx = (base[:, None] - np.arange(TAPS)[None, :]) % self._size
        return self._ring[ch][idx] @ row

    def process_block(self, block: np.ndarray) -> np.ndarray:
        """block: (channels, n). Returns a new (channels, n) array. The delay target is read once
        per block, which is the parameter's `control_rate` in parameters.csv."""
        n = block.shape[1]
        if n > self._chunk:
            out = np.empty_like(block)
            for at in range(0, n, self._chunk):
                end = min(n, at + self._chunk)
                out[:, at:end] = self._process_chunk(block[:, at:end])
            return out
        return self._process_chunk(block)

    def _process_chunk(self, block: np.ndarray) -> np.ndarray:
        channels, n = block.shape
        if n == 0:
            return block.copy()

        if not self._fading and self._target != self._cur:
            self._old = self._cur
            self._fading = True
            self._fade_pos = 0

        positions = (self._w + 1 + np.arange(n)) % self._size
        for ch in range(channels):
            self._ring[ch][positions] = block[ch]
        self._w = int(positions[-1])

        if not self._fading:
            out = np.empty_like(block)
            for ch in range(channels):
                out[ch] = self._read(ch, positions, self._cur)
            return out

        # amplitude-complementary ramp from the old tap to the target, possibly spanning blocks; the
        # first sample is already one step in and the fade's last sample is the target alone, as in
        # SincDelay.h (it once started on the old tap and ended a step short, then jumped 1/L)
        step = np.arange(n) + self._fade_pos + 1
        a = np.clip(1.0 - step / self._fade_len, 0.0, 1.0)
        out = np.empty_like(block)
        for ch in range(channels):
            old = self._read(ch, positions, self._old)
            new = self._read(ch, positions, self._target)
            out[ch] = a * old + (1.0 - a) * new
        self._fade_pos += n
        if self._fade_pos >= self._fade_len:
            self._cur = self._target
            self._old = self._target
            self._fading = False
            self._fade_pos = 0
        return out
