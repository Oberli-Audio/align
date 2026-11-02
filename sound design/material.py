"""Seeded synthetic test material for Align (G2).

The real material - a multi-mic drum loop, a DI/amp pair, a room pair with 1.2 s RT60 - lives in
OneDrive, not in git (CLAUDE.md). Everything here is generated from a seed so the prototype, the
harness and the test suite all measure the same signals on any machine, and so a number in
docs/status.md can be reproduced from the command beside it.

Each pair function returns (ref, trk, truth) where `ref` is the reference mic, `trk` is the mic to
align, and `truth` carries the delay in ms that Detect has to find and whether the polarity is
flipped. Positive `delay_ms` in `truth` means *the track is later than the reference by that much*,
so the Delay the plugin has to apply is its negative (docs/status.md, G1 sign convention).
"""

from __future__ import annotations

import numpy as np

SPEED_OF_SOUND = 343.0  # m/s at 20 C; the readout's distance uses this constant


# ---------------------------------------------------------------- exact fractional shift
def fractional_shift(x: np.ndarray, delay_samples: float) -> np.ndarray:
    """Shift `x` later by `delay_samples` (may be fractional) with a full-band FFT phase ramp.

    This is the *truth* generator, not the product's interpolator: it is exact to numerical
    precision for a band-limited signal, which is what makes "found within 0.02 ms" a statement
    about the detector rather than about the test rig. The product's own fractional delay is
    sinc_delay.SincDelay and is measured against this.
    """
    n = len(x)
    m = 1 << int(np.ceil(np.log2(n * 2)))
    spec = np.fft.rfft(x, m)
    freqs = np.fft.rfftfreq(m, d=1.0)  # cycles per sample
    spec *= np.exp(-2j * np.pi * freqs * delay_samples)
    return np.fft.irfft(spec, m)[:n]


# ---------------------------------------------------------------- building blocks
def _one_pole_lp(x: np.ndarray, fc: float, fs: float) -> np.ndarray:
    a = np.exp(-2.0 * np.pi * fc / fs)
    y = np.empty_like(x)
    s = 0.0
    for i, v in enumerate(x):
        s = (1.0 - a) * v + a * s
        y[i] = s
    return y


def _tilt(x: np.ndarray, fs: float, fc: float, low_gain: float, high_gain: float) -> np.ndarray:
    """A first-order subtractive split with a gain per band: a cheap stand-in for mic colouration."""
    low = _one_pole_lp(x, fc, fs)
    return low_gain * low + high_gain * (x - low)


def _room_ir(rng: np.random.Generator, fs: float, rt60: float, pre_delay_ms: float,
             n_early: int = 12) -> np.ndarray:
    """Early reflections plus an exponentially decaying noise tail - enough to smear a correlation
    peak the way a real room does, which is the only property the detector is tested against."""
    length = int(fs * (rt60 * 1.2 + 0.05))
    ir = np.zeros(length)
    ir[0] = 1.0
    start = int(pre_delay_ms * 1e-3 * fs)
    for _ in range(n_early):
        at = start + int(rng.uniform(0.0, 0.04) * fs)
        if at < length:
            ir[at] += rng.uniform(-0.6, 0.6)
    tail_from = int(0.02 * fs)
    t = np.arange(length - tail_from) / fs
    ir[tail_from:] += rng.normal(0.0, 1.0, length - tail_from) * 0.35 * np.exp(-6.9078 * t / rt60)
    return ir / np.max(np.abs(ir))


def _convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    return np.convolve(x, ir)[: len(x)]


# ---------------------------------------------------------------- sources
def drum_loop(fs: float, seed: int, bars: int = 4, bpm: float = 120.0) -> np.ndarray:
    """A seeded drum loop: kick, snare, closed hats, 4/4. Not musical, but it has the three things
    the detector needs - broadband transients, a tonal low end, and repetition at a known period
    (repetition is what produces the second correlation peak that confidence is measured against).
    """
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    n = int(fs * beat * 4 * bars) + int(0.5 * fs)
    out = np.zeros(n)

    def place(at_s: float, sig: np.ndarray, gain: float) -> None:
        at = int(at_s * fs)
        end = min(n, at + len(sig))
        if end > at:
            out[at:end] += gain * sig[: end - at]

    def kick() -> np.ndarray:
        t = np.arange(int(0.30 * fs)) / fs
        f = 55.0 + 95.0 * np.exp(-t / 0.018)
        body = np.sin(2 * np.pi * np.cumsum(f) / fs) * np.exp(-t / 0.085)
        click = rng.normal(0, 1, len(t)) * np.exp(-t / 0.0015) * 0.25
        return body + click

    def snare() -> np.ndarray:
        t = np.arange(int(0.22 * fs)) / fs
        tone = (np.sin(2 * np.pi * 185.0 * t) + 0.7 * np.sin(2 * np.pi * 330.0 * t)) * np.exp(-t / 0.05)
        noise = rng.normal(0, 1, len(t)) * np.exp(-t / 0.075)
        return 0.45 * tone + 0.8 * _tilt(noise, fs, 2000.0, 0.4, 1.0)

    def hat() -> np.ndarray:
        t = np.arange(int(0.06 * fs)) / fs
        noise = rng.normal(0, 1, len(t)) * np.exp(-t / 0.012)
        return 0.5 * _tilt(noise, fs, 6000.0, 0.08, 1.0)

    k, s, h = kick(), snare(), hat()
    for bar in range(bars):
        t0 = bar * beat * 4
        for b in (0, 2):
            place(t0 + b * beat, k, 0.9 * rng.uniform(0.92, 1.0))
        for b in (1, 3):
            place(t0 + b * beat, s, 0.7 * rng.uniform(0.9, 1.0))
        for i in range(8):
            place(t0 + i * beat / 2, h, 0.35 * rng.uniform(0.7, 1.0))
    return out / (np.max(np.abs(out)) + 1e-12) * 0.7


def bass_di(fs: float, seed: int, seconds: float = 4.0) -> np.ndarray:
    """A plucked bass line: a tonal, low-register source, the hardest case for a correlator that is
    not whitened (its autocorrelation has strong peaks one period apart)."""
    rng = np.random.default_rng(seed)
    n = int(fs * seconds)
    out = np.zeros(n)
    notes = [41.2, 55.0, 61.7, 49.0, 41.2, 73.4, 55.0, 49.0]  # E1 .. D2
    step = seconds / len(notes)
    for i, f0 in enumerate(notes):
        t = np.arange(int(step * fs * 1.1)) / fs
        env = np.exp(-t / (step * 0.55))
        sig = np.zeros_like(t)
        for h in range(1, 13):
            sig += (1.0 / h ** 1.35) * np.sin(2 * np.pi * f0 * h * t + rng.uniform(0, 2 * np.pi))
        at = int(i * step * fs)
        end = min(n, at + len(sig))
        out[at:end] += (sig * env)[: end - at]
    return out / (np.max(np.abs(out)) + 1e-12) * 0.7


# ---------------------------------------------------------------- pairs
def _finish(ref: np.ndarray, trk: np.ndarray, fs: float, delay_ms: float, invert: bool,
            seed: int, noise_dbfs: float = -46.0) -> tuple[np.ndarray, np.ndarray, dict]:
    rng = np.random.default_rng(seed + 977)
    trk = fractional_shift(trk, delay_ms * 1e-3 * fs)
    if invert:
        trk = -trk
    g = 10.0 ** (noise_dbfs / 20.0)
    ref = ref + rng.normal(0, g, len(ref))      # independent noise in each mic: the pair is never
    trk = trk + rng.normal(0, g, len(trk))      # a perfect match, so confidence means something
    return (ref.astype(np.float64), trk.astype(np.float64),
            {"delay_ms": delay_ms, "inverted": bool(invert), "fs": fs})


def drum_loop_pair(fs: float, seed: int = 1, delay_ms: float = 2.317,
                   invert: bool = True) -> tuple[np.ndarray, np.ndarray, dict]:
    """Kick-in against overheads: the brief's accuracy case (within 0.02 ms, confidence > 80 %)."""
    loop = drum_loop(fs, seed)
    overheads = _tilt(loop, fs, 400.0, 0.55, 1.0)
    kick_in = _tilt(loop, fs, 180.0, 1.0, 0.25)
    return _finish(overheads, kick_in, fs, delay_ms, invert, seed)


def _diffuse_partner(rng: np.random.Generator, tail: np.ndarray, fs: float,
                     rho_low: float = 0.7, rho_high: float = 0.15,
                     split_hz: float = 300.0) -> np.ndarray:
    """A second microphone's reverberant tail in the *same* room.

    Two mics a metre or two apart in one room do not hear independent reverb: the spatial coherence
    of a diffuse field is high at low frequencies and falls off with frequency (sinc(kd)). Modelling
    the second tail as `rho * first + sqrt(1 - rho^2) * independent` per band, rather than drawing
    a second independent room, is what makes the brief's 0.1 ms target on a reverberant pair a test
    of the detector instead of a test of an impossible signal: with two independent rooms the only
    correlated part is the direct sound, and no estimator can do better than its share of the
    energy.
    """
    other = rng.normal(0.0, float(np.std(tail)), len(tail))
    tail_low = _one_pole_lp(tail, split_hz, fs)
    other_low = _one_pole_lp(other, split_hz, fs)
    low = rho_low * tail_low + np.sqrt(max(0.0, 1.0 - rho_low ** 2)) * other_low
    high = (rho_high * (tail - tail_low)
            + np.sqrt(max(0.0, 1.0 - rho_high ** 2)) * (other - other_low))
    return low + high


def room_pair(fs: float, seed: int = 2, delay_ms: float = 2.317,
              rt60: float = 1.2, invert: bool = False) -> tuple[np.ndarray, np.ndarray, dict]:
    """A room pair with 1.2 s RT60: the brief's reverberant case (within 0.1 ms).

    One source, one room, two positions: the direct sound is shared, the early reflections differ,
    and the late tail is coherent at low frequencies and nearly independent at high ones.
    """
    rng = np.random.default_rng(seed)
    loop = drum_loop(fs, seed)
    ir_a = _room_ir(rng, fs, rt60, pre_delay_ms=8.0)
    tail_from = int(0.02 * fs)
    ir_b = ir_a.copy()
    # different early reflections at the second position
    ir_b[:tail_from] = _room_ir(rng, fs, rt60, pre_delay_ms=11.0)[:tail_from]
    ir_b[tail_from:] = _diffuse_partner(rng, ir_a[tail_from:], fs)
    a = _convolve(loop, ir_a)
    b = _convolve(loop, ir_b)
    peak = max(np.max(np.abs(a)), np.max(np.abs(b))) + 1e-12
    return _finish(a / peak * 0.7, b / peak * 0.7, fs, delay_ms, invert, seed)


def di_amp_pair(fs: float, seed: int = 3, delay_ms: float = 1.104,
                invert: bool = False) -> tuple[np.ndarray, np.ndarray, dict]:
    """Bass DI against an amp mic: tonal and low, where a whitened correlator earns its keep."""
    rng = np.random.default_rng(seed)
    di = bass_di(fs, seed)
    cab = _room_ir(rng, fs, 0.12, pre_delay_ms=1.5, n_early=5)
    amp = _tilt(_convolve(di, cab), fs, 1200.0, 1.0, 0.18)
    amp = amp / (np.max(np.abs(amp)) + 1e-12) * 0.7
    return _finish(di, amp, fs, delay_ms, invert, seed)


def pink_noise(fs: float, seconds: float, seed: int = 7) -> np.ndarray:
    """Paul Kellet's pink approximation, the same one the harness's --signal=noise:pink uses."""
    rng = np.random.default_rng(seed)
    w = rng.uniform(-1.0, 1.0, int(fs * seconds)).astype(np.float64)
    b0 = b1 = b2 = 0.0
    out = np.empty_like(w)
    for i, v in enumerate(w):
        b0 = 0.99765 * b0 + v * 0.0990460
        b1 = 0.96300 * b1 + v * 0.2965164
        b2 = 0.57000 * b2 + v * 1.0526913
        out[i] = 0.18 * (b0 + b1 + b2 + v * 0.1848)
    return out
