#!/usr/bin/env python3
"""release - the release recipe as functions (references/release-recipe.md).

    release.py dry-run   [--repo .] [--from <step>] [--to <step>]     (also: --dry-run)
    release.py run       [--repo .] [--from <step>] [--to <step>] [--yes]
    release.py steps
    release.py selftest

Six steps, in order, each tagged with where it runs:
    prepare   $          notices generated, Known issues written, shipcheck docs, one commit (--yes commits)
    tag       $          the tree is clean; git tag v<VERSION>, push
    ci        [workflow] build, provenance check, sign, zip, symbols, checksums, draft (templates/release.yml)
    smoke     [by hand]  download the draft's assets, release-assets, Ableton Live 10.1 under Rosetta, arm64 natively
    publish   $          gh release edit --draft=false
    announce  $          shipcheck message, pasted to the friends

`dry-run` prints every command without running anything and checks ship.toml and the tree;
`run` executes the `$` steps and prints the others. Nothing here can delete a release or
force-push; a failed step stops the run and keeps the files. Config: ship.toml at the repo
root (release-recipe.md shows it).
"""
import argparse
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["prepare", "tag", "ci", "smoke", "publish", "announce"]
EXT = {"VST3": "vst3", "AU": "component", "CLAP": "clap"}
WINDOWS_FORMATS = ("VST3", "CLAP")


class Ctx:
    def __init__(self, repo, dry, yes=False):
        self.repo = Path(repo).resolve()
        self.dry = dry
        self.yes = yes
        self.cfg = self.load_cfg()
        vp = self.repo / "VERSION"
        self.version = vp.read_text(encoding="utf-8").strip() if vp.exists() else None
        self.log = []

    def load_cfg(self):
        p = self.repo / "ship.toml"
        if not p.exists():
            raise SystemExit("release: no ship.toml in %s (release-recipe.md shows the template)" % self.repo)
        sys.path.insert(0, str(HERE))
        from shipcheck import load_toml
        return load_toml(p)

    @property
    def name(self):
        return self.cfg["product"]["name"]

    @property
    def formats(self):
        return [f for f in self.cfg["product"].get("formats", ["VST3"]) if f in EXT]

    def say(self, text):
        print(text)
        self.log.append(text)

    def sh(self, cmd, where="local", check=True):
        """Print the command; run it unless dry or it happens elsewhere (GitHub, by hand)."""
        line = cmd if isinstance(cmd, str) else " ".join(shlex.quote(c) for c in cmd)
        tag = {"local": "$", "github": "[workflow]", "hand": "[by hand]"}[where]
        self.say("  %s %s" % (tag, line))
        if self.dry or where != "local":
            return 0
        r = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=self.repo)
        if check and r.returncode != 0:
            raise RuntimeError("step failed: %s (exit %d)" % (line, r.returncode))
        return r.returncode

    def dirty(self):
        return subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True).stdout.strip()


def asset_names(c):
    """Version-free asset names, so releases/latest/download/<asset> never changes; the version
    lives in the tag and build-info-<platform>.json (github-releases.md)."""
    n = c.cfg["product"].get("asset_name") or c.name.replace(" ", "")
    return {"mac_zip": "%s-macOS.zip" % n, "win_zip": "%s-Windows-x64.zip" % n,
            "sym_mac": "%s-symbols-macOS.zip" % n, "sym_win": "%s-symbols-Windows.zip" % n,
            "info_mac": "build-info-macOS.json", "info_win": "build-info-Windows.json",
            "reg": "enable-crashdumps.reg", "sums": "SHA256SUMS.txt"}


def bundles_of(c, platform="macos"):
    fmts = c.formats if platform == "macos" else [f for f in c.formats if f in WINDOWS_FORMATS]
    return ["%s.%s" % (c.name, EXT[f]) for f in fmts]


# ----------------------------------------------------------------------------- steps

def prepare(c):
    c.say("1 prepare (you): the joint release gate is green on this commit; VERSION = %s and the CHANGELOG section are edited by hand (Sounds different when dspVersion or a taper changed, '(reported by M.)' on fixes); then generate, check, one commit" % c.version)
    c.say("  product %s, formats %s" % (c.name, " ".join(c.formats)))
    c.sh([sys.executable, str(HERE / "notices.py"), "generate", str(c.repo)])
    c.sh([sys.executable, str(HERE / "shipcheck.py"), "known-issues", str(c.repo), "--write"])
    c.sh([sys.executable, str(HERE / "shipcheck.py"), "docs", str(c.repo)])
    commit = ["git", "commit", "-am", "release %s" % c.version]
    if c.dry or c.yes:
        c.sh(commit, where="local" if c.yes and not c.dry else "hand")
    else:
        c.say("  $ %s   (run again with --yes to commit, after reading the diff)" % " ".join(shlex.quote(x) for x in commit))


def tag(c):
    t = "v%s" % c.version
    c.say("2 tag (you): %s on HEAD, pushed; the workflow builds from it" % t)
    c.sh(["git", "status", "--porcelain"])
    if not c.dry and c.dirty():
        raise RuntimeError("the tree is dirty; the prepare step commits everything before the tag")
    c.sh(["git", "tag", "-a", t, "-m", "%s %s" % (c.name, c.version)])
    c.sh(["git", "push"])
    c.sh(["git", "push", "origin", t])


def ci(c):
    a = asset_names(c)
    mac, win = bundles_of(c, "macos"), bundles_of(c, "windows")
    c.say("3 ci (the workflow, templates/release.yml): build, provenance, sign, zip, symbols, checksums, draft")
    c.say("   build: macOS universal Release, Windows /%s /arch:%s; the release preset's post-build runs dsymutil then strip -x" % (c.cfg["windows"].get("runtime", "MT"), c.cfg["windows"].get("arch", "SSE4.2")))
    c.sh("cmake --preset release && cmake --build --preset release", where="github")
    c.say("   sign (macos-14 runner, after dsymutil and strip): ad-hoc, both slices; friends follow the Open-Anyway paragraph")
    for b in mac:
        c.sh(["xattr", "-cr", b], where="github")
        c.sh(["codesign", "--force", "--sign", "-", b], where="github")
        c.sh(["codesign", "--verify", "--deep", "--strict", "--verbose=2", b], where="github")
        c.sh(["lipo", "-archs", "%s/Contents/MacOS/%s" % (b, c.name)], where="github")
    c.say("   zip: every macOS format in one zip, bundles at the top level, LICENSE and THIRD_PARTY_NOTICES.md beside them, no __MACOSX")
    c.sh("mkdir -p stage symbols && cp -R %s stage/ && cp \"$GITHUB_WORKSPACE\"/LICENSE \"$GITHUB_WORKSPACE\"/THIRD_PARTY_NOTICES.md stage/" % " ".join(shlex.quote(b) for b in mac), where="github")
    c.sh(["ditto", "-c", "-k", "--norsrc", "--noextattr", "stage", a["mac_zip"]], where="github")
    c.say("   symbols of this tag (feedback-loop.md 5): the dSYMs sit next to the bundles")
    c.sh("find . -maxdepth 2 -name \"*.dSYM\" -not -path \"./symbols/*\" -exec cp -R {} symbols/ \\;", where="github")
    c.sh(["ditto", "-c", "-k", "--norsrc", "--noextattr", "symbols", a["sym_mac"]], where="github")
    c.say("   provenance: build-info says Release, both slices, clean, version %s, JUCE 8.0.11 or newer, deployment target" % c.version)
    c.sh([sys.executable, "scripts/ship/buildinfo.py", "emit", "--repo", ".", "--build", "build", "--platform", "macos", "--symbols", "symbols/*.dSYM", "--out", a["info_mac"]], where="github")
    c.sh([sys.executable, "scripts/ship/buildinfo.py", "check", a["info_mac"], "--expect-version", c.version, "--platform", "macos"], where="github")
    c.say("   (windows-latest runner, shell: pwsh): %s" % (" and ".join(win) if win else "no Windows format in the set"))
    if win:
        c.sh("Compress-Archive -Path %s, LICENSE, THIRD_PARTY_NOTICES.md -DestinationPath %s" % (", ".join("'%s'" % b for b in win), a["win_zip"]), where="github")
    c.sh("Compress-Archive -Path '*.pdb' -DestinationPath %s   # /Zi and /DEBUG in Release keep the PDB" % a["sym_win"], where="github")
    c.sh("Copy-Item scripts/ship/%s ." % a["reg"], where="github")
    c.sh("python scripts/ship/buildinfo.py emit --repo . --build build --platform windows --symbols *.pdb --out %s" % a["info_win"], where="github")
    c.sh("python scripts/ship/buildinfo.py check %s --expect-version %s --platform windows" % (a["info_win"], c.version), where="github")
    c.say("   checksums and draft (ubuntu release job, after download-artifact merge-multiple)")
    c.sh("for f in *.zip; do [ -f \"$f\" ] && sha256sum \"$f\"; done > %s" % a["sums"], where="github")
    c.sh([sys.executable, "scripts/ship/shipcheck.py", "release-assets", "dist", "--repo", "."], where="github")
    c.sh("softprops/action-gh-release: draft, body = shipcheck.py changelog-section, files = %s" % ", ".join(a.values()), where="github")


def smoke(c):
    c.say("4 smoke (you): download the assets from the draft release, not the build folder; quit Ableton Live; replace the old bundles; Ableton Live 10.1 under Rosetta (x86_64 slice): the Open-Anyway dance, rescan, Init preset, last session, About shows %s and the SHA; then the arm64 slice natively" % c.version)
    c.sh([sys.executable, str(HERE / "shipcheck.py"), "release-assets", "~/Downloads/release-assets", "--repo", str(c.repo)], where="hand")
    if "AU" in c.formats:
        c.sh("auval -v aumu <PLUGIN_CODE> Obrl   # the downloaded .component, natively on the M-series", where="hand")
    else:
        c.sh("open the Standalone of this tag natively, play the Init preset   # the arm64 slice", where="hand")
    c.sh("open https://github.com/%s/releases" % c.cfg["product"].get("repo", "<owner>/<repo>"), where="hand")


def publish(c):
    c.say("5 publish (you): the draft becomes the release")
    c.sh(["gh", "release", "edit", "v%s" % c.version, "--draft=false"], where="hand" if c.dry else "local")


def announce(c):
    c.say("6 announce (you): paste this to the friends (shipcheck.py message)")
    out = subprocess.run([sys.executable, str(HERE / "shipcheck.py"), "message", str(c.repo)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        c.say("  | " + line)
    c.say("   done when a friend confirms the installed version plays his set; from his first report on, references/feedback-loop.md")


FUNCS = {"prepare": prepare, "tag": tag, "ci": ci, "smoke": smoke, "publish": publish, "announce": announce}


def run(a, dry):
    c = Ctx(a.repo, dry, getattr(a, "yes", False))
    i0 = STEPS.index(a.from_step) if a.from_step else 0
    i1 = STEPS.index(a.to_step) + 1 if a.to_step else len(STEPS)
    c.say("release %s %s (%s)%s" % (c.name, c.version, "dry run" if dry else "run", ", steps %s..%s" % (STEPS[i0], STEPS[i1 - 1]) if (i0 or i1 < len(STEPS)) else ""))
    for s in STEPS[i0:i1]:
        try:
            FUNCS[s](c)
        except RuntimeError as e:
            c.say("STOP at %s: %s" % (s, e))
            return 1
    return 0


def selftest():
    import shutil, tempfile, io, contextlib
    here = HERE.parent.parent / "tests" / "fixtures" / "fakeplugin"
    import os
    os.environ["OBERLI_REGISTRY"] = str(here.parent / "plugins.toml")   # shipcheck docs checks the fixture against its own registry
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        shutil.copytree(here, repo)
        g = lambda *x: subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *x], check=True, capture_output=True)
        g("init", "-q"); g("add", "-A"); g("commit", "-q", "-m", "fixture")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(argparse.Namespace(repo=repo, from_step=None, to_step=None), dry=True)
        out = buf.getvalue()
        expect("dry run passes", rc == 0)
        expect("six steps printed", all(("\n%d " % i) in out for i in range(1, 7)))
        expect("where tags", "[workflow]" in out and "[by hand]" in out and "\n  $ " in out)
        expect("prepare generates before the commit", out.index("notices.py") < out.index("shipcheck.py") < out.index("git commit"))
        expect("ad-hoc only", "--sign -" in out and "Developer ID" not in out and "notarytool" not in out and ".pkg" not in out)
        expect("zip with the notices", "ditto -c -k" in out and "--norsrc" in out and "THIRD_PARTY_NOTICES.md stage/" in out and "LICENSE, THIRD_PARTY_NOTICES.md -DestinationPath" in out)
        expect("symbols found next to the bundles", "find . -maxdepth 2 -name" in out and "-symbols-macOS.zip" in out and "*.pdb" in out and "enable-crashdumps.reg" in out)
        expect("dsymutil is the CMake post-build's, not a workflow command", "[workflow] dsymutil" not in out and "dsymutil then strip" in out)
        expect("provenance checked on both platforms", out.count("buildinfo.py check") >= 2 and "--expect-version 1.2.0" in out)
        expect("arm64 smoke", "natively" in out)
        expect("announce prints the message", "Sounds different" in out and "releases/latest" in out and "Quit Ableton Live" in out)
        # formats drive the zips: CLAP added -> both zips grow, AU -> macOS only
        (repo / "ship.toml").write_text((repo / "ship.toml").read_text().replace('formats = ["VST3"]', 'formats = ["VST3", "AU", "CLAP"]'))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(argparse.Namespace(repo=repo, from_step="ci", to_step="ci"), dry=True)
        o2 = buf.getvalue()
        expect("formats from ship.toml", "Fake Pad.component" in o2 and "'Fake Pad.clap', LICENSE" in o2 and ".component'" not in o2.split("windows-latest")[1])
        (repo / "ship.toml").write_text((repo / "ship.toml").read_text().replace('formats = ["VST3", "AU", "CLAP"]', 'formats = ["VST3"]'))
        # real run of prepare on the fixture passes and leaves the tree as it was (generators are idempotent)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(argparse.Namespace(repo=repo, from_step="prepare", to_step="prepare"), dry=False)
        expect("prepare runs the generators and shipcheck, commits only with --yes", rc == 0 and "--yes to commit" in buf.getvalue())
        touched = {l.split()[-1] for l in Ctx(repo, False).dirty().splitlines()}
        expect("prepare on a clean fixture changes only the notices' date line", touched <= {"THIRD_PARTY_NOTICES.md"})
        g("checkout", "--", ".")
        # a dirty tree stops the tag step
        (repo / "README.md").write_text((repo / "README.md").read_text() + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(argparse.Namespace(repo=repo, from_step="tag", to_step="tag"), dry=False)
        expect("dirty tree stops tag", rc == 1 and "dirty" in buf.getvalue())
    if fails:
        print("release selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("release selftest OK: dry run prints the six steps with their where tags, prepare generates then checks then commits once, ad-hoc only, formats from ship.toml drive both zips, the dSYMs are found next to the bundles, provenance checked per platform, arm64 smoke named, the message printed, prepare runs clean on the fixture, a dirty tree stops the tag")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", default="dry-run", choices=("dry-run", "run", "steps", "selftest"))
    ap.add_argument("--dry-run", dest="dry_flag", action="store_true", help="same as the dry-run mode")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--from", dest="from_step", choices=STEPS)
    ap.add_argument("--to", dest="to_step", choices=STEPS)
    ap.add_argument("--yes", action="store_true", help="prepare: commit after the checks")
    a = ap.parse_args(argv)
    if a.mode == "steps":
        print("\n".join(STEPS))
        return 0
    if a.mode == "selftest":
        return selftest()
    return run(a, dry=(a.mode == "dry-run" or a.dry_flag))


if __name__ == "__main__":
    sys.exit(main())
