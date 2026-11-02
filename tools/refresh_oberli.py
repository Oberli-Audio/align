#!/usr/bin/env python3
"""Refresh the family's shared code in a plugin repo: byte-copies Source/oberli/ (and the tests
and this tool that go with it) from the plugin template, and wires it into CMakeLists.txt and the
harness when the repo predates it.

Source/oberli/ is generated in ~/bob-skills (tools/template-src/Source/oberli) and published in
Oberli-Audio/plugin-template; a plugin never edits it. Run this in the plugin repo:

    python3 tools/refresh_oberli.py                      # from a fresh shallow clone of the template on GitHub
    python3 tools/refresh_oberli.py --from ~/Developer/oberli-audio/plugin-template
    python3 tools/refresh_oberli.py --check              # exit 1 when Source/oberli/ differs from its MANIFEST

A repo made before Source/oberli/ existed has no copy of this tool yet; fetch the template once:

    git clone --depth 1 https://github.com/Oberli-Audio/plugin-template /tmp/plugin-template
    python3 /tmp/plugin-template/tools/refresh_oberli.py --from /tmp/plugin-template

What it does, in order:
  1. replaces Source/oberli/ with the template's (files the template no longer has are removed);
  2. copies tools/tests/test_loudness.cpp, test_oberli.cpp, check_bounce.py and this tool;
  3. CMakeLists.txt: adds the Source/oberli glob, the binary data, the theme and accent (--accent,
     else the registry's entry), the links and the shared tests, if the file has none of them yet
     (it prints what it changed);
  4. notices.toml: adds Rubik and Nunito (the shared code bundles them) and regenerates THIRD_PARTY_NOTICES.md;
  5. tools/harness/Main.cpp: adds --non-realtime (the bounce null test needs it), if missing.
Then build and run `ctest --preset fast`, and commit: "oberli: refresh from plugin-template <sha>".
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE_URL = "https://github.com/Oberli-Audio/plugin-template"
COMPANIONS = ["tools/tests/test_loudness.cpp", "tools/tests/test_oberli.cpp", "tools/tests/check_bounce.py",
              "tools/gui_snapshot/Main.cpp",
              "tools/refresh_oberli.py"]
MANIFEST = "MANIFEST.sha256"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(repo):
    folder = repo / "Source" / "oberli"
    manifest = folder / MANIFEST
    if not manifest.exists():
        print("Source/oberli/%s missing: run tools/refresh_oberli.py" % MANIFEST, file=sys.stderr)
        return 1
    want = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(None, 1)
            want[name.strip()] = digest
    have = {p.relative_to(folder).as_posix(): sha256(p) for p in folder.rglob("*") if p.is_file() and p.name != MANIFEST}
    problems = ["edited: %s" % n for n in sorted(want) if n in have and have[n] != want[n]]
    problems += ["missing: %s" % n for n in sorted(set(want) - set(have))]
    problems += ["not from the template: %s" % n for n in sorted(set(have) - set(want))]
    if problems:
        print("Source/oberli/ differs from the template's copy (never edit it here; change ~/bob-skills "
              "tools/template-src/Source/oberli and refresh):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print("Source/oberli/ is the template's copy (%d files)" % len(want))
    return 0


def snippets(template):
    """tools/init/oberli-cmake.txt: '# >>> name' ... '# <<< name' blocks, each verbatim in the template's CMakeLists.txt."""
    path = template / "tools" / "init" / "oberli-cmake.txt"
    if not path.exists():
        sys.exit("refresh_oberli: %s has no tools/init/oberli-cmake.txt" % template)
    return dict(re.findall(r"# >>> (\S+)\n(.*?)# <<< \1\n", path.read_text(encoding="utf-8"), re.S))


def accent_hex(repo, template, given):
    """The product's accent as RRGGBB: --accent, else the one CMakeLists.txt already sets, else the
    registry's entry for ship.toml's slug (registry.py finds the registry as everywhere)."""
    if given:
        return given.lstrip("#").upper()
    m = re.search(r"OBERLI_ACCENT=0xFF([0-9A-Fa-f]{6})", (repo / "CMakeLists.txt").read_text(encoding="utf-8"))
    if m:
        return m.group(1).upper()
    try:
        sys.dont_write_bytecode = True   # leave no __pycache__ in the template clone
        sys.path.insert(0, str(template / "scripts" / "ship"))
        import registry as R
        path = R.find_registry(None)
        slug = R.load_toml(repo / "ship.toml").get("product", {}).get("slug")
        reg = R.load_toml(path) if path else {}
        entry = reg.get("plugin", {}).get(slug)
        if entry:
            return reg["family"]["accent_hex"][entry["accent"]].lstrip("#").upper()
    except Exception:  # noqa: BLE001 - any failure means: ask for --accent
        pass
    sys.exit("refresh_oberli: no accent known for this plugin: pass --accent '#RRGGBB', its category's "
             "(plugin-ui-bob brand sheet: instruments tangerine #F4511E, creative banana #F6BF26, "
             "mix sage #33B679, analysis peacock #039BE5)")


def wire_cmake(repo, template, accent=None):
    """Adds each snippet the repo's CMakeLists.txt lacks, at its anchor:
         sources        before target_sources(<Id> PRIVATE ${PRODUCT_SOURCES})   unless 'Source/oberli' is there
         binary         after that line                                          unless 'juce_add_binary_data(OberliUiData' is there
         plugin-links   into target_link_libraries(<Id> PRIVATE                   unless the plugin links OberliUiData
         harness-links  into target_link_libraries(<Id>Harness PRIVATE            unless the harness links OberliUiData
         bounce         before add_test(NAME preset_bank                          unless 'bounce_null' is there
         tests          at the end                                               unless 'OberliLoudnessTest' is there"""
    path = repo / "CMakeLists.txt"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^project\((\w+)\s", text, re.M)
    if m is None:
        print("CMakeLists.txt: no project() line; wire Source/oberli by hand as the template's CMakeLists.txt does")
        return
    pid = m.group(1)
    placeholder = "{{" + "ProductId" + "}}"   # spelled apart, so init_plugin.py leaves this line alone
    snip = {k: v.replace(placeholder, pid) for k, v in snippets(template).items()}
    if any("{{" + "AccentHexBare" + "}}" in v for v in snip.values()):
        hexa = accent_hex(repo, template, accent)
        snip = {k: v.replace("{{" + "AccentHexBare" + "}}", hexa) for k, v in snip.items()}
    sources_line = "target_sources(%s PRIVATE ${PRODUCT_SOURCES})\n" % pid
    plugin_links = "target_link_libraries(%s\n    PRIVATE\n" % pid
    harness_links = "target_link_libraries(%sHarness PRIVATE\n" % pid
    changed, manual = [], []

    def add(name, present, anchor, before):
        nonlocal text
        if name not in snip or present:
            return
        if anchor not in text:
            manual.append(name)
            return
        text = text.replace(anchor, snip[name] + anchor if before else anchor + snip[name], 1)
        changed.append(name)

    def links_ui(anchor):
        i = text.find(anchor)
        return i >= 0 and "OberliUiData" in text[i:text.find(")", i)]

    add("sources", "Source/oberli" in text, sources_line, True)
    add("binary", "juce_add_binary_data(OberliUiData" in text, sources_line, False)
    add("plugin-links", links_ui(plugin_links), plugin_links, False)
    add("harness-links", links_ui(harness_links), harness_links, False)
    add("bounce", "bounce_null" in text, "        add_test(NAME preset_bank", True)
    add("snapshot", "GuiSnapshot" in text, "# Real-time safety (rule 1): the harness with RealtimeSanitizer;", True)
    # the harness compiles the sources itself: it needs the theme and the accent too
    start = text.find("target_compile_definitions(%sHarness PRIVATE" % pid)
    if "binary" in snip and start >= 0 and "PRODUCT_OBERLI_DEFINITIONS" not in text[start:text.find(")", start)]:
        close = text.find(")", start)
        text = text[:close] + " ${PRODUCT_OBERLI_DEFINITIONS}" + text[close:]
        changed.append("harness definitions")
    if "tests" in snip and "OberliLoudnessTest" not in text:
        text = text.rstrip("\n") + "\n\n" + snip["tests"]
        changed.append("tests")

    path.write_text(text, encoding="utf-8")
    print("CMakeLists.txt: %s" % ("added " + ", ".join(changed) if changed else "already wired"))
    for name in manual:
        print("CMakeLists.txt: no anchor for '%s'; add that block of the template's tools/init/oberli-cmake.txt by hand" % name)


def wire_notices(repo, template):
    """The fonts ship with Source/oberli: each notices entry the repo lacks (by name), then
    THIRD_PARTY_NOTICES.md regenerated."""
    notices = repo / "notices.toml"
    entries = template / "tools" / "init" / "oberli-notices.toml"
    if not notices.exists() or not entries.exists():
        return
    text = notices.read_text(encoding="utf-8")
    body = "".join(l for l in entries.read_text(encoding="utf-8").splitlines(True) if not l.startswith("#"))
    added = []
    for block in re.split(r"\n(?=\[\[component\]\])", body):
        m = re.search(r'^name = "([^"]+)"', block, re.M)
        if m and 'name = "%s"' % m.group(1) not in text:
            text = text.rstrip("\n") + "\n\n" + block.strip("\n") + "\n"
            added.append(m.group(1))
    if not added:
        print("notices.toml: the shared code's fonts are there")
        return
    notices.write_text(text, encoding="utf-8")
    tool = repo / "scripts" / "ship" / "notices.py"
    if tool.exists():
        r = subprocess.run([sys.executable, str(tool), "generate", str(repo)], capture_output=True, text=True)
        print("notices.toml: added %s; THIRD_PARTY_NOTICES.md %s" % (", ".join(added), "regenerated" if r.returncode == 0 else "NOT regenerated: " + r.stderr.strip()[-200:]))
    else:
        print("notices.toml: added %s; regenerate THIRD_PARTY_NOTICES.md" % ", ".join(added))


def wire_harness(repo):
    path = repo / "tools" / "harness" / "Main.cpp"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if '"non-realtime"' in text:
        print("tools/harness/Main.cpp: --non-realtime already there")
        return
    steps = [
        ('"list-params", "list-presets" };', '"list-params", "list-presets", "non-realtime" };'),
        ("    processor->setNonRealtime (false);\n",
         '    const bool nonRealtime = args.has ("non-realtime");\n    processor->setNonRealtime (nonRealtime);\n'),
        ('set (applied, "seconds", seconds);', 'set (applied, "seconds", seconds); set (applied, "non_realtime", nonRealtime);'),
    ]
    for old, new in steps:
        if old not in text:
            print("tools/harness/Main.cpp: could not add --non-realtime (no '%s'); add it by hand as the template's harness has it" % old.strip())
            return
        text = text.replace(old, new, 1)
    text = re.sub(r'(    "  --solo=<part>[^\n]*\n)',
                  r'\1    "  --non-realtime               render as a bounce: setNonRealtime (true) (oberli/RenderSafety.h, check_bounce.py)\\n"\n',
                  text, count=1)
    path.write_text(text, encoding="utf-8")
    print("tools/harness/Main.cpp: added --non-realtime")


def refresh(repo, template, accent=None):
    src = template / "Source" / "oberli"
    if not (src / MANIFEST).exists():
        sys.exit("refresh_oberli: %s has no Source/oberli/%s" % (template, MANIFEST))
    dst = repo / "Source" / "oberli"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    pid = re.search(r"^project\((\w+)\s", (repo / "CMakeLists.txt").read_text(encoding="utf-8"), re.M)
    for rel in COMPANIONS:
        if (template / rel).exists():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template / rel, repo / rel)
            if rel.endswith(".cpp") and pid:   # the snapshot tool names the product's processor
                text = (repo / rel).read_text(encoding="utf-8")
                (repo / rel).write_text(text.replace("{{" + "ProductId" + "}}", pid.group(1)), encoding="utf-8")
    n = sum(1 for p in dst.rglob("*") if p.is_file())
    sha = subprocess.run(["git", "-C", str(template), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print("Source/oberli/: %d files from %s%s" % (n, template, " (%s)" % sha if sha else ""))
    wire_cmake(repo, template, accent)
    wire_notices(repo, template)
    wire_harness(repo)
    print("Then: cmake --preset release && cmake --build --preset release && ctest --preset fast, and commit "
          "\"oberli: refresh from plugin-template%s\"" % (" " + sha if sha else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", help="a plugin-template clone (default: a shallow clone from GitHub)")
    ap.add_argument("--repo", default=".", help="the plugin repo (default: here)")
    ap.add_argument("--check", action="store_true", help="only compare Source/oberli/ with its MANIFEST")
    ap.add_argument("--accent", help="the category's accent as #RRGGBB (default: CMakeLists.txt, else the registry)")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    if a.check:
        return check(repo)
    if not (repo / "CMakeLists.txt").exists():
        sys.exit("refresh_oberli: %s is not a plugin repo (no CMakeLists.txt)" % repo)
    if a.source:
        return refresh(repo, Path(a.source).expanduser().resolve(), a.accent)
    with tempfile.TemporaryDirectory() as d:
        clone = Path(d) / "plugin-template"
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", TEMPLATE_URL, str(clone)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("refresh_oberli: cannot clone %s:\n%s" % (TEMPLATE_URL, r.stderr))
        return refresh(repo, clone, a.accent)


if __name__ == "__main__":
    sys.exit(main())
