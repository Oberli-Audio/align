#!/usr/bin/env python3
"""buildinfo - build provenance as a file, and the guard that reads it.

    buildinfo.py emit  --repo . --build build [--out build/build-info.json] [--machine NAME] [--symbols <dSYM or .pdb> ...]
    buildinfo.py check build/build-info.json [--expect-version 1.2.0] [--require-archs x86_64,arm64]
                       [--platform macos|windows]
    buildinfo.py selftest

emit   reads VERSION, git (sha, dirty, branch, tag at HEAD), the CMake cache (build type, archs,
       deployment target, compiler, MSVC runtime), pins (JUCE commit from the FetchContent
       cache or CMakeLists, pluginval from validate_plugin.py) and writes build-info.json
       (versioning-and-provenance.md). Missing pieces are null, never invented.
check  fails when the tree was dirty, the config is not Release, a required slice is missing,
       the MSVC runtime is not MT on Windows, the version does not match --expect-version
       or the tag at HEAD, JUCE is older than 8.0.11 (its VST3 SDK then is not the MIT
       one), or the macOS deployment target is missing or above 11.0. Untracked files
       (build outputs) do not make the tree dirty. Exit 0 pass, 1 fail, 2 unusable.
"""
import argparse
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


def git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    except OSError:
        return None


def read_cache(build):
    p = Path(build) / "CMakeCache.txt"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([A-Za-z0-9_]+):[A-Z]+=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def find_pins(repo):
    repo = Path(repo)
    pins = {"juce": None, "vst3sdk": None, "clap_juce_extensions": None, "pluginval": None}
    cml = repo / "CMakeLists.txt"
    if cml.exists():
        text = cml.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"FetchContent_Declare\s*\(\s*JUCE.*?GIT_TAG\s+([0-9a-fA-F.v]+)", text, re.S)
        if m:
            pins["juce"] = m.group(1)
        m = re.search(r"clap[-_]juce[-_]extensions.*?GIT_TAG\s+([0-9a-fA-F.v]+)", text, re.S | re.I)
        if m:
            pins["clap_juce_extensions"] = m.group(1)
    for cand in repo.rglob("validate_plugin.py"):
        m = re.search(r'"pluginval":\s*"([^"]+)"', cand.read_text(encoding="utf-8", errors="replace"))
        if m:
            pins["pluginval"] = m.group(1)
            vs = re.search(r'"vst3sdk":\s*\{[^}]*"version":\s*"([^"]+)"', cand.read_text(encoding="utf-8", errors="replace"))
            if vs:
                pins["vst3sdk"] = vs.group(1)
            break
    return pins


def symbols_info(paths):
    """Name and UUID of the debug symbols shipped beside this build (feedback-loop.md 5): a crash
    file names the UUID of the slice that crashed, and this is how it is matched to a tag."""
    if not paths:
        return None
    out = []
    for p in paths:
        p = Path(p)
        entry = {"file": p.name, "uuids": []}
        if p.suffix == ".dSYM":
            try:
                r = subprocess.run(["dwarfdump", "--uuid", str(p)], capture_output=True, text=True)
                entry["uuids"] = re.findall(r"UUID: ([0-9A-Fa-f-]{36}) \((\w+)\)", r.stdout)
                entry["uuids"] = ["%s %s" % (u, arch) for u, arch in entry["uuids"]]
            except OSError:
                pass
        out.append(entry)
    return out


JUCE_MIN = (8, 0, 11)   # first JUCE whose bundled VST3 SDK is the MIT one (references/notices.md)


def juce_version(repo, build, cache):
    """JUCE's version from the fetched source (project(JUCE VERSION x.y.z)), or from a version-like GIT_TAG."""
    cands = []
    if cache.get("juce_SOURCE_DIR"):
        cands.append(Path(cache["juce_SOURCE_DIR"]))
    cands.append(Path(build) / "_deps" / "juce-src")
    for c in cands:
        cml = c / "CMakeLists.txt"
        if cml.exists():
            m = re.search(r"project\s*\(\s*JUCE\s+VERSION\s+(\d+\.\d+\.\d+)", cml.read_text(encoding="utf-8", errors="replace"), re.I)
            if m:
                return m.group(1)
    tag = find_pins(repo).get("juce") or ""
    m = re.match(r"v?(\d+\.\d+\.\d+)$", tag)
    return m.group(1) if m else None


def emit(a):
    repo = Path(a.repo)
    vp = repo / "VERSION"
    version = vp.read_text(encoding="utf-8").strip() if vp.exists() else None
    cache = read_cache(a.build)
    archs = [x for x in (cache.get("CMAKE_OSX_ARCHITECTURES") or "").split(";") if x]
    if not archs:
        archs = [platform.machine()]
    rt = cache.get("CMAKE_MSVC_RUNTIME_LIBRARY") or None
    msvc_runtime = None
    if rt:
        msvc_runtime = "MT" if rt.startswith("MultiThreaded") and "DLL" not in rt else "MD"
    info = {
        "product": a.product or (repo.name),
        "version": version,
        "tag": git(repo, "describe", "--tags", "--exact-match"),
        "git": {"sha": git(repo, "rev-parse", "--short=12", "HEAD"),
                "dirty": bool(git(repo, "status", "--porcelain", "--untracked-files=no")),   # build outputs in the tree are not edits
                "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD")},
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": a.machine or platform.node(),
        "platform": a.platform or ("macos" if sys.platform == "darwin" else "windows" if sys.platform.startswith("win") else "linux"),
        "config": cache.get("CMAKE_BUILD_TYPE") or None,
        "archs": archs,
        "deployment_target": cache.get("CMAKE_OSX_DEPLOYMENT_TARGET") or None,
        "compiler": " ".join(x for x in (cache.get("CMAKE_CXX_COMPILER_ID"), cache.get("CMAKE_CXX_COMPILER_VERSION")) if x) or None,
        "msvc_runtime": msvc_runtime,
        "pins": find_pins(repo),
        "juce_version": juce_version(repo, a.build, cache),
        "symbols": symbols_info(getattr(a, "symbols", None)),
    }
    out = Path(a.out) if a.out else Path(a.build) / "build-info.json"
    out.write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    print("wrote %s (%s %s, %s, %s)" % (out, info["product"], info["version"], info["config"], ",".join(info["archs"])))
    return 0


def check_info(info, expect_version=None, require_archs=None, plat=None):
    errs = []
    if info.get("git", {}).get("dirty"):
        errs.append("built from a dirty tree (uncommitted changes); a release is built from the tagged commit")
    if (info.get("config") or "").lower() != "release":
        errs.append("config is %r, not Release" % info.get("config"))
    plat = plat or info.get("platform")
    req = require_archs or (["x86_64", "arm64"] if plat == "macos" else [])
    missing = [x for x in req if x not in (info.get("archs") or [])]
    if missing:
        errs.append("missing slice(s) %s (archs: %s); Ableton Live 10.1 under Rosetta needs x86_64, a native DAW needs arm64" % (",".join(missing), ",".join(info.get("archs") or [])))
    if plat == "windows" and info.get("msvc_runtime") != "MT":
        errs.append("MSVC runtime is %r, not MT: the DLL would need the friend's redistributable" % info.get("msvc_runtime"))
    dt = info.get("deployment_target")
    if plat == "macos":
        if not dt:
            errs.append("no deployment target recorded: without CMAKE_OSX_DEPLOYMENT_TARGET in the cache the binary needs the macOS it was built on (a shipped build once required macOS 26.0)")
        else:
            try:
                major = tuple(int(x) for x in dt.split(".")[:2])
                if major > (11, 0):
                    errs.append("deployment target %s: friends on older macOS cannot load the plugin; the release preset sets 10.13 (arm64 implies 11.0)" % dt)
            except ValueError:
                errs.append("deployment target %r is not a version" % dt)
    v = info.get("version")
    if expect_version and v != expect_version:
        errs.append("version %r does not match expected %r" % (v, expect_version))
    tag = info.get("tag")
    if tag and v and tag != "v" + v:
        errs.append("tag at HEAD is %r but VERSION is %r" % (tag, v))
    if not tag:
        errs.append("HEAD is not tagged; a release is built from the tag v%s" % v)
    jv = info.get("juce_version")
    if not jv:
        errs.append("JUCE version unknown (no project(JUCE VERSION ...) in the fetched source, no version tag): cannot confirm the bundled VST3 SDK is the MIT one (JUCE %s or newer)" % ".".join(map(str, JUCE_MIN)))
    elif tuple(int(x) for x in jv.split(".")[:3]) < JUCE_MIN:
        errs.append("JUCE %s bundles the VST3 SDK under GPLv3 or Steinberg's agreement; pin JUCE %s or newer (VST3 SDK 3.8.0, MIT)" % (jv, ".".join(map(str, JUCE_MIN))))
    return errs


def check(a):
    p = Path(a.info)
    if not p.exists():
        print("buildinfo: %s not found" % p, file=sys.stderr)
        return 2
    info = json.loads(p.read_text(encoding="utf-8"))
    errs = check_info(info, a.expect_version, a.require_archs.split(",") if a.require_archs else None, a.platform)
    for e in errs:
        print("ERROR: " + e)
    if errs:
        print("buildinfo check: %d error(s)" % len(errs))
        return 1
    print("buildinfo check OK: %s %s, %s, %s, sha %s, tag %s" % (info.get("product"), info.get("version"), info.get("config"),
                                                           ",".join(info.get("archs") or []), info.get("git", {}).get("sha"), info.get("tag")))
    return 0


def selftest():
    import shutil, tempfile
    here = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "fakeplugin"
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        shutil.copytree(here, repo)
        g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)
        g("init", "-q"); g("add", "-A"); g("commit", "-q", "-m", "fixture"); g("tag", "v1.2.0")
        ns = argparse.Namespace(repo=repo, build=repo / "build", out=None, machine="selftest", product="Fake Pad", platform="macos", symbols=[str(repo / "Fake Pad.vst3.dSYM")])
        expect("emit", emit(ns) == 0)
        info = json.loads((repo / "build" / "build-info.json").read_text())
        expect("fields", info["version"] == "1.2.0" and info["tag"] == "v1.2.0" and info["config"] == "Release" and info["archs"] == ["arm64", "x86_64"] and not info["git"]["dirty"])
        expect("clean passes", not check_info(info, "1.2.0"))
        expect("symbols recorded", info["symbols"] and info["symbols"][0]["file"] == "Fake Pad.vst3.dSYM")
        expect("juce version read", info["juce_version"] == "8.0.12")
        bad = dict(info); bad["juce_version"] = "8.0.10"
        expect("old JUCE caught", any("pin JUCE 8.0.11" in e for e in check_info(bad, "1.2.0")))
        bad = dict(info); bad["deployment_target"] = "14.0"
        expect("high deployment target caught", any("older macOS" in e for e in check_info(bad, "1.2.0")))
        bad = dict(info); bad["deployment_target"] = None
        expect("missing deployment target caught", any("no deployment target" in e for e in check_info(bad, "1.2.0")))
        bad = dict(info); bad["juce_version"] = None
        expect("unknown JUCE caught", any("JUCE version unknown" in e for e in check_info(bad, "1.2.0")))
        expect("version mismatch", any("does not match" in e for e in check_info(info, "1.3.0")))
        bad = dict(info); bad["config"] = "Debug"
        expect("debug caught", any("not Release" in e for e in check_info(bad, "1.2.0")))
        bad = dict(info); bad["archs"] = ["arm64"]
        expect("missing slice", any("missing slice" in e for e in check_info(bad, "1.2.0")))
        bad = dict(info); bad["platform"] = "windows"; bad["msvc_runtime"] = "MD"; bad["archs"] = ["AMD64"]
        expect("MD caught", any("not MT" in e for e in check_info(bad, "1.2.0")))
        # dirty tree and untagged
        (repo / "VERSION").write_text("1.2.1\n")
        expect("dirty emit", emit(ns) == 0)
        info2 = json.loads((repo / "build" / "build-info.json").read_text())
        errs = check_info(info2, "1.2.1")
        expect("dirty and tag mismatch caught", any("dirty" in e for e in errs) and any("tag at HEAD" in e for e in errs))
        g("commit", "-q", "-am", "bump")
        expect("untagged emit", emit(ns) == 0)
        info3 = json.loads((repo / "build" / "build-info.json").read_text())
        expect("untagged caught", any("not tagged" in e for e in check_info(info3, "1.2.1")))
    if fails:
        print("buildinfo selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("buildinfo selftest OK: emit from the fixture with the symbols file and the JUCE version recorded; version, Debug, missing slice, MD runtime, dirty tree, tag mismatch, untagged HEAD, JUCE older than 8.0.11, unknown JUCE, a deployment target above 11.0 and a missing one each caught")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit")
    e.add_argument("--repo", default=".")
    e.add_argument("--build", default="build")
    e.add_argument("--out")
    e.add_argument("--machine")
    e.add_argument("--product")
    e.add_argument("--platform", choices=("macos", "windows", "linux"))
    e.add_argument("--symbols", nargs="*", help="dSYM bundles or .pdb files whose names (and UUIDs, via dwarfdump) are recorded")
    c = sub.add_parser("check")
    c.add_argument("info")
    c.add_argument("--expect-version")
    c.add_argument("--require-archs")
    c.add_argument("--platform", choices=("macos", "windows", "linux"))
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    return emit(a) if a.cmd == "emit" else check(a)


if __name__ == "__main__":
    sys.exit(main())
