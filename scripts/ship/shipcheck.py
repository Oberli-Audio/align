#!/usr/bin/env python3
"""shipcheck - the product documents are complete and consistent before a release.

    shipcheck.py docs <repo>              # all checks; exit 1 on any failure
    shipcheck.py secrets <repo>           # before going public: history and workflows scanned for secrets
    shipcheck.py release-assets <dir> [--repo .]   # the downloaded assets: names, zip layout, checksums, build-info (symbols: warnings)
    shipcheck.py message <repo>           # the pasteable message to the friends
    shipcheck.py changelog-section <repo> # print the CHANGELOG section for VERSION (release body)
    shipcheck.py known-issues <repo> [--write]   # README's Known issues from docs/status.md, Open exceptions (lines with a Friends: sentence)
    shipcheck.py registry <repo>          # ship.toml and CMakeLists.txt against the family registry (registry.py)
    shipcheck.py selftest

Checks (references/shipcheck.md):
  readme      README.md exists and has the sections friends need: an install section naming
              both platforms with the Open-Anyway / rescan words, uninstall, feedback (what he
              was doing, what he expected, the About copy, crash-report locations on both OS),
              licence; the releases/latest link.
  known-issues README's Known issues section equals what docs/status.md's Open exceptions generate
              (feedback-loop.md 6); `known-issues --write` regenerates it.
  changelog   CHANGELOG.md has a section for VERSION (Keep a Changelog heading); when
              ship.toml says sound_changed = true, that section carries "Sounds different".
  notices     notices.py: notices.toml covers every FetchContent / add_subdirectory / juce_add_module
              dependency and every bundled font, no copyleft component, licence texts present;
              THIRD_PARTY_NOTICES.md equals what the manifest generates.
  presets     presets/<slug>.* files on disk equal presets.csv (slugs, no extras, no missing);
              docs/presets.md (if present) names every preset.
  params      no parameter ID absent from parameters.csv is referenced in README, CHANGELOG,
              docs/parameters.md or docs/presets.md as `id` in backticks (a removed parameter
              must not survive in the friend-facing prose; engineering notes are not scanned).
  version     VERSION is x.y.z; the git tag v<VERSION>, if any, points at HEAD.
  license     a LICENSE file exists and carries the four things the README promises: free to use,
              the music is yours, presets you save are yours, all other rights reserved; no warranty.
  registry    ship.toml name, slug, asset_name and repo and CMakeLists.txt's codes, bundle id and
              names equal the product's entry in registry/plugins.toml (registry.py; skipped with a
              note when no registry is reachable on this machine).
  secrets     (own command) private keys, tokens, passwords in `git log -p --all` and .github/workflows.
Exit 0 pass, 1 failure(s), 2 unusable inputs.
"""
import csv
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

README_SECTIONS = {
    "install": [r"^##+\s*install"],
    "install-macos-open-anyway": [r"open anyway|xattr"],
    "install-windows-rescan": [r"common files\\vst3|rescan"],
    "uninstall": [r"^##+\s*uninstall|to remove|delete .*\.vst3"],
    "feedback": [r"^##+\s*feedback"],
    "feedback-what-and-expected": [r"doing right before|what (were )?you (were )?doing"],
    "feedback-about-copy": [r"about (panel|box)"],
    "crash-report-macos": [r"diagnosticreports|report a crash"],
    "crash-report-windows": [r"event viewer|crashdumps"],
    "known-issues": [r"^##+\s*known issues"],
    "licence": [r"^##+\s*licen[cs]e"],
    "releases-latest-link": [r"github\.com/[^/\s]+/[^/\s]+/releases/latest"],
    "quit-live-before-update": [r"quit ableton live|quit (your|the) daw"],
    "zip-not-source-code": [r"not .{0,20}source code|source code.{0,30}not"],
    "update-and-rollback": [r"^##+\s*update|previous release"],
}
SECRET_PATTERNS = [r"BEGIN (RSA|EC|OPENSSH|DSA|PGP) PRIVATE KEY", r"(?i)app-specific[- ]password\s*[:=]\s*\S{8,}",
                   r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+]{12,}",
                   r"ghp_[A-Za-z0-9]{30,}", r"xox[baprs]-[A-Za-z0-9-]{10,}", r"AKIA[0-9A-Z]{16}",
                   r"(?i)notarytool .*--password\s+\S+"]


def load_toml(path):
    """ship.toml with tomllib (3.11+) or a minimal parser for the subset ship.toml uses:
    [sections], [[arrays of tables]], key = "string" | true | false | integer | ["a", "b"], # comments."""
    text = Path(path).read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return _mini_toml(text)


def _mini_toml(text):
    import ast
    data, cur = {}, None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith('"') else raw.strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            cur = {}
            data.setdefault(line[2:-2].strip(), []).append(cur)
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = data.setdefault(line[1:-1].strip(), {})
            continue
        if "=" not in line:
            raise ValueError("ship.toml: cannot parse %r" % raw)
        k, v = (x.strip() for x in line.split("=", 1))
        if v in ("true", "false"):
            val = v == "true"
        elif v.startswith("["):
            val = list(ast.literal_eval(v))
        elif v.startswith('"'):
            val = ast.literal_eval(v)
        else:
            val = int(v)
        (cur if cur is not None else data)[k] = val
    return data


def read_toml(repo):
    p = Path(repo) / "ship.toml"
    return load_toml(p) if p.exists() else {}


def check_license(repo):
    """A public repo without a licence file is all-rights-reserved by default (github-releases.md)."""
    repo = Path(repo)
    cands = [p for p in repo.iterdir() if p.is_file() and p.name.upper().startswith("LICENSE")] if repo.exists() else []
    if not cands:
        return ["LICENSE missing: a public repo needs the licence file saying what the README's licence line says"]
    text = cands[0].read_text(encoding="utf-8", errors="replace").lower()
    errs = []
    for word, why in (("music", "that music made with the plugin belongs to its maker"), ("warranty", "that there is no warranty"),
                      ("reserved", "that all other rights are reserved (the clause that keeps the public source from being a licence to redistribute)"),
                      ("preset", "what the presets' terms are (factory presets part of the plugin, saved presets the user's own)")):
        if word not in text:
            errs.append("%s: should state %s" % (cands[0].name, why))
    return errs


def check_readme(repo):
    errs = []
    p = Path(repo) / "README.md"
    if not p.exists():
        return ["README.md missing (templates/README.md)"]
    text = p.read_text(encoding="utf-8")
    for name, pats in README_SECTIONS.items():
        if not any(re.search(pat, text, re.M | re.I) for pat in pats):
            errs.append("README.md: no %s" % name)
    return errs


def changelog_section(repo, version):
    p = Path(repo) / "CHANGELOG.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^## \[?v?%s\]?[^\n]*\n(.*?)(?=^## |\Z)" % re.escape(version), text, re.M | re.S)
    return m.group(1).strip() if m else None


def check_changelog(repo, version, cfg):
    sec = changelog_section(repo, version)
    if sec is None:
        return ["CHANGELOG.md: no section '## [%s] - <date>' (Keep a Changelog; sound-design-bob D.5.8)" % version]
    errs = []
    if not sec.strip():
        errs.append("CHANGELOG.md: the %s section is empty" % version)
    if cfg.get("release", {}).get("sound_changed") and "sounds different" not in sec.lower():
        errs.append("CHANGELOG.md: ship.toml says sound_changed = true but the %s section has no 'Sounds different:' line" % version)
    if cfg.get("release", {}).get("state_version_bumped") and "older version" not in sec.lower():
        errs.append("CHANGELOG.md: ship.toml says state_version_bumped = true but the %s section does not warn that projects will not open in older versions" % version)
    return errs


def check_notices(repo, cfg=None):
    """notices.py owns this: the manifest against CMake, licence texts, copyleft, and the generated file in sync."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import notices as N
    errs = N.check(repo, quiet=True)
    if not errs:
        errs = N.check_in_sync(repo)
    return errs


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check_presets(repo):
    repo = Path(repo)
    csvp = repo / "presets.csv"
    if not csvp.exists():
        return ["presets.csv missing"]
    rows = read_csv(csvp)
    slugs = [r["slug"].strip() for r in rows]
    errs = []
    pdir = repo / "presets"
    if pdir.exists():
        on_disk = {f.stem for f in pdir.iterdir() if f.is_file() and not f.name.startswith(".")}
        for s in slugs:
            if s not in on_disk:
                errs.append("presets/: no file for slug %r" % s)
        for s in sorted(on_disk - set(slugs)):
            errs.append("presets/%s.* exists but is not in presets.csv" % s)
    else:
        errs.append("presets/ folder missing")
    md = repo / "docs" / "presets.md"
    if md.exists():
        text = md.read_text(encoding="utf-8")
        for r in rows:
            if r["name"].strip() not in text:
                errs.append("docs/presets.md does not list %r (regenerate with presetlint.py render --md)" % r["name"].strip())
    return errs


def check_params(repo):
    repo = Path(repo)
    csvp = repo / "parameters.csv"
    if not csvp.exists():
        return ["parameters.csv missing"]
    ids = {r["id"].strip() for r in read_csv(csvp)}
    errs = []
    # friend-facing documents only: engineering notes under docs/ are full of code names that are not parameters
    files = [repo / "README.md", repo / "CHANGELOG.md", repo / "docs" / "parameters.md", repo / "docs" / "presets.md"]
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"`([a-z][A-Za-z0-9]{2,})`", text):
            tok = m.group(1)
            # lowerCamel tokens that look like parameter IDs: at least one capital inside, or listed in the removed list
            if re.match(r"^[a-z]+[A-Z][A-Za-z0-9]*$", tok) and tok not in ids:
                errs.append("%s references `%s`, which is not in parameters.csv (removed parameter still in prose?)" % (f.relative_to(repo), tok))
    return sorted(set(errs))


KNOWN_ISSUES_MARK = "<!-- generated by shipcheck.py known-issues --write from docs/status.md, Open exceptions -->"


def known_issues_lines(repo):
    """One line per open exception that carries a 'Friends:' sentence (feedback-loop.md 6,
    sound-design-bob D.9.2/D.9.4). Source: the 'Open exceptions' section of docs/status.md, one
    dated line per exception ('- EX-<n> <date>: ... Friends: <sentence>'); a resolved exception
    has left that section (it is a line under Decisions). 'Friends: none' stays out. Falls back
    to the older docs/exceptions.md (## EX-nnn entries without '### Resolution')."""
    out = []
    s = Path(repo) / "docs" / "status.md"
    if s.exists():
        m = re.search(r"^##+\s*Open exceptions[^\n]*\n(.*?)(?=^##+\s|\Z)", s.read_text(encoding="utf-8"), re.M | re.S)
        if m:
            for line in m.group(1).splitlines():
                e = re.match(r"^\s*-\s*(EX-\d+)\b.*?Friends:\s*(.+?)\s*$", line)
                if e and e.group(2).strip().rstrip(".").lower() not in ("none", "-", ""):
                    out.append("- %s (%s)" % (e.group(2).strip(), e.group(1)))
        return out
    p = Path(repo) / "docs" / "exceptions.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    for m in re.finditer(r"^## (EX-\d+)[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        exid, body = m.group(1), m.group(2)
        if re.search(r"^### Resolution", body, re.M):
            continue
        f = re.search(r"^Friends:\s*(.+)$", body, re.M)
        if f:
            out.append("- %s (%s)" % (f.group(1).strip(), exid))
    return out


def known_issues_text(repo):
    lines = known_issues_lines(repo)
    return KNOWN_ISSUES_MARK + "\n" + ("\n".join(lines) if lines else "None.") + "\n"


def readme_section(text, heading):
    m = re.search(r"^(##+\s*%s[^\n]*\n)(.*?)(?=^##+\s|\Z)" % heading, text, re.M | re.S | re.I)
    return m


def check_known_issues(repo):
    p = Path(repo) / "README.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    m = readme_section(text, "known issues")
    if not m:
        return []  # the readme check already reports the missing heading
    want = known_issues_text(repo).strip()
    have = m.group(2).strip()
    if have != want:
        return ["README.md: Known issues differs from docs/status.md, Open exceptions (lines with a Friends: sentence); run shipcheck.py known-issues . --write"]
    return []


def write_known_issues(repo):
    p = Path(repo) / "README.md"
    text = p.read_text(encoding="utf-8")
    m = readme_section(text, "known issues")
    body = known_issues_text(repo)
    if m:
        text = text[:m.start(2)] + body + ("\n" if not text[m.end(2):].startswith("\n") and text[m.end(2):] else "") + text[m.end(2):]
    else:
        text = text.rstrip("\n") + "\n\n## Known issues\n" + body
    p.write_text(text, encoding="utf-8")
    return 0


def check_version(repo):
    repo = Path(repo)
    vp = repo / "VERSION"
    if not vp.exists():
        return ["VERSION file missing (versioning-and-provenance.md)"], None
    v = vp.read_text(encoding="utf-8").strip()
    errs = []
    if not re.match(r"^\d+\.\d+\.\d+$", v):
        errs.append("VERSION %r is not x.y.z" % v)
    try:
        tag = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", "refs/tags/v%s^{commit}" % v],
                             capture_output=True, text=True)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
        if tag.returncode == 0 and head.returncode == 0 and tag.stdout.strip() != head.stdout.strip():
            errs.append("tag v%s exists but does not point at HEAD (bump VERSION or move the release commit)" % v)
    except OSError:
        pass
    return errs, v


def run_secrets(repo):
    """Before the repo goes public: scan the whole history and the workflows for secrets.
    Anything found is rotated, not deleted (history keeps it)."""
    repo = Path(repo)
    hits = []
    try:
        log = subprocess.run(["git", "-C", str(repo), "log", "-p", "--all", "--no-color"], capture_output=True, text=True, errors="replace").stdout
    except OSError:
        log = ""
    for pat in SECRET_PATTERNS:
        for m in re.finditer(pat, log):
            line = log[log.rfind("\n", 0, m.start()) + 1: log.find("\n", m.end())]
            if line.startswith("-") and not line.startswith("---"):
                continue  # a removed line still counts, but report the added one
            hits.append("history: " + line.strip()[:120])
    wf = repo / ".github" / "workflows"
    for f in sorted(wf.glob("*.y*ml")) if wf.exists() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                hits.append("%s: %s" % (f.relative_to(repo), text[max(0, m.start() - 20): m.end() + 20].replace("\n", " ")))
    for env in (repo / ".env", repo / "ship.local.toml"):
        if env.exists():
            tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", env.name], capture_output=True).returncode == 0
            if tracked:
                hits.append("%s is tracked by git; it belongs in .gitignore" % env.name)
    hits = sorted(set(hits))
    for h in hits:
        print("SECRET? " + h)
    if hits:
        print("shipcheck secrets: %d hit(s); rotate what is real, then make the repo public" % len(hits))
        return 1
    print("shipcheck secrets OK: no secret-shaped strings in the history or the workflows")
    return 0


def expected_assets(repo, cfg):
    """The version-free set (github-releases.md): required assets, and the symbols zips, which only warn."""
    name = cfg.get("product", {}).get("asset_name") or cfg.get("product", {}).get("name", "Plugin").replace(" ", "")
    want = ["%s-macOS.zip" % name, "%s-Windows-x64.zip" % name, "SHA256SUMS.txt", "build-info-macOS.json", "build-info-Windows.json"]
    wish = ["%s-symbols-macOS.zip" % name, "%s-symbols-Windows.zip" % name]
    return name, want, wish


def run_release_assets(assets_dir, repo):
    """The downloaded (or about-to-be-uploaded) assets: names, zip layout, checksums, provenance."""
    import hashlib
    import json
    import zipfile
    cfg = read_toml(repo)
    name, want, wish = expected_assets(repo, cfg)
    d = Path(assets_dir).expanduser()
    errs, warns = [], []
    if not d.exists():
        print("ERROR: %s does not exist" % d)
        return 1
    have = {p.name for p in d.iterdir() if p.is_file()}
    for w in want:
        if w not in have:
            errs.append("missing asset %s" % w)
    for w in wish:
        if w not in have:
            warns.append("no %s: a crash from this tag could not be symbolicated (feedback-loop.md 5)" % w)
    extra = sorted(h for h in have if h.endswith((".zip", ".pkg", ".exe", ".json", ".txt")) and h not in want + wish and not h.startswith("RELEASE_NOTES"))
    for e in extra:
        errs.append("unexpected asset %s (version-free names: %s)" % (e, ", ".join(want + wish)))
    bundle_exts = {".vst3", ".component", ".clap"}
    for z in sorted(d.glob("*.zip")):
        try:
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            errs.append("%s: not a zip" % z.name)
            continue
        bad = [n for n in names if n.startswith("__MACOSX") or "/._" in n or n.startswith("._") or n.endswith(".DS_Store")]
        if bad:
            errs.append("%s: macOS detritus inside (%s); build the Windows zip on Windows, the macOS zip with ditto --norsrc --noextattr" % (z.name, bad[0]))
        if any("\\" in n for n in names):
            errs.append("%s: backslash entry names (Windows PowerShell 5.1 Compress-Archive); use pwsh" % z.name)
        tops = sorted({n.split("/")[0] for n in names if n and not n.startswith("__MACOSX")})
        if "-symbols-" in z.name:
            if not any(n.endswith(".pdb") or ".dSYM/" in n or n.endswith(".dSYM") for n in names):
                warns.append("%s: no .dSYM or .pdb inside; a crash from this tag could not be symbolicated (the dSYM sits next to the bundle: find -name '*.dSYM', feedback-loop.md 5)" % z.name)
            continue
        docs_ok = {"LICENSE", "LICENSE.txt", "LICENSE.md", "THIRD_PARTY_NOTICES.md", "README.md"}
        tops_b = [x for x in tops if x not in docs_ok]
        if not tops_b or any(Path(x).suffix not in bundle_exts for x in tops_b):
            errs.append("%s: top-level entries %s; expected bundle folders (<Product>.vst3/ ...) plus LICENSE and THIRD_PARTY_NOTICES.md" % (z.name, tops))
        if "THIRD_PARTY_NOTICES.md" not in tops or not any(x.startswith("LICENSE") for x in tops):
            errs.append("%s: LICENSE and THIRD_PARTY_NOTICES.md must ride inside the zip (MIT and OFL texts travel with the binary)" % z.name)
    sums = d / "SHA256SUMS.txt"
    if sums.exists():
        listed = {}
        for line in sums.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                listed[parts[-1].lstrip("*")] = parts[0]
        for fname, digest in listed.items():
            if "/" in fname:
                errs.append("SHA256SUMS.txt lists %s with a folder prefix; a friend's sha256sum -c cannot find it (hash by basename)" % fname)
                continue
            f = d / fname
            if not f.exists():
                errs.append("SHA256SUMS.txt lists %s, which is not among the assets" % fname)
                continue
            real = hashlib.sha256(f.read_bytes()).hexdigest()
            if real != digest:
                errs.append("%s: checksum mismatch" % fname)
        for z in sorted(d.glob("*.zip")) + sorted(d.glob("*.pkg")):
            if z.name not in listed:
                errs.append("%s is not in SHA256SUMS.txt" % z.name)
    vp = Path(repo) / "VERSION"
    version = vp.read_text(encoding="utf-8").strip() if vp.exists() else None
    for info in ("build-info-macOS.json", "build-info-Windows.json"):
        f = d / info
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                errs.append("%s: not JSON" % info)
                continue
            if version and data.get("version") != version:
                errs.append("%s: version %r, VERSION is %r" % (info, data.get("version"), version))
            if (data.get("config") or "").lower() != "release":
                errs.append("%s: config %r" % (info, data.get("config")))
    for w in warns:
        print("WARN: " + w)
    for e in errs:
        print("ERROR: " + e)
    if errs:
        print("shipcheck release-assets: %d error(s), %d warning(s)" % (len(errs), len(warns)))
        return 1
    print("shipcheck release-assets OK: %s%s" % (", ".join(want), "; %d warning(s)" % len(warns) if warns else "; symbols present"))
    return 0


def message_text(repo):
    """The pasteable message to the friends, from CHANGELOG, VERSION and ship.toml."""
    cfg = read_toml(repo)
    errs, version = check_version(repo)
    name = cfg.get("product", {}).get("name", "the plugin")
    gh = cfg.get("product", {}).get("repo", "<owner>/<repo>")
    sec = changelog_section(repo, version) or ""
    bullets = []
    for l in sec.splitlines():
        s = l.strip()
        if s.startswith(("- ", "* ")):
            bullets.append(s[2:].strip())
        elif s and bullets and not s.startswith("#") and (l.startswith((" ", "\t"))):
            bullets[-1] += " " + s                      # a wrapped bullet continues on indented lines
    bullets = [b.rstrip(".") for b in bullets]
    sounds = [b for b in bullets if "sounds different" in b.lower()]
    new = [b for b in bullets if b not in sounds][:3]
    state_bump = cfg.get("release", {}).get("state_version_bumped")
    lines = ["%s %s is out: https://github.com/%s/releases/latest" % (name, version, gh), ""]
    if new:
        lines.append("New: " + "; ".join(new) + ".")
    if sounds:
        lines.append(re.sub(r"\*\*", "", sounds[0]))
    lines += ["",
              "Update: Quit Ableton Live. Download the zip for your system (not \"Source code\"). Windows: copy the whole %s.vst3 folder to C:\\Program Files\\Common Files\\VST3\\ (replace). macOS: Finder > Go > Go to Folder > ~/Library/Audio/Plug-Ins/VST3/, replace, start Ableton Live, then right away System Settings > Privacy & Security > Open Anyway, rescan. Details in the README." % name,
              "Your presets and settings stay."]
    if state_bump:
        lines.append("Projects saved with this version will not open in older versions; if you need to go back, keep the project and send me the .als.")
    else:
        lines.append("If it misbehaves: take the previous release from the same page (a project saved with this version still opens there), and tell me what happened.")
    subj = "%s %s: three words" % (name, version)
    lines += ["", "If something is off: tell me what you were doing right before, what you expected to hear, and paste what the About panel copies (one click). If you can, the .als after Collect All and Save and a ten-second bounce. Mail subject \"%s\" or just write me. Crash: macOS sends you the report pane (or ~/Library/Logs/DiagnosticReports/), Windows: %%LOCALAPPDATA%%\\CrashDumps after the enable-crashdumps.reg from the release page, or the Event Viewer entry." % subj]
    return "\n".join(lines)


def run_docs(repo):
    cfg = read_toml(repo)
    errs, version = check_version(repo)
    errs += check_readme(repo)
    errs += check_license(repo)
    if version:
        errs += check_changelog(repo, version, cfg)
    errs += check_notices(repo, cfg)
    errs += check_presets(repo)
    errs += check_params(repo)
    errs += check_known_issues(repo)
    errs += check_registry(repo)
    for e in errs:
        print("ERROR: " + e)
    if errs:
        print("shipcheck docs: %d error(s)" % len(errs))
        return 1
    print("shipcheck docs OK: README, CHANGELOG %s, notices, presets, parameters, known issues, VERSION, registry" % version)
    return 0


def check_registry(repo):
    """The repo against the family registry (registry.py beside this script). No registry on this
    machine is a note, not an error: CI runners and a friend's Mac have none."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import registry as R
    path = R.find_registry(os.environ.get("OBERLI_REGISTRY"))
    if path is None:
        print("note: no plugin registry reachable (OBERLI_REGISTRY, tools.toml or ~/bob-skills); registry check skipped")
        return []
    return ["registry: " + e for e in R.check_repo(repo, R.load_toml(path))]


# ----------------------------------------------------------------------------- selftest

def selftest():
    here = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "fakeplugin"
    import shutil
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    os.environ["OBERLI_REGISTRY"] = str(here.parent / "plugins.toml")   # the fixture's registry, not the family's
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        shutil.copytree(here, repo)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "fixture"], check=True)
        expect("fixture passes", run_docs(repo) == 0)
        # planted defects
        def planted(label, mutate, needle):
            with tempfile.TemporaryDirectory() as d2:
                r2 = Path(d2) / "repo"
                shutil.copytree(repo, r2)
                mutate(r2)
                cfg = read_toml(r2)
                errs, v = check_version(r2)
                errs += check_readme(r2) + check_license(r2) + (check_changelog(r2, v, cfg) if v else []) + check_notices(r2, cfg) + check_presets(r2) + check_params(r2) + check_known_issues(r2) + check_registry(r2)
                expect(label, any(needle in e for e in errs))
        planted("missing Open Anyway", lambda r: (r / "README.md").write_text((r / "README.md").read_text().replace("Open Anyway", "Open").replace("xattr", "x")), "open-anyway")
        planted("missing releases link", lambda r: (r / "README.md").write_text((r / "README.md").read_text().replace("releases/latest", "releases")), "releases-latest-link")
        planted("changelog behind VERSION", lambda r: (r / "VERSION").write_text("1.3.0\n"), "no section")
        planted("sounds different missing", lambda r: (r / "CHANGELOG.md").write_text((r / "CHANGELOG.md").read_text().replace("**Sounds different:**", "Changed:")), "Sounds different")
        planted("state bump unannounced", lambda r: (r / "ship.toml").write_text((r / "ship.toml").read_text().replace("state_version_bumped = false", "state_version_bumped = true")), "older versions")
        planted("quit Ableton Live missing", lambda r: (r / "README.md").write_text((r / "README.md").read_text().replace("Quit Ableton Live", "Close it")), "quit-live")
        planted("notices stale", lambda r: (r / "THIRD_PARTY_NOTICES.md").write_text("# Notices\nJUCE only. Steinberg."), "not what notices.toml generates")
        planted("dependency not in the manifest", lambda r: (r / "CMakeLists.txt").write_text((r / "CMakeLists.txt").read_text() + "\nFetchContent_Declare(signalsmith-stretch GIT_REPOSITORY x)\n"), "signalsmith-stretch")
        planted("licence without reserved", lambda r: (r / "LICENSE").write_text((r / "LICENSE").read_text().replace("reserved", "kept")), "reserved")
        planted("preset file missing", lambda r: (r / "presets" / "warm.oberlipreset").unlink(), "no file for slug")
        planted("stray preset file", lambda r: (r / "presets" / "stray.oberlipreset").write_text("x"), "not in presets.csv")
        planted("removed parameter in prose", lambda r: (r / "README.md").write_text((r / "README.md").read_text() + "\nTurn `oldShimmer` down.\n"), "oldShimmer")
        planted("bad version", lambda r: (r / "VERSION").write_text("1.2\n"), "not x.y.z")
        planted("licence file missing", lambda r: (r / "LICENSE").unlink(), "LICENSE missing")
        planted("plugin code off the registry", lambda r: (r / "CMakeLists.txt").write_text((r / "CMakeLists.txt").read_text().replace("Fkpd", "Fkpx")), "PLUGIN_CODE")
        planted("slug not registered", lambda r: (r / "ship.toml").write_text((r / "ship.toml").read_text().replace('slug = "fake-pad"', 'slug = "fake-pod"')), "not in the registry")
        planted("feedback without the About copy", lambda r: (r / "README.md").write_text(re.sub(r"(?i)about panel", "settings", (r / "README.md").read_text())), "feedback-about-copy")
        planted("feedback without what-and-expected", lambda r: (r / "README.md").write_text((r / "README.md").read_text().replace("what you were doing right before", "what happened")), "feedback-what-and-expected")
        planted("no Windows crash path", lambda r: (r / "README.md").write_text(re.sub(r"(?i)event viewer|crashdumps", "somewhere", (r / "README.md").read_text())), "crash-report-windows")
        planted("known issues stale", lambda r: (r / "docs" / "status.md").write_text((r / "docs" / "status.md").read_text().replace("## Handoff", "- EX-009 2026-11-01: hum; Friends: A hum at 50 Hz on the Init preset.\n\n## Handoff")), "Known issues differs")
        planted("known issues resolved but still listed", lambda r: (r / "docs" / "status.md").write_text(re.sub(r"^- EX-002 .*\n", "", (r / "docs" / "status.md").read_text(), flags=re.M)), "Known issues differs")
        # known-issues --write regenerates exactly the fixture's section
        with tempfile.TemporaryDirectory() as d5:
            r5 = Path(d5) / "repo"
            shutil.copytree(repo, r5)
            before = (r5 / "README.md").read_text()
            (r5 / "README.md").write_text(before.replace("(EX-002)", "(EX-999)"))
            expect("known-issues drift caught", check_known_issues(r5))
            write_known_issues(r5)
            expect("known-issues --write restores", (r5 / "README.md").read_text() == before and not check_known_issues(r5))
        # secrets: clean fixture passes; a committed token is found
        expect("secrets clean", run_secrets(repo) == 0)
        with tempfile.TemporaryDirectory() as d3:
            r3 = Path(d3) / "repo"
            shutil.copytree(repo, r3)
            (r3 / "notes.txt").write_text("token = ghp_" + "a" * 36 + "\n")
            subprocess.run(["git", "-C", str(r3), "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(r3), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "oops"], check=True)
            (r3 / "notes.txt").unlink()
            subprocess.run(["git", "-C", str(r3), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am", "remove"], check=True)
            expect("secret in history found after deletion", run_secrets(r3) == 1)
        # release-assets on a good and a bad folder
        import zipfile, hashlib, json as _json
        def make_assets(d, good=True):
            d.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(d / "FakePad-macOS.zip", "w") as zf:
                zf.writestr("Fake Pad.vst3/Contents/Info.plist", "x")
                zf.writestr("LICENSE", "x"); zf.writestr("THIRD_PARTY_NOTICES.md", "x")
                if not good:
                    zf.writestr("__MACOSX/._Fake Pad.vst3", "x")
            with zipfile.ZipFile(d / "FakePad-Windows-x64.zip", "w") as zf:
                zf.writestr("Fake Pad.vst3/Contents/x86_64-win/Fake Pad.vst3", "x")
                if good:
                    zf.writestr("LICENSE", "x"); zf.writestr("THIRD_PARTY_NOTICES.md", "x")
            with zipfile.ZipFile(d / "FakePad-symbols-macOS.zip", "w") as zf:
                zf.writestr("Fake Pad.vst3.dSYM/Contents/Resources/DWARF/Fake Pad" if good else "readme.txt", "x")
            if good:
                with zipfile.ZipFile(d / "FakePad-symbols-Windows.zip", "w") as zf:
                    zf.writestr("Fake Pad.pdb", "x")
            for plat in ("macOS", "Windows"):
                (d / ("build-info-%s.json" % plat)).write_text(_json.dumps({"version": "1.2.0" if good else "1.1.0", "config": "Release"}))
            lines = []
            for f in sorted(d.glob("*.zip")):
                dg = hashlib.sha256(f.read_bytes()).hexdigest()
                lines.append("%s  %s" % (dg, f.name if good else "macos/" + f.name))
            (d / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
        with tempfile.TemporaryDirectory() as d4:
            make_assets(Path(d4) / "ok", True)
            expect("release-assets passes", run_release_assets(Path(d4) / "ok", repo) == 0)
            make_assets(Path(d4) / "bad", False)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_release_assets(Path(d4) / "bad", repo)
            out = buf.getvalue()
            expect("release-assets catches detritus, prefix, version and the notices", rc == 1 and "detritus" in out and "folder prefix" in out and "VERSION is" in out and "must ride inside" in out)
            expect("symbols only warn", "WARN: FakePad-symbols-macOS.zip: no .dSYM" in out and "WARN: no FakePad-symbols-Windows.zip" in out and "no .dSYM" not in "".join(l for l in out.splitlines() if l.startswith("ERROR")))
            ok = Path(d4) / "ok"
            (ok / "FakePad-symbols-Windows.zip").unlink()
            (ok / "SHA256SUMS.txt").write_text("".join(l + "\n" for l in (ok / "SHA256SUMS.txt").read_text().splitlines() if "symbols-Windows" not in l))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_release_assets(ok, repo)
            expect("a set without a symbols zip passes with a warning", rc == 0 and "WARN: no FakePad-symbols-Windows.zip" in buf.getvalue())
        msg = message_text(repo)
        expect("message has the parts", all(x in msg for x in ("releases/latest", "Quit Ableton Live", "Source code", "Sounds different", "previous release", "doing right before", "About panel", "Fake Pad 1.2.0: three words", "CrashDumps")))
        expect("known-issues text", known_issues_text(repo).splitlines()[1].startswith("- ") and "(EX-002)" in known_issues_text(repo))
        sec = changelog_section(repo, "1.2.0")
        expect("changelog section extracted", sec is not None and "Added" in sec)
    if fails:
        print("shipcheck selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("shipcheck selftest OK: fixture passes (against the fixture registry); README sections (incl. the Feedback fields and both crash paths), licence file (and its reserved clause), changelog, Sounds different, a stale notices file, a dependency missing from notices.toml, presets, removed parameter, VERSION, stale Known issues, a plugin code off the registry and an unregistered slug each fail on a planted defect; known-issues --write restores the section; a token deleted from the tree is still found in the history; release-assets passes a clean set and catches detritus, prefixed checksums, a stale build-info and a zip without the notices, and warns (only) on a missing or empty symbols zip; the message has every part")
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
        print("usage: shipcheck.py %s <repo>" % cmd, file=sys.stderr)
        return 2
    repo = argv[1]
    if cmd == "docs":
        return run_docs(repo)
    if cmd == "secrets":
        return run_secrets(repo)
    if cmd == "message":
        print(message_text(repo))
        return 0
    if cmd == "release-assets":
        rp = "."
        if "--repo" in argv:
            rp = argv[argv.index("--repo") + 1]
        return run_release_assets(repo, rp)
    if cmd == "known-issues":
        if "--write" in argv:
            write_known_issues(repo)
            print("README.md: Known issues written from docs/status.md")
            return 0
        print(known_issues_text(repo), end="")
        return 0
    if cmd == "registry":
        errs = check_registry(repo)
        for e in errs:
            print("ERROR: " + e)
        if errs:
            return 1
        print("shipcheck registry OK")
        return 0
    if cmd == "changelog-section":
        errs, v = check_version(repo)
        sec = changelog_section(repo, v) if v else None
        if sec is None:
            print("no changelog section for %s" % v, file=sys.stderr)
            return 1
        print(sec)
        return 0
    print("unknown command %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
