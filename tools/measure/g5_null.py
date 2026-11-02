#!/usr/bin/env python3
"""G5: the port against the prototype, sample for sample (sound-design-bob F.8).

The same seeded material (`sound design/material.py`) and the same settings go through the numpy
prototype (`sound design/engine.py`, float64) and the real processor (the harness, float32), and the
residual is reported as F.8 asks: peak and RMS over the full render, absolute dBFS, **no
alignment** (a latency difference must fail), plus its spectrum's loudest third-octave band so a
failure says where it lives.

Both are driven the way a host drives the plugin: prepared at the parameter table's defaults, the
settings applied before the first block, blocks of 512. The settings are the prototype's
`reference_renders` list, so the G2 renders and this null are the same six cases.

The prototype runs its per-sample TPT Rotate here, the port's structure; its fast direct form
differs while the coefficient glides (measured: -78 dBFS against the port during a 0 -> 90 deg
glide, -126 dBFS with TPT).

Threshold (F.8 table): same structure, same arithmetic order, float with IIR state (the two
all-passes' one-pole state, the parameter smoothers) -> peak < -100 dBFS. The path has no long
feedback, so nothing should approach that.

    python3 tools/measure/g5_null.py                       # every setting at 48 kHz
    python3 tools/measure/g5_null.py --rates all --json build/g5.json
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dsp-kit"))
sys.path.insert(0, str(ROOT / "sound design"))
import dspkit as K  # noqa: E402
import material  # noqa: E402
import rotate  # noqa: E402
from engine import AlignEngine, Params, WINDOW_MS  # noqa: E402

# The prototype's fast Rotate is a direct form, identical to the TPT form for a *static* coefficient
# (--check rotate-structure) but not while the coefficient glides; G5 nulls against the structure
# the port has (F.8), so the per-sample TPT form, slower but the same machine.
rotate.FAST = False

HARNESS = os.environ.get("HARNESS", str(ROOT / "build/AlignHarness_artefacts/Release/AlignHarness"))
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
THRESHOLD_PEAK_DBFS = -100.0
BLOCK = 512


def settings(truth):
    """prototype.reference_renders' cases, in plain units."""
    d, inv = truth["delay_ms"], truth["inverted"]
    return {
        "init": Params(),
        "detected": Params(window=2, delay_ms=-d, polarity=inv),
        "rotate_90_below_110": Params(window=2, delay_ms=-d, polarity=inv, rotate_deg=90.0, below_hz=110.0),
        "live_window": Params(window=0, delay_ms=1.75, trim_db=-2.0),
        "wide_window": Params(window=4, delay_ms=-37.5, polarity=True, rotate_deg=180.0, below_hz=60.0, trim_db=3.0),
        "listen_sum": Params(window=2, delay_ms=-d, polarity=inv, listen=2),
    }


def normalised(p):
    """parameters.csv -> the harness's 0..1 (Source/Params.h ranges)."""
    return {
        "delay": (p.delay_ms + 200.0) / 400.0,
        "polarity": 1.0 if p.polarity else 0.0,
        "window": p.window / 4.0,
        "rotate": p.rotate_deg / 180.0,
        "below": ((p.below_hz - 30.0) / 970.0) ** 0.331680,
        "listen": p.listen / 2.0,
        "trim": (p.trim_db + 24.0) / 48.0,
        "bypass": 1.0 if p.bypass else 0.0,
    }


def as_rendered(p, plain):
    """The prototype's settings from the plain values the port's DSP read (product.params_plain):
    the host's 0..1 conversion is not what G5 tests, and on arm64 it is an FMA away from the
    decimal value (Delay 1.75 ms arrives as 1.7499924 ms, enough to pick the neighbouring kernel
    row at 44.1 kHz and to leave the whole-sample path at 192 kHz)."""
    return Params(delay_ms=plain["delay"], polarity=plain["polarity"] >= 0.5, window=int(round(plain["window"])),
                  rotate_deg=plain["rotate"], below_hz=plain["below"], listen=int(round(plain["listen"])),
                  trim_db=plain["trim"], bypass=plain["bypass"] >= 0.5)


def prototype(main, side, fs, p):
    eng = AlignEngine()
    eng.prepare(fs, BLOCK, Params())          # the defaults, as a freshly loaded plugin
    eng.set_params(p)                          # then the host's values, before the first block
    return eng.render(main.copy(), side.copy(), block=BLOCK).T, eng.latency_samples


def port(main, side, fs, p, d):
    a, b, out = Path(d) / "in.wav", Path(d) / "ref.wav", Path(d) / "out.wav"
    K.write_wav(a, main.T, fs)
    K.write_wav(b, side.T, fs)
    res = K.render(HARNESS, normalised(p), seed=1, sample_rate=fs, block=BLOCK, seconds=main.shape[1] / fs,
                   **{"in": a}, sidechain=b, out=out)
    y, _ = K.read_wav(out)
    return y, int(res["applied"]["latency_samples"]), res["product"]["params_plain"]


def loudest_band(residual, fs):
    """The third-octave band holding most of the residual's energy, for the characterisation."""
    r = residual[:, 0]
    spec = np.abs(np.fft.rfft(r)) ** 2
    f = np.fft.rfftfreq(len(r), 1.0 / fs)
    centres = 1000.0 * 2.0 ** (np.arange(-17, 14) / 3.0)
    energy = [float(spec[(f >= c * 2 ** (-1 / 6)) & (f < c * 2 ** (1 / 6))].sum()) for c in centres]
    return float(centres[int(np.argmax(energy))])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rates", default="48000", help="comma list or 'all'")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--json", help="write the rows here")
    a = ap.parse_args()
    rates = RATES if a.rates == "all" else tuple(int(r) for r in a.rates.split(","))
    rows, worst = [], -400.0
    with tempfile.TemporaryDirectory() as d:
        for fs in rates:
            ref, trk, truth = material.drum_loop_pair(fs, 1)
            n = int(a.seconds * fs)
            main_, side = np.stack([trk[:n]] * 2), np.stack([ref[:n]] * 2)
            for name, p in settings(truth).items():
                yc, lc, plain = port(main_, side, fs, p, d)
                yp, lp = prototype(main_, side, fs, as_rendered(p, plain))
                r = K.null_residual(yp, yc, align=False)
                band = loudest_band(yp[: len(yc)] - yc[: len(yp)], fs) if r["peak_dbfs"] > -300 else None
                row = dict(rate=fs, setting=name, latency_prototype=lp, latency_port=lc,
                           peak_dbfs=round(r["peak_dbfs"], 1), rms_dbfs=round(r["residual_dbfs"], 1),
                           loudest_band_hz=band, ok=bool(lp == lc and r["peak_dbfs"] < THRESHOLD_PEAK_DBFS))
                rows.append(row)
                worst = max(worst, r["peak_dbfs"])
                print("%6d  %-20s latency %6d/%-6d  peak %7.1f dBFS  rms %7.1f dBFS  %s" % (
                    fs, name, lp, lc, r["peak_dbfs"], r["residual_dbfs"], "ok" if row["ok"] else "FAIL"
                    + (" (band %.0f Hz)" % band if band else "")))
    ok = all(r["ok"] for r in rows)
    print("G5 null: %d/%d within %.0f dBFS, worst peak %.1f dBFS" % (sum(r["ok"] for r in rows), len(rows),
                                                                   THRESHOLD_PEAK_DBFS, worst))
    if a.json:
        Path(a.json).write_text(json.dumps({"threshold_peak_dbfs": THRESHOLD_PEAK_DBFS, "rows": rows}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
