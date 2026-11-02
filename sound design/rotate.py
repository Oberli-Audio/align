"""Rotate: the low-end phase rotation (G1 decision 3), mirroring Source/dsp/Rotate.h.

Two cascaded first-order TPT all-passes at the same corner. The corner is not a parameter: it is
solved from the angle the user asked for and the frequency it must be reached at, directly in the
digital domain, so the warping of the bilinear transform is inside the solution rather than an
error on top of it:

    phase(f) = -4 * atan( tan(pi f / fs) / g ),    g = tan(pi * Below / fs) / tan(Rotate / 4)

which gives exactly `-Rotate` at `Below`, 0 at DC, and -360 deg (indistinguishable from 0 for a
steady tone) far above the corner. Magnitude is exactly 1 at every setting and the stage has no
latency. At Rotate 180 the corner lands on Below, which is how the sketch drew it.

`g` is clamped to `G_MAX`, which keeps every angle down to about 0.002 deg reachable - far below
the degree the editor displays - so the stage never needs a "smallest usable angle". Rotate exactly
0 still bypasses the stage through a 15 ms amplitude-complementary crossfade, which is what makes
the brief's null test exact; the filter keeps running while bypassed, so coming back out of bypass
has no state transient.

`phase_response` is the analytic version of the same filter and is what the detector's Rotate
search and the editor's curve use, so the picture and the audio come from one formula (rule 9).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

FADE_MS = 15.0
FAST = True        # use the direct-form path for renders; `check_rotate_structure` proves the two
                   # realisations agree, so the prototype's structural claim is measured, not assumed
G_MAX = 1.0e4
G_MIN = 1.0e-4


def coefficient(rotate_deg: float, below_hz: float, fs: float) -> float:
    """The shared coefficient `g` of the two sections."""
    t = np.tan(np.deg2rad(max(rotate_deg, 1.0e-9)) / 4.0)
    g = np.tan(np.pi * min(below_hz, 0.49 * fs) / fs) / t
    return float(np.clip(g, G_MIN, G_MAX))


def phase_response(freqs: np.ndarray, rotate_deg: float, below_hz: float, fs: float) -> np.ndarray:
    """Phase in radians of the two-section cascade, the analytic form of what the audio does."""
    g = coefficient(rotate_deg, below_hz, fs)
    return -4.0 * np.arctan(np.tan(np.pi * np.asarray(freqs) / fs) / g)


class Rotate:
    """prepare / reset / set_params / process_block (F.9)."""

    def __init__(self) -> None:
        self._fs = 48000.0
        self._g = G_MAX
        self._state = np.zeros((2, 2))   # [channel][section]
        self._active = False
        self._mix = 0.0                  # 0 = dry, 1 = filtered
        self._fade_len = 1

    def prepare(self, fs: float, channels: int = 2) -> None:
        self._fs = float(fs)
        self._state = np.zeros((channels, 2))
        self._zi = np.zeros((channels, 2, 1))
        self._fade_len = max(1, int(round(FADE_MS * 1e-3 * fs)))
        self.reset()

    def reset(self) -> None:
        self._state[:] = 0.0
        self._zi[:] = 0.0
        self._mix = 1.0 if self._active else 0.0

    def set_params(self, rotate_deg: float, below_hz: float) -> None:
        """`rotate_deg` is the smoothed value; the bypass follows the *target*, so a parameter set
        to exactly 0 reaches a dry path instead of asymptotically approaching one."""
        self._g = coefficient(rotate_deg, below_hz, self._fs)
        self._active = rotate_deg > 0.0

    # -- audio ---------------------------------------------------------------------
    def _section(self, x: np.ndarray, ch: int, section: int) -> np.ndarray:
        """One first-order TPT all-pass: lp = v + s, s = lp + v, ap = 2 lp - x (rule 6)."""
        big_g = self._g / (1.0 + self._g)
        s = self._state[ch][section]
        y = np.empty_like(x)
        for i in range(x.shape[0]):
            v = (x[i] - s) * big_g
            lp = v + s
            s = lp + v
            y[i] = lp + lp - x[i]
        self._state[ch][section] = s
        return y

    def _section_df1(self, x: np.ndarray, ch: int, section: int) -> np.ndarray:
        """The same first-order all-pass as a direct form, (c + z^-1) / (1 + c z^-1) with
        c = (g - 1) / (g + 1) - the bilinear transform of (1 - s/wc) / (1 + s/wc) at prewarp g.
        Identical transfer function, run at C speed so the whole rate-and-block matrix fits in a
        prototype run. The C++ port uses the TPT form above."""
        c = (self._g - 1.0) / (self._g + 1.0)
        y, zf = lfilter([c, 1.0], [1.0, c], x, zi=self._zi[ch][section])
        self._zi[ch][section] = zf
        return y

    def process_block(self, block: np.ndarray) -> np.ndarray:
        channels, n = block.shape
        if n == 0:
            return block.copy()
        section = self._section_df1 if FAST else self._section
        wet = np.empty_like(block)
        for ch in range(channels):
            wet[ch] = section(section(block[ch], ch, 0), ch, 1)

        target = 1.0 if self._active else 0.0
        if self._mix == target:
            return wet if target == 1.0 else block.copy()
        step = (target - self._mix) / self._fade_len
        ramp = np.clip(self._mix + step * (np.arange(n) + 1), min(self._mix, target),
                       max(self._mix, target))
        self._mix = float(ramp[-1])
        return (1.0 - ramp) * block + ramp * wet
