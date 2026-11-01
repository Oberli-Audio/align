#!/usr/bin/env python3
"""notices - THIRD_PARTY_NOTICES.md generated from notices.toml, and the check that the
manifest matches what CMake actually pulls in (references/notices.md).

    notices.py generate <repo> [--out THIRD_PARTY_NOTICES.md]   # write the notices file with full licence texts
    notices.py check    <repo>                                   # manifest vs CMakeLists, licence files, markers, copyleft
    notices.py print    <repo>                                   # the generated text to stdout
    notices.py selftest

notices.toml (repo root):

    [check]
    cmake = ["CMakeLists.txt", "cmake/*.cmake"]     # files scanned for FetchContent_Declare, add_subdirectory, juce_add_module, fonts
    ignore = ["src", "tests"]                        # add_subdirectory targets that are your own code

    [[component]]
    name = "VST 3 SDK"            kind = "sdk"            # framework | sdk | library | font | faust | content
    version = "3.8.0"             spdx = "MIT"
    copyright = "Steinberg Media Technologies GmbH"
    url = "https://github.com/steinbergmedia/vst3sdk"
    license_file = "LICENSES/MIT.txt"                    # full text, pasted into the notices
    note = "VST is a registered trademark of Steinberg Media Technologies GmbH."
    cmake = "vst3sdk"                                    # the name in CMakeLists when it differs from name
    files = ["Inter-Regular.ttf"]                        # fonts: the bundled files

A component whose spdx is GPL or AGPL fails the check: this product is not GPL. A
`LicenseRef-*` licence (the JUCE EULA) needs a `note` instead of a file. Exit 0 pass, 1 fail.
"""
import glob
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from shipcheck import load_toml  # noqa: E402

KINDS = ["framework", "sdk", "library", "font", "faust", "content"]
KIND_TITLES = {"framework": "Framework", "sdk": "Plugin SDKs", "library": "Libraries", "font": "Fonts",
               "faust": "Faust library functions (generated code)", "content": "Content (samples, impulse responses, images)"}
MARKERS = {"MIT": "Permission is hereby granted", "OFL-1.1": "Reserved Font Name", "Apache-2.0": "Apache License",
           "BSD-3-Clause": "Redistributions of source code", "BSD-2-Clause": "Redistributions of source code",
           "ISC": "Permission to use, copy, modify", "MPL-2.0": "Mozilla Public License", "Zlib": "freely, subject to the following restrictions",
           "LicenseRef-STK-4.3": "STK", "CC-BY-4.0": "Attribution 4.0", "CC0-1.0": "CC0"}
COPYLEFT = re.compile(r"^(A?GPL|LGPL-2\.1-only|LGPL-3\.0-only)", re.I)
FONT_EXT = (".ttf", ".otf", ".woff", ".woff2")
GENERATED_LINE = "Generated %s by ship-bob notices.py from notices.toml. Do not edit by hand; edit the manifest."


def load_manifest(repo):
    p = Path(repo) / "notices.toml"
    if not p.exists():
        return None
    return load_toml(p)


def product_name(repo, manifest):
    ship = Path(repo) / "ship.toml"
    if ship.exists():
        try:
            return load_toml(ship).get("product", {}).get("name") or Path(repo).name
        except Exception:
            pass
    return manifest.get("product", {}).get("name") if isinstance(manifest.get("product"), dict) else Path(repo).name


def cmake_dependencies(repo, manifest):
    """Names CMake pulls in: FetchContent_Declare(<name>, add_subdirectory(<dir>), juce_add_module(<dir>),
    and font files named in juce_add_binary_data."""
    repo = Path(repo)
    chk = manifest.get("check", {}) if manifest else {}
    pats = chk.get("cmake", ["CMakeLists.txt", "cmake/*.cmake"])
    ignore = {x.lower() for x in chk.get("ignore", [])}
    files = []
    for pat in pats:
        files += [Path(f) for f in glob.glob(str(repo / pat))]
    deps, fonts = {}, {}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"#[^\n]*", "", text)
        for m in re.finditer(r"FetchContent_Declare\s*\(\s*([A-Za-z0-9_.\-]+)", text, re.I):
            deps.setdefault(m.group(1), "FetchContent_Declare in %s" % f.name)
        for m in re.finditer(r"add_subdirectory\s*\(\s*([^\s)]+)", text, re.I):
            name = Path(m.group(1).strip('"')).name
            if name.lower() not in ignore and not m.group(1).startswith("$"):
                deps.setdefault(name, "add_subdirectory in %s" % f.name)
        for m in re.finditer(r"juce_add_module\s*\(\s*([^\s)]+)", text, re.I):
            deps.setdefault(Path(m.group(1).strip('"')).name, "juce_add_module in %s" % f.name)
        for m in re.finditer(r"juce_add_binary_data\s*\((.*?)\)", text, re.I | re.S):
            for ff in re.findall(r"([^\s\"]+\.(?:ttf|otf|woff2?))", m.group(1), re.I):
                fonts.setdefault(Path(ff).name, "juce_add_binary_data in %s" % f.name)
    return deps, fonts


def check(repo, manifest=None, quiet=False):
    repo = Path(repo)
    manifest = manifest if manifest is not None else load_manifest(repo)
    errs = []
    if manifest is None:
        return ["notices.toml missing at the repo root (ship-bob references/notices.md)"]
    comps = manifest.get("component", [])
    if not comps:
        errs.append("notices.toml: no [[component]] entries")
    names = {}
    font_files = {}
    for c in comps:
        n = c.get("name")
        if not n:
            errs.append("notices.toml: a component without a name")
            continue
        for key in ("kind", "spdx", "copyright"):
            if not c.get(key):
                errs.append("notices.toml: %s has no %s" % (n, key))
        if c.get("kind") and c["kind"] not in KINDS:
            errs.append("notices.toml: %s has kind %r, expected one of %s" % (n, c["kind"], ", ".join(KINDS)))
        spdx = c.get("spdx", "")
        alternatives = [s.strip() for s in re.split(r"\s+OR\s+", spdx) if s.strip()] or [spdx]
        if alternatives and all(COPYLEFT.match(s) for s in alternatives):
            errs.append("%s is %s: copyleft code cannot ship in this product (references/notices.md); replace it or make the product GPL" % (n, spdx))
        lf = c.get("license_file")
        if lf:
            p = repo / lf
            if not p.exists():
                errs.append("%s: license_file %s does not exist" % (n, lf))
            else:
                markers = [MARKERS[s] for s in alternatives if s in MARKERS]
                text_l = p.read_text(encoding="utf-8", errors="replace").lower()
                if markers and not any(m.lower() in text_l for m in markers):
                    errs.append("%s: %s does not look like the %s text (expected one of %r in it)" % (n, lf, spdx, markers))
        elif spdx.startswith("LicenseRef-"):
            if not c.get("note"):
                errs.append("%s: a LicenseRef licence needs a note saying under what terms it is used" % n)
        elif c.get("kind") != "content":
            errs.append("%s: no license_file; MIT, BSD, OFL and Apache require their text to travel with the binary" % n)
        if re.search(r"\bVST\b", n, re.I) and "registered trademark" not in (c.get("note") or "").lower():
            errs.append("%s: the note must carry 'VST is a registered trademark of Steinberg Media Technologies GmbH.'" % n)
        if c.get("kind") == "font" and not c.get("files"):
            errs.append("%s: a font entry lists its bundled files" % n)
        for alias in {n.lower(), (c.get("cmake") or n).lower()}:
            names[alias] = n
        for ff in c.get("files", []) or []:
            font_files[Path(ff).name.lower()] = n
    deps, fonts = cmake_dependencies(repo, manifest)
    for d, where in sorted(deps.items()):
        if d.lower() not in names:
            errs.append("CMake pulls in %s (%s) and notices.toml has no entry for it" % (d, where))
    for f, where in sorted(fonts.items()):
        if f.lower() not in font_files:
            errs.append("BinaryData bundles font %s (%s) and no font entry in notices.toml lists it" % (f, where))
    if not quiet:
        for e in errs:
            print("ERROR: " + e)
        if errs:
            print("notices check: %d error(s)" % len(errs))
        else:
            print("notices check OK: %d component(s), %d CMake dependenc%s and %d font file(s) all in the manifest" % (
                len(comps), len(deps), "y" if len(deps) == 1 else "ies", len(fonts)))
    return errs


def generate_text(repo, manifest=None, date=None):
    repo = Path(repo)
    manifest = manifest if manifest is not None else load_manifest(repo)
    if manifest is None:
        raise SystemExit("notices.toml missing")
    date = date or time.strftime("%Y-%m-%d")
    out = ["# Third-party notices - %s" % product_name(repo, manifest), "",
           GENERATED_LINE % date, "",
           "This product bundles or is built with the components below. Each keeps its own licence; the full texts follow. "
           "The product's own terms are in `LICENSE`.", ""]
    comps = manifest.get("component", [])
    for kind in KINDS:
        group = [c for c in comps if c.get("kind") == kind]
        if not group:
            continue
        out += ["## " + KIND_TITLES[kind], ""]
        for c in group:
            head = c["name"] + (" %s" % c["version"] if c.get("version") else "")
            out.append("### " + head)
            line = "Copyright (c) %s." % c.get("copyright", "")
            if c.get("spdx"):
                line += " Licence: %s." % c["spdx"]
            if c.get("url"):
                line += " %s" % c["url"]
            out.append(line)
            if c.get("files"):
                out.append("Bundled file(s): %s." % ", ".join(c["files"]))
            if c.get("note"):
                out.append(c["note"])
            lf = c.get("license_file")
            if lf and (repo / lf).exists():
                out += ["", "```", (repo / lf).read_text(encoding="utf-8", errors="replace").strip(), "```"]
            out.append("")
    out += ["## Trademarks", "",
            "Host and system names in the documentation (Ableton Live, Logic Pro, macOS, Windows and others) name where the product "
            "runs and are trademarks of their respective owners. No logo of theirs is used.", ""]
    return "\n".join(out).rstrip() + "\n"


def strip_date(text):
    return re.sub(r"^Generated \d{4}-\d{2}-\d{2} ", "Generated <date> ", text, flags=re.M)


def check_in_sync(repo):
    """shipcheck docs: THIRD_PARTY_NOTICES.md equals what the manifest generates (date aside)."""
    repo = Path(repo)
    p = repo / "THIRD_PARTY_NOTICES.md"
    if load_manifest(repo) is None:
        return []  # check() already reports the missing manifest
    if not p.exists():
        return ["THIRD_PARTY_NOTICES.md missing: run notices.py generate ."]
    if strip_date(p.read_text(encoding="utf-8")) != strip_date(generate_text(repo)):
        return ["THIRD_PARTY_NOTICES.md is not what notices.toml generates: run notices.py generate ."]
    return []


def generate(repo, out=None):
    text = generate_text(repo)
    p = Path(out) if out else Path(repo) / "THIRD_PARTY_NOTICES.md"
    p.write_text(text, encoding="utf-8")
    print("wrote %s (%d components)" % (p, len(load_manifest(repo).get("component", []))))
    return 0


# ----------------------------------------------------------------------------- selftest

def selftest():
    import shutil, tempfile
    here = HERE.parent.parent / "tests" / "fixtures" / "fakeplugin"
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        shutil.copytree(here, repo)
        expect("fixture manifest passes", not check(repo, quiet=True))
        expect("fixture notices in sync", not check_in_sync(repo))
        text = generate_text(repo)
        expect("full MIT text pasted", "Permission is hereby granted" in text and "WITHOUT WARRANTY OF ANY KIND" in text)
        expect("full OFL text pasted", "PREAMBLE" in text and "Reserved Font Name" in text)
        expect("font files listed", "Bundled file(s): Inter-Regular.ttf" in text)
        expect("trademark line", "registered trademark of Steinberg" in text)
        expect("no version in title", "Fake Pad 1.2.0" not in text.splitlines()[0])

        def planted(label, mutate, needle, fn=None):
            with tempfile.TemporaryDirectory() as d2:
                r2 = Path(d2) / "repo"
                shutil.copytree(repo, r2)
                mutate(r2)
                errs = (fn or (lambda r: check(r, quiet=True)))(r2)
                expect(label, any(needle in e for e in errs))
        toml = lambda r: (r / "notices.toml")
        planted("FetchContent without entry", lambda r: (r / "CMakeLists.txt").write_text((r / "CMakeLists.txt").read_text() + "\nFetchContent_Declare(chowdsp_wdf GIT_REPOSITORY x GIT_TAG y)\n"), "chowdsp_wdf")
        planted("font without entry", lambda r: (r / "CMakeLists.txt").write_text((r / "CMakeLists.txt").read_text().replace("Inter-Regular.ttf", "Inter-Regular.ttf fonts/Inter-Bold.ttf")), "Inter-Bold.ttf")
        planted("GPL rejected", lambda r: toml(r).write_text(toml(r).read_text() + '\n[[component]]\nname = "zita"\nkind = "faust"\nspdx = "GPL-2.0-or-later"\ncopyright = "x"\nnote = "x"\n'), "copyleft")
        # an OR expression with a permissive alternative passes (JUCE's ASIO: LicenseRef-Steinberg-ASIO OR GPL-3.0)
        with tempfile.TemporaryDirectory() as d4:
            r4 = Path(d4) / "repo"
            shutil.copytree(repo, r4)
            toml(r4).write_text(toml(r4).read_text() + '\n[[component]]\nname = "asio"\nkind = "sdk"\nspdx = "LicenseRef-Steinberg-ASIO OR GPL-3.0-only"\ncopyright = "Steinberg"\nlicense_file = "LICENSES/MIT.txt"\nnote = "used under the Steinberg ASIO licence"\n')
            expect("OR expression with a permissive side passes", not any("copyleft" in e for e in check(r4, quiet=True)))
        planted("wrong licence text", lambda r: (r / "LICENSES" / "MIT.txt").write_text("not the text\n"), "does not look like the MIT text")
        planted("missing licence file", lambda r: toml(r).write_text(toml(r).read_text().replace('license_file = "LICENSES/OFL-1.1.txt"', "")), "no license_file")
        planted("trademark note missing", lambda r: toml(r).write_text(toml(r).read_text().replace("VST is a registered trademark", "VST is a mark")), "registered trademark")
        planted("stale notices file", lambda r: (r / "THIRD_PARTY_NOTICES.md").write_text("# old\n"), "not what notices.toml generates", check_in_sync)
        # generate restores sync
        with tempfile.TemporaryDirectory() as d3:
            r3 = Path(d3) / "repo"
            shutil.copytree(repo, r3)
            (r3 / "THIRD_PARTY_NOTICES.md").write_text("# old\n")
            generate(r3)
            expect("generate restores sync", not check_in_sync(r3))
    if fails:
        print("notices selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("notices selftest OK: the fixture manifest passes and its notices are in sync with full MIT and OFL texts, font files and the trademark line; an unlisted FetchContent, an unlisted font, a GPL component, a wrong licence text, a missing licence file, a missing trademark note and a stale notices file are each caught; an OR expression with a permissive side passes; generate restores sync")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if len(argv) < 2:
        print("usage: notices.py %s <repo>" % cmd, file=sys.stderr)
        return 2
    repo = argv[1]
    if cmd == "check":
        return 1 if check(repo) else 0
    if cmd == "generate":
        out = argv[argv.index("--out") + 1] if "--out" in argv else None
        errs = check(repo)
        if errs:
            return 1
        return generate(repo, out)
    if cmd == "print":
        print(generate_text(repo), end="")
        return 0
    print("unknown command %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
