#!/usr/bin/env python3
"""The bounce null test (Source/oberli/RenderSafety.h), as one CTest.

    python3 tools/tests/check_bounce.py --harness <harness> --kind instrument|effect [--wire]

Renders the same input twice through the harness, as playback and as a bounce
(--non-realtime), at a fixed and at a random block size, and requires the two outputs to be
bit-identical: the audio path must not depend on isNonRealtime(). With --wire (a plugin that
measures and passes the audio unchanged) the output must also equal the input, sample for
sample. Needs numpy and scipy.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

RATE = 48000


def render(harness, out, extra):
    r = subprocess.run([harness, "--seed=1", "--sample-rate=%d" % RATE, "--seconds=3", "--out=%s" % out, *extra],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("harness failed (%s):\n%s" % (" ".join(extra), r.stderr))
    echo = json.loads(r.stdout)
    want = "--non-realtime" in extra
    if bool(echo.get("applied", {}).get("non_realtime")) != want:
        sys.exit("the harness did not echo non_realtime=%s: rebuild it (flag --non-realtime)" % want)
    return wavfile.read(out)[1].astype(np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", required=True)
    ap.add_argument("--kind", choices=("instrument", "effect"), required=True)
    ap.add_argument("--wire", action="store_true", help="the plugin passes its input unchanged")
    a = ap.parse_args()

    fails = 0
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        source = []
        if a.kind == "instrument":
            source = ["--notes=48,55,60,64", "--gate=2"]
        else:
            rng = np.random.default_rng(7)
            noise = (rng.standard_normal((3 * RATE, 2)) * 0.1).astype(np.float32)
            wavfile.write(d / "in.wav", RATE, noise)
            source = ["--in=%s" % (d / "in.wav")]

        for block in ("512", "random:11"):
            play = render(a.harness, d / "play.wav", [*source, "--block=%s" % block])
            bounce = render(a.harness, d / "bounce.wav", [*source, "--block=%s" % block, "--non-realtime"])
            diff = float(np.max(np.abs(play - bounce))) if play.size else 0.0
            ok = play.shape == bounce.shape and diff == 0.0
            print("%-44s %s" % ("bounce == playback, block %s" % block, "ok" if ok else "FAILED (max difference %.3g)" % diff))
            fails += not ok

            if a.wire and a.kind == "effect":
                n = min(len(play), len(noise))
                wdiff = float(np.max(np.abs(play[:n] - noise[:n].astype(np.float64))))
                ok = wdiff == 0.0
                print("%-44s %s" % ("wire: output == input, block %s" % block, "ok" if ok else "FAILED (max difference %.3g)" % wdiff))
                fails += not ok

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
