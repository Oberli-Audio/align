#!/usr/bin/env python3
"""Project test scaffold - copy to <project>/tools/tests/ and fill in the TODOs.

Drives the product's offline renderer (harness-contract.md v3) and asserts on its JSON and
WAVs with dspkit. Run directly, or register with CTest (snippet at the bottom):

    HARNESS=build/MyPluginHarness python3 -m unittest test_template -v
    HARNESS=... python3 test_template.py --label fast     # the inner loop (D.3.6: under 60 s)

Labels (D.3.1): fast = contract, rate/block matrix, health, properties (every build, < 60 s);
render = goldens and presence tests (every commit); the host validators are not here
(validate_plugin.py). Every test is a rule or a DoD line from the core card; the name says
which. Per-test seconds are printed; a `fast` test over FAST_BUDGET_S fails.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.environ.get("DSPKIT", str(Path(__file__).resolve().parent)))
import dspkit as K  # noqa: E402

HARNESS = os.environ.get("HARNESS", "build/{{ProductId}}Harness_artefacts/Release/{{ProductId}}Harness")
GOLDEN_DIR = Path(os.environ.get("GOLDEN_DIR", "tools/tests/golden"))   # committed goldens + sidecars
GOLDEN_ARCH = os.environ.get("GOLDEN_ARCH", "x86_64")                # D.2.1: the slice the host runs
DEFAULT = dict(seed=1, sample_rate=48000, block=512, seconds=2.0)
SOURCE = {{HarnessSourceDict}}
PARAM = ("outGain", 0.25)            # one real parameter ID and a non-default value
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
BLOCKS = (0, 1, 13, 32, 64, 512, 4096)
INSTRUMENT = "notes" in SOURCE
FAST_BUDGET_S = float(os.environ.get("FAST_BUDGET_S", "20"))   # one test; the whole `fast` label stays under 60 s
# F.8 tolerances (peak of the residual, absolute dBFS, no alignment): same machine and
# compiler bit-exact; across slices feed-forward -100, feedback tails -80.
GOLDEN_PEAK_DB = {"same": -140.0, "cross-feedforward": -100.0, "cross-feedback": -80.0}


def run(params=None, **flags):
    f = dict(DEFAULT, **SOURCE)
    f.update(flags)
    res = K.render(HARNESS, params, **f)
    echo = {k: v for k, v in f.items() if k in ("seed", "sample_rate", "block", "seconds", "preset")
            and not (k == "block" and str(v).startswith("random:"))}
    K.assert_echo(res, params, **echo)                                     # rule 13
    return res


class Timed(unittest.TestCase):
    label = "fast"

    def setUp(self):
        self._t0 = time.time()

    def tearDown(self):
        dt = time.time() - self._t0
        print("  [%s %.1f s]" % (self.label, dt), end="", flush=True)
        if self.label == "fast" and dt > FAST_BUDGET_S:
            self.fail("fast test took %.0f s; budget %.0f s (D.3.6: move it to a slower tier, do not delete it)" % (dt, FAST_BUDGET_S))


class Contract(Timed):
    def test_harness_echoes_params(self):                                  # rule 13
        pid, val = PARAM
        res = run({pid: val})
        self.assertAlmostEqual(res["applied"]["params"][pid], val, places=6)

    def test_seeded_runs_are_bit_identical(self):                          # DoD: reset + seed
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.wav", Path(d) / "b.wav"
            run(out=a)
            run(out=b)
            xa, _ = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertTrue((xa == xb).all(), "two seeded renders differ")


class RateAndBlock(Timed):
    def test_rate_block_matrix_is_clean(self):                             # DoD: 42 combinations
        for fs in RATES:
            for blk in BLOCKS:
                with self.subTest(fs=fs, block=blk):
                    res = run(sample_rate=fs, block=blk, seconds=0.25)
                    self.assertEqual(res["health"]["nan"] + res["health"]["inf"], 0)
                    self.assertLess(res["levels"]["peak_dbfs"], 0.0)

    def test_random_block_sizes_from_zero(self):                           # D.5.1, fuzz
        res = run(block="random:7", max_block=1024, seconds=0.5)
        self.assertEqual(res["health"]["nan"], 0)

    def test_block_larger_than_announced(self):                            # D.5.1
        # NaN-free is not enough: a plugin that renders only the announced part of an oversized
        # block leaves a silent gap. Compare, window by window, against the same render in
        # announced-size blocks (seen once: a 6 dB drop in one window, whole-file
        # RMS within 1 dB).
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "ref.wav", Path(d) / "big.wav"
            run(block=256, max_block=256, seconds=0.5, out=a)
            res = run(block=1024, max_block=256, seconds=0.5, out=b)
            self.assertEqual(res["health"]["nan"], 0)
            xa, fs = K.read_wav(a)
            xb, _ = K.read_wav(b)
            self.assertLess(K.dropout_db(xa, xb, fs), 3.0, "an oversized block rendered quieter than its announced-size twin")


class Health(Timed):
    def test_silence_after_notes_has_no_denormal_storm_or_dc(self):        # DoD: silence test, 48 k/64
        flags = dict(seconds=10.0, profile=1, sample_rate=48000, block=64, warmup=200)
        if INSTRUMENT:
            flags["gate"] = 0.5                                             # notes off early, the rest silent
        res = run(**flags)
        self.assertLess(res["levels"]["dc_dbfs"], -80.0)
        self.assertLess(res["profile"]["p999_pct"], 25.0)                  # rule 20: p99.9 judged
        print("over_deadline (reported, not judged, rule 20):", res["profile"]["over_deadline"])

    def test_latency_matches_impulse(self):                                # rule 7
        if INSTRUMENT:
            self.skipTest("effects only")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "imp.wav"
            res = run(signal="impulse", out=out)
            x, fs = K.read_wav(out)
            ref = x[:, :1] * 0.0
            ref[0, 0] = 0.5
            measured = K.latency_samples(ref, x[:, :1])
            self.assertEqual(measured, res["applied"]["latency_samples"])

    def test_tail_is_silent_after_reported_tail(self):                     # D.2.5, D.5.1
        if not INSTRUMENT:
            self.skipTest("instruments; effects feed an impulse instead")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "tail.wav"
            res = run(seconds=6.0, gate=1.0, out=out)
            x, fs = K.read_wav(out)
            after = x[int((1.0 + res["applied"]["tail_seconds"]) * fs):]
            self.assertLess(K.peak_dbfs(after) if after.size else -400.0, -90.0)


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
                        # a clean refusal (non-zero exit with a message) is acceptable; a crash is not
                        self.assertNotIn("Segmentation", str(e))
                        self.assertNotIn("-11", str(e).split(")")[0])
                        continue
                    self.assertEqual(res["health"]["nan"], 0)


class Goldens(Timed):
    """F.13.6: a golden per defining feature, rendered on GOLDEN_ARCH, with a sidecar."""
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


class DefiningFeatures(Timed):
    """Rule 13: one presence test per defining feature in the brief. Show each failing
    on a build without the feature (D.3.8) before trusting it."""
    label = "render"

    def test_feature_present(self):                                        # TODO
        self.skipTest("write one test per defining feature in brief.md")


# CTest registration (CMakeLists.txt of the project):
#   add_test(NAME py-fast   COMMAND ${Python3_EXECUTABLE} tools/tests/test_template.py --label fast)
#   add_test(NAME py-render COMMAND ${Python3_EXECUTABLE} tools/tests/test_template.py --label render)
#   set_tests_properties(py-fast PROPERTIES LABELS "fast" TIMEOUT 60 ENVIRONMENT "HARNESS=$<TARGET_FILE:MyPluginHarness>")
#   set_tests_properties(py-render PROPERTIES LABELS "render" TIMEOUT 600 ENVIRONMENT "HARNESS=$<TARGET_FILE:MyPluginHarness>")
# Then: ctest -L fast (inner loop), ctest -L render, ctest -LE validation.

if __name__ == "__main__":
    label = None
    if "--label" in sys.argv:
        i = sys.argv.index("--label")
        label = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    if label:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for cls in (Contract, RateAndBlock, Health, Properties, Goldens, DefiningFeatures):
            if cls.label == label:
                suite.addTests(loader.loadTestsFromTestCase(cls))
        t0 = time.time()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        dt = time.time() - t0
        print("label %s: %.0f s" % (label, dt))
        sys.exit(0 if result.wasSuccessful() and (label != "fast" or dt < 3.0 * FAST_BUDGET_S) else 1)
    unittest.main(verbosity=2)
