#!/usr/bin/env python3
"""presetlint - the preset bank as a tested deliverable (playbook F.14.3, D.8.8, D.6.5).

    presetlint.py bank   presets.csv parameters.csv [--harness H] [--tier P|F] [--track instrument|effect]
    presetlint.py render presets.csv parameters.csv --harness H [--tier P|F] [--notes 48,55,60,64]
                         [--seconds 6] [--gate 4] [--n 4] [--ceiling -1.0] [--budget-max 50]
                         [--baseline docs/presets.json] [--write-baseline] [--md docs/presets.md]
    presetlint.py sample [-o presets.csv]
    presetlint.py selftest

bank    the CSV alone: columns, slug and name rules, one init, categories, edge presets, bank
        size by tier; with --harness also that --list-presets equals the CSV in order.
render  per preset through the harness: Init equals the parameter table's defaults; seeded
        loudness spread (P: one render each, every preset within +/-1 LU of the bank median;
        F: --n renders each, mean, within +/-0.35 LU); true peak under the ceiling; health (NaN, clipping, click on note-off);
        CPU worst block per preset (rule 20); state round trip (state out, in, out: bytewise
        and render-identical); drift against a baseline (F.13.10). Writes the Markdown
        preset list for docs/presets.md and a JSON report.

presets.csv columns: slug,name,category,tags,edge,author,notes
  slug      ^[a-z0-9-]+$, unique, the file name (rule 10); exactly one row 'init'
  name      display name, 24 characters or fewer, no trailing period, unique case-insensitively
  category  one of the brief's fixed list (CATEGORIES below, override with --categories)
  tags      3-6 from a fixed vocabulary, '|'-separated (Tier F; may be empty at P)
  edge      Y for the 3-4 presets the translation battery runs on (F.7)
Exit codes: 0 pass, 1 a check failed, 2 the inputs are unusable.
"""
import argparse
import csv
import io
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dspkit as K  # noqa: E402
import paramgen as PG  # noqa: E402

CATEGORIES = ["Bed", "Motion", "Dark", "Bright", "Keys-like", "FX"]
BANK_SIZE = {("P", "instrument"): (12, 20), ("P", "effect"): (8, 12),
             ("F", "instrument"): (30, 60), ("F", "effect"): (30, 60), ("S", "instrument"): (1, 1), ("S", "effect"): (1, 1)}
SPREAD_LU = {"P": 1.0, "F": 0.35}   # +/- around the bank median (the brief's "+/-1 LU"), not loudest minus quietest
NAME_MAX = 24
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
COLUMNS = ["slug", "name", "category", "tags", "edge", "author", "notes"]

SAMPLE_CSV = """slug,name,category,tags,edge,author,notes
init,Init,Bed,,N,Oberli Audio,the parameter table's defaults
warm,Warm Bed,Bed,soft|wide|slow,N,Oberli Audio,
edge,Edge of Light,Bright,bright|wide|airy,Y,Oberli Audio,widest and brightest; translation battery
"""


class BankError(Exception):
    pass


def read_bank(path_or_text):
    text = path_or_text if "\n" in str(path_or_text) else Path(path_or_text).read_bytes().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise BankError("presets.csv is empty")
    missing = [c for c in COLUMNS[:5] if c not in rows[0]]
    if missing:
        raise BankError("presets.csv lacks column(s) %s" % ", ".join(missing))
    for r in rows:
        for c in COLUMNS:
            r[c] = (r.get(c) or "").strip()
        r["tag_list"] = [t for t in r["tags"].split("|") if t]
    return rows


# ----------------------------------------------------------------------------- bank

def check_bank(rows, tier="P", track="instrument", categories=None, listing=None):
    """Shape and names. Returns a list of error strings (empty = pass)."""
    cats = categories or CATEGORIES
    errs = []
    slugs = [r["slug"] for r in rows]
    for r in rows:
        s = r["slug"]
        if not SLUG_RE.match(s):
            errs.append("slug %r is not ^[a-z0-9-]+$ (rule 10: ASCII slugs, the display name lives inside)" % s)
        n = r["name"]
        if not n:
            errs.append("%s: empty name" % s)
        if len(n) > NAME_MAX:
            errs.append("%s: name %r is %d characters; %d at most" % (s, n, len(n), NAME_MAX))
        if n.endswith("."):
            errs.append("%s: name ends with a period" % s)
        if unicodedata.normalize("NFC", n) != n:
            errs.append("%s: name is not NFC-normalised" % s)
        if re.match(r"^(preset|patch)\s*\d+$", n.lower()):
            errs.append("%s: %r names nothing (F.14.3: the sound or the use)" % (s, n))
        if r["category"] not in cats:
            errs.append("%s: category %r not in %s" % (s, r["category"], cats))
        if r["edge"] not in ("Y", "N", ""):
            errs.append("%s: edge must be Y or N" % s)
        if tier == "F" and not 3 <= len(r["tag_list"]) <= 6:
            errs.append("%s: %d tags; Tier F asks for 3-6" % (s, len(r["tag_list"])))
    dup = sorted({s for s in slugs if slugs.count(s) > 1})
    if dup:
        errs.append("duplicate slug(s): %s" % ", ".join(dup))
    names = [r["name"].lower() for r in rows]
    dupn = sorted({n for n in names if names.count(n) > 1})
    if dupn:
        errs.append("duplicate name(s), case-insensitive: %s" % ", ".join(dupn))
    if slugs.count("init") != 1:
        errs.append("exactly one 'init' row is required (Init = the table defaults)")
    elif slugs[0] != "init":
        errs.append("'init' must be the first row (first in the list, F.14.3)")
    lo, hi = BANK_SIZE[(tier, track)]
    n_real = len([r for r in rows if r["slug"] != "init"])
    if tier != "S" and not lo <= n_real <= hi:
        errs.append("%d presets besides Init; Tier %s %s asks for %d-%d" % (n_real, tier, track, lo, hi))
    edges = [r for r in rows if r["edge"] == "Y"]
    if tier != "S" and not 1 <= len(edges) <= 4:
        errs.append("%d edge presets; mark 3-4 (widest, darkest, most reverb, loudest bass) for the translation battery" % len(edges))
    if listing is not None:
        want = [r["slug"] for r in rows]
        have = [p.get("slug") for p in listing]
        if have != want:
            errs.append("harness --list-presets differs from presets.csv: harness %s, csv %s" % (have, want))
        for p, r in zip(listing, rows):
            if p.get("slug") == r["slug"] and p.get("name") != r["name"]:
                errs.append("%s: harness name %r, csv %r" % (r["slug"], p.get("name"), r["name"]))
    return errs


# ----------------------------------------------------------------------------- render

def _render_args(a, extra=None):
    f = dict(sample_rate=48000, block=64, seconds=a.seconds, notes=a.notes, gate=a.gate, seed=a.seed)
    if extra:
        f.update(extra)
    return f


def check_init(harness, params, a):
    res = K.render(harness, preset="init", **_render_args(a, dict(seconds=0.5)))
    errs = []
    applied = res.get("applied", {}).get("params", {})
    for p in params:
        if p["kind"] == "bypass":
            continue
        want = PG.to_normalised(p, p["fdefault"]) if p["type"] != "choice" else p["fdefault"]
        got = applied.get(p["id"])
        if got is None:
            errs.append("init: harness did not echo %s" % p["id"])
            continue
        # the harness may echo normalised or plain; accept either within 1e-4
        if abs(float(got) - float(want)) > 1e-4 and abs(float(got) - float(p["fdefault"])) > 1e-4:
            errs.append("init: %s is %r, table default %r (normalised %.4f); Init must equal the table (F.14.3)"
                        % (p["id"], got, p["fdefault"], want))
    return errs


def check_loudness(harness, rows, a):
    """Per preset: integrated LUFS over the hold (seeded at P, mean of --n at F)."""
    errs, table = [], {}
    for r in rows:
        vals, tp, clicks, nans = [], [], [], 0
        runs = 1 if a.tier != "F" else a.n
        for i in range(runs):
            seed = a.seed if a.tier != "F" else a.seed + i
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / "r.wav"
                res = K.render(harness, preset=r["slug"], **_render_args(a, dict(seed=seed, out=out)))
                x, fs = K.read_wav(out)
                hold = x[: int(a.gate * fs)] if a.gate else x
                vals.append(K.integrated_lufs(hold, fs))
                tp.append(K.true_peak_dbtp(x, fs))
                clicks.append(res.get("health", {}).get("max_click_db", K.max_click_db(x, fs)))
                nans += res.get("health", {}).get("nan", 0) + res.get("health", {}).get("inf", 0)
        table[r["slug"]] = {"lufs": statistics.mean(vals), "swing": max(vals) - min(vals) if len(vals) > 1 else 0.0,
                            "true_peak": max(tp), "click_db": max(clicks), "nan": nans}
        if nans:
            errs.append("%s: %d NaN/Inf samples" % (r["slug"], nans))
        if max(tp) > a.ceiling:
            errs.append("%s: true peak %.1f dBTP above the ceiling %.1f" % (r["slug"], max(tp), a.ceiling))
        if max(clicks) > a.click_db:
            errs.append("%s: max_click_db %.1f dB above %.1f (click on note-off? D.10)" % (r["slug"], max(clicks), a.click_db))
    lufs = {s: v["lufs"] for s, v in table.items() if s != "init"} or {s: v["lufs"] for s, v in table.items()}
    med = statistics.median(lufs.values())
    spread = max(abs(v - med) for v in lufs.values())          # the farthest preset from the bank median
    span = max(lufs.values()) - min(lufs.values())
    limit = SPREAD_LU[a.tier if a.tier in SPREAD_LU else "P"]
    for s, v in table.items():
        v["offset"] = v["lufs"] - med
    if spread > limit:
        worst = sorted(lufs.items(), key=lambda kv: abs(kv[1] - med))[-2:]
        errs.append("loudness: the farthest preset is %.2f LU from the bank median, Tier %s allows +/-%.2f (integrated over the hold; span %.2f LU); farthest: %s"
                    % (spread, a.tier, limit, span, ", ".join("%s %+.2f" % (s, v - med) for s, v in worst)))
    return errs, {"median_lufs": med, "spread_lu": spread, "span_lu": span, "limit_lu": limit, "presets": table}


def check_cpu(harness, rows, a):
    """p99.9 per preset against the budget; a maximum over the budget counts only when it recurs at the
    same position in three runs (perf.py's reading: a moving maximum is the scheduler, not the DSP)."""
    import perf as P
    errs, table = [], {}
    fs, block = int(getattr(a, "sample_rate", 48000) or 48000), int(getattr(a, "block", 64) or 64)
    for r in rows:
        res = K.render(harness, preset=r["slug"], profile=1, warmup=200, **_render_args(a))
        prof = res.get("profile")
        if not prof:
            return ["harness returned no profile block (contract --profile)"], {}
        table[r["slug"]] = {k: prof.get(k) for k in ("p99_pct", "p999_pct", "max_pct", "over_deadline", "first_block_pct")}
        if prof.get("p999_pct", 0) > a.budget_p999:
            errs.append("%s: p99.9 %.1f %% of the deadline at %d/%d; budget %.0f (rule 20)"
                        % (r["slug"], prof.get("p999_pct", 0), fs, block, a.budget_p999))
        if prof.get("max_pct", 0) > a.budget_max:
            runs = [prof] + [K.render(harness, preset=r["slug"], profile=1, warmup=200, **_render_args(a)).get("profile", prof) for _ in range(2)]
            rm = P.read_max(runs, block, fs)
            table[r["slug"]]["max_reading"] = rm["reading"]
            if rm["reading"] == "DSP":
                errs.append("%s: recurring max %.1f %% of the deadline at %.2f s in three runs; budget %.0f (rule 20)"
                            % (r["slug"], rm["max_pct"], rm["at_s"], a.budget_max))
            else:
                table[r["slug"]]["note"] = "max %.1f %% moved between runs: scheduling, not DSP (perf.py)" % rm["max_pct"]
    if table:
        heaviest = max(table.items(), key=lambda kv: kv[1]["max_pct"] or 0)[0]
        table["_heaviest"] = heaviest
    return errs, table


def check_roundtrip(harness, rows, a):
    """state out -> state in -> state out: bytewise identical; renders bit-identical."""
    errs = []
    for r in rows:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ra = K.render(harness, preset=r["slug"], state_out=d / "a.state", out=d / "a.wav", **_render_args(a, dict(seconds=1.0)))
            rb = K.render(harness, state_in=d / "a.state", state_out=d / "b.state", out=d / "b.wav", **_render_args(a, dict(seconds=1.0)))
            if (d / "a.state").read_bytes() != (d / "b.state").read_bytes():
                errs.append("%s: state does not round-trip bytewise (D.5.3)" % r["slug"])
            pa, pb = ra["applied"].get("params", {}), rb["applied"].get("params", {})
            off = [k for k in pa if abs(float(pa[k]) - float(pb.get(k, 1e9))) > 1e-6]
            if off:
                errs.append("%s: parameters differ after state load: %s" % (r["slug"], ", ".join(off)))
            xa, _ = K.read_wav(d / "a.wav")
            xb, _ = K.read_wav(d / "b.wav")
            if xa.shape != xb.shape or not (xa == xb).all():
                errs.append("%s: render after state load is not bit-identical to the preset render" % r["slug"])
    return errs


def markdown(rows, loud, cpu):
    out = ["## Presets", "", "Generated by presetlint.py from presets.csv - do not edit.", "",
           "| Preset | Category | Tags | Level | CPU max | Notes |", "|---|---|---|---|---|---|"]
    for r in rows:
        l = loud.get("presets", {}).get(r["slug"], {})
        c = cpu.get(r["slug"], {})
        lvl = ("%+.1f LU" % l["offset"]) if "offset" in l else "-"
        cp = ("%.0f %%" % c["max_pct"]) if c.get("max_pct") is not None else "-"
        edge = " (edge)" if r["edge"] == "Y" else ""
        out.append("| **%s**%s | %s | %s | %s | %s | %s |" % (r["name"], edge, r["category"], ", ".join(r["tag_list"]) or "-", lvl, cp, r["notes"]))
    return "\n".join(out) + "\n"


def run_render(a):
    rows = read_bank(a.presets)
    params = PG.read_table(a.parameters)
    errs = check_bank(rows, a.tier, a.track, a.categories, K.list_presets(a.harness))
    errs += check_init(a.harness, params, a)
    e, loud = check_loudness(a.harness, rows, a)
    errs += e
    e, cpu = check_cpu(a.harness, rows, a)
    errs += e
    errs += check_roundtrip(a.harness, rows, a)
    report = {"tier": a.tier, "notes": a.notes, "gate": a.gate, "seconds": a.seconds, "seed": a.seed,
              "loudness": loud, "cpu": cpu, "errors": errs}
    if a.baseline and Path(a.baseline).exists() and not a.write_baseline:
        base = json.loads(Path(a.baseline).read_text())
        drift = {}
        for s, v in loud.get("presets", {}).items():
            b = base.get("loudness", {}).get("presets", {}).get(s)
            if b:
                drift[s] = v["lufs"] - b["lufs"]
                if abs(drift[s]) > a.drift_lu:
                    errs.append("%s: %+.2f LU against the baseline (bank drift, F.13.10; regenerate the bank or the baseline with a changelog line)" % (s, drift[s]))
        report["drift_lu"] = drift
    if a.write_baseline and a.baseline:
        Path(a.baseline).write_text(json.dumps(report, indent=1))
    if a.md:
        Path(a.md).write_text(markdown(rows, loud, cpu))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1))
    for e in errs:
        print("ERROR: " + e)
    n = len(rows)
    if errs:
        print("presetlint render: %d presets, %d error(s)" % (n, len(errs)))
        return 1
    print("presetlint render OK: %d presets, spread %.2f LU (limit %.2f), heaviest %s at %.0f %% max, round trip clean"
          % (n, loud["spread_lu"], loud["limit_lu"], cpu.get("_heaviest"), cpu.get(cpu.get("_heaviest"), {}).get("max_pct", 0)))
    return 0


def run_bank(a):
    rows = read_bank(a.presets)
    listing = K.list_presets(a.harness) if a.harness else None
    errs = check_bank(rows, a.tier, a.track, a.categories, listing)
    if a.parameters and a.harness:
        errs += check_init(a.harness, PG.read_table(a.parameters), a)
    for e in errs:
        print("ERROR: " + e)
    if errs:
        print("presetlint bank: %d presets, %d error(s)" % (len(rows), len(errs)))
        return 1
    print("presetlint bank OK: %d presets, Tier %s %s%s" % (len(rows), a.tier, a.track, ", matches the harness" if listing else ""))
    return 0


# ----------------------------------------------------------------------------- selftest

def selftest():
    """Every check shown failing on a planted defect before it is trusted (D.3.8)."""
    import contextlib

    @contextlib.contextmanager
    def env(**kv):
        old = {k: os.environ.get(k) for k in kv}
        os.environ.update({k: str(v) for k, v in kv.items()})
        try:
            yield
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    harness = HERE / "fake_harness.py"
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "presets.csv").write_text(SAMPLE_CSV)
        (d / "parameters.csv").write_text(PARAMS_CSV)
        ns = lambda **kw: argparse.Namespace(**dict(dict(presets=d / "presets.csv", parameters=d / "parameters.csv", harness=harness,
                                                          tier="S", track="instrument", categories=None, notes="48,55,60,64", gate=2.0,
                                                          seconds=3.0, seed=1, n=2, ceiling=-0.5, click_db=-6.0, budget_p999=25.0,
                                                          budget_max=50.0, baseline=None, write_baseline=False, md=None, json=None,
                                                          drift_lu=0.5), **kw))
        fails = []
        def expect(label, cond):
            if not cond:
                fails.append(label)
        # bank: good sample passes at S (3 presets); fails P size rule; planted defects
        rows = read_bank(SAMPLE_CSV)
        expect("bank passes at S", not check_bank(rows, "S"))
        expect("bank size rule at P", any("asks for 12-20" in e for e in check_bank(rows, "P")))
        bad = read_bank(SAMPLE_CSV.replace("warm,Warm Bed", "Warm,Warm Bed"))
        expect("slug rule", any("not ^[a-z0-9-]+$" in e for e in check_bank(bad, "S")))
        bad = read_bank(SAMPLE_CSV.replace("Edge of Light", "A Very Long Preset Name Indeed."))
        expect("name length and period", sum(("characters" in e) + ("period" in e) for e in check_bank(bad, "S")) == 2)
        bad = read_bank(SAMPLE_CSV.replace("edge,Edge of Light,Bright", "edge,Edge of Light,Lush"))
        expect("category list", any("not in" in e for e in check_bank(bad, "S")))
        bad = read_bank(SAMPLE_CSV.replace("init,Init", "warm2,Init"))
        expect("one init", any("exactly one 'init'" in e for e in check_bank(bad, "S")))
        with env(FAKE_SLUG_DUP=1):
            expect("harness listing diff", any("--list-presets differs" in e for e in check_bank(rows, "S", listing=K.list_presets(harness))))
        expect("harness listing equal", not check_bank(rows, "S", listing=K.list_presets(harness)))
        # init = defaults
        params = PG.read_table(d / "parameters.csv")
        expect("init equals defaults", not check_init(harness, params, ns()))
        with env(FAKE_INIT_OFF=1):
            expect("init off caught", any("Init must equal the table" in e for e in check_init(harness, params, ns())))
        # loudness: the sample bank spans about 5 LU (init -? / warm -6 / edge +3): fails at P on purpose...
        a = ns(tier="P")
        e, loud = check_loudness(harness, rows, a)
        expect("spread reported", "spread_lu" in loud and loud["spread_lu"] > 0)
        # ...so test the pass path with the offset switch pulling edge down to init's level
        with env(FAKE_LOUD="edge:-3"):
            e2, loud2 = check_loudness(harness, rows, a)
            expect("spread shrinks with the offset", loud2["spread_lu"] < loud["spread_lu"])
        with env(FAKE_LOUD="warm:+20"):
            e3, _ = check_loudness(harness, rows, a)
            expect("spread failure", any("from the bank median" in e for e in e3))
        with env(FAKE_NAN=1):
            e4, _ = check_loudness(harness, rows, a)
            expect("nan failure", any("NaN" in e for e in e4))
        with env(FAKE_CLICK=1):
            e5, _ = check_loudness(harness, rows, a)
            expect("click on note-off", any("click" in e for e in e5))
        # cpu
        e, cpu = check_cpu(harness, rows, a)
        expect("cpu passes", not e and cpu.get("_heaviest"))
        with env(FAKE_JITTER_AT=400):
            e6, _ = check_cpu(harness, rows, ns(tier="P", budget_max=50.0))
            expect("cpu spike caught", any("budget" in e for e in e6))
        # round trip
        expect("round trip clean", not check_roundtrip(harness, rows, a))
        with env(FAKE_STATE_DRIFT=1):
            expect("round trip drift caught", any("round-trip" in e or "differ after state load" in e for e in check_roundtrip(harness, rows, a)))
        # markdown
        md = markdown(rows, loud, cpu)
        expect("markdown has every preset", all(r["name"] in md for r in rows))
    if fails:
        print("presetlint selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("presetlint selftest OK: bank rules, harness listing, Init = defaults, loudness distance from the median, NaN, click, recurring CPU maximum, round trip - each shown failing on a planted defect")
    return 0


PARAMS_CSV = """id,version_added,type,kind,name,short,group,core,unit,min,max,default,centre,bipolar,choices,steps,format_kind,precision,parse_aliases,automatable,smoothing,smoothing_domain,control_rate,meaning,tooltip,notes
gain,1,float,plain,Gain,Gain,Output,Y,%,0,100,75,,N,,0,percent,0,,Y,20,linear,block,quiet / voiced / loud,Output level of the pad,
tone,1,float,plain,Tone,Tone,Colour,Y,%,0,100,50,,N,,0,percent,0,,Y,20,linear,block,dark / warm / open,Brightness of the top layer,
mode,1,choice,plain,Mode,Mode,Space,Y,,0,2,0,,N,Hall|Plate|Room,3,choice,0,,Y,0,crossfade,event,,Reverb character,
bypass,1,bool,bypass,Bypass,Bypass,Output,N,,0,1,0,,N,,2,bool,0,,Y,0,crossfade,event,,Bypass the plugin (latency compensated),
"""


# ----------------------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("bank", "render"):
        s = sub.add_parser(name)
        s.add_argument("presets")
        s.add_argument("parameters", nargs="?" if name == "bank" else None)
        s.add_argument("--harness", required=(name == "render"))
        s.add_argument("--tier", choices=("S", "P", "F"), default="P")
        s.add_argument("--track", choices=("instrument", "effect"), default="instrument")
        s.add_argument("--categories", type=lambda v: v.split(","), help="comma-separated fixed list (default: %s)" % ",".join(CATEGORIES))
        s.add_argument("--notes", default="48,55,60,64", help="reference chord (brief: default C3-E3-G3-C4 as MIDI notes)")
        s.add_argument("--gate", type=float, default=4.0, help="note-off time in seconds (loudness window = the hold)")
        s.add_argument("--seconds", type=float, default=8.0)
        s.add_argument("--seed", type=int, default=1)
        s.add_argument("--n", type=int, default=4, help="renders per preset at Tier F")
        s.add_argument("--ceiling", type=float, default=-1.0, help="true-peak ceiling in dBTP")
        s.add_argument("--click-db", type=float, default=-6.0, help="max_click_db above this is a click")
        s.add_argument("--budget-p999", type=float, default=25.0)
        s.add_argument("--budget-max", type=float, default=50.0)
        s.add_argument("--baseline", help="JSON report of the previous release (drift check)")
        s.add_argument("--write-baseline", action="store_true")
        s.add_argument("--drift-lu", type=float, default=0.5)
        s.add_argument("--md", help="write the Markdown preset list here (docs/presets.md)")
        s.add_argument("--json", help="write the JSON report here")
    sub.add_parser("selftest")
    sub.add_parser("sample").add_argument("-o", "--out")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "sample":
        (Path(a.out).write_text(SAMPLE_CSV) if a.out else sys.stdout.write(SAMPLE_CSV))
        return 0
    try:
        return run_bank(a) if a.cmd == "bank" else run_render(a)
    except (BankError, PG.TableError, OSError, subprocess.CalledProcessError, RuntimeError) as e:
        print("presetlint: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
