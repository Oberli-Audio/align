#!/usr/bin/env python3
"""init_plugin - turn a fresh clone of Oberli-Audio/plugin-template into a product.

Run inside the clone (or with --repo-dir). It derives the identifiers from the product name,
takes a free four-character code and a free accent from the family registry (or the ones you
pass), registers the product there, fills every {{placeholder}} in the tree, swaps the
instrument table in for an instrument, regenerates Params.h, the manual and the notices, removes
itself, checks the result (no placeholder left, shipcheck docs green) and commits "init from
template".

    python3 tools/init_plugin.py --product "Shimmer" --kind effect [--code Shim] [--accent saffron]
                                 [--tier S|P|F] [--repo Oberli-Audio/shimmer] [--registry <plugins.toml>]
                                 [--registered] [--no-commit] [--repo-dir <clone>] [--date YYYY-MM-DD]
    python3 tools/init_plugin.py --check          # no placeholder left in the tree

--registered uses the product's existing registry entry instead of adding one (a repo started
again after a failed init). The registry is found like registry.py finds it: $OBERLI_REGISTRY,
~/.config/oberli/tools.toml, ~/bob-skills.
"""
import argparse
import csv
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{[A-Za-z]+\}\}")
TEXT_SUFFIXES = {".txt", ".md", ".cpp", ".h", ".py", ".toml", ".json", ".csv", ".yml", ".yaml", ".cmake", ".oberlipreset",
                 ".sh", ".reg", ".example", ".gitignore", ".in"}
TEXT_NAMES = {"CMakeLists.txt", "LICENSE", "VERSION", ".gitignore"}


def is_text(p):
    return p.suffix in TEXT_SUFFIXES or p.name in TEXT_NAMES


def tree_files(root):
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(root).parts and "__pycache__" not in p.parts:
            yield p


def placeholders_left(root):
    hits = []
    for p in tree_files(root):
        if not is_text(p):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in PLACEHOLDER.findall(line):
                hits.append("%s:%d: %s" % (p.relative_to(root), i, m))
    return hits


def init_params_xml(csv_path):
    lines = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lines.append('      <PARAM id="%s" value="%s"/>' % (row["id"], row["default"]))
    return "\n".join(lines)


def substitutions(entry, a, root):
    today = a.date or dt.date.today().isoformat()
    inst = entry["kind"] == "instrument"
    return {
        "Product": entry["name"], "ProductId": entry["id"], "slug": entry["slug"], "bundle": entry["bundle"],
        "BundleId": entry["bundle_id"], "Code": entry["code"], "accent": entry["accent"], "AccentHex": entry["accent_hex"],
        "AccentHexBare": entry["accent_hex"].lstrip("#"), "theme": entry["theme"], "kind": entry["kind"],
        "Repo": entry["repo"], "Owner": entry["repo"].split("/")[0], "Year": today[:4], "Date": today, "Tier": a.tier,
        "Formats": "VST3 Standalone",
        "HarnessSource": "--notes=60 --gate=1" if inst else "--signal=impulse",
        "HarnessSourceDict": 'dict(notes="48,55,60,64", gate=1.0)' if inst else 'dict(signal="impulse")',
        "InitParams": init_params_xml(root / "parameters.csv"),
    }


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("init_plugin: %s failed\n%s%s" % (" ".join(str(c) for c in cmd), r.stdout, r.stderr))
    return r.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--product")
    ap.add_argument("--kind", choices=("instrument", "effect"))
    ap.add_argument("--code")
    ap.add_argument("--accent")
    ap.add_argument("--tier", default="S", choices=("S", "P", "F"))
    ap.add_argument("--repo", help="owner/repo on GitHub (default: the registry's owner and the slug)")
    ap.add_argument("--registry")
    ap.add_argument("--registered", action="store_true", help="use the existing registry entry for this product")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--date")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.repo_dir).resolve()

    if a.check:
        hits = placeholders_left(root)
        for h in hits:
            print(h)
        print("init_plugin check: %s" % ("%d placeholder(s) left" % len(hits) if hits else "no placeholder left"))
        return 1 if hits else 0

    if not a.product or not a.kind:
        ap.error("--product and --kind are required")
    if (root / "CMakeLists.txt").exists() and not placeholders_left(root):
        sys.exit("init_plugin: this tree has no placeholders left; it was initialised already")
    if not (root / "CMakeLists.txt").exists() or not (root / "tools/init_plugin.py").exists():
        sys.exit("init_plugin: run it inside a fresh clone of the template (CMakeLists.txt and tools/init_plugin.py expected)")

    sys.path.insert(0, str(root / "scripts/ship"))
    import registry as R
    path = R.find_registry(a.registry)
    if path is None:
        sys.exit("init_plugin: no registry found (set OBERLI_REGISTRY, or registry.plugins in ~/.config/oberli/tools.toml)")
    reg = R.load_toml(path)
    d = R.derive(a.product)
    fam = reg["family"]
    if a.registered:
        e = reg.get("plugin", {}).get(d["slug"])
        if e is None:
            sys.exit("init_plugin: --registered, but %s is not in %s" % (d["slug"], path))
        entry = dict(e, slug=d["slug"], bundle=d["bundle"], accent_hex=fam["accent_hex"][e["accent"]], theme=R.KINDS[e["kind"]])
    else:
        try:
            entry = R.add(path, a.product, a.kind, a.code, a.accent, a.repo)
        except ValueError as ex:
            sys.exit("init_plugin: %s" % ex)
        print("registered %s in %s: code %s, accent %s" % (entry["slug"], path, entry["code"], entry["accent"]))
    if entry["kind"] != a.kind:
        sys.exit("init_plugin: the registry says %s is an %s, you said %s" % (entry["slug"], entry["kind"], a.kind))

    # the instrument table replaces the effect one before the substitutions (InitParams reads it)
    if a.kind == "instrument":
        (root / "tools/init/parameters.instrument.csv").replace(root / "parameters.csv")
    sub = substitutions(entry, a, root)

    # fill every placeholder
    changed = 0
    for p in tree_files(root):
        if not is_text(p):
            continue
        text = p.read_text(encoding="utf-8")
        new = PLACEHOLDER.sub(lambda m: sub.get(m.group(0)[2:-2], m.group(0)), text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1

    # the README's template note goes; the generated files follow the table and the manifest
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    if text.startswith("<!-- Oberli-Audio/plugin-template"):
        text = text.split("-->\n", 1)[1]
        readme.write_text(text, encoding="utf-8")
    kit = root / "scripts/dsp-kit"
    run([sys.executable, str(kit / "paramgen.py"), "juce", "parameters.csv", "-o", "Source/Params.h"], root)
    run([sys.executable, str(kit / "paramgen.py"), "manual", "parameters.csv", "-o", "docs/parameters.md"], root)
    run([sys.executable, str(root / "scripts/ship/notices.py"), "generate", "."], root)
    run([sys.executable, str(root / "scripts/ship/shipcheck.py"), "known-issues", ".", "--write"], root)

    # the init material leaves the product
    for p in (root / "tools/init/parameters.instrument.csv", root / "tools/init_plugin.py"):
        if p.exists():
            p.unlink()
    if (root / "tools/init").exists() and not any((root / "tools/init").iterdir()):
        (root / "tools/init").rmdir()

    hits = placeholders_left(root)
    if hits:
        sys.exit("init_plugin: placeholders left:\n  " + "\n  ".join(hits))
    env = dict(os.environ, OBERLI_REGISTRY=str(path))
    r = subprocess.run([sys.executable, str(root / "scripts/ship/shipcheck.py"), "docs", "."], cwd=str(root), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        sys.exit("init_plugin: shipcheck docs is not green on the initialised tree:\n" + r.stdout + r.stderr)
    r = subprocess.run([sys.executable, str(root / "scripts/ship/shipcheck.py"), "registry", "."], cwd=str(root), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        sys.exit("init_plugin: the tree disagrees with its registry entry:\n" + r.stdout + r.stderr)

    if not a.no_commit and (root / ".git").is_dir():
        subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init from template: %s (%s, %s, %s)" % (entry["name"], entry["kind"], entry["code"], entry["accent"])],
                       cwd=str(root), check=True)
        print("committed: init from template")
    print("%s initialised: %s, code %s, accent %s (%s), theme %s, tier %s; %d files filled. Next: cmake --preset release && cmake --build --preset release, then ctest --preset fast"
          % (entry["name"], entry["kind"], entry["code"], entry["accent"], entry["accent_hex"], entry["theme"], a.tier, changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
