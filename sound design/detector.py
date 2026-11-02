"""Detect: GCC-PHAT delay and polarity, and the Rotate suggestion (G1 decision 1).

Mirrors Source/dsp/Detector.h/.cpp, which runs on the detect worker thread and owns every buffer
it uses (allocated in prepareToPlay, never on the audio thread).

Sign convention, fixed here once and asserted by a test: with `ref` the reference mic and `trk` the
track being aligned, `r = ifft(fft(ref) * conj(fft(trk)))` peaks at lag `k = -tau` when the track is
later than the reference by `tau`. The Delay the plugin must apply to line them up is exactly that
lag, so **the refined peak lag in milliseconds is the Delay value**, with no sign flip anywhere
between the detector and the parameter.

The Rotate suggestion never filters anything. Because the Rotate stage is an all-pass, the Pearson
correlation of the rotated track against the reference over a band is

    corr(th, below) = Re( sum_k C_k * exp(-i * phase_k(th, below)) ) / sqrt(sum|R|^2 * sum|T|^2)

with `C_k = R_k conj(T_k)` over the band's bins: one cross-spectrum, then a sum per grid point.
The phase comes from rotate.phase_response, the same formula the audio and the editor's curve use,
so a suggestion can never disagree with what applying it does (rule 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import rotate as rotate_stage
from material import SPEED_OF_SOUND

# -- constants, documented beside the code (G4 port rule) ------------------------------
BAND_LO_HZ = 60.0         # below this a mic carries rumble, not information
BAND_HI_HZ = 8000.0       # above this the pair decorrelates on anything but a close pair
WHITEN_BETA = 1.0         # partial whitening: S / |S|^beta. 1.0 is full PHAT, 0.0 plain
                          # cross-correlation. Full PHAT weights every bin equally, which is what
                          # sharpens the peak on tonal and reverberant material - and also what
                          # amplifies bins holding nothing but an uncorrelated reverb tail. The
                          # value is set by the G2 whiten sweep (prototype.py --check whiten),
                          # not by taste: 1.0 measured best on all three pairs at once, and below
                          # 0.7 the bass DI/amp pair locks onto the wrong period of the note and
                          # misses by 14 ms - the failure the G1 trade-off paragraph predicted.
WHITEN_EPS = 1.0e-3       # regularisation, relative to the mean cross-spectrum magnitude in band
TAPER_ALPHA = 0.1         # Tukey taper on both frames, so the frame edges do not ring
SECOND_PEAK_GUARD_MS = 1.0  # the second peak must be at least this far from the first
SILENCE_DBFS = -60.0      # a reference quieter than this over the whole frame is "silent"
ROTATE_BAND_HI_HZ = 300.0   # the band the Rotate suggestion is fitted over (sketch 4.2)
ROTATE_GRID_DEG = np.arange(0.0, 181.0, 2.0)
ROTATE_GRID_BELOW_HZ = (60.0, 80.0, 110.0, 150.0, 200.0)
ROTATE_MIN_GAIN = 0.05    # the suggestion is only shown if it buys at least this much correlation
ROTATE_OTHER_MIC_MIN_GAIN = 0.15  # the bar for "put Align on the other mic" is higher than for a
                          # suggestion the user accepts with one button: re-routing a session is a
                          # bigger ask than Apply, so it has to be worth more than a marginal gain


@dataclass
class RotateSuggestion:
    needed: bool
    rotate_deg: float = 0.0
    below_hz: float = 0.0
    corr_before: float = 0.0
    corr_after: float = 0.0
    other_mic: bool = False       # a rotation would help, but only in the direction Rotate cannot
    other_mic_gain: float = 0.0   # produce: it can make this track's low end later, never earlier

    def words(self) -> str:
        if self.other_mic:
            return ("Rotate cannot help here: this track's low end is late. "
                    "Put Align on the reference mic instead")
        if not self.needed:
            return "No rotation needed"
        return (f"Detect suggests {self.rotate_deg:.0f}° below {self.below_hz:.0f} Hz"
                f" · correlation below {ROTATE_BAND_HI_HZ:.0f} Hz"
                f" {self.corr_before:.2f} → {self.corr_after:.2f}")


@dataclass
class DetectResult:
    ok: bool
    reason: str = ""
    delay_ms: float = 0.0
    inverted: bool = False
    confidence_pct: float = 0.0
    distance_cm: float = 0.0
    peak: float = 0.0
    second_peak: float = 0.0
    curve: np.ndarray = field(default_factory=lambda: np.zeros(0))
    curve_lags_ms: np.ndarray = field(default_factory=lambda: np.zeros(0))
    suggestion: RotateSuggestion = field(default_factory=lambda: RotateSuggestion(False))

    def words(self) -> str:
        """The readout the brief asks for, in words, with the distance (defining feature 3)."""
        if not self.ok:
            return self.reason
        sign = "+" if self.delay_ms >= 0 else "−"
        pol = "polarity flipped" if self.inverted else "polarity matched"
        low = "low confidence " if self.confidence_pct < 50.0 else "confidence "
        tail = ": play a louder section" if self.confidence_pct < 50.0 else ""
        return (f"Peak {sign}{abs(self.delay_ms):.2f} ms · {self.distance_cm:.0f} cm · "
                f"{pol} · {low}{self.confidence_pct:.0f} %{tail}")


def search_range_ms(window_ms: float) -> tuple[float, float]:
    """[-Window, +max(Window, 20 ms)]: the range the current Window can actually apply
    (docs/status.md, G1 decision 6). A positive delay costs buffer, not latency."""
    return -window_ms, max(window_ms, 20.0)


def _tukey(n: int, alpha: float) -> np.ndarray:
    if alpha <= 0.0 or n < 4:
        return np.ones(n)
    w = np.ones(n)
    edge = int(alpha * (n - 1) / 2.0)
    if edge < 1:
        return w
    t = np.arange(edge)
    ramp = 0.5 * (1.0 - np.cos(np.pi * t / edge))
    w[:edge] = ramp
    w[n - edge:] = ramp[::-1]
    return w


def _parabolic(y_minus: float, y_zero: float, y_plus: float) -> tuple[float, float]:
    """Vertex offset in samples and vertex value of the parabola through three points."""
    denom = y_minus - 2.0 * y_zero + y_plus
    if denom == 0.0:
        return 0.0, y_zero
    delta = 0.5 * (y_minus - y_plus) / denom
    delta = float(np.clip(delta, -1.0, 1.0))
    value = y_zero - 0.25 * (y_minus - y_plus) * delta
    return delta, value


def detect(ref: np.ndarray, trk: np.ndarray, fs: float, window_ms: float = 20.0,
           with_suggestion: bool = True, beta: float = WHITEN_BETA) -> DetectResult:
    n = int(min(len(ref), len(trk)))
    if n < int(0.25 * fs):
        return DetectResult(False, "Not enough audio yet")
    a = np.asarray(ref[-n:], dtype=np.float64)
    b = np.asarray(trk[-n:], dtype=np.float64)

    rms_db = 20.0 * np.log10(np.sqrt(np.mean(a * a)) + 1e-30)
    if rms_db < SILENCE_DBFS:
        return DetectResult(False, "Reference is silent")

    taper = _tukey(n, TAPER_ALPHA)
    a = (a - a.mean()) * taper
    b = (b - b.mean()) * taper

    m = 1 << int(np.ceil(np.log2(2 * n)))
    spec_a = np.fft.rfft(a, m)
    spec_b = np.fft.rfft(b, m)
    cross = spec_a * np.conj(spec_b)

    freqs = np.fft.rfftfreq(m, d=1.0 / fs)
    band = (freqs >= BAND_LO_HZ) & (freqs <= min(BAND_HI_HZ, 0.49 * fs))
    if not band.any():
        return DetectResult(False, "Sample rate leaves no analysis band")

    whitened = np.zeros_like(cross)
    mag = np.abs(cross[band])
    eps = WHITEN_EPS * (mag.mean() + 1e-30)
    whitened[band] = cross[band] / np.power(mag + eps, beta)
    corr = np.fft.irfft(whitened, m)

    lo_ms, hi_ms = search_range_ms(window_ms)
    lo = int(np.floor(lo_ms * 1e-3 * fs))
    hi = int(np.ceil(hi_ms * 1e-3 * fs))
    lags = np.arange(lo, hi + 1)
    values = corr[lags % m]
    if len(lags) < 3:
        return DetectResult(False, "Search window is empty")

    k = int(np.argmax(np.abs(values)))
    k = int(np.clip(k, 1, len(values) - 2))
    # the parabola is fitted to the magnitudes and the sign is taken from the peak sample, so an
    # inverted pair reads as a downward peak and the curve the editor draws shows the flip
    # directly rather than inferring it (defining feature 1)
    sign = 1.0 if values[k] >= 0.0 else -1.0
    delta, magnitude = _parabolic(abs(values[k - 1]), abs(values[k]), abs(values[k + 1]))
    vertex = sign * magnitude
    refined_lag = lags[k] + delta
    delay_ms = refined_lag / fs * 1e3

    guard = max(1, int(SECOND_PEAK_GUARD_MS * 1e-3 * fs))
    mask = np.abs(lags - lags[k]) > guard
    second = float(np.max(np.abs(values[mask]))) if mask.any() else 0.0
    peak = abs(float(vertex))
    confidence = 0.0 if peak <= 0.0 else float(np.clip((peak - second) / peak * 100.0, 0.0, 100.0))

    result = DetectResult(
        ok=True,
        delay_ms=float(delay_ms),
        inverted=bool(vertex < 0.0),
        confidence_pct=confidence,
        distance_cm=abs(float(delay_ms)) * 1e-3 * SPEED_OF_SOUND * 100.0,
        peak=peak,
        second_peak=second,
        curve=values.copy(),
        curve_lags_ms=lags / fs * 1e3,
    )
    if with_suggestion:
        result.suggestion = suggest_rotate(a, b, fs, result.delay_ms, result.inverted)
    return result


def low_band_correlation(ref: np.ndarray, trk: np.ndarray, fs: float,
                         hi_hz: float = ROTATE_BAND_HI_HZ) -> float:
    """Pearson correlation of the two signals restricted to [BAND_LO_HZ / 3, hi_hz], via Parseval.
    The editor's correlation meter is the wideband version of this."""
    n = int(min(len(ref), len(trk)))
    m = 1 << int(np.ceil(np.log2(2 * n)))
    spec_r = np.fft.rfft(np.asarray(ref[-n:], dtype=np.float64), m)
    spec_t = np.fft.rfft(np.asarray(trk[-n:], dtype=np.float64), m)
    freqs = np.fft.rfftfreq(m, d=1.0 / fs)
    band = (freqs >= BAND_LO_HZ / 3.0) & (freqs <= hi_hz)
    num = float(np.real(np.sum(spec_r[band] * np.conj(spec_t[band]))))
    den = float(np.sqrt(np.sum(np.abs(spec_r[band]) ** 2) * np.sum(np.abs(spec_t[band]) ** 2)))
    return 0.0 if den <= 0.0 else num / den


def suggest_rotate(ref: np.ndarray, trk: np.ndarray, fs: float, delay_ms: float,
                   inverted: bool) -> RotateSuggestion:
    """Grid search over (Rotate, Below) on the already delay- and polarity-aligned pair.

    The search is a sum over the cross-spectrum's low-band bins, not a filtering pass, because the
    stage is an all-pass: rotating the track cannot change its norm, only the real part of the
    inner product (see the module docstring).
    """
    n = int(min(len(ref), len(trk)))
    m = 1 << int(np.ceil(np.log2(2 * n)))
    spec_r = np.fft.rfft(np.asarray(ref[-n:], dtype=np.float64), m)
    spec_t = np.fft.rfft(np.asarray(trk[-n:], dtype=np.float64), m)

    freqs = np.fft.rfftfreq(m, d=1.0 / fs)
    # apply the found delay and polarity to the track's spectrum: both are exact in this domain.
    # Shifting a signal later by d seconds multiplies its spectrum by exp(-2i pi f d), and
    # `delay_ms` already is the Delay the plugin will apply, so the sign needs no flip.
    spec_t = spec_t * np.exp(-2j * np.pi * freqs * (delay_ms * 1e-3))
    if inverted:
        spec_t = -spec_t

    band = (freqs >= BAND_LO_HZ / 3.0) & (freqs <= ROTATE_BAND_HI_HZ)
    if not band.any():
        return RotateSuggestion(False)
    cross = spec_r[band] * np.conj(spec_t[band])
    den = float(np.sqrt(np.sum(np.abs(spec_r[band]) ** 2) * np.sum(np.abs(spec_t[band]) ** 2)))
    if den <= 0.0:
        return RotateSuggestion(False)
    band_freqs = freqs[band]

    before = float(np.real(np.sum(cross))) / den
    best = (before, 0.0, 0.0)
    best_opposite = before
    for below in ROTATE_GRID_BELOW_HZ:
        for theta in ROTATE_GRID_DEG:
            if theta == 0.0:
                continue
            phase = rotate_stage.phase_response(band_freqs, float(theta), float(below), fs)
            value = float(np.real(np.sum(cross * np.exp(-1j * phase)))) / den
            if value > best[0]:
                best = (value, float(theta), float(below))
            # the same grid in the direction the stage cannot produce: Rotate can only make this
            # track's low end later, never earlier (docs/status.md, G1 decision 3). When only that
            # direction helps, the fix is to put Align on the other mic of the pair, and saying so
            # is more use than "No rotation needed".
            opposite = float(np.real(np.sum(cross * np.exp(1j * phase)))) / den
            best_opposite = max(best_opposite, opposite)
    after, theta, below = best
    if after - before >= ROTATE_MIN_GAIN:
        return RotateSuggestion(True, theta, below, before, after,
                                other_mic_gain=best_opposite - before)
    if best_opposite - before >= ROTATE_OTHER_MIC_MIN_GAIN:
        return RotateSuggestion(False, corr_before=before, corr_after=before, other_mic=True,
                                other_mic_gain=best_opposite - before)
    return RotateSuggestion(False, corr_before=before, corr_after=before,
                            other_mic_gain=best_opposite - before)
