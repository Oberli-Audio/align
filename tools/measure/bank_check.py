#!/usr/bin/env python3
"""G5: the factory bank measured as an effect (sound-design-bob F.14.3), and docs/presets.md.

`presetlint.py render` is shaped for instruments: it passes --notes/--gate, which an effect harness
ignores (contract: instruments only), so an effect renders the harness's default impulse - a sample
step of 0 dB and a loudness under the gate - and it compares a choice parameter's normalised echo
with its plain index. Until the kit handles effects (docs/status.md, Waiting for Björn) this is the
same set of checks with an effect's input: the seeded drum-loop pair through every preset.

Per preset: Init equals parameters.csv (normalised, every parameter); integrated loudness of the
output within +/-1 LU of the bank median (Tier P, Init excluded); true peak (16x) under -1 dBTP;
no NaN/Inf; max_click within +1 dB of the input's own (a preset must not add a click); the worst
block at 48 k/64 (rule 20, reported); the state round trip bytewise and render-identical.

    python3 tools/measure/bank_check.py --md docs/presets.md
"""
import argparse
import csv
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "tests"))
sys.path.insert(0, str(ROOT / "scripts" / "dsp-kit"))
import test_plugin as T  # noqa: E402
from test_plugin import K, M  # noqa: E402
import paramgen as PG  # noqa: E402

SPREAD_LU, CEILING_DBTP = 1.0, -1.0


def render(d, slug, **flags):
    return K.render(T.HARNESS, preset=slug, seed=1, **flags)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--md", help="write the preset list here (docs/presets.md)")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(ROOT / "presets.csv", encoding="utf-8")))
    table = PG.read_table(str(ROOT / "parameters.csv"))
    errs, out = [], {}
    fs = 48000
    ref, trk, _ = M.drum_loop_pair(fs, 1)
    n = int(4.0 * fs)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        K.write_wav(d / "trk.wav", T.stereo(trk[:n]), fs)
        K.write_wav(d / "ref.wav", T.stereo(ref[:n]), fs)
        x_in = T.stereo(trk[:n])
        in_click = K.max_click_db(x_in)

        # Init = the table's defaults, normalised as the contract echoes them
        applied = render(d, "init", signal="silence", seconds=0.1)["applied"]["params"]
        for p in table:
            if p["kind"] == "bypass":
                continue
            want = PG.to_normalised(p, p["fdefault"])
            if abs(float(applied[p["id"]]) - want) > 1e-4:
                errs.append("init: %s is %r, the table's default normalises to %.4f" % (p["id"], applied[p["id"]], want))

        for r in rows:
            s = r["slug"]
            res = render(d, s, **{"in": d / "trk.wav"}, sidechain=d / "ref.wav", sample_rate=fs, block=512,
                         seconds=n / fs, out=d / "o.wav")
            y, _ = K.read_wav(d / "o.wav")
            lat = int(res["applied"]["latency_samples"])
            y = y[lat:]                                   # the host compensates the reported latency
            lufs = K.integrated_lufs(y, fs)
            tp = K.true_peak_dbtp(y, fs, oversample=16)
            click = K.max_click_db(y)
            nan = res["health"]["nan"] + res["health"]["inf"]
            prof = K.render(T.HARNESS, preset=s, seed=1, sample_rate=48000, block=64, seconds=5.0, profile=1, warmup=200,
                            signal="noise:pink:-20", sidechain_signal="noise:pink:-20")["profile"]
            render(d, s, signal="silence", seconds=0.1, state_out=d / "a.state")
            ra = render(d, s, state_in=d / "a.state", state_out=d / "b.state", signal="noise:pink:-20",
                        sidechain_signal="noise:pink:-20", seconds=0.5, out=d / "a.wav")
            render(d, s, state_in=d / "b.state", signal="noise:pink:-20", sidechain_signal="noise:pink:-20",
                   seconds=0.5, out=d / "b.wav")
            same_state = (d / "a.state").read_bytes() == (d / "b.state").read_bytes()
            same_render = bool((K.read_wav(d / "a.wav")[0] == K.read_wav(d / "b.wav")[0]).all())
            out[s] = dict(name=r["name"], category=r["category"], edge=r["edge"], notes=r["notes"], lufs=lufs,
                          true_peak=tp, click_db=click, nan=nan, p999_pct=prof["p999_pct"], max_pct=prof["max_pct"],
                          latency_ms=lat / fs * 1e3, state_ok=same_state and same_render)
            if nan:
                errs.append("%s: %d NaN/Inf" % (s, nan))
            if tp > CEILING_DBTP:
                errs.append("%s: true peak %.2f dBTP above %.1f" % (s, tp, CEILING_DBTP))
            if click > in_click + 1.0:
                errs.append("%s: max_click %.2f dB, the input's own %.2f" % (s, click, in_click))
            if not out[s]["state_ok"]:
                errs.append("%s: state round trip not bytewise or not render-identical" % s)
            print("%-26s %7.2f LUFS  TP %6.2f dBTP  click %6.2f dB  p99.9 %5.2f %%  state %s" % (
                s, lufs, tp, click, prof["p999_pct"], "ok" if out[s]["state_ok"] else "FAIL"), flush=True)

    loud = {s: v["lufs"] for s, v in out.items() if s != "init"}
    med = statistics.median(loud.values())
    spread = max(abs(v - med) for v in loud.values())
    if spread > SPREAD_LU:
        errs.append("loudness: %.2f LU from the median; Tier P allows +/-%.1f" % (spread, SPREAD_LU))
    print("loudness: median %.2f LUFS, farthest %.3f LU (Tier P +/-%.1f); input max_click %.2f dB" % (med, spread, SPREAD_LU, in_click))

    if a.md:
        lines = ["# Factory presets", "",
                 "Generated by `python3 tools/measure/bank_check.py --md docs/presets.md` from `presets.csv` and",
                 "`presets/`; do not edit by hand. Delay, Polarity and Rotate are 0 in every preset: Detect measures",
                 "them per session, so a preset sets up a source pair (the Window, Static or Track, where Rotate",
                 "starts). Level: the seeded drum-loop pair through the preset, latency compensated, integrated;",
                 "offset from the bank median (Init excluded). Edge presets (the translation battery, F.7) are",
                 "marked with an asterisk.", "",
                 "| Preset | Category | Latency | Level | Notes |", "|---|---|---|---|---|"]
        for s, v in out.items():
            lines.append("| **%s**%s | %s | %.0f ms | %+.2f LU | %s |" % (v["name"], " *" if v["edge"] == "Y" else "", v["category"],
                                                                     v["latency_ms"], v["lufs"] - med, v["notes"]))
        Path(a.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps({"presets": out, "median_lufs": med, "spread_lu": spread, "errors": errs}, indent=1))
    for e in errs:
        print("ERROR:", e)
    print("bank_check: %d presets, %d error(s)" % (len(out), len(errs)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
