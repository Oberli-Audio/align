#!/usr/bin/env python3
"""G3: Align's metric table, every number measured on the port through the harness.

The suite (tools/tests/test_plugin.py) asserts thresholds; this prints the values behind them, one
row per line of the brief's quality targets and of E.11's "all effects" row, so docs/status.md can
quote each number with the command that produced it. Helpers and material are the suite's own, so
the table and the tests measure the same thing the same way.

    python3 tools/measure/g3_metrics.py                    # the table, markdown, about two minutes
    python3 tools/measure/g3_metrics.py --json build/g3.json --skip cpu

CPU (rule 20) is measured on the slice the brief budgets (x86_64 under Rosetta, 48 k/64, Track mode
with the 200 ms Window), three runs; it is only *judged* on the reference machine (an Apple M3 Pro,
the brief's cpu_reference_machine), and the machine is printed beside it.
"""
import argparse
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "tests"))
import test_plugin as T  # noqa: E402  (the suite's helpers, material and harness path)
from test_plugin import K, M  # noqa: E402

sys.path.insert(0, str(ROOT / "sound design"))
from prototype import _rotated  # noqa: E402  (the Rotate suggestion's truth generator)

ROWS = []


def row(metric, target, value, ok, method):
    ROWS.append(dict(metric=metric, target=target, value=value, ok=bool(ok), method=method))
    print("%-4s %-46s %-34s %s" % ("ok" if ok else "FAIL", metric, value, target), flush=True)


def latency_and_nulls(d):
    fs = 48000
    worst_err, lats = 0, []
    for ms in T.WINDOW_MS:
        x = T.impulse_at(fs, 0.5, 0.1)
        res, y = T.render_pair(d, x * 0.0, x, fs, {"window": T.n_window(ms)})
        measured = int(np.argmax(np.abs(y[:, 0]))) - int(0.1 * fs)
        worst_err = max(worst_err, abs(measured - T.latency(res)), abs(T.latency(res) - round(ms * 1e-3 * fs)))
        lats.append(T.latency(res))
    row("latency reported = measured = Window", "0 samples error, every Window",
        "%d samples worst; %s" % (worst_err, "/".join(map(str, lats))), worst_err == 0, "impulse at 0.1 s, 48 k, five Windows")

    x = M.pink_noise(fs, 1.0, seed=7) * 0.3
    s0, worst = int(T.SETTLE_S * fs), -400.0
    for ms in T.WINDOW_MS:
        res, y = T.render_pair(d, x, x, fs, {"window": T.n_window(ms)})
        L = T.latency(res)
        worst = max(worst, K.null_residual(T.stereo(x)[s0: len(x) - L], y[s0 + L:], align=False)["peak_dbfs"])
    row("null at Delay 0 / Polarity off / Rotate 0", "< -120 dBFS (brief thd_n: null)", "%.1f dBFS worst of 5 Windows" % worst,
        worst < -120.0, "pink noise, residual after latency compensation")

    res, y = T.render_pair(d, x, x, fs, {"delay": T.n_delay(-3.1), "polarity": 1.0, "rotate": T.n_rotate(120.0),
                                         "trim": T.n_trim(-6.0), "bypass": 1.0})
    L = T.latency(res)
    r = K.null_residual(T.stereo(x)[s0: len(x) - L], y[s0 + L:], align=False)["peak_dbfs"]
    row("bypass null against the compensated input", "< -120 dBFS (rule 7)", "%.1f dBFS" % r, r < -120.0,
        "bypass on with every control moved")


def fractional_delay(d):
    for fs in (44100, 48000):
        x = T.impulse_at(fs, 0.5, 0.1)
        res, y = T.render_pair(d, x * 0.0, x, fs, {"delay": T.n_delay(0.37)})
        at = int(round(0.1 * fs)) + T.latency(res)
        seg = y[at - 2048: at + 2048, 0] / 0.5
        n = 1 << 16
        H = np.fft.rfft(seg, n)
        f = np.fft.rfftfreq(n, 1.0 / fs)
        band = (f >= 20.0) & (f <= 18000.0)
        err = float(np.max(np.abs(20.0 * np.log10(np.abs(H[band])))))
        ph = np.unwrap(np.angle(H))
        i = int(np.argmin(np.abs(f - 1000.0)))
        gd = -(ph[i + 1] - ph[i - 1]) / (2.0 * np.pi * (f[i + 1] - f[i - 1])) * 1e3 - 2048.0 / fs * 1e3
        row("fractional delay flatness, %g k" % (fs / 1000), "< 0.05 dB to 18 kHz (brief)",
            "%.5f dB; delay %.5f ms" % (err, gd), err < 0.05 and abs(gd - 0.37) < 1e-3, "impulse through Delay 0.37 ms, FFT")


def rotate_stage(d):
    fs = 48000
    worst_mag, worst_ph = 0.0, 0.0
    for deg in (10.0, 45.0, 90.0, 135.0, 180.0):
        for below in (30.0, 120.0, 400.0, 1000.0):
            x = T.impulse_at(fs, 2.0, 0.2)
            _, y = T.render_pair(d, x * 0.0, x, fs, {"rotate": T.n_rotate(deg), "below": T.n_below(below),
                                                     "window": T.n_window(0.0)})
            h = y[int(0.2 * fs): int(0.2 * fs) + int(1.5 * fs), 0] / 0.5
            n = 1 << 18
            H = np.fft.rfft(h, n)
            f = np.fft.rfftfreq(n, 1.0 / fs)
            band = (f >= 20.0) & (f <= 20000.0)
            worst_mag = max(worst_mag, float(np.max(np.abs(20.0 * np.log10(np.abs(H[band]))))))
            ph = float(np.degrees(np.angle(H[int(np.argmin(np.abs(f - below)))])))
            worst_ph = max(worst_ph, abs((-ph - deg + 180.0) % 360.0 - 180.0))
    row("Rotate magnitude, 20 Hz - 20 kHz", "< 0.05 dB (G1)", "%.2e dB worst of 20 settings" % worst_mag, worst_mag < 0.05,
        "impulse, Rotate 10-180 x Below 30-1000 Hz")
    row("Rotate phase at Below vs the set angle", "< 1 deg (G1)", "%.3f deg worst" % worst_ph, worst_ph < 1.0,
        "the same renders; FFT bin nearest Below")


def detect(d):
    worst_err, worst_conf, flips, worst_ms = 0.0, 100.0, True, 0.0
    for fs in T.RATES:
        ref, trk, truth = M.drum_loop_pair(fs, 1)
        n = int(5.0 * fs)
        res, _ = T.render_pair(d, ref[:n], trk[:n], fs, detect_at=T.DETECT_AT)
        det = res["product"]["detects"][0]
        worst_err = max(worst_err, abs(det["delay_ms"] + truth["delay_ms"]))
        worst_conf = min(worst_conf, det["confidence_pct"])
        flips = flips and det["inverted"]
        worst_ms = max(worst_ms, det["elapsed_ms"])
    row("Detect, drum loop 2.317 ms flipped", "< 0.02 ms, flipped, > 80 % (brief)",
        "%.4f ms, %s, %.1f %% worst of 6 rates" % (worst_err, "flipped" if flips else "MISSED FLIP", worst_conf),
        worst_err < 0.02 and flips and worst_conf > 80.0, "4-bar seeded loop, press at 4.5 s")
    row("Detect time, press to result", "< 200 ms on the M3 Pro (brief)", "%.0f ms worst of 6 rates" % worst_ms,
        worst_ms < 200.0, "the harness's clock, worker poll included; %s" % platform.machine())

    fs = 48000
    for name, fn, seed, tol, at in (("room pair, 1.2 s RT60", M.room_pair, 2, 0.1, T.DETECT_AT),
                                    ("bass DI vs amp", M.di_amp_pair, 3, 0.1, 3.9)):
        ref, trk, truth = fn(fs, seed)
        n = min(len(ref), int(5.0 * fs))
        res, _ = T.render_pair(d, ref[:n], trk[:n], fs, detect_at=at)
        det = res["product"]["detects"][0]
        err = abs(det["delay_ms"] + truth["delay_ms"])
        row("Detect, %s" % name, "< %g ms (brief)" % tol, "%.4f ms, confidence %.1f %%" % (err, det["confidence_pct"]),
            err < tol, "seeded pair, 48 k")


def comb(d):
    fs, delay_ms = 48000, 2.317
    ref = M._tilt(M.drum_loop(fs, 1), fs, 300.0, 0.8, 1.0)
    trk = M.fractional_shift(ref.copy(), delay_ms * 1e-3 * fs)
    n = int(8.0 * fs)
    ref, trk = ref[:n], trk[:n]
    notch = 1.0 / (2.0 * delay_ms * 1e-3)
    res, y = T.render_pair(d, ref, trk, fs, detect_at=T.DETECT_AT)
    L, settle = T.latency(res), int((T.DETECT_AT + 0.1) * fs)
    before = T.notch_depth_db(y[L: int(T.DETECT_AT * fs), 0] + ref[: int(T.DETECT_AT * fs) - L], fs, notch)
    after = T.notch_depth_db(y[settle:, 0] + ref[settle - L: n - L], fs, notch)
    row("comb notch at %.1f Hz in the sum" % notch, "< -10 dB before, > -1.5 dB after (feature 2)",
        "%.1f dB -> %.1f dB" % (before, after), before < -10.0 and after > -1.5, "level-matched pair, Detect at 4.5 s")


def rotate_suggestion(d):
    fs = 48000
    base = M._tilt(M.drum_loop(fs, 11), fs, 180.0, 1.0, 0.25)
    n = int(5.0 * fs)
    cases = {}
    for name, inverse in (("reachable", True), ("other direction", False)):
        trk = M.fractional_shift(_rotated(base, fs, 70.0, 110.0, inverse=inverse), 2.317e-3 * fs)
        res, _ = T.render_pair(d, base[:n], trk[:n], fs, detect_at=T.DETECT_AT)
        cases[name] = res["product"]["detects"][0]["suggestion"]
    ref, trk, _ = M.drum_loop_pair(fs, 1)
    res, _ = T.render_pair(d, ref[:n], trk[:n], fs, detect_at=T.DETECT_AT)
    cases["delay only"] = res["product"]["detects"][0]["suggestion"]
    r, o, z = cases["reachable"], cases["other direction"], cases["delay only"]
    gain = r["corr_after"] - r["corr_before"]
    ok = r["needed"] and gain >= 0.05 and o["other_mic"] and not o["needed"] and not z["needed"] and not z["other_mic"]
    row("Rotate suggestion (low_register)", ">= +0.05 low-band corr, or says none/other mic",
        "+%.2f (%.2f -> %.2f); other mic: %s; delay-only: silent" % (gain, r["corr_before"], r["corr_after"],
                                                                     "said" if o["other_mic"] else "NOT SAID"),
        ok, "pair rotated 70 deg below 110 Hz each way; the drum pair")


def clicks(d):
    fs = 48000
    t = np.arange(2 * fs) / fs
    sine = 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)
    ref_click = K.max_click_db(T.stereo(sine))
    _, y = T.render_pair(d, sine * 0.0, sine, fs, block=64,
                         automate="delay:0.5=%r,1.5=%r" % (T.n_delay(0.0), T.n_delay(2.0)))
    over = K.peak_dbfs(y) - K.peak_dbfs(T.stereo(sine))
    row("Delay sweep 2 ms over 1 s, 1 kHz sine", "overshoot <= 0.01 dB (brief click)",
        "%.4f dB; max_click %.2f dB (sine %.2f)" % (over, K.max_click_db(y), ref_click),
        over <= 0.01 and K.max_click_db(y) <= ref_click + 1.0, "automation per 64-sample block")
    worst = -400.0
    for pid, on in (("polarity", 1.0), ("rotate", T.n_rotate(90.0)), ("listen", 1.0), ("bypass", 1.0)):
        _, y = T.render_pair(d, sine, sine, fs, {"window": T.n_window(0.0)}, block=64,
                             automate="%s:0.999=0,1.0=%r" % (pid, on))
        worst = max(worst, K.max_click_db(y))
    row("switches: polarity, Rotate, Listen, bypass", "max_click within +1 dB of the sine (rule 2)",
        "%.2f dB worst (sine %.2f)" % (worst, ref_click), worst <= ref_click + 1.0, "each switched at 1.0 s")


def mono_and_silence(d):
    fs = 48000
    x = M.pink_noise(fs, 1.0, seed=7) * 0.3
    _, y = T.render_pair(d, x, x, fs, {"rotate": T.n_rotate(150.0), "below": T.n_below(90.0), "delay": T.n_delay(-1.37),
                                       "polarity": 1.0, "trim": T.n_trim(3.0)})
    diff = float(np.max(np.abs(y[:, 0] - y[:, 1])))
    row("mono in, mono out (rule 15)", "L == R exactly", "max abs(L - R) = %g" % diff, diff == 0.0, "every stage engaged")
    res = T.run({"rotate": T.n_rotate(180.0), "below": T.n_below(30.0)}, signal="silence", sidechain_signal="silence",
                seconds=60.0, sample_rate=48000, block=64)
    h = res["health"]
    row("60 s of silence", "no NaN/Inf/denormals, DC < -80 dBFS", "NaN %d, Inf %d, DC %.0f dBFS" % (
        h["nan"], h["inf"], res["levels"]["dc_dbfs"]), h["nan"] + h["inf"] == 0 and res["levels"]["dc_dbfs"] < -80.0,
        "Rotate 180 at 30 Hz, the longest-ringing setting")


def track(d):
    fs = 48000
    loop = np.tile(M.drum_loop(fs, 1), 2)
    ref = M._tilt(loop, fs, 400.0, 0.55, 1.0)
    at = int(4.0 * fs)
    trk = np.concatenate([M.fractional_shift(ref.copy(), 2.317e-3 * fs)[:at],
                          M.fractional_shift(ref.copy(), 4.317e-3 * fs)[at:]])
    curve = {}
    for after in (1.0, 2.0, 3.0, 3.25, 3.5, 3.75, 4.0, 4.5):
        n = int((4.0 + after) * fs)
        res, _ = T.render_pair(d, ref[:n], trk[:n], fs, {"delay": T.n_delay(-2.317), "mode": 1.0}, non_realtime=1)
        curve[after] = res["product"]["track_offset_ms"]
    settled = next((a for a in sorted(curve) if abs(curve[a] + 2.0) <= 0.1), None)
    row("Track, 2 ms step", "settles within 3 s (G1; read as within 5 %)",
        "%.3f ms at 3 s; within 5 %% at %s" % (curve[3.0], "%.2f s" % settled if settled else "> 4.5 s"),
        settled is not None and settled <= 3.0, "offline (audio-time Track), 1 s frame, tau 1 s")
    return curve


def cpu():
    old = K.ARCH
    K.ARCH = "x86_64"
    try:
        runs = []
        for seed in (1, 2, 3):
            res = K.render(T.HARNESS, {"mode": 1.0, "window": T.n_window(200.0)}, seed=seed, sample_rate=48000, block=64,
                           seconds=20.0, profile=1, warmup=200, signal="noise:pink:-20", sidechain_signal="noise:pink:-20")
            runs.append(res["profile"])
            arch = res["applied"]["build"]["arch"]
    finally:
        K.ARCH = old
    machine = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    p999 = max(r["p999_pct"] for r in runs)
    mx = sorted(r["max_pct"] for r in runs)[1]                     # the recurring max: the median of three
    row("CPU, 48 k/64, Track, Window 200 ms (rule 20)", "p99.9 < 25 %, recurring max < 50 %",
        "p99.9 %.2f %%, max %.2f %% (%s, %s)" % (p999, mx, arch, machine), p999 < 25.0 and mx < 50.0,
        "three 20 s runs, harness --profile, over_deadline %s" % [r["over_deadline"] for r in runs])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--skip", default="", help="comma list: cpu, track, detect, ...")
    a = ap.parse_args()
    skip = set(filter(None, a.skip.split(",")))
    track_curve = None
    with tempfile.TemporaryDirectory() as d:
        steps = (("latency", latency_and_nulls), ("delay", fractional_delay), ("rotate", rotate_stage), ("detect", detect),
                 ("comb", comb), ("suggestion", rotate_suggestion), ("clicks", clicks), ("mono", mono_and_silence))
        for key, fn in steps:
            if key not in skip:
                fn(d)
        if "track" not in skip:
            track_curve = track(d)
    if "cpu" not in skip:
        cpu()
    print("\n| Metric | Target | Measured | | Method |\n|---|---|---|---|---|")
    for r in ROWS:
        print("| %s | %s | %s | %s | %s |" % (r["metric"], r["target"], r["value"], "ok" if r["ok"] else "**fail**", r["method"]))
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": ROWS, "track_curve": track_curve}, indent=1))
    failed = [r["metric"] for r in ROWS if not r["ok"]]
    print("\nG3 metrics: %d/%d within target%s" % (len(ROWS) - len(failed), len(ROWS), "; failing: " + ", ".join(failed) if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
