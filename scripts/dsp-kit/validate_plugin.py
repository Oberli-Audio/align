#!/usr/bin/env python3
"""The unattended part of the release gate (joint-plugin-workflow.md "Release gate";
playbook G6, D.5.7) for any VST3 plugin.

One command runs your build command, your test command, the Steinberg VST3 validator
and pluginval, and an optional real-time check command (RTSan or the malloc trap) -
then writes every log and a JSON summary to one folder and exits non-zero if anything
failed. The attended part of the gate (hosts, the friend at 64 samples, listening) stays
in the list. Copy it into the project (CI must not
depend on ~/.claude) together with a versions.json:

    {"pluginval": "v1.0.4", "vst3sdk": {"commit": "<sha>", "version": "3.8.1"}}

Profiles - pick by tier and occasion (playbook D.3.6):

  quick   every change that touches the host interface: DSP tests, Steinberg
          validator, pluginval strictness 5 (the host-compatibility floor)
  full    before a merge or release - Tier P's G6: DSP tests, Steinberg
          validator, pluginval strictness 10 at all six sample rates and eight
          block sizes, with a fixed, logged seed; the real-time check if its
          command is given. At Tier F the release gate runs it a second time
          with --sanitizer asan against a from-source pluginval and the asan
          build (D.1.6, tiers.md)
  soak    nightly or before a Tier F release: everything in full, plus pluginval
          strictness 10 repeated 5x in random order with a fresh seed (fuzzing
          state and parameters; the seed is logged so any failure reproduces)

    python3 validate_plugin.py --plugin "build/My_artefacts/Release/VST3/My.vst3" \
        --build-cmd "cmake --build build --target My_VST3" \
        --test-cmd "ctest --test-dir build -LE validation" \
        --rtsan-cmd "python3 tools/tests/run.py --tool build-rtsan/MyHarness"
    python3 validate_plugin.py --plugin ... --profile quick --no-build
    python3 validate_plugin.py --plugin ... --only pluginval --seed 0x1234     # reproduce

pluginval is looked for in $PLUGINVAL, in ~/.config/oberli/tools.toml (pluginval.app,
toolchain.py), on PATH, in /Applications/pluginval.app, then in build-validators/;
--fetch-pluginval downloads the pinned release there. With --sanitizer only $PLUGINVAL
(else tools.toml's pluginval.asan / pluginval.tsan) counts, built with that sanitizer:
unset, not a file or uninstrumented fails the step (no fallback, no download).
The Steinberg validator is built from the pinned VST3 SDK commit into
build-validators/ on first use (without full Xcode, -DXCODE_VERSION is passed).
It is never built with a sanitizer: on macOS, --sanitizer inserts the runtime the
plugin itself links (its LC_RPATH, else xcrun clang) into the validator alone, since
a runtime that only arrives with the dlopen'd plugin does not start. The validator
step also fails on "MIDI Mapping supplied for ..." lines: the validator logs them as
Info, but each is a wrong answer from the plugin (JUCE's VST3 wrapper read past an
array this way, D.1.6).

    python3 validate_plugin.py selftest      # the parsing this script relies on

Exit codes: 0 all passed; 1 something failed (with --strict, also a skipped
step); 77 every requested step was skipped (missing plugin bundle or tool) -
CTest reports that as skipped. A mix of passes and skips is 0 without --strict.
"""
import argparse
import json
import os
import platform
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path.cwd()
PINS = {"pluginval": "v1.0.4", "vst3sdk": {"commit": "3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96", "version": "3.8.1"}}
TOOLS_DIR = ROOT / "build-validators"


def toolchain_value(key):
    """A path from the machine file ~/.config/oberli/tools.toml (toolchain.py beside this script),
    or None: the file is optional and the environment always wins."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import toolchain
        return toolchain.get(key)
    except Exception:
        return None
SKIP = 77

RATES_ALL = "44100,48000,88200,96000,176400,192000"
BLOCKS_ALL = "1,32,64,128,256,512,1024,2048"      # 1: pluginval's default list omits it
PROFILES = {
    "quick": {"steps": ["ctest", "validator", "pluginval"], "level": 5,
              "rates": None, "blocks": None, "repeat": 1, "randomise": False},
    "full": {"steps": ["ctest", "validator", "pluginval", "rtsan"], "level": 10,
             "rates": RATES_ALL, "blocks": BLOCKS_ALL, "repeat": 1, "randomise": False},
    "soak": {"steps": ["ctest", "validator", "pluginval", "pluginval_soak", "rtsan"], "level": 10,
             "rates": RATES_ALL, "blocks": BLOCKS_ALL, "repeat": 5, "randomise": True},
}
IS_MAC, IS_WIN = sys.platform == "darwin", sys.platform.startswith("win")


class Unavailable(Exception):
    """A step cannot run here (missing tool or bundle) - reported as skipped."""


class Refused(Exception):
    """A step was asked for with a tool that cannot give a valid verdict - reported as failed."""


def run(cmd, log, cwd=None, env=None, timeout=None):
    """Run cmd, tee everything to log, return (exit code, output)."""
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("$ " + " ".join('"%s"' % c if " " in str(c) else str(c) for c in cmd) + "\n\n")
        fh.flush()
        try:
            p = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, timeout=timeout,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               errors="replace")
            out, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as e:
            out, code = (e.stdout or "") if isinstance(e.stdout, str) else "", 124
            out += "\n[validate.py] TIMEOUT after %ss\n" % timeout
        fh.write(out)
        fh.write("\n[validate.py] exit %d after %.0f s\n" % (code, time.time() - t0))
    return code, out


def bundle_from(path):
    """Accept the .vst3 bundle or any path inside it (e.g. CMake's TARGET_FILE_DIR)."""
    p = Path(path).resolve()
    for q in [p] + list(p.parents):
        if q.suffix == ".vst3":
            return q
    return p


# ------------------------------------------------------------------ tools

SANITIZER_MARKERS = {"asan": b"__asan_", "tsan": b"__tsan_"}


def instrumented(binary, sanitizer):
    """Whether binary was built with the sanitizer: instrumented code calls the runtime's
    __asan_/__tsan_ entry points, imported (macOS, Windows) or linked in (Linux)."""
    return SANITIZER_MARKERS[sanitizer] in Path(binary).read_bytes()


def sanitized_pluginval(sanitizer, fetch):
    """Under --sanitizer only $PLUGINVAL counts, and only a build with that sanitizer. The
    signed download dies on "Interceptors are not working", which reads like a sanitizer
    report against the plugin, so there is no fallback to PATH, /Applications or a download."""
    pv = os.environ.get("PLUGINVAL") or toolchain_value("pluginval." + sanitizer)
    if fetch:
        raise Refused("--fetch-pluginval with --sanitizer %s: the download is built without it; "
                      "build pluginval from source (D.1.6) and set PLUGINVAL" % sanitizer)
    if not pv:
        raise Refused("--sanitizer %s needs PLUGINVAL set (or pluginval.%s in ~/.config/oberli/tools.toml) to a "
                      "pluginval built from source with %s (D.1.6)" % (sanitizer, sanitizer, sanitizer))
    if not Path(pv).is_file():
        hint = ' ("~" is not expanded inside an env argument: use $HOME)' if pv.startswith("~") else ""
        raise Refused("PLUGINVAL=%s is not a file%s; no fallback under --sanitizer" % (pv, hint))
    if not instrumented(pv, sanitizer):
        raise Refused("PLUGINVAL=%s is not built with %s (no %s symbols): build it from source (D.1.6)"
                      % (pv, sanitizer, SANITIZER_MARKERS[sanitizer].decode()))
    return Path(pv)


def find_pluginval(fetch, sanitizer="none"):
    if sanitizer != "none":
        return sanitized_pluginval(sanitizer, fetch)
    candidates = [os.environ.get("PLUGINVAL"), toolchain_value("pluginval.app"), shutil.which("pluginval"),
                  "/Applications/pluginval.app/Contents/MacOS/pluginval"]
    local = TOOLS_DIR / ("pluginval-" + PINS["pluginval"])
    candidates += [local / "pluginval.app/Contents/MacOS/pluginval", local / "pluginval.exe", local / "pluginval"]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    if not fetch:
        raise Unavailable("pluginval not found - install it, set PLUGINVAL, or pass --fetch-pluginval")
    asset = "pluginval_macOS.zip" if IS_MAC else "pluginval_Windows.zip" if IS_WIN else "pluginval_Linux.zip"
    url = "https://github.com/Tracktion/pluginval/releases/download/%s/%s" % (PINS["pluginval"], asset)
    local.mkdir(parents=True, exist_ok=True)
    zpath = local / asset
    print("[validate] downloading %s" % url, flush=True)
    urllib.request.urlretrieve(url, zpath)
    if IS_MAC:   # keep the app bundle's symlinks and permissions intact
        subprocess.run(["ditto", "-x", "-k", str(zpath), str(local)], check=True)
    else:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(local)
    for c in candidates[3:]:
        if Path(c).is_file():
            os.chmod(c, 0o755)
            return Path(c)
    raise Unavailable("pluginval download unpacked, but no executable found in %s" % local)


def find_validator(build_if_missing=True):
    sdk = TOOLS_DIR / "vst3sdk"
    out = TOOLS_DIR / "vst3sdk-build"
    name = "validator.exe" if IS_WIN else "validator"
    hits = sorted(out.rglob(name)) if out.exists() else []
    hits = [h for h in hits if h.is_file() and (IS_WIN or os.access(h, os.X_OK))]
    stamp = out / "pinned-commit.txt"
    if hits and stamp.exists() and stamp.read_text().strip() == PINS["vst3sdk"]["commit"]:
        return hits[0]
    if not build_if_missing:
        raise Unavailable("Steinberg validator not built")
    commit = PINS["vst3sdk"]["commit"]
    print("[validate] building the Steinberg validator from VST3 SDK %s (%s)"
          % (PINS["vst3sdk"]["version"], commit[:7]), flush=True)
    if sdk.exists():
        shutil.rmtree(sdk)
    sdk.mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", *a], cwd=sdk, check=True, capture_output=True)
    git("init", "-q")
    git("remote", "add", "origin", "https://github.com/steinbergmedia/vst3sdk.git")
    git("fetch", "-q", "--depth", "1", "origin", commit)
    git("checkout", "-q", "FETCH_HEAD")
    git("submodule", "update", "-q", "--init", "--depth", "1", "--", "base", "cmake", "pluginterfaces", "public.sdk")
    cfg = ["cmake", "-B", str(out), "-S", str(sdk), "-DCMAKE_BUILD_TYPE=Release",
           "-DSMTG_ENABLE_VST3_PLUGIN_EXAMPLES=OFF", "-DSMTG_ENABLE_VSTGUI_SUPPORT=OFF",
           "-DSMTG_ENABLE_VST3_HOSTING_EXAMPLES=OFF"]
    env = dict(os.environ)
    if IS_MAC:
        cfg += ["-G", "Ninja"] if shutil.which("ninja") else []
        if subprocess.run(["xcodebuild", "-version"], capture_output=True).returncode != 0:
            # Command Line Tools only: the SDK's configure asks xcodebuild for a version and
            # needs XCODE_VERSION as an environment variable AND a CMake variable (playbook D.4.2)
            env["XCODE_VERSION"] = "16.0"
            cfg += ["-DXCODE_VERSION=16.0", "-DCMAKE_C_COMPILER=clang", "-DCMAKE_CXX_COMPILER=clang++"]
    if out.exists():
        shutil.rmtree(out)
    log = TOOLS_DIR / "vst3sdk-build.log"
    with open(log, "w") as fh:
        subprocess.run(cfg, check=True, stdout=fh, stderr=subprocess.STDOUT, env=env)
        subprocess.run(["cmake", "--build", str(out), "--target", "validator", "--config", "Release"],
                       check=True, stdout=fh, stderr=subprocess.STDOUT, env=env)
    stamp.write_text(commit + "\n")
    return find_validator(build_if_missing=False)


# ------------------------------------------------------------------ steps

def step_build(a, logs):
    if not a.build_cmd:
        raise Unavailable("no --build-cmd given")
    code, _ = run(shlex.split(a.build_cmd), logs / "build.log")
    return code == 0, a.build_cmd


def step_ctest(a, logs):
    if not a.test_cmd:
        raise Unavailable("no --test-cmd given")
    code, out = run(shlex.split(a.test_cmd), logs / "tests.log", timeout=3600)
    m = re.search(r"\d+% tests passed(?:, (\d+) tests failed)? out of (\d+)", out)
    if not m:
        return code == 0, "exit %d" % code
    failed = int(m.group(1) or 0)
    return code == 0, "%d of %s passed" % (int(m.group(2)) - failed, m.group(2))


SANITIZER_RUNTIMES = {"asan": "libclang_rt.asan_osx_dynamic.dylib", "tsan": "libclang_rt.tsan_osx_dynamic.dylib"}


def rpaths(otool_l):
    """LC_RPATH directories from `otool -l` output, without @-relative entries."""
    return [p for p in re.findall(r"^\s*path (.+?) \(offset \d+\)", otool_l, re.M) if not p.startswith("@")]


def sanitizer_runtime(bundle, lib):
    """The runtime the plugin was built against: Python, an Apple binary, may not load it
    ("Sanitizer load violates platform policy"), so it goes to the validator process only."""
    binaries = sorted(p for p in (bundle / "Contents" / "MacOS").glob("*") if p.is_file())
    if binaries:
        out = subprocess.run(["otool", "-l", str(binaries[0])], capture_output=True, text=True).stdout
        for d in rpaths(out):
            if (Path(d) / lib).is_file():
                return Path(d) / lib
    out = subprocess.run(["xcrun", "clang", "-print-file-name=" + lib], capture_output=True, text=True).stdout.strip()
    return Path(out) if out and Path(out).is_file() else None


def wrong_midi_mappings(out):
    """Validator Info lines that are wrong answers by the plugin: a mapping for a controller
    number >= kCountCtrlNumber or for an event bus it does not have."""
    return sum(1 for l in out.splitlines() if "MIDI Mapping supplied for" in l)


def step_validator(a, logs):
    if not a.plugin.exists():
        raise Unavailable("no plugin bundle at %s" % a.plugin)
    v = find_validator()
    env, note = None, ""
    if IS_MAC and a.sanitizer in SANITIZER_RUNTIMES:
        rt = sanitizer_runtime(a.plugin, SANITIZER_RUNTIMES[a.sanitizer])
        if rt is None:
            return False, "no %s runtime for the validator (not in the plugin's LC_RPATH, not from xcrun clang)" % a.sanitizer
        env, note = dict(os.environ, DYLD_INSERT_LIBRARIES=str(rt)), ", %s runtime inserted" % a.sanitizer
    code, out = run([v, a.plugin], logs / "steinberg-validator.log", timeout=1800, env=env)
    # the exit code is the verdict (F.13.5); the counts are detail only
    m = re.search(r"Result: (\d+) tests passed, (\d+) tests failed", out)
    detail = ("%s passed, %s failed (SDK %s)" % (m.group(1), m.group(2), PINS["vst3sdk"]["version"])) if m else "exit %d, see log" % code
    wrong = wrong_midi_mappings(out)
    if wrong:
        detail += "; %d wrong MIDI mapping answers (logged as Info, a plugin defect: D.1.6)" % wrong
    return code == 0 and not wrong, detail + note


def selftest():
    otool = ("Load command 20\n          cmd LC_RPATH\n      cmdsize 32\n         path @executable_path (offset 12)\n"
             "Load command 21\n          cmd LC_RPATH\n      cmdsize 80\n"
             "         path /Library/Developer/CommandLineTools/usr/lib/clang/21/lib/darwin (offset 12)\n")
    assert rpaths(otool) == ["/Library/Developer/CommandLineTools/usr/lib/clang/21/lib/darwin"], rpaths(otool)
    log = ("[MIDI Mapping]\nInfo:  ===MIDI Mapping ====================================\n"
           + "Info:  MIDI Mapping supplied for a wrong ControllerNumbers value (bigger than the max)\n" * 16
           + "Info:  MIDI Mapping supplied for an unknown event bus\n[Succeeded]\n")
    assert wrong_midi_mappings(log) == 17, wrong_midi_mappings(log)
    assert wrong_midi_mappings("[MIDI Mapping]\nInfo:  ===MIDI Mapping ===\n[Succeeded]\n") == 0
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        plain, asan = Path(d) / "plain", Path(d) / "asan"
        plain.write_bytes(b"\xcf\xfa\xed\xfe _main _juce_init")
        asan.write_bytes(b"\xcf\xfa\xed\xfe _main ___asan_init ___asan_report_load8")
        assert not instrumented(plain, "asan") and instrumented(asan, "asan") and not instrumented(asan, "tsan")
    print("validate_plugin selftest OK: rpath parsing, wrong MIDI mapping lines, sanitizer symbols")
    return 0


def slowdown(a):
    """A sanitizer build runs about ten times slower: every pluginval timeout scales with it."""
    return 10 if a.sanitizer != "none" else 1


def pluginval_cmd(a, prof, seed, repeat, randomise, logs, name):
    pv = find_pluginval(a.fetch_pluginval, a.sanitizer)
    if not a.plugin.exists():
        raise Unavailable("no plugin bundle at %s" % a.plugin)
    # pinned to PINS["pluginval"] (1.x syntax). pluginval 2.0 (beta, 2026-10) changes this to
    # `pluginval validate [opts] <plugin>`, errors on unknown options, compiles the Steinberg
    # validator in (run once, not twice) and adds --json-results; migrate here when it ships.
    timeout_ms = a.timeout_ms * slowdown(a)
    cmd = [pv, "--strictness-level", str(prof["level"]), "--random-seed", seed,
           "--timeout-ms", str(timeout_ms), "--output-dir", logs]
    if prof["rates"]:
        cmd += ["--sample-rates", prof["rates"]]
    if prof["blocks"]:
        cmd += ["--block-sizes", prof["blocks"]]
    if repeat > 1:
        cmd += ["--repeat", str(repeat)]
    if randomise:
        cmd += ["--randomise"]
    if a.skip_gui_tests:
        cmd += ["--skip-gui-tests"]
    cmd += ["--validate", a.plugin]
    return cmd


def summarise_pluginval(out):
    fails = sorted(set(l.strip() for l in out.splitlines() if re.search(r"!!!|FAILED|\bfailed\b", l)))
    return fails[:8]


def count_pluginval(out):
    """Tests started and the verdict line, parsed from the 1.x log (D.5.7): the summary names
    them, so a run that silently tested nothing is visible."""
    started = len(re.findall(r"^Starting test", out, re.M))
    # pluginval 1.0.x prints "SUCCESS" (and "FAILED" on failure); older builds "ALL TESTS PASSED"
    passed = bool(re.search(r"^(SUCCESS|ALL TESTS PASSED)\b", out, re.M))
    return started, passed


KNOWN_FALSE_POSITIVES = [
    "state restoration below strictness 8 on parameters that quantise (2.0 tests per parameter)",
    "GUI and DPI tests on a headless runner (use --skip-gui-tests there, never in the release gate)",
    "timeouts under sanitizers (this script scales every pluginval timeout 10x with --sanitizer)",
    "a bundle broken by an artefact round trip (validate the build output, not a re-zipped copy)",
]


def step_pluginval(a, logs, prof):
    cmd = pluginval_cmd(a, prof, a.seed, 1, False, logs, "strictness%d" % prof["level"])
    code, out = run(cmd, logs / "pluginval.log", timeout=a.step_timeout * slowdown(a))
    fails = summarise_pluginval(out) if code else []
    started, verdict = count_pluginval(out)
    ok = code == 0 and verdict and started > 0
    return ok, "strictness %d, seed %s, %d tests started%s%s%s" % (prof["level"], a.seed, started,
        ", rates %s" % prof["rates"] if prof["rates"] else ", default rates",
        "" if verdict else ", no SUCCESS line",
        ("; " + " | ".join(fails)) if fails else "")


def step_pluginval_soak(a, logs, prof):
    seed = "0x%08x" % random.SystemRandom().getrandbits(32)
    cmd = pluginval_cmd(a, prof, seed, prof["repeat"], True, logs, "soak")
    code, out = run(cmd, logs / "pluginval-soak.log", timeout=a.step_timeout * prof["repeat"] * slowdown(a))
    fails = summarise_pluginval(out) if code else []
    return code == 0, "strictness %d x%d randomised, seed %s (reproduce: --only pluginval --seed %s)%s" % (
        prof["level"], prof["repeat"], seed, seed, ("; " + " | ".join(fails)) if fails else "")


def step_rtsan(a, logs):
    if not a.rtsan_cmd:
        raise Unavailable("no --rtsan-cmd given")
    if a.rtsan_selftest_cmd:
        env = dict(os.environ)
        c1, _ = run(shlex.split(a.rtsan_selftest_cmd), logs / "rtsan-selftest.log", env=env, timeout=300)
        if c1 == 0:
            return False, "RTSan self-test did not fire - the check is not live"
    code, _ = run(shlex.split(a.rtsan_cmd), logs / "rtsan.log", timeout=3600)
    return code == 0, a.rtsan_cmd


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=PROFILES, default="full")
    ap.add_argument("--only", help="comma-separated steps: build,ctest,validator,pluginval,pluginval_soak,rtsan")
    ap.add_argument("--plugin", required=True, help="the .vst3 bundle (or a path inside it)")
    ap.add_argument("--build-cmd", help="command that builds the bundle")
    ap.add_argument("--test-cmd", help="command that runs the product's tests")
    ap.add_argument("--rtsan-cmd", help="command that runs the real-time check: the harness suite under RealtimeSanitizer, or with the malloc trap (D.1.6)")
    ap.add_argument("--rtsan-selftest-cmd", help="command that must FAIL if the real-time check is live (D.1.6)")
    ap.add_argument("--pins", help="versions.json (default: the kit's pins)")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--seed", default="0x48505631", help="pluginval random seed (default fixed, so runs compare)")
    ap.add_argument("--fetch-pluginval", action="store_true")
    ap.add_argument("--skip-gui-tests", action="store_true", help="for headless machines")
    ap.add_argument("--timeout-ms", type=int, default=60000, help="pluginval: max silence per test")
    ap.add_argument("--sanitizer", choices=("none", "asan", "tsan"), default="none",
                    help="the plugin and pluginval are built with this sanitizer: timeouts x10, PLUGINVAL must point at a "
                         "from-source build (the signed download cannot load the runtime), anything else fails the "
                         "pluginval step. Tier P's release gate runs "
                         "the full profile once plain and once with --sanitizer asan (D.1.6); tsan is Tier F")
    ap.add_argument("--step-timeout", type=int, default=3600, help="seconds per pluginval run")
    ap.add_argument("--out", help="log folder (default build-validation/<timestamp>)")
    ap.add_argument("--strict", action="store_true",
                    help="a skipped step is a failure (CI: a missing tool must not pass silently)")
    argv = sys.argv[1:]
    if argv[:1] == ["selftest"]:
        sys.exit(selftest())
    if argv and argv[0] in PROFILES:          # `validate_plugin.py full --plugin ...` reads as --profile full
        argv = ["--profile", argv[0]] + argv[1:]
    a = ap.parse_args(argv)

    prof = PROFILES[a.profile]
    if a.pins:
        PINS.update(json.loads(Path(a.pins).read_text()))
    a.plugin = bundle_from(a.plugin)
    steps = a.only.split(",") if a.only else (([] if a.no_build else ["build"]) + prof["steps"])
    logs = Path(a.out) if a.out else ROOT / "build-validation" / time.strftime("%Y%m%d-%H%M%S")
    logs.mkdir(parents=True, exist_ok=True)

    runners = {"build": lambda: step_build(a, logs), "ctest": lambda: step_ctest(a, logs),
               "validator": lambda: step_validator(a, logs), "pluginval": lambda: step_pluginval(a, logs, prof),
               "pluginval_soak": lambda: step_pluginval_soak(a, logs, prof), "rtsan": lambda: step_rtsan(a, logs)}
    results, any_fail, any_skip = [], False, False
    print("[validate] profile %s, plugin %s, logs %s" % (a.profile, a.plugin, logs), flush=True)
    for s in steps:
        t0 = time.time()
        try:
            ok, detail = runners[s]()
            status = "PASS" if ok else "FAIL"
        except Unavailable as e:
            status, detail = "SKIP", str(e)
        except Refused as e:
            status, detail = "FAIL", str(e)
        except subprocess.CalledProcessError as e:
            status, detail = "FAIL", "setup failed (%s): see %s" % (Path(str(e.cmd[0])).name, TOOLS_DIR / "vst3sdk-build.log")
        dt = time.time() - t0
        results.append({"step": s, "status": status, "seconds": round(dt), "detail": detail})
        any_fail |= status == "FAIL"
        any_skip |= status == "SKIP"
        print("[validate] %-15s %s  %4.0f s  %s" % (s, status, dt, detail), flush=True)

    summary = {"profile": a.profile, "plugin": str(a.plugin), "platform": platform.platform(),
               "pins": PINS, "seed": a.seed, "steps": results,
               "result": "FAIL" if any_fail or (a.strict and any_skip)
                         else ("SKIP" if any_skip and all(r["status"] == "SKIP" for r in results)
                               else "PASS")}
    (logs / "summary.json").write_text(json.dumps(summary, indent=1))
    print("[validate] %s - summary in %s" % (summary["result"], logs / "summary.json"))
    if summary["result"] == "FAIL":
        sys.exit(1)
    if summary["result"] == "SKIP":
        sys.exit(SKIP)


if __name__ == "__main__":
    main()
