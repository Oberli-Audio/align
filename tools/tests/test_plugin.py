#!/usr/bin/env python3
"""Align's test suite (sound-design-bob D.3), from the kit's test_template.py.

Drives the real processor through the offline renderer (harness contract v3 plus Align's sidechain
and --detect-at extensions, DEVELOPING.md) and asserts on its JSON and WAVs with dspkit. The pair
material is the prototype's own seeded generator (`sound design/material.py`), so the suite and
the G2 prototype measure the same signals.

    HARNESS=build/AlignHarness_artefacts/Release/AlignHarness python3 tools/tests/test_plugin.py --label fast
    HARNESS=... python3 tools/tests/test_plugin.py --label render

Labels (D.3.1): fast = contract, rate/block matrix, health, properties, the path's own rules and the
defining features at 48 kHz (every build, < 60 s); render = goldens, Detect at every rate, the
reverberant and tonal pairs, the Rotate suggestion (every commit). The host validators are not here
(validate_plugin.py). Every test names the rule, the brief line or the G1 decision it holds.

Sign convention (material.py): a pair's truth `delay_ms` > 0 means the track is *later* than the
reference, so the Delay that aligns it is the negative - and that negative is what Detect reports
and writes (`detects[].delay_ms`, the readout's "Peak -2.32 ms" with a typographic minus).

The harness applies --param after prepareToPlay (contract), so a Window, Bypass or Polarity that
differs from the default crossfades in over the first milliseconds; the nulls compare from SETTLE_S.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("DSPKIT", str(ROOT / "scripts" / "dsp-kit")))
sys.path.insert(0, str(ROOT / "sound design"))
import dspkit as K  # noqa: E402
import material as M  # noqa: E402

HARNESS = os.environ.get("HARNESS", str(ROOT / "build/AlignHarness_artefacts/Release/AlignHarness"))
GOLDEN_DIR = Path(os.environ.get("GOLDEN_DIR", str(ROOT / "tools/tests/golden")))
GOLDEN_ARCH = os.environ.get("GOLDEN_ARCH", "x86_64")                # D.2.1: the slice the host runs
DEFAULT = dict(seed=1, sample_rate=48000, block=512, seconds=2.0)
# The track and the reference both carry seeded pink noise: every render exercises the sidechain
# bus and the analysis rings, not only the audio path.
SOURCE = dict(signal="noise:pink:-20", sidechain_signal="noise:pink:-20")
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
BLOCKS = (0, 1, 13, 32, 64, 512, 4096)
WINDOW_MS = (0.0, 5.0, 20.0, 50.0, 200.0)                            # parameters.csv: window choices
INSTRUMENT = False
SETTLE_S = 0.05     # longer than every crossfade on the path (10-15 ms) and the smoothers' settling
FAST_BUDGET_S = float(os.environ.get("FAST_BUDGET_S", "20"))
# rule 20 is judged on the budget machine only (perf.py run --arch <the host's slice>); a cloud VM or
# a laptop on battery reports p99.9 here. DSPKIT_BUDGET_MACHINE=1 makes this suite judge it as well.
BUDGET_MACHINE = os.environ.get("DSPKIT_BUDGET_MACHINE") == "1"
GOLDEN_PEAK_DB = {"same": -140.0, "cross-feedforward": -100.0, "cross-feedback": -80.0}


# ---------------------------------------------------------------- parameters.csv, normalised
# The harness takes 0..1 (contract). These mirror Source/Params.h, which paramgen writes from the CSV.
def n_delay(ms):
    return (ms + 200.0) / 400.0


def n_rotate(deg):
    return deg / 180.0


def n_below(hz):
    return ((hz - 30.0) / 970.0) ** 0.331680                           # skew from centre 150 Hz


def n_window(ms):
    return WINDOW_MS.index(ms) / 4.0


def n_trim(db):
    return (db + 24.0) / 48.0


PARAM = ("trim", n_trim(6.0))            # one real parameter ID and a non-default value


# ---------------------------------------------------------------- rendering
def run(params=None, **flags):
    f = dict(DEFAULT, **SOURCE)
    if "in_" in flags:                                                   # --in replaces --signal
        flags["in"] = flags.pop("in_")
    if "in" in flags:
        f.pop("signal", None)
    if "sidechain" in flags:
        f.pop("sidechain_signal", None)
    f.update(flags)
    res = K.render(HARNESS, params, **f)
    echo = {k: v for k, v in f.items() if k in ("seed", "sample_rate", "block", "seconds", "preset")
            and not (k == "block" and str(v).startswith("random:"))}
    K.assert_echo(res, params if not f.get("detect_at") else None, **echo)   # rule 13; Detect rewrites delay
    return res


def stereo(x):
    x = np.asarray(x, dtype=np.float64)
    return np.stack([x, x], axis=1)


def write(d, name, x, fs):
    path = Path(d) / name
    K.write_wav(path, stereo(x) if np.ndim(x) == 1 else x, fs)
    return path


def impulse_at(fs, seconds, at_s, amp=0.5):
    x = np.zeros(int(round(seconds * fs)))
    x[int(round(at_s * fs))] = amp
    return x


def render_pair(d, ref, trk, fs, params=None, **flags):
    """The track on the main bus, the reference on the sidechain; returns (res, out)."""
    a = write(d, "trk.wav", trk, fs)
    b = write(d, "ref.wav", ref, fs)
    out = Path(d) / "out.wav"
    res = run(params, in_=a, sidechain=b, out=out, sample_rate=fs, seconds=len(trk) / fs, **flags)
    x, _ = K.read_wav(out)
    return res, x


def latency(res):
    return int(res["applied"]["latency_samples"])


def notch_depth_db(mix, fs, notch_hz):
    """The comb notch's depth in a summed pair against its surroundings (prototype check_sum_comb)."""
    n = len(mix)
    spec = np.abs(np.fft.rfft(mix, n))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    near = (freqs > notch_hz * 0.9) & (freqs < notch_hz * 1.1)
    wide = (freqs > notch_hz * 0.4) & (freqs < notch_hz * 2.5)
    k = max(1, int(len(freqs) * 6.0 / fs))
    smooth = np.convolve(spec, np.ones(k) / k, mode="same")
    return float(K.db(float(np.min(smooth[near])) / (float(np.median(smooth[wide])) + 1e-30)))


class Timed(unittest.TestCase):
    label = "fast"

    def setUp(self):
        self._t0 = time.time()

    def tearDown(self):
        dt = time.time() - self._t0
        print("  [%s %.1f s]" % (self.label, dt), end="", flush=True)
        if self.label == "fast" and dt > FAST_BUDGET_S:
            self.fail("fast test took %.0f s; budget %.0f s (D.3.6: move it to a slower tier, do not delete it)" % (dt, FAST_BUDGET_S))


# ================================================================ the kit's generic battery
class Contract(Timed):
    def test_harness_echoes_params(self):                                  # rule 13
        pid, val = PARAM
        res = run({pid: val})
        self.assertAlmostEqual(res["applied"]["params"][pid], val, places=6)

    def test_seeded_runs_are_bit_identical(self):                          # rule 8: reset + seed
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.wav", Path(d) / "b.wav"
            run({"rotate": n_rotate(90.0), "delay": n_delay(-1.3)}, out=a)
            run({"rotate": n_rotate(90.0), "delay": n_delay(-1.3)}, out=b)
            xa, _ = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertTrue((xa == xb).all(), "two seeded renders differ")

    def test_sidechain_is_connected(self):                                 # the reference bus exists
        res = run(seconds=0.25)
        self.assertTrue(res["product"]["sidechain_connected"])


class RateAndBlock(Timed):
    def test_rate_block_matrix_is_clean(self):                             # DoD: 42 combinations
        for fs in RATES:
            for blk in BLOCKS:
                with self.subTest(fs=fs, block=blk):
                    res = run({"rotate": n_rotate(90.0)}, sample_rate=fs, block=blk, seconds=0.25)
                    self.assertEqual(res["health"]["nan"] + res["health"]["inf"], 0)
                    self.assertLess(res["levels"]["peak_dbfs"], 0.0)

    def test_random_block_sizes_from_zero(self):                           # D.5.1, fuzz
        res = run(block="random:7", max_block=1024, seconds=0.5)
        self.assertEqual(res["health"]["nan"], 0)

    def test_block_larger_than_announced(self):                            # D.5.1
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "ref.wav", Path(d) / "big.wav"
            run(block=256, max_block=256, seconds=0.5, out=a)
            res = run(block=1024, max_block=256, seconds=0.5, out=b)
            self.assertEqual(res["health"]["nan"], 0)
            xa, fs = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertLess(K.dropout_db(xa, xb, fs), 3.0, "an oversized block rendered quieter than its announced-size twin")


class Health(Timed):
    def test_silence_has_no_denormal_storm_or_dc(self):                    # DoD: silence test, 48 k/64
        res = run({"rotate": n_rotate(180.0), "below": n_below(30.0)}, signal="silence",
                  sidechain_signal="silence", seconds=10.0, profile=1, sample_rate=48000, block=64, warmup=200)
        self.assertLess(res["levels"]["dc_dbfs"], -80.0)
        if BUDGET_MACHINE:
            self.assertLess(res["profile"]["p999_pct"], 25.0)              # rule 20: judged on the budget machine
        print("p99.9 %.1f %% (%s), over_deadline %s (reported, not judged, rule 20)" % (
            res["profile"]["p999_pct"], "judged" if BUDGET_MACHINE else "reported: not the budget machine", res["profile"]["over_deadline"]))

    def test_latency_matches_impulse_at_every_window(self):                # rule 7; brief: latency = Window
        for ms in WINDOW_MS:
            with self.subTest(window_ms=ms), tempfile.TemporaryDirectory() as d:
                out = Path(d) / "imp.wav"
                res = run({"window": n_window(ms)}, signal="impulse", sidechain_signal="silence", seconds=0.5, out=out)
                x, fs = K.read_wav(out)
                ref = np.zeros_like(x[:, :1])
                ref[0, 0] = 0.5
                self.assertEqual(K.latency_samples(ref, x[:, :1]), latency(res))
                self.assertEqual(latency(res), int(round(ms * 1e-3 * fs)), "reported latency is not the Window")


class Properties(Timed):
    def test_state_round_trip_is_bytewise(self):                           # D.5.3
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pid, val = PARAM
            run({pid: val}, state_out=d / "a.state", out=d / "a.wav", seconds=0.5)
            rb = run(state_in=d / "a.state", state_out=d / "b.state", out=d / "b.wav", seconds=0.5)
            self.assertEqual((d / "a.state").read_bytes(), (d / "b.state").read_bytes())
            self.assertAlmostEqual(rb["applied"]["params"][pid], val, places=6)
            xa, _ = K.read_wav(d / "a.wav")
            xb, _ = K.read_wav(d / "b.wav")
            self.assertTrue((xa == xb).all())

    def test_state_round_trip_is_bytewise_for_every_parameter(self):       # D.5.3, rule 19
        listed = json.loads(subprocess.run(K.harness_cmd(HARNESS) + ["--list-params"], capture_output=True, text=True, check=True).stdout)
        odd = {p["id"]: 0.3 if p.get("steps", 0) in (0, None) else round(0.3 * (p["steps"] - 1)) / (p["steps"] - 1)
               for p in listed if p.get("steps", 0) != 2}           # bools (and bypass) stay at their default
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, params in (("defaults", None), ("odd", odd)):
                run(params, state_out=d / "a.state", seconds=0.1)
                run(state_in=d / "a.state", state_out=d / "b.state", seconds=0.1)
                run(state_in=d / "b.state", state_out=d / "c.state", seconds=0.1)
                a, b, c = ((d / n).read_bytes() for n in ("a.state", "b.state", "c.state"))
                self.assertEqual(a, b, "%s: the state changed on the first load and save" % name)
                self.assertEqual(b, c, "%s: the state drifts on every load and save" % name)

    def test_corrupted_state_does_not_crash(self):                         # D.5.3, fuzz
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            run(state_out=d / "good.state", seconds=0.25)
            good = (d / "good.state").read_bytes()
            cases = {"empty": b"", "truncated": good[: len(good) // 2], "garbage": bytes(range(256)) * 4,
                     "flipped": bytes(b ^ 0x55 for b in good)}
            for name, blob in cases.items():
                with self.subTest(case=name):
                    (d / "bad.state").write_bytes(blob)
                    try:
                        res = K.render(HARNESS, state_in=d / "bad.state", seconds=0.25, **{k: v for k, v in DEFAULT.items() if k != "seconds"}, **SOURCE)
                    except RuntimeError as e:
                        self.assertNotIn("Segmentation", str(e))      # a clean refusal is fine, a crash is not
                        self.assertNotIn("-11", str(e).split(")")[0])
                        continue
                    self.assertEqual(res["health"]["nan"], 0)


# ================================================================ Align's audio path (G1 decisions)
class Path_(Timed):
    """The rejection measurements G1 named for each family, on the port."""

    def test_null_at_neutral_after_compensation_every_window(self):        # brief must_do 4, rule 7
        fs = 48000
        x = M.pink_noise(fs, 1.0, seed=7) * 0.3
        with tempfile.TemporaryDirectory() as d:
            for ms in WINDOW_MS:
                with self.subTest(window_ms=ms):
                    res, y = render_pair(d, x, x, fs, {"window": n_window(ms)})
                    L, s0 = latency(res), int(SETTLE_S * fs)
                    r = K.null_residual(stereo(x)[s0: len(x) - L], y[s0 + L:], align=False)
                    self.assertLess(r["peak_dbfs"], -140.0, "Delay 0 / Polarity off / Rotate 0 is not a wire")

    def test_bypass_is_latency_compensated_and_nulls(self):                # rule 7 [E]
        fs = 48000
        x = M.pink_noise(fs, 1.0, seed=7) * 0.3
        with tempfile.TemporaryDirectory() as d:
            res, y = render_pair(d, x, x, fs, {"delay": n_delay(-3.1), "polarity": 1.0, "rotate": n_rotate(120.0),
                                               "trim": n_trim(-6.0), "bypass": 1.0})
            L, s0 = latency(res), int(SETTLE_S * fs)
            self.assertGreater(L, 0)
            r = K.null_residual(stereo(x)[s0: len(x) - L], y[s0 + L:], align=False)
            self.assertLess(r["peak_dbfs"], -140.0, "bypass does not null against the latency-compensated input")

    def test_live_window_has_zero_latency_and_no_negative_delay(self):     # G1 clamp decision
        fs = 48000
        x = M.pink_noise(fs, 1.0, seed=7) * 0.3
        with tempfile.TemporaryDirectory() as d:
            res, y = render_pair(d, x, x, fs, {"window": n_window(0.0), "delay": n_delay(-5.0)})
            self.assertEqual(latency(res), 0)
            s0 = int(SETTLE_S * fs)
            r = K.null_residual(stereo(x)[s0:], y[s0:], align=False)
            self.assertLess(r["peak_dbfs"], -140.0, "a negative Delay leaked through at Window 0 (live)")

    def test_positive_delay_is_not_clamped_to_the_window(self):            # G1 clamp decision
        fs = 48000
        with tempfile.TemporaryDirectory() as d:
            x = impulse_at(fs, 1.0, 0.1)
            res, y = render_pair(d, x * 0.0, x, fs, {"window": n_window(5.0), "delay": n_delay(30.0)})
            got = (int(np.argmax(np.abs(y[:, 0]))) - latency(res)) / fs * 1e3 - 100.0
            self.assertAlmostEqual(got, 30.0, delta=1.0 / fs * 1e3)

    def test_fractional_delay_is_flat_to_18k(self):                        # brief response_error_db, G1 sinc
        for fs in (44100, 48000):
            with self.subTest(fs=fs), tempfile.TemporaryDirectory() as d:
                x = impulse_at(fs, 0.5, 0.1)
                res, y = render_pair(d, x * 0.0, x, fs, {"delay": n_delay(0.37)})
                at = int(round(0.1 * fs)) + latency(res)
                seg = y[at - 2048: at + 2048, 0] / 0.5
                n = 1 << 16
                H = np.abs(np.fft.rfft(seg, n))
                f = np.fft.rfftfreq(n, 1.0 / fs)
                band = (f >= 20.0) & (f <= 18000.0)
                err = float(np.max(np.abs(20.0 * np.log10(H[band]))))
                self.assertLess(err, 0.05, "fractional delay not flat within 0.05 dB to 18 kHz (%.4f dB)" % err)
                # and the delay is where the parameter says (group delay at 1 kHz)
                ph = np.unwrap(np.angle(np.fft.rfft(seg, n)))
                i = int(np.argmin(np.abs(f - 1000.0)))
                gd_ms = -(ph[i + 1] - ph[i - 1]) / (2.0 * np.pi * (f[i + 1] - f[i - 1])) * 1e3 - 2048.0 / fs * 1e3
                self.assertAlmostEqual(gd_ms, 0.37, delta=1e-3)

    def test_polarity_flips_the_signal(self):                              # core control
        fs = 48000
        x = M.pink_noise(fs, 1.0, seed=7) * 0.3
        with tempfile.TemporaryDirectory() as d:
            res, y = render_pair(d, x, x, fs, {"polarity": 1.0, "window": n_window(0.0)})
            skip = int(SETTLE_S * fs)                                      # past the switch's crossfade
            r = K.null_residual(-stereo(x)[skip:], y[skip:], align=False)
            self.assertLess(r["peak_dbfs"], -140.0)

    def test_rotate_is_magnitude_flat_and_reaches_its_angle_at_below(self):    # G1 Rotate rejection
        fs = 48000
        for deg, below in ((90.0, 120.0), (180.0, 80.0), (45.0, 400.0)):
            with self.subTest(rotate=deg, below=below), tempfile.TemporaryDirectory() as d:
                x = impulse_at(fs, 2.0, 0.2)
                res, y = render_pair(d, x * 0.0, x, fs, {"rotate": n_rotate(deg), "below": n_below(below),
                                                         "window": n_window(0.0)})
                at = int(round(0.2 * fs))
                h = y[at: at + int(1.5 * fs), 0] / 0.5
                n = 1 << 18
                Hc = np.fft.rfft(h, n)
                f = np.fft.rfftfreq(n, 1.0 / fs)
                band = (f >= 20.0) & (f <= 20000.0)
                mag = float(np.max(np.abs(20.0 * np.log10(np.abs(Hc[band])))))
                self.assertLess(mag, 0.05, "Rotate moves the magnitude by %.4f dB" % mag)
                i = int(np.argmin(np.abs(f - below)))
                phase = float(np.degrees(np.angle(Hc[i])))
                off = (-phase - deg + 180.0) % 360.0 - 180.0                   # wrap: 180 deg reads as +-180
                self.assertLess(abs(off), 1.0, "phase at Below is %.2f deg, wanted -%.0f" % (phase, deg))

    def test_rotate_smoothing_does_not_depend_on_block_size(self):        # failures.md 2026-11-03, rules 2 and 12
        """Rotate and Below once advanced their one-pole by a per-sample coefficient once per block:
        tau was 20 ms x the block size (10 s at 512), so an applied suggestion took seconds to arrive
        and the output depended on the host's buffer. The same glide at three block sizes must be one
        render, and the angle must be there within a few tau."""
        fs = 48000
        x = M.pink_noise(fs, 0.6, seed=7) * 0.3
        renders = {}
        with tempfile.TemporaryDirectory() as d:
            for blk in (32, 512, 4096):
                _, y = render_pair(d, x, x, fs, {"rotate": n_rotate(90.0), "window": n_window(0.0)}, block=blk)
                renders[blk] = y
            for blk in (512, 4096):
                r = K.null_residual(renders[32], renders[blk], align=False)
                self.assertLess(r["peak_dbfs"], -140.0, "Rotate's glide differs at block %d (%.1f dBFS)" % (blk, r["peak_dbfs"]))
            imp = impulse_at(fs, 1.0, 0.15)                                  # 7.5 tau after the change
            _, y = render_pair(d, imp * 0.0, imp, fs, {"rotate": n_rotate(90.0), "window": n_window(0.0)}, block=512)
        h = y[int(0.15 * fs): int(0.15 * fs) + fs // 2, 0] / 0.5
        n = 1 << 17
        f = np.fft.rfftfreq(n, 1.0 / fs)
        phase = float(np.degrees(np.angle(np.fft.rfft(h, n)[int(np.argmin(np.abs(f - 120.0)))])))
        self.assertLess(abs(phase + 90.0), 1.0, "150 ms after Rotate 90 the phase at Below is %.2f deg" % phase)

    def test_crossfades_land_on_their_target_at_any_block_size(self):      # failures.md 2026-11-03, rule 2
        """Polarity, Listen, bypass and Rotate's bypass once took their step from the *remaining*
        distance at every block: each fade was geometric, so its length depended on the block size,
        and in float it stalled about 2e-5 short of its target (polarity stayed at gain -0.99998,
        never a flip). Each switch must render identically at three block sizes and be exact after."""
        fs = 48000
        x = M.pink_noise(fs, 0.5, seed=7) * 0.3
        L20 = int(round(0.020 * fs))
        cases = {"polarity": ({"polarity": 1.0, "window": n_window(0.0)}, -stereo(x), 0),
                 "bypass": ({"bypass": 1.0, "polarity": 1.0, "rotate": n_rotate(120.0)}, stereo(x), L20),
                 "listen_ref": ({"listen": 0.5, "window": n_window(0.0)}, stereo(x), 0)}
        with tempfile.TemporaryDirectory() as d:
            for name, (params, want, lat) in cases.items():
                with self.subTest(switch=name):
                    renders = {blk: render_pair(d, x, x, fs, params, block=blk)[1] for blk in (64, 512, 4096)}
                    for blk in (512, 4096):
                        r = K.null_residual(renders[64], renders[blk], align=False)
                        self.assertLess(r["peak_dbfs"], -140.0, "%s fades differently at block %d" % (name, blk))
                    s0 = int(SETTLE_S * fs)
                    r = K.null_residual(want[s0: len(x) - lat], renders[512][s0 + lat:], align=False)
                    self.assertLess(r["peak_dbfs"], -140.0, "%s never lands on its target (%.1f dBFS)" % (name, r["peak_dbfs"]))

    def test_mono_in_stays_mono(self):                                     # rule 15 by construction
        fs = 48000
        x = M.pink_noise(fs, 1.0, seed=7) * 0.3
        with tempfile.TemporaryDirectory() as d:
            res, y = render_pair(d, x, x, fs, {"rotate": n_rotate(150.0), "below": n_below(90.0),
                                               "delay": n_delay(-1.37), "polarity": 1.0, "trim": n_trim(3.0)})
            self.assertTrue((y[:, 0] == y[:, 1]).all(), "a mono input left the path in stereo")

    def test_delay_sweep_does_not_overshoot_or_click(self):                # brief click line, G1 crossfade law
        fs = 48000
        t = np.arange(2 * fs) / fs
        sine = 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)
        with tempfile.TemporaryDirectory() as d:
            res, y = render_pair(d, sine * 0.0, sine, fs, block=64,
                                 automate="delay:0.5=%r,1.5=%r" % (n_delay(0.0), n_delay(2.0)))
            over = K.peak_dbfs(y) - K.peak_dbfs(stereo(sine))
            self.assertLessEqual(over, 0.01, "the delay crossfade adds level (%.4f dB)" % over)
            self.assertLessEqual(K.max_click_db(y), K.max_click_db(stereo(sine)) + 1.0)

    def test_switches_do_not_click(self):                                  # rule 2: switches crossfaded
        fs = 48000
        t = np.arange(2 * fs) / fs
        sine = 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)
        for pid, on in (("polarity", 1.0), ("rotate", n_rotate(90.0)), ("listen", 1.0), ("bypass", 1.0)):
            with self.subTest(switch=pid), tempfile.TemporaryDirectory() as d:
                res, y = render_pair(d, sine, sine, fs, {"window": n_window(0.0)}, block=64,
                                     automate="%s:0.999=0,1.0=%r" % (pid, on))
                self.assertLessEqual(K.max_click_db(y), K.max_click_db(stereo(sine)) + 1.0, "%s clicks" % pid)


# ================================================================ Detect and the defining features
DETECT_AT = 4.5     # seconds into the 4-bar loop: the ring holds more than the detector reads


class Defining(Timed):
    """Rule 13: one presence test per defining feature and must_do line of the brief."""

    def _drum_detect(self, fs, d, **params):
        ref, trk, truth = M.drum_loop_pair(fs, 1)
        n = int(5.0 * fs)
        res, y = render_pair(d, ref[:n], trk[:n], fs, params or None, detect_at=DETECT_AT)
        self.assertEqual(len(res["product"]["detects"]), 1)
        return res, res["product"]["detects"][0], truth, y, ref[:n]

    def test_detect_finds_the_drum_loop_delay_and_polarity(self):         # must_do 1, feature 1
        with tempfile.TemporaryDirectory() as d:
            res, det, truth, _, _ = self._drum_detect(48000, d)
            self.assertTrue(det["arrived"] and det["ok"], det)
            self.assertAlmostEqual(det["delay_ms"], -truth["delay_ms"], delta=0.02)
            self.assertTrue(det["inverted"])
            self.assertGreater(det["confidence_pct"], 80.0)
            # the sign of the well's peak (feature 1) is `inverted`; `peak` is its magnitude, which the
            # confidence is built on. The signed curve itself reaches the editor with the Strip wiring.
            self.assertGreater(det["peak"], det["second_peak"])
            # Detect writes delay and polarity (one host edit), never Rotate (brief: only Apply sets it)
            p = res["applied"]["params"]
            self.assertAlmostEqual(p["delay"] * 400.0 - 200.0, det["delay_ms"], delta=0.01)
            self.assertEqual(p["polarity"], 1.0)
            self.assertEqual(p["rotate"], 0.0)

    def test_readout_in_words_with_distance(self):                          # feature 3
        with tempfile.TemporaryDirectory() as d:
            _, det, truth, _, _ = self._drum_detect(48000, d)
            cm = round(abs(det["delay_ms"]) * 1e-3 * M.SPEED_OF_SOUND * 100.0)
            sign = "+" if det["delay_ms"] >= 0 else "\u2212"                   # a typographic minus
            want = "^Peak %s%s ms · %d cm · polarity flipped · confidence \\d+ %%$" % (
                sign, re.escape("%.2f" % abs(det["delay_ms"])), cm)
            self.assertRegex(det["words"], want)

    def test_sum_comb_disappears_after_detect(self):                       # feature 2 (the Sum well's audio)
        fs = 48000
        delay_ms = 2.317
        loop = M.drum_loop(fs, 1)
        ref = M._tilt(loop, fs, 300.0, 0.8, 1.0)                           # a level-matched pair combs fully
        trk = M.fractional_shift(ref.copy(), delay_ms * 1e-3 * fs)
        n = int(8.0 * fs)
        ref, trk = ref[:n], trk[:n]
        notch = 1.0 / (2.0 * delay_ms * 1e-3)
        with tempfile.TemporaryDirectory() as d:
            res, y = render_pair(d, ref, trk, fs, detect_at=DETECT_AT)
            L = latency(res)
            settle = int((DETECT_AT + 0.1) * fs)
            before = y[L: int(DETECT_AT * fs), 0] + ref[: int(DETECT_AT * fs) - L]
            after = y[settle:, 0] + ref[settle - L: n - L]
            db_before, db_after = notch_depth_db(before, fs, notch), notch_depth_db(after, fs, notch)
            self.assertLess(db_before, -10.0, "the misaligned pair should comb (%.1f dB)" % db_before)
            self.assertGreater(db_after, -1.5, "the comb notch is still there after Detect (%.1f dB)" % db_after)

    def test_detect_never_proposes_a_delay_the_window_cannot_apply(self):  # G1 clamp decision
        fs = 48000
        ref, trk, truth = M.drum_loop_pair(fs, 1, invert=False)          # the track is late: needs -2.317 ms
        n = int(5.0 * fs)
        with tempfile.TemporaryDirectory() as d:
            res, _ = render_pair(d, ref[:n], trk[:n], fs, {"window": n_window(0.0)}, detect_at=DETECT_AT)
            delay = res["applied"]["params"]["delay"] * 400.0 - 200.0
            self.assertGreaterEqual(delay, 0.0, "Detect wrote a negative Delay at Window 0 (live)")
            self.assertEqual(latency(res), 0)


class DetectBattery(Timed):
    """The accuracy lines of the brief at every rate and on the hard pairs (render label: slower)."""
    label = "render"

    def test_drum_loop_at_every_rate(self):                                # brief: 0.02 ms, > 80 %
        for fs in RATES:
            with self.subTest(fs=fs), tempfile.TemporaryDirectory() as d:
                ref, trk, truth = M.drum_loop_pair(fs, 1)
                n = int(5.0 * fs)
                res, _ = render_pair(d, ref[:n], trk[:n], fs, detect_at=DETECT_AT)
                det = res["product"]["detects"][0]
                self.assertAlmostEqual(det["delay_ms"], -truth["delay_ms"], delta=0.02)
                self.assertTrue(det["inverted"])
                self.assertGreater(det["confidence_pct"], 80.0)

    def test_room_pair_within_0_1ms(self):                                 # brief: reverberant pair
        fs = 48000
        ref, trk, truth = M.room_pair(fs, 2)
        n = int(5.0 * fs)
        with tempfile.TemporaryDirectory() as d:
            res, _ = render_pair(d, ref[:n], trk[:n], fs, detect_at=DETECT_AT)
            det = res["product"]["detects"][0]
            self.assertAlmostEqual(det["delay_ms"], -truth["delay_ms"], delta=0.1)
            self.assertEqual(det["inverted"], truth["inverted"])

    def test_bass_di_amp_pair(self):                                       # G2: whitening exponent 1.0
        fs = 48000
        ref, trk, truth = M.di_amp_pair(fs, 3)
        n = min(len(ref), int(4.0 * fs))
        with tempfile.TemporaryDirectory() as d:
            res, _ = render_pair(d, ref[:n], trk[:n], fs, detect_at=3.9)
            det = res["product"]["detects"][0]
            self.assertAlmostEqual(det["delay_ms"], -truth["delay_ms"], delta=0.1,
                                   msg="the tonal pair locked onto the wrong period")


class Goldens(Timed):
    """F.13.6: one native golden, rendered on GOLDEN_ARCH, with a sidecar."""
    label = "render"

    def test_goldens_match(self):
        sidecars = sorted(GOLDEN_DIR.glob("*.json")) if GOLDEN_DIR.exists() else []
        if not sidecars:
            self.skipTest("no goldens in %s yet (render them with the harness, write <name>.json beside each)" % GOLDEN_DIR)
        for sc in sidecars:
            meta = json.loads(sc.read_text())
            with self.subTest(golden=sc.stem), tempfile.TemporaryDirectory() as d:
                out = Path(d) / "now.wav"
                flags = dict(meta["flags"])
                flags["out"] = out
                res = K.render(HARNESS, meta.get("params"), **flags)
                arch = res["applied"].get("build", {}).get("arch")
                kind = "same" if arch == meta.get("arch") else ("cross-feedback" if meta.get("feedback") else "cross-feedforward")
                now, fs = K.read_wav(out)
                gold, _ = K.read_wav(sc.with_suffix(".wav"))
                r = K.null_residual(gold, now, align=False)                   # a latency change must fail
                self.assertLess(r["peak_dbfs"], GOLDEN_PEAK_DB[kind],
                                "%s: residual against the golden (%s) - regenerate only with a changelog line (D.3.5)" % (sc.stem, kind))


SUITES = (Contract, RateAndBlock, Health, Properties, Path_, Defining, DetectBattery, Goldens)

if __name__ == "__main__":
    label = None
    if "--label" in sys.argv:
        i = sys.argv.index("--label")
        label = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    if label:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for cls in SUITES:
            if cls.label == label:
                suite.addTests(loader.loadTestsFromTestCase(cls))
        t0 = time.time()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        dt = time.time() - t0
        print("label %s: %.0f s" % (label, dt))
        sys.exit(0 if result.wasSuccessful() and (label != "fast" or dt < 3.0 * FAST_BUDGET_S) else 1)
    unittest.main(verbosity=2)
