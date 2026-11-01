#!/usr/bin/env python3
"""Self-tests for dspkit.py - every measurement checked against a standard or an
analytic result before any product trusts it (rule 17, F.13.11).

    python3 test_dspkit.py          # unittest, ~20 s
"""
import json
import math
import unittest
import os
from pathlib import Path
import tempfile
import sys
import subprocess

import numpy as np
from scipy import signal

import dspkit as K


def sine(freq, dbfs, seconds, fs, phase=0.0, channels=2):
    t = np.arange(int(round(seconds * fs))) / fs
    x = 10.0 ** (dbfs / 20.0) * np.sin(2 * np.pi * freq * t + phase)
    return np.repeat(x[:, None], channels, axis=1)


def sequence(parts, fs, freq=1000.0):
    return np.vstack([sine(freq, d, s, fs) for d, s in parts])


class KWeighting(unittest.TestCase):
    def test_coefficients_match_bs1770_at_48k(self):
        sos = K.k_weighting_sos(48000)
        shelf = [1.53512485958697, -2.69169618940638, 1.19839281085285,
                 1.0, -1.69065929318241, 0.73248077421585]
        hp = [1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621]
        np.testing.assert_allclose(sos[0], shelf, atol=1e-8)
        np.testing.assert_allclose(sos[1], hp, atol=1e-8)

    def test_gain_at_1khz_is_rate_independent(self):
        # +0.69 dB at 1 kHz is what the -0.691 offset in BS.1770 cancels. The redesign from
        # the 48 kHz-fitted prototype moves it by 0.011 dB at 96 kHz and 0.020 dB at 192 kHz
        # (measured 2026-10-02) - far inside EBU's +/-0.1 LU; EBU case 1 passes at every rate.
        for fs in (44100, 48000, 88200, 96000, 192000):
            w, h = signal.sosfreqz(K.k_weighting_sos(fs), worN=[1000.0], fs=fs)
            self.assertAlmostEqual(20 * math.log10(abs(h[0])), 0.691, delta=0.03, msg=str(fs))


class EbuTech3341(unittest.TestCase):
    """Integrated loudness, EBU Tech 3341 minimum requirements (stereo, 1 kHz)."""

    def check(self, parts, expected, fs=48000):
        got = K.integrated_lufs(sequence(parts, fs), fs)
        self.assertAlmostEqual(got, expected, delta=0.1, msg="fs=%d got %.3f" % (fs, got))

    def test_case1_minus23(self):
        for fs in (44100, 48000, 88200, 96000, 176400, 192000):
            self.check([(-23.0, 20.0)], -23.0, fs)

    def test_case2_minus33(self):
        self.check([(-33.0, 20.0)], -33.0)

    def test_case3_relative_gate(self):
        self.check([(-36.0, 10.0), (-23.0, 60.0), (-36.0, 10.0)], -23.0)

    def test_case4_absolute_and_relative_gate(self):
        self.check([(-72.0, 10.0), (-36.0, 10.0), (-23.0, 60.0), (-36.0, 10.0), (-72.0, 10.0)], -23.0)

    def test_momentary_of_steady_tone(self):
        x = sequence([(-23.0, 5.0)], 48000)
        self.assertAlmostEqual(K.momentary_max_lufs(x, 48000), -23.0, delta=0.1)


class EbuTech3342(unittest.TestCase):
    """Loudness range, EBU Tech 3342 cases 1-3 (+/-1 LU)."""

    def check(self, a, b, expected):
        x = sequence([(a, 20.0), (b, 20.0)], 48000)
        self.assertAlmostEqual(K.loudness_range_lu(x, 48000), expected, delta=1.0)

    def test_case1(self):
        self.check(-20.0, -30.0, 10.0)

    def test_case2(self):
        self.check(-20.0, -15.0, 5.0)

    def test_case3(self):
        self.check(-40.0, -20.0, 20.0)


class Peaks(unittest.TestCase):
    def test_intersample_peak_of_quarter_rate_sine(self):
        fs = 48000
        x = sine(fs / 4.0, 0.0, 0.1, fs, phase=math.pi / 4)      # samples sit 45 deg off the peaks
        fade = int(0.01 * fs)                                     # an abrupt start would add Gibbs
        ramp = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2       # overshoot to the true peak (real,
        x[:fade] *= ramp[:, None]; x[-fade:] *= ramp[::-1, None]  # but not what this test is about)
        self.assertAlmostEqual(K.peak_dbfs(x), -3.01, delta=0.02)
        self.assertGreater(K.true_peak_dbtp(x, fs, oversample=16), -0.05)
        self.assertLess(K.true_peak_dbtp(x, fs, oversample=16), 0.05)

    def test_rms_and_crest_of_sine(self):
        x = sine(997.0, -6.0, 1.0, 48000)
        self.assertAlmostEqual(K.rms_dbfs(x), -9.01, delta=0.02)
        self.assertAlmostEqual(K.crest_factor_db(x), 3.01, delta=0.03)


class Comparison(unittest.TestCase):
    def test_latency_and_null(self):
        rng = np.random.default_rng(7)
        a = rng.standard_normal(48000) * 0.1
        b = np.concatenate([np.zeros(1234), a])[:48000]
        self.assertEqual(K.latency_samples(a, b), 1234)
        res = K.null_residual(a, b)
        self.assertEqual(res["lag"], 1234)
        self.assertLess(res["relative_db"], -200)

    def test_residual_of_small_gain_error(self):
        rng = np.random.default_rng(8)
        a = rng.standard_normal(48000) * 0.1
        res = K.null_residual(a, a * (1 + 1e-3), align=False)
        self.assertAlmostEqual(res["relative_db"], -60.0, delta=0.1)


class Distortion(unittest.TestCase):
    def test_pure_sine_has_no_harmonics(self):
        x = sine(1000.0, -1.0, 1.0, 48000, channels=1)
        self.assertLess(K.thd_db(x, 48000, 1000.0), -100.0)

    def test_quadratic_term_gives_known_second_harmonic(self):
        fs, f0 = 48000, 1000.0
        t = np.arange(fs) / fs
        x = np.cos(2 * np.pi * f0 * t)
        y = x + 0.01 * x ** 2              # H2 amplitude 0.005 -> -46.02 dB
        prof = K.harmonic_profile(y, fs, f0)
        self.assertAlmostEqual(prof["H2"], 20 * math.log10(0.005), delta=0.1)
        self.assertLess(prof["H3"], -100.0)


class Decay(unittest.TestCase):
    def test_t60_of_exponential_noise(self):
        fs, t60 = 48000, 1.5
        rng = np.random.default_rng(3)
        n = int(3 * t60 * fs)
        env = 10.0 ** (-3.0 * np.arange(n) / (t60 * fs))     # -60 dB at t60 (amplitude)
        ir = rng.standard_normal(n) * env
        self.assertAlmostEqual(K.schroeder_t60(ir, fs), t60, delta=0.05 * t60)


class RepeatVariation(unittest.TestCase):
    def test_identical_repeats_are_sterile(self):
        x = sine(220.0, -12.0, 1.0, 48000)
        r = K.repeat_variation([x, x.copy(), x.copy()], 48000)
        self.assertEqual(r["pairs"], 3)
        self.assertLess(r["min_residual_db"], -200.0)
        self.assertAlmostEqual(r["max_level_diff_db"], 0.0, places=6)

    def test_independent_noise_is_uncorrelated(self):
        rng = np.random.default_rng(5)
        segs = [rng.standard_normal((48000, 2)) * 0.1 for _ in range(3)]
        r = K.repeat_variation(segs, 48000)
        self.assertAlmostEqual(r["min_residual_db"], 3.01, delta=0.1)
        self.assertLess(r["max_level_diff_db"], 0.1)

    def test_level_change_between_repeats(self):
        x = sine(220.0, -12.0, 1.0, 48000)
        r = K.repeat_variation([x, x * K.undb(-1.0)], 48000)
        self.assertAlmostEqual(r["max_level_diff_db"], 1.0, places=3)
        self.assertAlmostEqual(r["max_env_diff_db"], 1.0, places=2)


class Cpu(unittest.TestCase):
    def test_block_time_report(self):
        rep = K.block_time_report([0.0001] * 99 + [0.001], 64, 48000)
        self.assertAlmostEqual(rep["deadline_ms"], 1.3333, places=3)
        self.assertAlmostEqual(rep["max_pct"], 75.0, places=3)
        self.assertEqual(rep["over_deadline"], 0)
        self.assertAlmostEqual(rep["worst_block_at_s"], 99 * 64 / 48000.0, places=6)

    def test_warmup_and_first_block(self):                                 # contract v3 profile
        rep = K.block_time_report([0.002] + [0.0001] * 98 + [0.0015], 64, 48000, warmup=10)
        self.assertAlmostEqual(rep["first_block_pct"], 150.0, places=3)     # reported, excluded
        self.assertEqual(rep["warmup_blocks"], 10)
        self.assertEqual(rep["blocks"], 90)
        self.assertEqual(rep["over_deadline"], 1)
        self.assertAlmostEqual(rep["max_pct"], 112.5, places=3)


class ClickAbsolute(unittest.TestCase):
    def test_max_click_db_is_absolute(self):                              # contract max_click_db
        x = sine(220.0, -6.0, 1.0, 48000)
        smooth = K.max_click_db(x, 48000)
        self.assertLess(smooth, -25.0)
        self.assertGreater(smooth, -40.0)
        x2 = x.copy()
        x2[24011:] *= -1.0                                               # away from a zero crossing
        self.assertGreater(K.max_click_db(x2, 48000), -8.0)
        quiet = x * 0.01                                                   # level-independent
        self.assertAlmostEqual(K.max_click_db(quiet, 48000), smooth, places=6)


class Residual(unittest.TestCase):
    def test_peak_and_rms_of_residual(self):
        a = sine(1000.0, -6.0, 0.5, 48000)
        b = a.copy()
        b[1000] += 1e-3
        r = K.null_residual(a, b, align=False)
        self.assertAlmostEqual(r["peak_dbfs"], -60.0, places=1)
        self.assertLess(r["residual_dbfs"], r["peak_dbfs"])


class Clicks(unittest.TestCase):
    def test_discontinuity_stands_out(self):
        x = sine(220.0, -6.0, 1.0, 48000, channels=1)[:, 0]
        fade = 480                                       # an abrupt start is itself a (small) click
        x[:fade] *= np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
        clean = K.click_score(x, 48000)
        x2 = x.copy()
        x2[24011:] *= -1.0                       # polarity flip away from a zero crossing = a click
        self.assertLess(clean, -80.0)
        self.assertGreater(K.click_score(x2, 48000), -30.0)


class HarnessContract(unittest.TestCase):
    """render() and assert_echo() against the fake harness - including the defect that
    invalidated Horizon Pad's G5 (a harness silently ignoring --param)."""

    def setUp(self):
        import os
        self.h = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_harness.py")

    def test_echo_accepted_when_applied(self):
        res = K.render(self.h, {"gain": 0.25}, seconds=0.1)
        self.assertTrue(K.assert_echo(res, {"gain": 0.25}))

    def test_echo_catches_a_dropped_param(self):
        import os
        os.environ["FAKE_DROP_PARAMS"] = "1"
        try:
            res = K.render(self.h, {"gain": 0.25}, seconds=0.1)
            with self.assertRaises(AssertionError):
                K.assert_echo(res, {"gain": 0.25})
        finally:
            del os.environ["FAKE_DROP_PARAMS"]

    def test_unknown_param_is_an_error(self):
        with self.assertRaises(RuntimeError):
            K.render(self.h, {"nope": 1.0}, seconds=0.1)

    def test_nan_exit_returns_json(self):                                  # contract: exit 3
        import os
        os.environ["FAKE_NAN"] = "1"
        try:
            res = K.render(self.h, seconds=0.2, notes="60")
            self.assertEqual(res.get("_exit"), 3)
            self.assertGreater(res["health"]["nan"], 0)
        finally:
            del os.environ["FAKE_NAN"]

    def test_arch_is_echoed_and_checked(self):                             # D.2.1 slices
        import platform
        res = K.render(self.h, seconds=0.1)
        self.assertTrue(K.assert_echo(res, arch=platform.machine()))
        with self.assertRaises(AssertionError):
            K.assert_echo(res, arch="not-an-arch")

    def test_list_presets_shape(self):
        ps = K.list_presets(self.h)
        self.assertEqual([p["slug"] for p in ps][0], "init")
        self.assertTrue(all({"slug", "name", "category"} <= set(p) for p in ps))


class PresetAndPerfTools(unittest.TestCase):
    """The two bank and budget tools prove their checks on planted defects (D.3.8)."""

    def test_dropout_catches_a_silent_gap(self):                           # D.5.1
        self.h = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_harness.py")
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.wav", Path(d) / "b.wav"
            K.render(self.h, notes="60", seconds=0.5, block=256, max_block=256, out=a)
            K.render(self.h, notes="60", seconds=0.5, block=1024, max_block=256, out=b)
            xa, fs = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertLess(K.dropout_db(xa, xb, fs), 1.0)
            env = dict(os.environ, FAKE_BLOCK_GAP="1")
            subprocess.run([sys.executable, self.h, "--notes=60", "--seconds=0.5", "--block=1024", "--max-block=256", "--out=%s" % b],
                           check=True, capture_output=True, env=env)
            xg, _ = K.read_wav(b)
            self.assertGreater(K.dropout_db(xa, xg, fs), 20.0)

    def test_presetlint_selftest(self):
        import subprocess, sys, os
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, os.path.join(here, "presetlint.py"), "selftest"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_perf_selftest(self):
        import subprocess, sys, os
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, os.path.join(here, "perf.py"), "selftest"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class ValidatePluginSanitizer(unittest.TestCase):
    """Under --sanitizer, a pluginval that cannot load the runtime fails the step loudly
    instead of falling back to the signed download (D.1.6)."""

    def run_pluginval(self, d, pluginval):
        env = {k: v for k, v in os.environ.items() if k != "PLUGINVAL"}
        env["OBERLI_TOOLS"] = os.path.join(d, "no-tools.toml")   # this machine's tools.toml must not supply pluginval.asan here
        if pluginval is not None:
            env["PLUGINVAL"] = str(pluginval)
        here = os.path.dirname(os.path.abspath(__file__))
        out = Path(d) / ("logs-%d" % len(os.listdir(d)))
        r = subprocess.run([sys.executable, os.path.join(here, "validate_plugin.py"), "--plugin", "/nonexistent.vst3",
                            "--only", "pluginval", "--sanitizer", "asan", "--out", str(out)],
                           capture_output=True, text=True, env=env, cwd=d)
        step = json.loads((out / "summary.json").read_text())["steps"][0]
        return r.returncode, step["status"], step["detail"]

    def test_unset_missing_or_uninstrumented_pluginval_fails(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "pluginval-plain"
            plain.write_bytes(b"\xcf\xfa\xed\xfe _main _juce_init")
            for pv, says in [(None, "needs PLUGINVAL"), ("~/pluginval-asan/pluginval", "use $HOME"),
                             (Path(d) / "missing", "is not a file"), (plain, "not built with asan")]:
                code, status, detail = self.run_pluginval(d, pv)
                self.assertEqual((code, status), (1, "FAIL"), detail)
                self.assertIn(says, detail)

    def test_instrumented_pluginval_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            asan = Path(d) / "pluginval-asan"
            asan.write_bytes(b"\xcf\xfa\xed\xfe _main ___asan_init ___asan_report_load8")
            code, status, detail = self.run_pluginval(d, asan)      # gets past pluginval, stops at the bundle
            self.assertEqual((code, status), (77, "SKIP"), detail)
            self.assertIn("no plugin bundle", detail)

    def test_soak_timeout_scales_with_the_sanitizer(self):
        # --step-timeout 1 x 5 repeats is 5 s plain, 50 s under asan; the stand-in takes 5.5 s
        with tempfile.TemporaryDirectory() as d:
            pv = Path(d) / "pluginval-asan"
            pv.write_text("#!%s\n# ___asan_init\nimport time\ntime.sleep(5.5)\nprint('SUCCESS')\n" % sys.executable)
            pv.chmod(0o755)
            (Path(d) / "Fake.vst3").mkdir()
            here = os.path.dirname(os.path.abspath(__file__))
            r = subprocess.run([sys.executable, os.path.join(here, "validate_plugin.py"), "--plugin", str(Path(d) / "Fake.vst3"),
                                "--profile", "soak", "--only", "pluginval_soak", "--sanitizer", "asan", "--step-timeout", "1",
                                "--out", str(Path(d) / "logs")],
                               capture_output=True, text=True, env=dict(os.environ, PLUGINVAL=str(pv)), cwd=d)
            step = json.loads((Path(d) / "logs" / "summary.json").read_text())["steps"][0]
            self.assertEqual((r.returncode, step["status"]), (0, "PASS"), step["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
