#!/usr/bin/env python3
"""The parameter table against the built plugin and the manual, as one CTest.

    python3 tools/tests/check_table.py --harness <harness> --kind instrument|effect [--frozen last.csv]

Runs the harness's --list-params into a file and calls paramgen.py check on parameters.csv with
it, the committed docs/parameters.md and, when given, the last release's table (ID freeze).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "scripts" / "dsp-kit"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", required=True)
    ap.add_argument("--kind", choices=("instrument", "effect"), required=True)
    ap.add_argument("--frozen")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        listing = Path(d) / "params.json"
        r = subprocess.run([a.harness, "--list-params"], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            return r.returncode
        listing.write_text(r.stdout, encoding="utf-8")
        cmd = [sys.executable, str(KIT / "paramgen.py"), "check", str(ROOT / "parameters.csv"),
               "--list-params", str(listing), "--kind", a.kind]
        manual = ROOT / "docs" / "parameters.md"
        if manual.exists():
            cmd += ["--manual", str(manual)]
        if a.frozen:
            cmd += ["--frozen", a.frozen]
        return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
