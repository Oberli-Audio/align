#!/usr/bin/env python3
"""toolchain - one machine file for every tool the Oberli Audio repos need (D.1.6, release gate).

The repos carry no machine paths. `~/.config/oberli/tools.toml` (or $OBERLI_TOOLS) names, per
machine, the Homebrew LLVM with RealtimeSanitizer, Faust, the signed pluginval and the ones
built from source with ASan and TSan, the VST3 SDK checkout, the hosts, and the registry. The
kit reads it (validate_plugin.py takes pluginval from it when $PLUGINVAL is unset), the CMake
presets read it through the environment (`eval "$(python3 scripts/dsp-kit/toolchain.py env)"`
before `cmake --preset rtsan`), and a reinstalled Mac or a friend's machine is reproducible by
copying tools.toml.example and filling it in.

    toolchain.py path                 where the file is (or would be)
    toolchain.py get llvm.root        one value, expanded; exit 1 when unset
    toolchain.py env                  export lines: LLVM_ROOT, FAUST, PLUGINVAL, PLUGINVAL_ASAN,
                                      PLUGINVAL_TSAN, VST3SDK, OBERLI_REGISTRY (only the set ones)
    toolchain.py check                every path that is set exists; exit 1 otherwise
    toolchain.py init                 copy tools.toml.example to the machine file (never overwrites)
    toolchain.py selftest

Pure Python 3.9+; tomllib when available, else a minimal parser for the subset tools.toml uses.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "tools.toml.example"
DEFAULT = Path(os.path.expanduser("~/.config/oberli/tools.toml"))
# key in tools.toml -> environment variable the presets, the kit and the ship scripts read
ENV = [("llvm.root", "LLVM_ROOT"), ("faust.faust", "FAUST"), ("pluginval.app", "PLUGINVAL"),
       ("pluginval.asan", "PLUGINVAL_ASAN"), ("pluginval.tsan", "PLUGINVAL_TSAN"),
       ("validator.vst3sdk", "VST3SDK"), ("registry.plugins", "OBERLI_REGISTRY")]


def _mini_toml(text):
    import ast
    data, cur = {}, None
    cur = data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            cur = data
            for part in line[1:line.index("]")].split("."):
                cur = cur.setdefault(part.strip(), {})
            continue
        if "=" not in line:
            raise ValueError("tools.toml: cannot parse %r" % raw)
        k, v = (x.strip() for x in line.split("=", 1))
        if v.startswith('"'):
            v = v[: v.rindex('"') + 1]
            val = ast.literal_eval(v)
        elif v.startswith("["):
            val = list(ast.literal_eval(v[: v.rindex("]") + 1]))
        else:
            v = v.split("#", 1)[0].strip()
            val = (v == "true") if v in ("true", "false") else int(v)
        cur[k] = val
    return data


def location():
    return Path(os.path.expanduser(os.environ.get("OBERLI_TOOLS") or str(DEFAULT)))


def load(path=None):
    """The file as a dict; an empty dict when the file does not exist."""
    p = Path(path) if path else location()
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    return tomllib.loads(text) if tomllib is not None else _mini_toml(text)


def get(key, data=None, default=None):
    """'llvm.root' -> the expanded value, or default when unset or empty."""
    d = load() if data is None else data
    for part in key.split("."):
        if not isinstance(d, dict) or part not in d:
            return default
        d = d[part]
    if isinstance(d, str):
        return os.path.expanduser(d) if d else default
    return d


def env_lines(data=None):
    d = load() if data is None else data
    out = []
    for key, var in ENV:
        v = get(key, d)
        if v:
            out.append("export %s=%s" % (var, _sh_quote(str(v))))
    return out


def _sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def check(data=None, path=None):
    """Every path-like value that is set must exist. Returns the list of problems."""
    d = load(path) if data is None else data
    probs = []
    if not d:
        return ["no tools.toml at %s (toolchain.py init writes the example there)" % (path or location())]
    for section, vals in d.items():
        if not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if isinstance(v, str) and v and (v.startswith("/") or v.startswith("~")):
                if not Path(os.path.expanduser(v)).exists():
                    probs.append("%s.%s: %s does not exist" % (section, k, v))
    return probs


def init():
    p = location()
    if p.exists():
        return "%s exists; not overwritten" % p
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(EXAMPLE, p)
    return "wrote %s from tools.toml.example: fill in the paths of this machine" % p


def selftest():
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    sample = EXAMPLE.read_text(encoding="utf-8")
    d = _mini_toml(sample)
    if tomllib is not None:
        expect("mini parser equals tomllib on the example", d == tomllib.loads(sample))
    expect("example has the sections the kit reads", all(k in d for k in ("llvm", "faust", "pluginval", "validator", "hosts", "registry")))
    expect("get expands ~", get("registry.plugins", d, "").startswith(str(Path.home())))
    expect("get default on unset", get("nothing.here", d, "x") == "x" and get("pluginval.tsan", d, None) is None)
    lines = env_lines(d)
    expect("env exports the set keys only", any(l.startswith("export LLVM_ROOT=") for l in lines) and not any("PLUGINVAL_TSAN" in l for l in lines))
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "tools.toml"
        p.write_text('[llvm]\nroot = "%s"\n[pluginval]\napp = "/no/such/pluginval"\n' % t, encoding="utf-8")
        probs = check(load(p), p)
        expect("check reports the missing path only", probs == ["pluginval.app: /no/such/pluginval does not exist"])
        expect("check without a file explains", "no tools.toml" in check({}, p)[0])
    if fails:
        print("toolchain selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("toolchain selftest OK: the example parses with both parsers and has every section, get expands and defaults, env exports only set keys, check names the missing path")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if cmd == "path":
        print(location())
        return 0
    if cmd == "init":
        print(init())
        return 0
    if cmd == "get":
        if len(argv) < 2:
            print("usage: toolchain.py get <section.key>", file=sys.stderr)
            return 2
        v = get(argv[1])
        if v is None:
            print("%s is not set in %s" % (argv[1], location()), file=sys.stderr)
            return 1
        print(v)
        return 0
    if cmd == "env":
        print("\n".join(env_lines()))
        return 0
    if cmd == "check":
        probs = check()
        for p in probs:
            print("ERROR: " + p)
        if probs:
            return 1
        print("toolchain check OK: %s" % location())
        return 0
    print("unknown command %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
