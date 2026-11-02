#!/usr/bin/env python3
"""Align - the G2 prototype and its programmatic checks.

The brief's track is "effect" with an analysis stage, so G2's prototype is numpy, not Faust
(sound-design-bob F.15.1, the per-track gate table: "Faust; a numpy model for STFT/spectral
effects" for E, "a numpy/scipy reference implementation of the standard" for A). Every module here
is in the structure the C++ port will use, so G5 can null the port against it:

    material.py     seeded test material and the exact fractional shift that defines the truth
    sinc_delay.py   the fractional delay line           -> Source/dsp/SincDelay.h
    rotate.py       the low-end phase rotation          -> Source/dsp/Rotate.h
    detector.py     GCC-PHAT and the Rotate suggestion  -> Source/dsp/Detector.h
    engine.py       the audio path and the rings        -> Source/dsp/AlignEngine.h

Usage:
    python3 "sound design/prototype.py" --all --seed 1
    python3 "sound design/prototype.py" --kernel-search      # the G3 kernel constants
Writes sound design/g2.json (every number, with the check that produced it) and
sound design/renders/*.wav (the reference renders G5 nulls the port against).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from scipy.io import wavfile

import detector
import material
import rotate as rotate_stage
import sinc_delay
from engine import AlignEngine, Params

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERS = os.path.join(HERE, "renders")
RATES = (44100.0, 48000.0, 88200.0, 96000.0, 176400.0, 192000.0)


# ---------------------------------------------------------------- helpers
def db(x: float) -> float:
    return -300.0 if x <= 0.0 else float(20.0 * np.log10(x))


def max_click_db(x: np.ndarray) -> float:
    """The harness contract's definition: the largest sample-to-sample step over the render's peak.
    Absolute, so it compares across settings. A clean 1 kHz sine at 48 kHz reads about -17.7 dB; a
    discontinuity reads between -6 and +6 dB."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    step = float(np.max(np.abs(np.diff(x, axis=-1)))) if x.shape[-1] > 1 else 0.0
    return -300.0 if peak <= 0.0 or step <= 0.0 else float(20.0 * np.log10(step / peak))


def peak_db(x: np.ndarray) -> float:
    return db(float(np.max(np.abs(x))) if x.size else 0.0)


def rms_db(x: np.ndarray) -> float:
    return db(float(np.sqrt(np.mean(x * x))) if x.size else 0.0)


def stereo(x: np.ndarray) -> np.ndarray:
    return np.vstack([x, x])


def write_wav(name: str, fs: float, data: np.ndarray) -> str:
    os.makedirs(RENDERS, exist_ok=True)
    path = os.path.join(RENDERS, name)
    wavfile.write(path, int(fs), np.ascontiguousarray(data.T.astype(np.float32)))
    return os.path.relpath(path, os.path.dirname(HERE))


# ---------------------------------------------------------------- checks
def check_rotate_structure(fs: float = 48000.0) -> dict:
    """The TPT cascade is the filter the analytic formula says it is, and nothing else.

    Three claims are checked rather than assumed: the time-domain cascade's measured phase matches
    rotate.phase_response (so the editor's curve and the audio agree, rule 9); the magnitude is
    flat (so Rotate changes phase only); and the phase at Below is exactly the set angle.
    """
    out = {"max_phase_error_deg": 0.0, "max_magnitude_error_db": 0.0,
           "max_angle_error_at_below_deg": 0.0, "per_angle": []}
    n = 1 << 16
    imp = np.zeros((2, n))
    imp[:, 0] = 1.0
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    audible = (freqs >= 20.0) & (freqs <= 20000.0)
    for below in (60.0, 120.0, 300.0, 1000.0):
        for theta in (1.0, 15.0, 48.0, 90.0, 135.0, 180.0):
            stage = rotate_stage.Rotate()
            stage.prepare(fs)
            stage.set_params(theta, below)
            stage.fade.snap(1.0)                      # measure the stage itself, not the crossfade
            y = stage.process_block(imp.copy())
            spec = np.fft.rfft(y[0], n)
            measured = np.unwrap(np.angle(spec))
            expected = rotate_stage.phase_response(freqs, theta, below, fs)
            band = audible & (freqs <= 0.45 * fs)
            phase_err = np.max(np.abs(np.angle(np.exp(1j * (measured[band] - expected[band])))))
            mag_err = np.max(np.abs(20.0 * np.log10(np.abs(spec[band]) + 1e-300)))
            at_below = np.interp(below, freqs, np.rad2deg(expected))
            angle_err = abs(at_below + theta)
            out["per_angle"].append({
                "below_hz": below, "rotate_deg": theta,
                "phase_error_deg": float(np.rad2deg(phase_err)),
                "magnitude_error_db": float(mag_err),
                "angle_at_below_deg": float(at_below),
            })
            out["max_phase_error_deg"] = max(out["max_phase_error_deg"], float(np.rad2deg(phase_err)))
            out["max_magnitude_error_db"] = max(out["max_magnitude_error_db"], float(mag_err))
            out["max_angle_error_at_below_deg"] = max(out["max_angle_error_at_below_deg"],
                                                      float(angle_err))
    # the fast realisation the prototype renders with must be the TPT one the port will use
    n2 = 1 << 13
    x = np.random.default_rng(0).normal(0.0, 0.3, (2, n2))
    runs = {}
    for fast in (False, True):
        rotate_stage.FAST = fast
        st = rotate_stage.Rotate()
        st.prepare(fs)
        st.set_params(48.0, 120.0)
        st.fade.snap(1.0)
        y = np.empty_like(x)
        for at in range(0, n2, 256):
            y[:, at:at + 256] = st.process_block(x[:, at:at + 256].copy())
        runs[fast] = y
    rotate_stage.FAST = True
    out["tpt_vs_direct_form_peak_dbfs"] = peak_db(runs[True] - runs[False]) - peak_db(x)
    out["pass"] = (out["max_magnitude_error_db"] < 0.05
                   and out["max_phase_error_deg"] < 1.0
                   and out["max_angle_error_at_below_deg"] < 1.0
                   and out["tpt_vs_direct_form_peak_dbfs"] < -140.0)
    return out


def kernel_search(target_db: float = 0.05) -> dict:
    """Choose TAPS, KAISER_BETA and CUTOFF against the brief's response_error_db.

    The target is "flat within 0.05 dB to 18 kHz". 18 kHz is 0.75 of Nyquist at 48 kHz and 0.816 at
    44.1 kHz, so the harder rate decides. The smallest table that clears both wins; ties go to the
    shorter kernel, because the taps are the audio thread's cost.
    """
    fracs = np.linspace(0.0, 1.0, 17)
    results = []
    for taps in (32, 48, 64):
        for beta in (6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0):
            for cutoff in (0.85, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98, 1.0):
                table = sinc_delay.design_kernels(taps, 256, beta, cutoff)
                rows = np.round(fracs * 256).astype(int)
                worst = 0.0
                worst_rate = None
                for fs in (44100.0, 48000.0):
                    freqs = np.linspace(20.0, 18000.0, 400)
                    resp = sinc_delay.kernel_response(table[rows], fs, freqs)
                    err = float(np.max(np.abs(20.0 * np.log10(np.abs(resp) + 1e-300))))
                    if err > worst:
                        worst, worst_rate = err, fs
                results.append({"taps": taps, "beta": beta, "cutoff": cutoff,
                                "max_error_db": worst, "worst_rate": worst_rate})
    ok = [r for r in results if r["max_error_db"] <= target_db]
    ok.sort(key=lambda r: (r["taps"], r["max_error_db"]))
    best = ok[0] if ok else min(results, key=lambda r: r["max_error_db"])
    return {"target_db": target_db, "chosen": best, "candidates_passing": len(ok),
            "current": {"taps": sinc_delay.TAPS, "beta": sinc_delay.KAISER_BETA,
                        "cutoff": sinc_delay.CUTOFF}}


def check_delay_response(fs: float = 48000.0, delay_ms: float = 0.37) -> dict:
    """The brief's response_error_db: an impulse through a 0.37 ms delay, FFT, flatness to 18 kHz.

    0.37 ms is 17.8 samples at 48 kHz, above MIN_SINC_SAMPLES, so this measures the sinc path - the
    one every window except "0 (live)" uses.
    """
    n = 1 << 15
    line = sinc_delay.SincDelay()
    line.prepare(fs, 4096.0, max_block=1024)
    line.set_delay_samples(delay_ms * 1e-3 * fs)
    line.reset()                                   # start at the delay, so no crossfade is measured
    imp = np.zeros((2, n))
    imp[:, 0] = 1.0
    y = line.process_block(imp)
    spec = np.fft.rfft(y[0], n)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    band = (freqs >= 20.0) & (freqs <= 18000.0)
    mag = 20.0 * np.log10(np.abs(spec[band]) + 1e-300)
    group = -np.gradient(np.unwrap(np.angle(spec)), freqs * 2.0 * np.pi)
    low = (freqs >= 100.0) & (freqs <= 10000.0)
    return {
        "delay_ms": delay_ms, "sample_rate": fs,
        "max_error_db": float(np.max(np.abs(mag))),
        "measured_delay_ms": float(np.median(group[low]) * 1e3),
        "delay_error_ms": float(abs(np.median(group[low]) * 1e3 - delay_ms)),
        "pass": bool(np.max(np.abs(mag)) < 0.05),
    }


def check_accuracy(seed: int = 1) -> dict:
    """The brief's accuracy targets, on each pair, at every supported rate for the drum loop."""
    cases = []
    for fs in RATES:
        ref, trk, truth = material.drum_loop_pair(fs, seed)
        res = detector.detect(ref, trk, fs, window_ms=20.0, with_suggestion=False)
        cases.append({"case": "drum_loop", "sample_rate": fs,
                      "truth_delay_ms": truth["delay_ms"], "truth_inverted": truth["inverted"],
                      "expected_delay_ms": -truth["delay_ms"],
                      "found_delay_ms": res.delay_ms, "error_ms": abs(res.delay_ms + truth["delay_ms"]),
                      "found_inverted": res.inverted, "confidence_pct": res.confidence_pct,
                      "tolerance_ms": 0.02, "words": res.words()})
    # The brief names two tolerances: 0.02 ms on the drum loop and 0.1 ms on the reverberant pair.
    # The DI/amp pair is a third case and takes the reverberant tolerance, because the two signals
    # differ by a cabinet's impulse response and not only by a delay: the best overall alignment of
    # a filtered pair is legitimately a few hundredths of a millisecond from the applied shift.
    for name, fn, tol, window in (("room_1v2s", material.room_pair, 0.1, 20.0),
                                  ("di_amp", material.di_amp_pair, 0.1, 20.0)):
        fs = 48000.0
        ref, trk, truth = fn(fs)
        res = detector.detect(ref, trk, fs, window_ms=window, with_suggestion=False)
        cases.append({"case": name, "sample_rate": fs,
                      "truth_delay_ms": truth["delay_ms"], "truth_inverted": truth["inverted"],
                      "expected_delay_ms": -truth["delay_ms"],
                      "found_delay_ms": res.delay_ms, "error_ms": abs(res.delay_ms + truth["delay_ms"]),
                      "found_inverted": res.inverted, "confidence_pct": res.confidence_pct,
                      "tolerance_ms": tol, "words": res.words()})
    for c in cases:
        c["pass"] = bool(c["error_ms"] <= c["tolerance_ms"]
                         and c["found_inverted"] == c["truth_inverted"])
    drum = [c for c in cases if c["case"] == "drum_loop"]
    return {"cases": cases,
            "drum_loop_min_confidence_pct": min(c["confidence_pct"] for c in drum),
            "pass": all(c["pass"] for c in cases)
                    and min(c["confidence_pct"] for c in drum) > 80.0}


def check_whiten(fs: float = 48000.0, seed: int = 1) -> dict:
    """Choose detector.WHITEN_BETA by measurement, across all three pairs at once.

    Full PHAT (beta = 1) is the textbook answer and the sharpest peak on tonal material, but it
    weights a bin holding only an uncorrelated reverb tail as heavily as one holding the direct
    sound, which is exactly the reverberant case. The winner is the largest beta that clears every
    pair's tolerance, because a larger beta is the sharper peak when it works.
    """
    pairs = [("drum_loop", material.drum_loop_pair(fs, seed), 0.02),
             ("room_1v2s", material.room_pair(fs), 0.1),
             ("di_amp", material.di_amp_pair(fs), 0.1)]
    rows = []
    for beta in (0.0, 0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0):
        row = {"beta": beta, "cases": {}, "all_pass": True}
        for name, (ref, trk, truth), tol in pairs:
            res = detector.detect(ref, trk, fs, window_ms=20.0, with_suggestion=False, beta=beta)
            err = abs(res.delay_ms + truth["delay_ms"])
            ok = bool(err <= tol and res.inverted == truth["inverted"])
            row["cases"][name] = {"error_ms": err, "confidence_pct": res.confidence_pct,
                                  "inverted": res.inverted, "tolerance_ms": tol, "ok": ok}
            row["all_pass"] = row["all_pass"] and ok
        rows.append(row)
    passing = [r for r in rows if r["all_pass"]]
    chosen = max((r["beta"] for r in passing), default=None)
    return {"rows": rows, "chosen_beta": chosen, "current_beta": detector.WHITEN_BETA,
            "pass": chosen is not None and abs(chosen - detector.WHITEN_BETA) < 1e-9}


def check_silence_and_short(fs: float = 48000.0) -> dict:
    """Detect refuses rather than guesses: a silent reference and too little audio."""
    ref, trk, _ = material.drum_loop_pair(fs, 1)
    silent = detector.detect(np.zeros_like(ref), trk, fs, with_suggestion=False)
    short = detector.detect(ref[:1000], trk[:1000], fs, with_suggestion=False)
    return {"silent_reference": {"ok": silent.ok, "words": silent.words()},
            "too_short": {"ok": short.ok, "words": short.words()},
            "pass": (not silent.ok) and (not short.ok)
                    and silent.reason == "Reference is silent"}


def check_null(fs: float = 48000.0) -> dict:
    """The brief's must_do: Delay 0, Polarity off, Rotate 0 nulls against the input.

    Two cases. "live" is Window 0, where the plugin reports no latency and the path has to be a
    wire sample for sample. "compensated" is Window 20 ms, where the plugin delays by exactly the
    whole number of samples it reports, so undoing the reported latency has to null exactly too -
    that is what a host's delay compensation does.
    """
    ref, trk, _ = material.drum_loop_pair(fs, 1)
    main = stereo(trk[: int(4 * fs)])
    side = stereo(ref[: int(4 * fs)])
    out = {}
    for name, window in (("live", 0), ("compensated", 2)):
        eng = AlignEngine()
        eng.prepare(fs, 512, Params(window=window))
        y = eng.render(main.copy(), side.copy())
        lat = eng.latency_samples
        a = main[:, : main.shape[1] - lat] if lat else main
        b = y[:, lat:] if lat else y
        res = a - b
        out[name] = {"window_index": window, "latency_samples": lat,
                     "residual_peak_dbfs": peak_db(res), "residual_rms_dbfs": rms_db(res)}
    out["pass"] = all(v["residual_peak_dbfs"] < -140.0 for k, v in out.items() if k != "pass")
    return out


def check_stage_nulls(fs: float = 48000.0) -> dict:
    """Each stage on its own: the identity settings have to be exact, not nearly exact."""
    ref, trk, _ = material.drum_loop_pair(fs, 1)
    main = stereo(trk[: int(2 * fs)])
    side = stereo(ref[: int(2 * fs)])
    rows = {}
    for name, params in (
        ("rotate_0", Params(window=0, rotate_deg=0.0)),
        ("trim_0db", Params(window=0, trim_db=0.0)),
        ("polarity_off", Params(window=0, polarity=False)),
        ("bypass", Params(window=0, bypass=True)),
    ):
        eng = AlignEngine()
        eng.prepare(fs, 512, params)
        y = eng.render(main.copy(), side.copy())
        rows[name] = {"residual_peak_dbfs": peak_db(main - y)}
    # polarity on must be exactly the inverse once the crossfade has settled
    eng = AlignEngine()
    eng.prepare(fs, 512, Params(window=0, polarity=True))
    y = eng.render(main.copy(), side.copy())
    skip = int(0.1 * fs)
    rows["polarity_on_is_exact_inverse"] = {
        "residual_peak_dbfs": peak_db(main[:, skip:] + y[:, skip:])}
    rows["pass"] = all(v["residual_peak_dbfs"] < -140.0 for k, v in rows.items() if k != "pass")
    return rows


def check_latency(fs: float = 48000.0) -> dict:
    """Reported latency equals measured latency, for every Window (the brief's latency target)."""
    rows = []
    n = 1 << 15
    imp = np.zeros((2, n))
    imp[:, 0] = 1.0
    for idx, ms in enumerate([0.0, 5.0, 20.0, 50.0, 200.0]):
        eng = AlignEngine()
        eng.prepare(fs, 512, Params(window=idx))
        y = eng.render(imp.copy(), np.zeros_like(imp))
        measured = int(np.argmax(np.abs(y[0])))
        rows.append({"window_ms": ms, "reported_samples": eng.latency_samples,
                     "measured_peak_at_sample": measured,
                     "error_samples": abs(measured - eng.latency_samples)})
    return {"rows": rows, "sample_rate": fs,
            "pass": all(r["error_samples"] == 0 for r in rows)}


def check_delay_clamp(fs: float = 48000.0) -> dict:
    """The clamp of G1 decision 6, and the invariant that Detect cannot propose what it cannot apply."""
    rows = []
    for idx, ms in enumerate([0.0, 5.0, 20.0, 50.0, 200.0]):
        lo, hi = detector.search_range_ms(ms)
        eng = AlignEngine()
        for wanted, expected in ((-300.0, -ms), (300.0, 200.0), (lo, lo), (hi, hi)):
            eng.prepare(fs, 512, Params(window=idx, delay_ms=wanted))
            rows.append({"window_ms": ms, "delay_set_ms": wanted,
                         "clamped_to_ms": eng.clamped_delay_ms, "expected_ms": expected,
                         "ok": abs(eng.clamped_delay_ms - expected) < 1e-9})
        rows.append({"window_ms": ms, "search_lo_ms": lo, "search_hi_ms": hi,
                     "ok": lo >= -ms and hi <= 200.0})
    return {"rows": rows, "pass": all(r["ok"] for r in rows)}


def check_click(fs: float = 48000.0) -> dict:
    """The brief's click test: Track sweeping 2 ms over 1 s on a 1 kHz sine, no sample above
    peak + 0.01 dB. The same render also covers the three switches, judged on the harness
    contract's `max_click_db` rather than on overshoot.

    Two criteria, because they answer two different questions. Overshoot is the brief's, and it is
    the one that matters for the delay: a crossfade between two taps of the *same* signal must
    never add level, which is why the law is amplitude-complementary. A switch that changes a
    filter coefficient is not a crossfade of one signal - the Rotate stage sweeps its corner while
    it fades in - so a few thousandths of a decibel of overshoot there is a transient, not a click.
    What would be audible is a discontinuity, and `max_click_db` is what measures that: a clean
    1 kHz sine reads about -17.7 dB and a real step reads near 0 dB.
    """
    n = int(2.0 * fs)
    t = np.arange(n) / fs
    sine = stereo(0.5 * np.sin(2.0 * np.pi * 1000.0 * t))
    silence = np.zeros_like(sine)
    rows = {}

    eng = AlignEngine()
    eng.prepare(fs, 64, Params(window=2))
    block = 64
    out = np.empty_like(sine)
    at = 0
    while at < n:
        k = min(block, n - at)
        now = at / fs
        swept = 0.0 if now < 0.5 else min(2.0, (now - 0.5) * 2.0)
        eng.set_params(Params(window=2, delay_ms=swept))
        out[:, at:at + k] = eng.process_block(sine[:, at:at + k], silence[:, at:at + k])
        at += k
    rows["track_sweep_2ms_over_1s"] = {
        "input_peak_dbfs": peak_db(sine), "output_peak_dbfs": peak_db(out),
        "overshoot_db": peak_db(out) - peak_db(sine),
        "max_click_db": max_click_db(out), "reference_click_db": max_click_db(sine)}

    for name, a, b in (("polarity_switch", Params(window=0), Params(window=0, polarity=True)),
                       ("rotate_bypass_in", Params(window=0), Params(window=0, rotate_deg=90.0)),
                       ("listen_switch", Params(window=0), Params(window=0, listen=2))):
        eng = AlignEngine()
        eng.prepare(fs, 64, a)
        out = np.empty_like(sine)
        at = 0
        while at < n:
            k = min(block, n - at)
            eng.set_params(b if at / fs >= 1.0 else a)
            out[:, at:at + k] = eng.process_block(sine[:, at:at + k], silence[:, at:at + k])
            at += k
        rows[name] = {"input_peak_dbfs": peak_db(sine), "output_peak_dbfs": peak_db(out),
                      "overshoot_db": peak_db(out) - peak_db(sine),
                      "max_click_db": max_click_db(out), "reference_click_db": max_click_db(sine)}
    sweep = rows["track_sweep_2ms_over_1s"]
    switches = [v for k, v in rows.items() if k != "track_sweep_2ms_over_1s"]
    rows["pass"] = bool(sweep["overshoot_db"] <= 0.01
                        and sweep["max_click_db"] <= sweep["reference_click_db"] + 1.0
                        and all(v["max_click_db"] <= v["reference_click_db"] + 1.0
                                for v in switches))
    return rows


def check_mono_bass(fs: float = 48000.0) -> dict:
    """Rule 15, asserted instead of assumed: a mono input stays mono at every setting, because both
    channels get identical coefficients and nothing here modulates."""
    ref, trk, _ = material.drum_loop_pair(fs, 1)
    main = stereo(trk[: int(2 * fs)])
    side = stereo(ref[: int(2 * fs)])
    worst = 0.0
    for params in (Params(window=2, delay_ms=1.3, rotate_deg=90.0, below_hz=120.0, trim_db=-3.0),
                   Params(window=4, delay_ms=-37.0, polarity=True, rotate_deg=180.0, below_hz=60.0)):
        eng = AlignEngine()
        eng.prepare(fs, 512, params)
        y = eng.render(main.copy(), side.copy())
        worst = max(worst, float(np.max(np.abs(y[0] - y[1]))))
    return {"max_channel_difference": worst, "pass": worst < 1e-12}


def check_rates_and_blocks(fs_list=RATES) -> dict:
    """The definition-of-done row: clean at every rate and at blocks 0, 1, 13, 32, 64, 512, 4096
    and one larger than announced, with no NaN, no Inf and no dependence on the block size."""
    rows = []
    for fs in fs_list:
        ref, trk, _ = material.drum_loop_pair(fs, 1)
        main = stereo(trk[: int(1.0 * fs)])
        side = stereo(ref[: int(1.0 * fs)])
        params = Params(window=2, delay_ms=1.3, rotate_deg=48.0, below_hz=110.0, trim_db=-2.0)
        reference = None
        for block in (1, 13, 32, 64, 512, 4096, 9000):
            eng = AlignEngine()
            eng.prepare(fs, 512, params)          # announced 512, driven with up to 9000
            y = eng.render(main.copy(), side.copy(), block=block)
            if reference is None:
                reference = y
            rows.append({"sample_rate": fs, "block": block,
                         "nan": int(np.isnan(y).sum()), "inf": int(np.isinf(y).sum()),
                         "peak_dbfs": peak_db(y),
                         "vs_block1_peak_dbfs": peak_db(y - reference)})
        # a zero-length block must be legal
        eng = AlignEngine()
        eng.prepare(fs, 512, params)
        empty = eng.process_block(np.zeros((2, 0)), np.zeros((2, 0)))
        rows.append({"sample_rate": fs, "block": 0, "nan": 0, "inf": 0,
                     "peak_dbfs": -300.0, "vs_block1_peak_dbfs": -300.0,
                     "zero_block_shape": list(empty.shape)})
    return {"rows": rows,
            "max_block_dependence_dbfs": max(r["vs_block1_peak_dbfs"] for r in rows),
            "pass": all(r["nan"] == 0 and r["inf"] == 0 for r in rows)
                    and max(r["vs_block1_peak_dbfs"] for r in rows) < -140.0}


def check_reset_reproducible(fs: float = 48000.0) -> dict:
    """Rule 8: two runs from reset are bit-identical."""
    ref, trk, _ = material.drum_loop_pair(fs, 1)
    main = stereo(trk[: int(2 * fs)])
    side = stereo(ref[: int(2 * fs)])
    params = Params(window=2, delay_ms=-3.7, rotate_deg=90.0, below_hz=80.0, trim_db=1.5)
    eng = AlignEngine()
    eng.prepare(fs, 512, params)
    first = eng.render(main.copy(), side.copy())
    eng.reset()
    second = eng.render(main.copy(), side.copy())
    return {"residual_peak_dbfs": peak_db(first - second),
            "bit_identical": bool(np.array_equal(first, second)),
            "pass": bool(np.array_equal(first, second))}


def check_sum_comb(fs: float = 48000.0) -> dict:
    """Defining feature 2: the Sum well's comb notches disappear.

    A 2.317 ms offset puts the first notch at 1 / (2 * 2.317 ms) = 215.8 Hz. The check is the
    depth of the summed spectrum at that frequency before and after alignment.
    """
    # Two mics at the same level on the same source, 2.317 ms apart: that is what combs. The
    # tilted pair of drum_loop_pair combs only partly, because the two mics do not carry the same
    # level at 216 Hz, so it would make a weak presence test for a display feature.
    delay_ms = 2.317
    loop = material.drum_loop(fs, 1)
    ref = material._tilt(loop, fs, 300.0, 0.8, 1.0)
    trk = material.fractional_shift(ref.copy(), delay_ms * 1e-3 * fs)
    n = int(4 * fs)
    main, side = stereo(trk[:n]), stereo(ref[:n])
    notch_hz = 1.0 / (2.0 * delay_ms * 1e-3)

    def notch_depth(mix: np.ndarray) -> float:
        spec = np.abs(np.fft.rfft(mix, n))
        freqs = np.fft.rfftfreq(n, d=1.0 / fs)
        near = (freqs > notch_hz * 0.9) & (freqs < notch_hz * 1.1)
        wide = (freqs > notch_hz * 0.4) & (freqs < notch_hz * 2.5)
        # smooth with a 1/6-octave-ish window so single bins do not decide the number
        k = max(1, int(len(freqs) * 6.0 / fs))
        kernel = np.ones(k) / k
        smooth = np.convolve(spec, kernel, mode="same")
        return db(float(np.min(smooth[near])) / (float(np.median(smooth[wide])) + 1e-30))

    rows = {}
    for name, params in (("before", Params(window=2, delay_ms=0.0)),
                         ("after", Params(window=2, delay_ms=-delay_ms))):
        eng = AlignEngine()
        eng.prepare(fs, 512, params)
        out = eng.render(main.copy(), side.copy())
        lat = eng.latency_samples
        summed = out[0, lat:] + side[0, : side.shape[1] - lat]
        rows[name] = {"notch_hz": notch_hz, "notch_depth_db": notch_depth(summed)}
    rows["improvement_db"] = rows["after"]["notch_depth_db"] - rows["before"]["notch_depth_db"]
    rows["pass"] = bool(rows["before"]["notch_depth_db"] < -10.0
                        and rows["after"]["notch_depth_db"] > -1.5)
    return rows


def _rotated(x: np.ndarray, fs: float, deg: float, below: float,
             inverse: bool = False) -> np.ndarray:
    """Apply the Rotate stage's exact phase to a signal, or its inverse, in the frequency domain:
    the truth generator for the suggestion test.

    `inverse=False` is what the stage itself does - it makes the low band *later*. `inverse=True`
    makes it earlier, which is the state of a track the stage can then correct.
    """
    m = 1 << int(np.ceil(np.log2(2 * len(x))))
    spec = np.fft.rfft(x, m)
    freqs = np.fft.rfftfreq(m, d=1.0 / fs)
    phase = rotate_stage.phase_response(freqs, deg, below, fs)
    return np.fft.irfft(spec * np.exp((-1j if inverse else 1j) * phase), m)[:len(x)]


def check_rotate_suggestion(fs: float = 48000.0) -> dict:
    """The brief's low_register target, in the three cases the suggestion has to tell apart.

    1. A pair whose low end a rotation *can* fix: the suggestion must fire and must buy at least
       ROTATE_MIN_GAIN of low-band correlation.
    2. A pair rotated the other way: Rotate cannot make a track's low end earlier, so the honest
       answer is "put Align on the other mic", not "no rotation needed".
    3. A pair a delay already aligns: no suggestion at all, or Apply would be offered for nothing.

    The pairs are matched in tilt, so the only difference between the two mics is the rotation
    under test and the delay - which is what makes "the suggestion recovered it" mean something.

    The assertion is on the correlation it reaches, not on the (Rotate, Below) it returns, because
    that pair is deliberately not unique: the filter depends only on the corner
    `Below / tan(Rotate/4)`, so 52 deg below 80 Hz and 70 deg below 110 Hz are the same filter to
    within a hertz. A test that pinned the numbers would fail on a correct answer.
    """
    loop = material.drum_loop(fs, 11)
    base = material._tilt(loop, fs, 180.0, 1.0, 0.25)
    truth_deg, truth_below = 70.0, 110.0
    rows = {}

    # 1. reachable direction: the track's low end is early, Rotate's lag brings it back
    trk = material.fractional_shift(_rotated(base, fs, truth_deg, truth_below, inverse=True),
                                    2.317e-3 * fs)
    res = detector.detect(base, trk, fs, window_ms=20.0)
    s = res.suggestion
    rows["reachable"] = {"truth_rotate_deg": truth_deg, "truth_below_hz": truth_below,
                         "found_delay_ms": res.delay_ms, "suggested": s.needed,
                         "rotate_deg": s.rotate_deg, "below_hz": s.below_hz,
                         "corr_before": s.corr_before, "corr_after": s.corr_after,
                         "gain": s.corr_after - s.corr_before, "words": s.words()}

    # 2. the direction the stage cannot produce: the low end is already late
    trk = material.fractional_shift(_rotated(base, fs, truth_deg, truth_below), 2.317e-3 * fs)
    res = detector.detect(base, trk, fs, window_ms=20.0)
    s = res.suggestion
    rows["other_direction"] = {"suggested": s.needed, "other_mic": s.other_mic,
                               "other_mic_gain": s.other_mic_gain, "words": s.words()}

    # 3. a pair a delay alone aligns
    ref, trk, _ = material.drum_loop_pair(fs, 1)
    s = detector.detect(ref, trk, fs, window_ms=20.0).suggestion
    rows["delay_only"] = {"suggested": s.needed, "other_mic": s.other_mic,
                          "other_mic_gain": s.other_mic_gain, "words": s.words()}

    rows["pass"] = bool(
        rows["reachable"]["suggested"]
        and rows["reachable"]["gain"] >= detector.ROTATE_MIN_GAIN
        and rows["other_direction"]["other_mic"] and not rows["other_direction"]["suggested"]
        and not rows["delay_only"]["suggested"] and not rows["delay_only"]["other_mic"])
    return rows


def check_readout() -> dict:
    """Defining feature 3: the readout in words, with the distance."""
    res = detector.DetectResult(ok=True, delay_ms=2.31, inverted=True, confidence_pct=94.0,
                                distance_cm=2.31e-3 * material.SPEED_OF_SOUND * 100.0)
    text = res.words()
    low = detector.DetectResult(ok=True, delay_ms=-0.4, inverted=False, confidence_pct=38.0,
                                distance_cm=0.4e-3 * material.SPEED_OF_SOUND * 100.0).words()
    return {"example": text, "low_confidence_example": low,
            "pass": ("2.31 ms" in text and "79 cm" in text and "polarity flipped" in text
                     and "94 %" in text and "low confidence 38 %" in low)}


def reference_renders(fs: float = 48000.0, seed: int = 1) -> dict:
    """The renders G5 nulls the port against, and the material behind them.

    Each render is the whole plugin at one setting, driven block-wise exactly as the harness drives
    the processor, so the port can be compared sample for sample.
    """
    ref, trk, truth = material.drum_loop_pair(fs, seed)
    n = int(4 * fs)
    main, side = stereo(trk[:n]), stereo(ref[:n])
    files = {"input_main": write_wav("g2_in_main.wav", fs, main),
             "input_sidechain": write_wav("g2_in_ref.wav", fs, side)}
    settings = {
        "init": Params(),
        "detected": Params(window=2, delay_ms=-truth["delay_ms"], polarity=truth["inverted"]),
        "rotate_90_below_110": Params(window=2, delay_ms=-truth["delay_ms"],
                                      polarity=truth["inverted"], rotate_deg=90.0, below_hz=110.0),
        "live_window": Params(window=0, delay_ms=1.75, trim_db=-2.0),
        "wide_window": Params(window=4, delay_ms=-37.5, polarity=True, rotate_deg=180.0,
                              below_hz=60.0, trim_db=3.0),
        "listen_sum": Params(window=2, delay_ms=-truth["delay_ms"], polarity=truth["inverted"],
                             listen=2),
    }
    rows = {}
    for name, params in settings.items():
        eng = AlignEngine()
        eng.prepare(fs, 512, params)
        y = eng.render(main.copy(), side.copy())
        rows[name] = {"file": write_wav(f"g2_{name}.wav", fs, y),
                      "peak_dbfs": peak_db(y), "rms_dbfs": rms_db(y),
                      "latency_samples": eng.latency_samples,
                      "nan": int(np.isnan(y).sum()), "inf": int(np.isinf(y).sum())}
    return {"sample_rate": fs, "seed": seed, "truth": truth, "inputs": files, "renders": rows}


def listening_ab(fs: float = 48000.0, seed: int = 1) -> dict:
    """The A/B for the listening checkpoint (F.18.7): the *sum* of the pair, four bars misaligned,
    then the same four bars aligned, level-matched, in one file.

    What Align changes cannot be judged on the processed track alone - a delay of 2.3 ms on one mic
    sounds like nothing by itself. The comb filtering is in the sum, so that is what gets listened
    to, and the two halves are matched in integrated level so the comparison is about the comb and
    not about loudness (core card, section 5, point 2).
    """
    ref, trk, truth = material.drum_loop_pair(fs, seed, invert=False)
    n = int(4.0 * fs)
    main, side = stereo(trk[:n]), stereo(ref[:n])
    halves = []
    for params in (Params(window=2, delay_ms=0.0),
                   Params(window=2, delay_ms=-truth["delay_ms"])):
        eng = AlignEngine()
        eng.prepare(fs, 512, params)
        out = eng.render(main.copy(), side.copy())
        lat = eng.latency_samples
        summed = 0.5 * (out[:, lat:] + side[:, : side.shape[1] - lat])
        halves.append(summed)
    k = min(h.shape[1] for h in halves)
    halves = [h[:, :k] for h in halves]
    rms = [float(np.sqrt(np.mean(h * h))) for h in halves]
    halves[1] = halves[1] * (rms[0] / (rms[1] + 1e-30))      # level-match before listening
    gap = np.zeros((2, int(0.5 * fs)))
    both = np.concatenate([halves[0], gap, halves[1]], axis=1)
    both = both / (np.max(np.abs(both)) + 1e-12) * 0.89
    return {"file": write_wav("g2_listen_ab_misaligned_then_aligned.wav", fs, both),
            "seconds_per_half": k / fs, "gap_seconds": 0.5,
            "level_match_gain_db": db(rms[0] / (rms[1] + 1e-30)),
            "note": "first half: Delay 0 (combed). second half: Delay applied (aligned)."}


# ---------------------------------------------------------------- CLI
CHECKS = {
    "rotate-structure": check_rotate_structure,
    "delay-response": check_delay_response,
    "accuracy": check_accuracy,
    "silence": check_silence_and_short,
    "whiten": check_whiten,
    "null": check_null,
    "stage-nulls": check_stage_nulls,
    "latency": check_latency,
    "clamp": check_delay_clamp,
    "click": check_click,
    "mono-bass": check_mono_bass,
    "rates-blocks": check_rates_and_blocks,
    "reset": check_reset_reproducible,
    "sum-comb": check_sum_comb,
    "rotate-suggestion": check_rotate_suggestion,
    "readout": check_readout,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="every check, then the reference renders")
    ap.add_argument("--check", action="append", default=[], choices=sorted(CHECKS),
                    help="one check by name; repeatable")
    ap.add_argument("--kernel-search", action="store_true", help="choose the sinc kernel constants")
    ap.add_argument("--renders", action="store_true", help="write the reference renders only")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(HERE, "g2.json"))
    args = ap.parse_args()

    report: dict = {"seed": args.seed}
    if args.kernel_search:
        report["kernel_search"] = kernel_search()
    names = sorted(CHECKS) if args.all else args.check
    for name in names:
        report[name] = CHECKS[name]()
    if args.all or args.renders:
        report["reference_renders"] = reference_renders(seed=args.seed)
        report["listening_ab"] = listening_ab(seed=args.seed)

    failed = [k for k, v in report.items() if isinstance(v, dict) and v.get("pass") is False]
    report["failed"] = failed
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True, default=float)

    for k in names:
        v = report[k]
        state = "pass" if v.get("pass") else ("-" if "pass" not in v else "FAIL")
        print(f"{state:>5}  {k}")
    if "kernel_search" in report:
        print("kernel:", json.dumps(report["kernel_search"]["chosen"]))
    print(f"wrote {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
