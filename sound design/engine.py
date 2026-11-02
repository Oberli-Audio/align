"""AlignEngine: the audio path, mirroring Source/dsp/AlignEngine.h.

    in -> polarity -> fractional delay (Window + Delay) -> Rotate -> Trim -> out
    Listen: Off = out, Ref = the sidechain, Sum = (out + ref) / 2 in mono on both channels

Every stage is individually nullable, which is what the brief's null test asserts: Polarity off is a
wire, Delay 0 with Window 0 is a wire, Rotate 0 is a wire (the stage is crossfaded out), Trim 0 dB
is a wire. With a Window above zero the plugin delays by exactly `round(Window * fs / 1000)` whole
samples and reports that number, so the host's compensation is exact and the null closes after it.

Latency and the clamp (G1 decision 6):
    latency_samples = round(Window_ms * fs / 1000)
    internal delay  = latency_samples + clamp(Delay_ms, -Window_ms, +200 ms) * fs / 1000

The engine is block-based and reads its parameter targets once per block, which is the
`control_rate` column of parameters.csv; smoothing uses the `smoothing` column's tau. Rotate and
Below move a filter coefficient, so they advance on a control grid of CONTROL_MS fixed to the
stream (rule 2: sub-blocks of at most 32 samples), never once per block: the smoothing time and the
output do not depend on the block size (docs/failures.md, 2026-11-03).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import rotate as rotate_stage
from fade import LinearFade
from sinc_delay import SincDelay

WINDOW_MS = (0.0, 5.0, 20.0, 50.0, 200.0)
DELAY_MAX_MS = 200.0
POLARITY_FADE_MS = 15.0
LISTEN_FADE_MS = 15.0
TRIM_TAU_MS = 20.0
ROTATE_TAU_MS = 20.0
BELOW_TAU_MS = 20.0
CONTROL_MS = 0.16        # 7 samples at 44.1 kHz, 31 at 192 kHz
SNAP = 1e-4              # a smoother lands on its target within this (degrees, Hz)
ANALYSIS_SECONDS = 4.0


@dataclass
class Params:
    """Plain units, exactly the parameter table's (parameters.csv)."""
    delay_ms: float = 0.0
    polarity: bool = False
    window: int = 2          # index into WINDOW_MS
    rotate_deg: float = 0.0
    below_hz: float = 120.0
    listen: int = 0          # 0 Off, 1 Ref, 2 Sum
    trim_db: float = 0.0
    bypass: bool = False

    @property
    def window_ms(self) -> float:
        return WINDOW_MS[int(self.window)]


def _tau_coefficient(tau_ms: float, fs: float) -> float:
    if tau_ms <= 0.0:
        return 0.0
    return float(np.exp(-1.0 / (tau_ms * 1e-3 * fs)))


class _Smoothed:
    """One-pole smoother on the value itself; `domain` only documents what the value is."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self._a = 0.0

    def prepare(self, tau_ms: float, fs: float, value: float) -> None:
        self._a = _tau_coefficient(tau_ms, fs)
        self.value = value

    def push(self, target: float) -> float:
        self.value = target + self._a * (self.value - target)
        return self.value

    def step(self, target: float, snap: float) -> float:
        """push(), landing exactly on the target within `snap`, so a settled stage is recognisable."""
        nxt = target + self._a * (self.value - target)
        self.value = target if abs(nxt - target) <= snap else nxt
        return self.value


class AlignEngine:
    def __init__(self) -> None:
        self.delay = SincDelay()
        self.rotate = rotate_stage.Rotate()
        self._fs = 48000.0
        self._params = Params()
        self._trim = _Smoothed(1.0)
        self._rot = _Smoothed(0.0)
        self._below = _Smoothed(120.0)
        self._pol = LinearFade()
        self._listen = [LinearFade(), LinearFade(), LinearFade()]
        self._latency = 0
        self.ring_in = np.zeros(0)
        self.ring_ref = np.zeros(0)
        self._ring_w = 0
        self._ring_filled = 0

    # -- lifecycle -----------------------------------------------------------------
    def prepare(self, fs: float, max_block: int = 512, params: Params | None = None) -> None:
        self._fs = float(fs)
        if params is not None:
            self._params = params
        max_delay = (DELAY_MAX_MS + max(WINDOW_MS)) * 1e-3 * fs
        self.delay.prepare(fs, max_delay, max_block)
        self.rotate.prepare(fs)
        self._pol.prepare(int(round(POLARITY_FADE_MS * 1e-3 * fs)), 0.0)
        for f in self._listen:
            f.prepare(int(round(LISTEN_FADE_MS * 1e-3 * fs)), 0.0)
        n = int(round(ANALYSIS_SECONDS * fs))
        self.ring_in = np.zeros(n)
        self.ring_ref = np.zeros(n)
        self.set_params(self._params)
        self._trim.prepare(TRIM_TAU_MS, fs, 10.0 ** (self._params.trim_db / 20.0))
        self._control_period = int(np.clip(round(CONTROL_MS * 1e-3 * fs), 1, 32))
        self._rot.prepare(ROTATE_TAU_MS, fs / self._control_period, self._params.rotate_deg)
        self._below.prepare(BELOW_TAU_MS, fs / self._control_period, self._params.below_hz)
        # The Rotate stage learns its bypass state here, before reset(), so a freshly prepared
        # processor starts at the setting it was given instead of fading into it - and so reset()
        # restores exactly what prepare() produced, which is what rule 8 asks of it.
        self.rotate.set_params(self._params.rotate_deg, self._params.below_hz)
        self.reset()

    def reset(self) -> None:
        self.delay.reset()
        self.rotate.reset()
        self._pol.snap(1.0 if self._params.polarity else 0.0)
        for s, f in enumerate(self._listen):
            f.snap(1.0 if s == int(self._params.listen) else 0.0)
        self._rot.value = self._params.rotate_deg
        self._below.value = self._params.below_hz
        self._countdown = 0
        self.ring_in[:] = 0.0
        self.ring_ref[:] = 0.0
        self._ring_w = 0
        self._ring_filled = 0

    # -- parameters ----------------------------------------------------------------
    def set_params(self, p: Params) -> None:
        self._params = p
        self._latency = int(round(p.window_ms * 1e-3 * self._fs))
        clamped = float(np.clip(p.delay_ms, -p.window_ms, DELAY_MAX_MS))
        self.delay.set_delay_samples(self._latency + clamped * 1e-3 * self._fs)

    @property
    def latency_samples(self) -> int:
        return self._latency

    @property
    def clamped_delay_ms(self) -> float:
        return float(np.clip(self._params.delay_ms, -self._params.window_ms, DELAY_MAX_MS))

    # -- audio ---------------------------------------------------------------------
    def _write_rings(self, main: np.ndarray, ref: np.ndarray) -> None:
        n = main.shape[1]
        size = len(self.ring_in)
        idx = (self._ring_w + np.arange(n)) % size
        self.ring_in[idx] = main.mean(axis=0)
        self.ring_ref[idx] = ref.mean(axis=0)
        self._ring_w = int((self._ring_w + n) % size)
        self._ring_filled = min(size, self._ring_filled + n)

    def analysis_frames(self) -> tuple[np.ndarray, np.ndarray]:
        """The last `ANALYSIS_SECONDS` of both buses, oldest first - what Detect is given."""
        size = len(self.ring_in)
        n = self._ring_filled
        idx = (self._ring_w - n + np.arange(n)) % size
        return self.ring_in[idx].copy(), self.ring_ref[idx].copy()

    def process_block(self, main: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """main, ref: (2, n). Returns (2, n). `ref` is the sidechain bus."""
        channels, n = main.shape
        if n == 0:
            return main.copy()
        self._write_rings(main, ref)
        if self._params.bypass:
            return main.copy()

        # polarity, crossfaded (a polarity crossfade passes through silence; that is what a
        # polarity switch is, and it cannot overshoot)
        self._pol.set_target(1.0 if self._params.polarity else 0.0)
        x = main * (1.0 - 2.0 * self._pol.ramp(n))

        x = self.delay.process_block(x)

        x = self._process_rotate(x)

        # Trim, smoothed per sample. The closed form of the one-pole is used so the block size
        # cannot change the result: value_i = target + (v0 - target) * a^(i+1).
        trim_target = 10.0 ** (self._params.trim_db / 20.0)
        a = self._trim._a
        trim = trim_target + (self._trim.value - trim_target) * a ** (np.arange(n) + 1)
        self._trim.value = float(trim[-1])
        x = x * trim

        # Listen: a three-way crossfade so switching never clicks
        target = np.zeros(3)
        target[int(self._params.listen)] = 1.0
        mix = np.empty((3, n))
        for s in range(3):
            self._listen[s].set_target(target[s])
            mix[s] = self._listen[s].ramp(n)
        mono = 0.5 * (x.mean(axis=0) + ref.mean(axis=0))
        out = mix[0] * x + mix[1] * ref + mix[2] * mono[None, :]
        return out

    def _process_rotate(self, x: np.ndarray) -> np.ndarray:
        """Rotate on the control grid; a settled block runs in one piece (AlignEngine.h processRotate)."""
        p, n, period = self._params, x.shape[1], self._control_period
        if (self._rot.value == p.rotate_deg and self._below.value == p.below_hz
                and self.rotate.settled(p.rotate_deg > 0.0)):
            self._countdown = (self._countdown - n) % period
            return self.rotate.process_block(x)
        out = np.empty_like(x)
        at = 0
        while at < n:
            if self._countdown <= 0:
                rot = self._rot.step(p.rotate_deg, SNAP)
                below = self._below.step(p.below_hz, SNAP)
                self.rotate.set_params(rot if p.rotate_deg > 0.0 else 0.0, below)
                self._countdown = period
            k = min(self._countdown, n - at)
            out[:, at:at + k] = self.rotate.process_block(x[:, at:at + k])
            self._countdown -= k
            at += k
        return out

    def render(self, main: np.ndarray, ref: np.ndarray, block: int = 512) -> np.ndarray:
        """Block-wise render of a whole signal, the way the harness drives the processor."""
        n = main.shape[1]
        out = np.empty_like(main)
        at = 0
        while at < n:
            k = min(block, n - at)
            out[:, at:at + k] = self.process_block(main[:, at:at + k], ref[:, at:at + k])
            at += k
        return out
