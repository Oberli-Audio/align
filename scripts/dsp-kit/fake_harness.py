#!/usr/bin/env python3
"""A small instrument-shaped renderer that implements harness-contract.md (v3), used only
to test the kit: dspkit.render/assert_echo, test_template.py, presetlint.py and perf.py.

Sound: a sum of sines for --notes with a 50 ms attack and 200 ms release at --gate, through
a gain parameter, 32 samples of latency. Three factory presets: init (= table defaults),
warm (-6 dB), edge (+3 dB, flagged edge). Block times are synthetic and deterministic from
the seed: a 5x spike in the first block and at every --preset-at change, so perf.py's
recurring-vs-scheduling split is testable.

Environment switches (so the kit can prove its checks fail, D.3.8):
  FAKE_DROP_PARAMS=1   ignore --param (Horizon Pad's 2026 bug)
  FAKE_NAN=1           inject a NaN and exit 3
  FAKE_LOUD=slug:dB    offset one preset's level by dB (loudness spread failure)
  FAKE_SLUG_DUP=1      --list-presets repeats a slug
  FAKE_INIT_OFF=1      the init preset differs from the table defaults
  FAKE_JITTER_AT=n     add a moving spike at block n + seed (a scheduling maximum)
  FAKE_STATE_DRIFT=1   --state-in loads gain 1 % off (round-trip failure)
  FAKE_CLICK=1         a step at the gate (click on note-off)
  FAKE_NO_IDLE=1       block cost stays at 4 % after the tail (idle failure)
  FAKE_BLOCK_GAP=1     a block larger than --max-block renders only its first max-block samples (silent gap)
"""
import json
import os
import platform
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import dspkit as K  # noqa: E402

PARAMS = {"gain": {"default": 0.75, "steps": 0, "automatable": True},
          "tone": {"default": 0.5, "steps": 0, "automatable": True},
          "mode": {"default": 0.0, "steps": 3, "automatable": True}}
PRESETS = [{"slug": "init", "name": "Init", "category": "Bed", "params": {"gain": 0.75, "tone": 0.5, "mode": 0.0}},
           {"slug": "warm", "name": "Warm Bed", "category": "Bed", "params": {"gain": 0.5, "tone": 0.3, "mode": 0.0}},
           {"slug": "edge", "name": "Edge of Light", "category": "Bright", "params": {"gain": 0.875, "tone": 0.9, "mode": 2.0}}]
if os.environ.get("FAKE_INIT_OFF"):
    PRESETS[0]["params"]["tone"] = 0.6


def gain_db(g):
    return -24.0 + 24.0 * g + (3.0 if g > 0.8 else 0.0)   # edge sits +3 dB above init on purpose


def main(argv):
    args = {"seed": "1", "sample-rate": "48000", "block": "512", "seconds": "2.0", "signal": "",
            "notes": "", "gate": "", "warmup": "0", "preset": "", "max-block": ""}
    repeat = {"preset-at": [], "reprepare-at": []}
    params = {k: v["default"] for k, v in PARAMS.items()}
    applied_preset = None
    state_in = None
    if "--help" in argv or "-h" in argv:
        print(__doc__.rstrip())
        print("\nFlags, --flag=value form (harness-contract.md): --seed=N --sample-rate=HZ --block=N|random:SEED\n"
              "  --max-block=N --seconds=S --notes=60,64,67 --gate=S --signal=impulse|sine:HZ:DBFS --preset=SLUG\n"
              "  --param=ID=VALUE (repeatable) --preset-at=T:SLUG --reprepare-at=T (repeatable) --warmup=N --profile=1\n"
              "  --state-in=FILE --state-out=FILE --out=FILE.wav --list-presets --list-params\n"
              "Prints one JSON object (applied state, metrics, profile) on stdout; exit 0 ok, 2 bad input, 3 NaN/Inf.\n"
              "Only for testing the kit: python3 test_dspkit.py runs it; a product's own harness replaces it.")
        return 0
    for a in argv:
        if a == "--list-presets":
            ps = [{"slug": p["slug"], "name": p["name"], "category": p["category"]} for p in PRESETS]
            if os.environ.get("FAKE_SLUG_DUP"):
                ps.append(dict(ps[1]))
            print(json.dumps(ps))
            return 0
        if a == "--list-params":
            print(json.dumps([{"id": k, "default": v["default"], "steps": v["steps"],
                               "automatable": v["automatable"]} for k, v in PARAMS.items()]))
            return 0
        k, _, v = a[2:].partition("=")
        if k == "param":
            pid, _, val = v.partition("=")
            if pid not in params:
                print("unknown parameter " + pid, file=sys.stderr)
                return 2
            if not os.environ.get("FAKE_DROP_PARAMS"):
                params[pid] = float(val)
        elif k == "preset":
            match = [p for p in PRESETS if p["slug"] == v]
            if not match:
                print("unknown preset " + v, file=sys.stderr)
                return 2
            params.update(match[0]["params"])
            applied_preset = v
        elif k == "state-in":
            state_in = json.load(open(v))
            params.update(state_in.get("params", {}))
            if os.environ.get("FAKE_STATE_DRIFT"):
                params["gain"] *= 1.01
            applied_preset = state_in.get("preset")
        elif k in repeat:
            repeat[k].append(v)
        else:
            args[k] = v

    fs = int(args["sample-rate"])
    seed = int(args["seed"])
    seconds = float(args["seconds"])
    n = int(seconds * fs)
    blk_arg = args["block"]
    rng = np.random.default_rng(seed)
    if blk_arg.startswith("random:"):
        brng = np.random.default_rng(int(blk_arg.split(":")[1]))
        max_block = int(args["max-block"] or 1024)
        sizes = []
        total = 0
        while total < n:
            b = int(brng.integers(0, max_block + 1))
            sizes.append(b)
            total += b
        block_nominal = max_block
    else:
        block_nominal = int(blk_arg)
        max_block = int(args["max-block"] or block_nominal)
        sizes = [block_nominal] * (n // max(block_nominal, 1)) + ([n % block_nominal] if block_nominal and n % block_nominal else [])

    # --- the "DSP": additive sines with attack/release, gain, 32 samples latency
    notes = [int(x) for x in args["notes"].split(",") if x.strip()] if args["notes"] else []
    t = np.arange(n) / fs
    x = np.zeros(n)
    if notes:
        for m in notes:
            f = 440.0 * 2 ** ((m - 69) / 12.0)
            x += np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi) * 0.0) / len(notes)
        env = np.minimum(1.0, t / 0.05)
        if args["gate"]:
            g = float(args["gate"])
            rel = np.clip(1.0 - (t - g) / 0.2, 0.0, 1.0)
            env = env * np.where(t < g, 1.0, rel)
        x *= env
        if args["gate"] and os.environ.get("FAKE_CLICK"):
            gi = min(int(float(args["gate"]) * fs), n - 1)
            x[gi] += 0.9                                   # a one-sample step at note-off
    elif args["signal"] == "impulse":
        x[0] = 0.5
    elif args["signal"].startswith("sine"):
        _, hz, dbfs = (args["signal"].split(":") + ["1000", "-20"])[:3]
        x = 10 ** (float(dbfs) / 20.0) * np.sin(2 * np.pi * float(hz) * t)
    tone = 1.0 - 0.3 * (1.0 - params["tone"])
    y = np.concatenate([np.zeros(32), x])[:n] * 10.0 ** (gain_db(params["gain"]) / 20.0) * tone
    if os.environ.get("FAKE_BLOCK_GAP") and block_nominal > max_block:
        pos = 0                                                # the rest of an oversized block stays silent (a real bug seen once)
        for b in sizes:
            y[pos + max_block: pos + b] = 0.0
            pos += b
    loud = os.environ.get("FAKE_LOUD", "")
    if loud and applied_preset and loud.split(":")[0] == applied_preset:
        y *= 10.0 ** (float(loud.split(":")[1]) / 20.0)
    if os.environ.get("FAKE_NAN"):
        y[n // 2] = float("nan")
    y2 = np.stack([y, y], axis=1)
    if "out" in args:
        K.write_wav(args["out"], y2, fs)
    if "state-out" in args:
        json.dump({"version": 1, "preset": applied_preset, "params": params}, open(args["state-out"], "w"))

    nan = int(np.isnan(y).sum())
    res = {"contract": 3,
           "applied": {"seed": seed, "sample_rate": fs, "block": block_nominal, "max_block": max_block,
                       "seconds": seconds, "preset": applied_preset, "solo": None,
                       "params": params, "notes": notes, "gate": float(args["gate"]) if args["gate"] else None,
                       "latency_samples": 32, "tail_seconds": 0.2,
                       "preset_at": repeat["preset-at"], "reprepare_at": repeat["reprepare-at"],
                       "build": {"commit": "fake", "config": "Release", "arch": platform.machine()}},
           "levels": {"peak_dbfs": K.peak_dbfs(y2) if np.any(y2) else -400.0, "rms_dbfs": K.rms_dbfs(y2),
                      "true_peak_dbtp": K.true_peak_dbtp(y2, fs) if np.any(y2) else -400.0,
                      "dc_dbfs": K.dc_offset_dbfs(y2)},
           "health": {"nan": nan, "inf": int(np.isinf(y).sum()),
                      "clipped_samples": int(np.sum(np.abs(y) >= 1.0)),
                      "max_click_db": K.max_click_db(y2, fs) if np.any(y2) else -400.0},
           "loudness": {"integrated_lufs": K.integrated_lufs(y2, fs) if np.any(y2) and n > fs // 2 else -70.0,
                        "momentary_max_lufs": K.momentary_max_lufs(y2, fs) if np.any(y2) and n > fs // 2 else -70.0}}
    if "profile" in args:
        # synthetic, deterministic block times: 4 % of the deadline, 5x in the first block and
        # at each preset change, a moving spike with FAKE_JITTER_AT
        deadline = block_nominal / fs if block_nominal else 1e-3
        times = np.full(len(sizes), 0.04 * deadline) + rng.uniform(0, 0.002 * deadline, len(sizes))
        if args["gate"] and not os.environ.get("FAKE_NO_IDLE"):
            # lazy stages: once the tail has decayed the synthetic cost drops to 0.5 % (D.2.5)
            quiet_from = int((float(args["gate"]) + 0.2 + 0.3) * fs / max(block_nominal, 1))
            times[quiet_from:] = 0.005 * deadline
        if len(times):
            times[0] *= 5.0
        for pa in repeat["preset-at"]:
            at = int(float(pa.split(":")[0]) * fs / max(block_nominal, 1))
            if at < len(times):
                times[at] *= 5.0
        if os.environ.get("FAKE_JITTER_AT"):
            j = int(os.environ["FAKE_JITTER_AT"]) + seed
            if j < len(times):
                times[j] *= 30.0
        res["profile"] = K.block_time_report(times, block_nominal or 1, fs, warmup=int(args["warmup"]))
    print(json.dumps(res))
    return 3 if nan else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
