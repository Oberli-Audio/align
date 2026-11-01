#!/usr/bin/env python3
"""perf - the CPU budget as a repeatable measurement (rule 20, D.2.1).

    perf.py run --harness H [--harness2 H_x86] [--presets all|slug,...] [--config 48000/64,44100/32]
                [--seconds 60] [--runs 3] [--warmup 200] [--notes 48,55,60,64] [--preset-at 30:slug]
                [--budget-p999 25] [--budget-max 50] [--idle-pct 2] [--arch x86_64]
                [--baseline docs/perf.json] [--write-baseline --reason "..."] [--md docs/perf.md] [--json out.json]
    perf.py selftest

For every (harness, preset, configuration) the harness renders --runs times with --profile.
Reported per cell: median p50 / p99 / p99.9, the maximum with its reading - "DSP" when
worst_block_at_s recurs within one block in at least two runs, "scheduling" when it moves
(D.2.1: read a maximum by where it falls) - over_deadline, the first block after prepare,
the preset-change spike (--preset-at), and the idle figure (a render with --gate 0.5 and
the rest silent). Judged: p99.9 and a recurring max per instance, the first block after
prepare, the idle figure, and the regression (p99 or a recurring max up by more than
--regress, 20 %, against the baseline of the same arch and machine tag). Reported, never
judged: over_deadline and a scheduling max; an offline normal-priority harness is
preempted now and then, and the friend playing the heaviest preset at 64 samples is the
dropout test (rule 20).

Exit 0 pass, 1 budget or regression, 2 inputs unusable. Local machine only at Tier P: on a
shared CI runner the absolute numbers are noise (D.3.6).
"""
import argparse
import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dspkit as K  # noqa: E402


def profile(harness, preset, fs, block, a, extra=None):
    """One harness run with --profile; returns the profile dict plus the echoed arch."""
    flags = dict(sample_rate=fs, block=block, seconds=a.seconds, seed=a.seed, profile=1, warmup=a.warmup, notes=a.notes)
    if a.gate:
        flags["gate"] = a.gate
    if preset:
        flags["preset"] = preset
    if extra:
        flags.update(extra)
    res = K.render(harness, **flags)
    if "profile" not in res:
        raise RuntimeError("harness returned no profile block")
    p = dict(res["profile"])
    p["arch"] = res.get("applied", {}).get("build", {}).get("arch")
    return p


def read_max(runs, block, fs):
    """DSP if the worst block recurs within one block in at least two runs, else scheduling."""
    pos = [r["worst_block_at_s"] for r in runs]
    tol = block / float(fs) * 1.5
    recurring = any(sum(abs(p - q) <= tol for q in pos) >= 2 for p in pos)
    worst = max(runs, key=lambda r: r["max_pct"])
    return {"max_pct": worst["max_pct"], "at_s": worst["worst_block_at_s"], "reading": "DSP" if recurring else "scheduling",
            "positions_s": pos}


def measure_cell(harness, preset, fs, block, a):
    saved, K.ARCH = K.ARCH, a.arch or K.ARCH   # a native harness is started under `arch -x86_64`; Python stays native
    try:
        runs = [profile(harness, preset, fs, block, a) for _ in range(a.runs)]
    finally:
        K.ARCH = saved                         # one cell's slice must not leak into the next

    archs = {r["arch"] for r in runs}
    if a.arch and archs != {a.arch}:
        raise RuntimeError("harness %s rendered on %s, expected %s (D.2.1: measure the slice the host runs)" % (harness, archs, a.arch))
    cell = {"arch": archs.pop() if len(archs) == 1 else sorted(archs), "runs": a.runs,
            "p50_pct": statistics.median(r["p50_pct"] for r in runs),
            "p99_pct": statistics.median(r["p99_pct"] for r in runs),
            "p999_pct": statistics.median(r["p999_pct"] for r in runs),
            "over_deadline": max(r["over_deadline"] for r in runs),
            "first_block_pct": statistics.median(r["first_block_pct"] for r in runs),
            "max": read_max(runs, block, fs)}
    if a.preset_at:
        pa = profile(harness, preset, fs, block, a, {"preset_at": a.preset_at})
        cell["preset_change_max_pct"] = pa["max_pct"]
        cell["preset_change_at_s"] = pa["worst_block_at_s"]
    return cell


def judge(cell, a, base=None):
    errs = []
    if cell["p999_pct"] > a.budget_p999:
        errs.append("p99.9 %.1f %% over the budget %.0f %%" % (cell["p999_pct"], a.budget_p999))
    if cell["max"]["reading"] == "DSP" and cell["max"]["max_pct"] > a.budget_max:
        errs.append("recurring max %.1f %% at %.2f s over the budget %.0f %%" % (cell["max"]["max_pct"], cell["max"]["at_s"], a.budget_max))
    # over_deadline is in the row and the JSON but never judged (rule 20): the harness thread is preempted now and then
    if cell["first_block_pct"] > 2.0 * max(cell["max"]["max_pct"], cell["p999_pct"]) and cell["first_block_pct"] > a.budget_max:
        errs.append("first block after prepare %.0f %% (lazy initialisation? D.2.1)" % cell["first_block_pct"])
    if base:
        if base.get("p99_pct") and cell["p99_pct"] > base["p99_pct"] * (1 + a.regress / 100.0):
            errs.append("p99 %.1f %% is %.0f %% above the baseline %.1f %%" % (cell["p99_pct"], 100 * (cell["p99_pct"] / base["p99_pct"] - 1), base["p99_pct"]))
        bm = base.get("max", {})
        if bm.get("reading") == "DSP" and cell["max"]["reading"] == "DSP" and cell["max"]["max_pct"] > bm["max_pct"] * (1 + a.regress / 100.0):
            errs.append("recurring max %.1f %% above the baseline %.1f %%" % (cell["max"]["max_pct"], bm["max_pct"]))
    return errs


def run(a):
    harnesses = [a.harness] + ([a.harness2] if a.harness2 else [])
    presets = [None] if a.presets == "default" else (None if a.presets == "all" else a.presets.split(","))
    if presets is None:
        presets = [p["slug"] for p in K.list_presets(a.harness)]
    configs = [(int(c.split("/")[0]), int(c.split("/")[1])) for c in a.config.split(",")]
    base = json.loads(Path(a.baseline).read_text()) if a.baseline and Path(a.baseline).exists() and not a.write_baseline else None
    report = {"machine": a.machine or platform.node(), "seconds": a.seconds, "runs": a.runs, "warmup": a.warmup,
              "budget": {"p999_pct": a.budget_p999, "max_pct": a.budget_max}, "cells": {}, "errors": []}
    for h in harnesses:
        for preset in presets:
            for fs, block in configs:
                cell = measure_cell(h, preset, fs, block, a)
                key = "%s|%s|%d/%d" % (cell["arch"], preset or "default", fs, block)
                bcell = (base or {}).get("cells", {}).get(key)
                if base and bcell and base.get("machine") != report["machine"]:
                    bcell = None  # another machine's baseline says nothing about this one
                errs = ["%s: %s" % (key, e) for e in judge(cell, a, bcell)]
                report["cells"][key] = cell
                report["errors"] += errs
        # idle: notes released early, the rest of the render silent
        if a.idle_pct is not None:
            idle = profile(h, presets[0], configs[0][0], configs[0][1], a, {"gate": 0.5, "seconds": max(a.seconds, 10.0)})
            report["cells"]["%s|idle|%d/%d" % (idle["arch"], configs[0][0], configs[0][1])] = {"p50_pct": idle["p50_pct"], "p99_pct": idle["p99_pct"]}
            if idle["p50_pct"] > a.idle_pct:
                report["errors"].append("idle p50 %.1f %% above %.0f %% after the tail (lazy stages, voice kill? D.2.5)" % (idle["p50_pct"], a.idle_pct))
    if a.write_baseline and a.baseline:
        report["reason"] = a.reason or ""
        Path(a.baseline).write_text(json.dumps(report, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1))
    md = markdown(report)
    if a.md:
        Path(a.md).write_text(md)
    print(md)
    for e in report["errors"]:
        print("ERROR: " + e)
    if report["errors"]:
        return 1
    print("perf OK: %d cell(s), every p99.9 and recurring max within budget%s" % (len(report["cells"]), ", no regression" if base else ""))
    return 0


def markdown(report):
    out = ["## CPU (rule 20) - %s, %d runs, %.0f s each" % (report["machine"], report["runs"], report["seconds"]), "",
           "| arch | preset | fs/block | p50 | p99 | p99.9 | max | reading | first block | over (reported) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for key, c in report["cells"].items():
        arch, preset, cfg = key.split("|")
        if "max" not in c:
            out.append("| %s | %s | %s | %.1f | %.1f | - | - | idle | - | - |" % (arch, preset, cfg, c["p50_pct"], c["p99_pct"]))
            continue
        out.append("| %s | %s | %s | %.1f | %.1f | %.1f | %.1f at %.2f s | %s | %.0f | %d |" % (
            arch, preset, cfg, c["p50_pct"], c["p99_pct"], c["p999_pct"], c["max"]["max_pct"], c["max"]["at_s"],
            c["max"]["reading"], c["first_block_pct"], c["over_deadline"]))
    return "\n".join(out) + "\n"


def selftest():
    import contextlib, os, tempfile

    @contextlib.contextmanager
    def env(**kv):
        old = {k: os.environ.get(k) for k in kv}
        os.environ.update({k: str(v) for k, v in kv.items()})
        try:
            yield
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    h = HERE / "fake_harness.py"
    ns = lambda **kw: argparse.Namespace(**dict(dict(harness=h, harness2=None, presets="all", config="48000/64", seconds=4.0, runs=3,
                                                     warmup=200, notes="48,55,60,64", gate=None, preset_at="2:edge", budget_p999=25.0,
                                                     budget_max=50.0, idle_pct=2.0, arch=None, baseline=None, write_baseline=False,
                                                     reason="", md=None, json=None, seed=1, regress=20.0, machine="selftest"), **kw))
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    a = ns()
    cell = measure_cell(h, "warm", 48000, 64, a)
    expect("first block reported", cell["first_block_pct"] > cell["p999_pct"])
    expect("preset-change spike is the recurring max", cell["max"]["reading"] == "DSP" and abs(cell["max"]["at_s"] - 2.0) < 0.01
           or cell.get("preset_change_max_pct", 0) > cell["p999_pct"])
    expect("no errors on the fake", not judge(cell, a))
    over = dict(cell); over["over_deadline"] = 3
    expect("over_deadline is reported, never judged", not judge(over, a) and "| 3 |" in markdown({"machine": "t", "runs": 3, "seconds": 4.0, "cells": {"x86_64|warm|48000/64": over}}))
    # a moving spike (seed-dependent position) reads as scheduling: fake jitter at block n+seed, three runs same seed -> recurring.
    # So vary the seed per run to make it move: emulate by three cells with different seeds
    runs = []
    for s in (1, 20, 40):
        with env(FAKE_JITTER_AT=1000):
            runs.append(profile(h, "warm", 48000, 64, ns(seed=s)))
    rm = read_max(runs, 64, 48000)
    expect("moving spike reads scheduling", rm["reading"] == "scheduling" and rm["max_pct"] > 50)
    with env(FAKE_JITTER_AT=1000):
        cell2 = measure_cell(h, "warm", 48000, 64, a)       # same seed every run -> recurs -> DSP, over budget
        expect("recurring spike fails the budget", any("recurring max" in e for e in judge(cell2, a)))
    # regression against a baseline
    base = dict(cell); base["p99_pct"] = cell["p99_pct"] / 2.0
    expect("regression caught", any("above the baseline" in e for e in judge(cell, a, base)))
    expect("no regression against itself", not judge(cell, a, cell))
    with env(FAKE_NO_IDLE=1), tempfile.TemporaryDirectory() as d:
        expect("idle failure caught", run(ns(presets="warm", json=Path(d) / "x.json")) == 1)
    # arch assertion
    try:
        measure_cell(h, "warm", 48000, 64, ns(arch="not-this-arch"))
        fails.append("arch mismatch not caught")
    except RuntimeError:
        pass
    # end to end with baseline file and markdown
    with tempfile.TemporaryDirectory() as d:
        b = Path(d) / "perf.json"
        expect("run writes baseline", run(ns(presets="warm", baseline=b, write_baseline=True, reason="selftest", md=Path(d) / "perf.md")) == 0 and b.exists())
        expect("run against baseline passes", run(ns(presets="warm", baseline=b)) == 0)
        expect("markdown written", "| x86_64 |" in (Path(d) / "perf.md").read_text() or "| arm64 |" in (Path(d) / "perf.md").read_text()
               or "| aarch64 |" in (Path(d) / "perf.md").read_text() or "| AMD64 |" in (Path(d) / "perf.md").read_text())
    if fails:
        print("perf selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("perf selftest OK: first block, preset-change spike, recurring vs scheduling maximum, over_deadline reported not judged, budget, regression, arch check, baseline round trip")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("--harness", required=True)
    s.add_argument("--harness2", help="a second harness binary (the other slice), e.g. the x86_64 build")
    s.add_argument("--presets", default="all", help="all | default | slug,slug")
    s.add_argument("--config", default="48000/64", help="fs/block list, e.g. 48000/64,44100/32")
    s.add_argument("--seconds", type=float, default=60.0)
    s.add_argument("--runs", type=int, default=3)
    s.add_argument("--warmup", type=int, default=200)
    s.add_argument("--notes", default="48,55,60,64")
    s.add_argument("--gate", type=float)
    s.add_argument("--preset-at", help="t:slug, a preset change during the render")
    s.add_argument("--budget-p999", type=float, default=25.0)
    s.add_argument("--budget-max", type=float, default=50.0)
    s.add_argument("--idle-pct", type=float, default=2.0)
    s.add_argument("--arch", help="the slice the host runs, e.g. x86_64: the harness is started under `arch -x86_64` on macOS and applied.build.arch is asserted; Python itself stays native")
    s.add_argument("--machine", help="machine tag for the baseline (default hostname)")
    s.add_argument("--baseline")
    s.add_argument("--write-baseline", action="store_true")
    s.add_argument("--reason", default="")
    s.add_argument("--regress", type=float, default=20.0, help="percent over the baseline that fails")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--md")
    s.add_argument("--json")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    try:
        return run(a)
    except (RuntimeError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print("perf: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
