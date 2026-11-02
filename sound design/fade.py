"""LinearFade: the one crossfade position every switch on the path uses, mirroring Source/dsp/Fade.h.

A change of target starts a straight line from wherever the fade is to the new target, over the
full length, and the last sample lands on the target exactly. The position is the closed form
`start + step * done`, so it does not depend on the block size, and fades started together stay
amplitude-complementary. docs/failures.md 2026-11-03: a step re-derived from the remaining distance
at every block made each fade geometric and block-size dependent (and, in the float32 port, it
stalled about 2e-5 short of its target).
"""

from __future__ import annotations

import numpy as np


class LinearFade:
    def __init__(self) -> None:
        self.value = 0.0
        self.target = 0.0
        self._start = 0.0
        self._step = 0.0
        self._length = 1
        self._done = 1

    def prepare(self, length: int, initial: float) -> None:
        self._length = max(1, int(length))
        self.snap(initial)

    def snap(self, v: float) -> None:
        """Jump to `v` with no fade (prepare, reset, a measurement of the stage alone)."""
        self.value = self.target = self._start = float(v)
        self._step = 0.0
        self._done = self._length

    def set_target(self, t: float) -> None:
        if t == self.target:
            return
        self._start = self.value
        self.target = float(t)
        self._step = (t - self.value) / self._length
        self._done = 0

    def idle(self) -> bool:
        return self._done >= self._length

    def ramp(self, n: int) -> np.ndarray:
        """The positions for the next n samples."""
        if n <= 0:
            return np.zeros(0)
        if self.idle():
            return np.full(n, self.value)
        k = self._done + np.arange(1, n + 1)
        r = np.where(k >= self._length, self.target, self._start + self._step * k)
        self._done = min(self._length, self._done + n)
        self.value = float(r[-1])
        return r
