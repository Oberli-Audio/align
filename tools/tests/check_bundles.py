#!/usr/bin/env python3
"""The macOS release bundles load and can be symbolicated.

For every bundle the release preset built (build/*_artefacts/Release/VST3/*.vst3, .../Standalone/*.app):
the signature verifies (`codesign --verify --deep --strict`: macOS will not load a broken one,
on Apple Silicon and under Rosetta alike), and its dSYM holds debug info for every architecture
of the binary with matching UUIDs, so a crash report from either slice can be symbolicated.
A universal LTO link writes one temporary object per architecture; a shared -object_path_lto
path keeps only the last one and leaves the other slice of the dSYM empty.
Usage: python3 tools/tests/check_bundles.py [build dir]
"""
import re
import subprocess
import sys
from pathlib import Path

BUILD = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "build")


def run(*cmd):
    return subprocess.run(list(cmd), capture_output=True, text=True)


def uuids(path):
    return dict((a, u) for u, a in re.findall(r"UUID: (\S+) \((\w+)\)", run("dwarfdump", "--uuid", str(path)).stdout))


def binary(bundle):
    macos = bundle / "Contents" / "MacOS"
    return next(macos.iterdir()) if macos.is_dir() else None


def main():
    bundles = sorted(BUILD.glob("*_artefacts/Release/VST3/*.vst3")) + sorted(BUILD.glob("*_artefacts/Release/Standalone/*.app"))
    if not bundles:
        print(f"no release bundle under {BUILD}: build the release preset first")
        return 1
    errors = []
    for b in bundles:
        sig = run("codesign", "--verify", "--deep", "--strict", str(b))
        if sig.returncode != 0:
            errors.append(f"{b.name}: signature invalid ({sig.stderr.strip().splitlines()[-1]})")
        exe = binary(b)
        dsym = b.parent / (b.name + ".dSYM")
        if exe is None or not dsym.is_dir():
            errors.append(f"{b.name}: no {'binary' if exe is None else 'dSYM beside it'}")
            continue
        have, want = uuids(dsym), uuids(exe)
        for arch, uuid in want.items():
            if have.get(arch) != uuid:
                errors.append(f"{b.name}: dSYM {arch} UUID {have.get(arch)} != binary {uuid}")
                continue
            info = run("dwarfdump", "--arch", arch, "--debug-info", str(dsym)).stdout
            units = info.count("DW_TAG_compile_unit")
            print(f"{b.name} {arch}: {units} compile units, {info.count('DW_TAG_subprogram')} functions")
            if units == 0:
                errors.append(f"{b.name}: the dSYM's {arch} slice has no debug info")
    print(f"{len(bundles)} bundles; {len(errors)} errors")
    for e in errors:
        print("  error:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
