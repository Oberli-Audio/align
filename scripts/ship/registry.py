#!/usr/bin/env python3
"""registry - the Oberli Audio plugin registry (registry/plugins.toml in ship-bob) as a check.

One list of products, codes, bundle ids and accents, so a four-character code or an accent is
decided once per plugin and never reused. Where the file is looked for, in this order:
$OBERLI_REGISTRY, the `registry.plugins` entry of ~/.config/oberli/tools.toml, the skill's own
registry/plugins.toml next to this script's grandparent, ~/bob-skills/plugins/ship-bob/skills/
ship-bob/registry/plugins.toml.

    registry.py list                         every plugin with code, accent and kind
    registry.py check <repo>                 ship.toml and CMakeLists.txt agree with the entry for
                                             the repo's slug; the registry itself is consistent
    registry.py propose --name "Shimmer"     a free code and a free accent for a new product
    registry.py add --name "Shimmer" --kind effect [--code Shmr] [--accent saffron] [--repo o/r]
                                             append the entry (refuses a taken slug, code or accent)
    registry.py selftest                     the checks fail on planted defects

Exit codes: 0 ok, 1 a check failed, 2 bad arguments or no registry found.
Pure Python 3.9+; tomllib when available (3.11+), else a minimal parser for the subset used.
"""
import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

HERE = Path(__file__).resolve().parent
KINDS = {"instrument": "charcoal", "effect": "bone"}   # kind -> theme (plugin-ui-bob brand sheet)
CODE_RE = re.compile(r"^[A-Z][a-z0-9]{3}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ----------------------------------------------------------------------------- toml

def _mini_toml(text):
    """[sections], [a.b] dotted sections, key = "string" | true | false | integer | ["a", "b"], # comments."""
    import ast
    data = {}
    cur = data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            name = line[1:line.index("]")].strip()
            cur = data
            for part in name.split("."):
                cur = cur.setdefault(part.strip().strip('"'), {})
            continue
        if "=" not in line:
            raise ValueError("plugins.toml: cannot parse %r" % raw)
        k, v = (x.strip() for x in line.split("=", 1))
        if "#" in v and not v.startswith('"') and not v.startswith("["):
            v = v.split("#", 1)[0].strip()
        elif v.startswith('"') and v.count('"') >= 2:
            v = v[: v.rindex('"') + 1]
        elif v.startswith("[") and "]" in v:
            v = v[: v.rindex("]") + 1]
        if v in ("true", "false"):
            val = v == "true"
        elif v.startswith("["):
            val = list(ast.literal_eval(v))
        elif v.startswith('"'):
            val = ast.literal_eval(v)
        else:
            val = int(v)
        cur[k.strip('"')] = val
    return data


def load_toml(path):
    text = Path(path).read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return _mini_toml(text)


# ----------------------------------------------------------------------------- locate

def tools_toml_registry():
    p = Path(os.path.expanduser("~/.config/oberli/tools.toml"))
    if not p.exists():
        return None
    try:
        reg = load_toml(p).get("registry", {}).get("plugins")
    except Exception:
        return None
    return Path(os.path.expanduser(reg)) if reg else None


def find_registry(explicit=None):
    candidates = [explicit, os.environ.get("OBERLI_REGISTRY"), tools_toml_registry(),
                  HERE.parent.parent / "registry" / "plugins.toml",
                  Path.home() / "bob-skills/plugins/ship-bob/skills/ship-bob/registry/plugins.toml"]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    return None


# ----------------------------------------------------------------------------- derive

def derive(name):
    """Product name -> id (CamelCase), slug (kebab), bundle part (lowercase, no spaces)."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        raise ValueError("product name %r has no letters" % name)
    return {"id": "".join(w[:1].upper() + w[1:] for w in words),
            "slug": "-".join(w.lower() for w in words),
            "bundle": "".join(w.lower() for w in words)}


def taken_codes(reg):
    codes = {reg["family"]["manufacturer_code"]}
    codes |= {p["code"] for p in reg.get("plugin", {}).values()}
    return codes


def propose_code(name, reg):
    """First free code: initials, then consonant skeletons, then letters with a digit."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    letters = "".join(words).lower()
    cands = []
    if len(words) >= 2:
        cands.append((words[0][:2] + words[1][:2]).lower())
        cands.append((words[0][:1] + words[1][:3]).lower())
    cands.append(letters[:4])
    cons = re.sub(r"[aeiou]", "", letters)
    cands.append(cons[:4])
    cands.append((letters[:3] + "1"))
    taken = {c.lower() for c in taken_codes(reg)}
    for c in cands:
        c = (c + "xxxx")[:4]
        c = c[0].upper() + c[1:]
        if CODE_RE.match(c) and c.lower() not in taken:
            return c
    for i in range(2, 100):
        c = letters[:1].upper() + letters[1:2] + ("%02d" % i)
        if CODE_RE.match(c) and c.lower() not in taken:
            return c
    raise ValueError("no free code for %r" % name)


def propose_accent(reg):
    used = {p["accent"] for p in reg.get("plugin", {}).values()}
    for a in reg["family"]["accents"]:
        if a not in used:
            return a
    raise ValueError("every accent of the brand sheet is taken; the brand sheet must grow first")


# ----------------------------------------------------------------------------- checks

def check_registry(reg):
    errs = []
    fam = reg.get("family", {})
    for k in ("name", "manufacturer_code", "bundle_prefix", "github_owner", "accents", "accent_hex", "preset_extension"):
        if k not in fam:
            errs.append("family.%s missing" % k)
    if errs:
        return errs
    if not CODE_RE.match(fam["manufacturer_code"]):
        errs.append("family.manufacturer_code %r is not one upper + three lower characters" % fam["manufacturer_code"])
    for a in fam["accents"]:
        if a not in fam["accent_hex"]:
            errs.append("family.accent_hex has no %s" % a)
    seen = {"code": {fam["manufacturer_code"].lower(): "family"}, "accent": {}, "bundle_id": {}, "id": {}, "name": {}}
    for slug, p in reg.get("plugin", {}).items():
        if not SLUG_RE.match(slug):
            errs.append("plugin.%s: slug is not kebab-case" % slug)
        for k in ("name", "id", "code", "kind", "accent", "bundle_id", "repo"):
            if k not in p:
                errs.append("plugin.%s: %s missing" % (slug, k))
        if any(k not in p for k in ("name", "id", "code", "kind", "accent", "bundle_id")):
            continue
        d = derive(p["name"])
        if d["slug"] != slug:
            errs.append("plugin.%s: the slug of %r is %s" % (slug, p["name"], d["slug"]))
        if d["id"] != p["id"]:
            errs.append("plugin.%s: id %r, expected %s" % (slug, p["id"], d["id"]))
        if not CODE_RE.match(p["code"]):
            errs.append("plugin.%s: code %r is not one upper + three lower characters" % (slug, p["code"]))
        if p["kind"] not in KINDS:
            errs.append("plugin.%s: kind %r (instrument or effect)" % (slug, p["kind"]))
        if p["accent"] not in fam["accents"]:
            errs.append("plugin.%s: accent %r is not on the brand sheet" % (slug, p["accent"]))
        if p["bundle_id"] != fam["bundle_prefix"] + d["bundle"]:
            errs.append("plugin.%s: bundle_id %r, expected %s" % (slug, p["bundle_id"], fam["bundle_prefix"] + d["bundle"]))
        for k in ("code", "accent", "bundle_id", "id", "name"):
            key = p[k].lower() if k == "code" else p[k]
            if key in seen[k]:
                errs.append("plugin.%s: %s %r already used by %s" % (slug, k, p[k], seen[k][key]))
            seen[k][key] = slug
    return errs


def cmake_value(text, key):
    m = re.search(r"^\s*%s\s+(?:\"([^\"]*)\"|([^\s)]+))" % re.escape(key), text, re.M)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else None


def check_repo(repo, reg):
    """ship.toml and CMakeLists.txt of a product repo against its registry entry."""
    repo = Path(repo)
    errs = check_registry(reg)
    ship = repo / "ship.toml"
    if not ship.exists():
        return errs + ["%s: no ship.toml" % repo]
    cfg = load_toml(ship).get("product", {})
    slug = cfg.get("slug")
    entry = reg.get("plugin", {}).get(slug)
    if entry is None:
        return errs + ["ship.toml slug %r is not in the registry (registry.py add)" % slug]
    for k, rk in (("name", "name"), ("asset_name", "id"), ("repo", "repo")):
        if cfg.get(k) != entry.get(rk):
            errs.append("ship.toml %s = %r, registry says %r" % (k, cfg.get(k), entry.get(rk)))
    cm = repo / "CMakeLists.txt"
    if cm.exists():
        text = cm.read_text(encoding="utf-8")
        fam = reg["family"]
        for key, want in (("PLUGIN_CODE", entry["code"]), ("PLUGIN_MANUFACTURER_CODE", fam["manufacturer_code"]),
                          ("BUNDLE_ID", entry["bundle_id"]), ("PRODUCT_NAME", entry["name"]),
                          ("COMPANY_NAME", fam["name"])):
            got = cmake_value(text, key)
            if got != want:
                errs.append("CMakeLists.txt %s is %r, registry says %r" % (key, got, want))
    return errs


# ----------------------------------------------------------------------------- add

def entry_text(slug, name, pid, code, kind, accent, bundle_id, repo):
    return ("\n[plugin.%s]\nname = \"%s\"\nid = \"%s\"\ncode = \"%s\"\nkind = \"%s\"\naccent = \"%s\"\n"
            "bundle_id = \"%s\"\nrepo = \"%s\"\nclass_id = \"\"\nfirst_release = \"\"\n"
            % (slug, name, pid, code, kind, accent, bundle_id, repo))


def add(path, name, kind, code=None, accent=None, repo=None):
    """Append an entry; returns the entry dict. Raises ValueError on a taken slug, code or accent."""
    reg = load_toml(path)
    errs = check_registry(reg)
    if errs:
        raise ValueError("registry is inconsistent: " + "; ".join(errs))
    if kind not in KINDS:
        raise ValueError("kind %r: instrument or effect" % kind)
    d = derive(name)
    plugins = reg.get("plugin", {})
    if d["slug"] in plugins:
        raise ValueError("slug %s is taken (%s)" % (d["slug"], plugins[d["slug"]]["name"]))
    code = code or propose_code(name, reg)
    if not CODE_RE.match(code):
        raise ValueError("code %r: one upper + three lower characters" % code)
    if code.lower() in {c.lower() for c in taken_codes(reg)}:
        raise ValueError("code %s is taken" % code)
    accent = accent or propose_accent(reg)
    if accent not in reg["family"]["accents"]:
        raise ValueError("accent %r is not on the brand sheet (%s)" % (accent, ", ".join(reg["family"]["accents"])))
    if accent in {p["accent"] for p in plugins.values()}:
        raise ValueError("accent %s is taken" % accent)
    fam = reg["family"]
    bundle_id = fam["bundle_prefix"] + d["bundle"]
    repo = repo or "%s/%s" % (fam["github_owner"], d["slug"])
    text = Path(path).read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    Path(path).write_text(text + entry_text(d["slug"], name, d["id"], code, kind, accent, bundle_id, repo), encoding="utf-8")
    return {"slug": d["slug"], "name": name, "id": d["id"], "code": code, "kind": kind, "accent": accent,
            "accent_hex": fam["accent_hex"][accent], "theme": KINDS[kind], "bundle_id": bundle_id, "repo": repo,
            "bundle": d["bundle"]}


# ----------------------------------------------------------------------------- selftest

SAMPLE = """[family]
name = "Oberli Audio"
manufacturer_code = "Obrl"
bundle_prefix = "com.oberliaudio."
github_owner = "Oberli-Audio"
preset_extension = ".oberlipreset"
accents = ["mango", "saffron"]

[family.accent_hex]
mango = "#F09300"
saffron = "#F6BF26"

[plugin.fake-pad]
name = "Fake Pad"
id = "FakePad"
code = "Fkpd"
kind = "instrument"
accent = "mango"
bundle_id = "com.oberliaudio.fakepad"
repo = "Oberli-Audio/fake-pad"
class_id = ""
first_release = ""
"""


def selftest():
    fails = []
    expect = lambda label, cond: None if cond else fails.append(label)
    reg = _mini_toml(SAMPLE)
    expect("mini parser reads dotted sections", reg["plugin"]["fake-pad"]["code"] == "Fkpd" and reg["family"]["accent_hex"]["mango"] == "#F09300")
    if tomllib is not None:
        expect("mini parser equals tomllib", reg == tomllib.loads(SAMPLE))
    expect("sample registry is consistent", check_registry(reg) == [])
    expect("derive", derive("Horizon Pad") == {"id": "HorizonPad", "slug": "horizon-pad", "bundle": "horizonpad"})
    expect("propose code avoids taken", propose_code("Fake Pad", reg) != "Fkpd" and CODE_RE.match(propose_code("Shimmer", reg)))
    expect("propose accent is the free one", propose_accent(reg) == "saffron")
    bad = _mini_toml(SAMPLE.replace('accent = "mango"', 'accent = "lime"'))
    expect("accent off the sheet fails", any("not on the brand sheet" in e for e in check_registry(bad)))
    dup = _mini_toml(SAMPLE + SAMPLE[SAMPLE.index("[plugin.fake-pad]"):].replace("fake-pad", "fake-pod").replace("Fake Pad", "Fake Pod").replace("FakePad", "FakePod").replace("fakepad", "fakepod"))
    e = check_registry(dup)
    expect("duplicate code and accent fail", any("code" in x for x in e) and any("accent" in x for x in e))
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "plugins.toml"
        p.write_text(SAMPLE, encoding="utf-8")
        e = add(p, "Shimmer", "effect")
        expect("add appends a consistent entry", e["accent"] == "saffron" and e["theme"] == "bone" and check_registry(load_toml(p)) == []
               and load_toml(p)["plugin"]["shimmer"]["bundle_id"] == "com.oberliaudio.shimmer")
        try:
            add(p, "Shimmer", "effect")
            fails.append("second add of the same slug should fail")
        except ValueError:
            pass
        try:
            add(p, "Other Thing", "effect", code="Fkpd")
            fails.append("taken code should fail")
        except ValueError:
            pass
        try:
            add(p, "Third Thing", "effect")
            fails.append("no free accent should fail")
        except ValueError:
            pass
        # a repo against its entry
        repo = Path(d) / "repo"
        repo.mkdir()
        (repo / "ship.toml").write_text('[product]\nname = "Fake Pad"\nslug = "fake-pad"\nasset_name = "FakePad"\nrepo = "Oberli-Audio/fake-pad"\nformats = ["VST3"]\n', encoding="utf-8")
        (repo / "CMakeLists.txt").write_text('juce_add_plugin(FakePad\n    COMPANY_NAME "Oberli Audio"\n    BUNDLE_ID "com.oberliaudio.fakepad"\n'
                                             '    PLUGIN_MANUFACTURER_CODE Obrl\n    PLUGIN_CODE Fkpd\n    PRODUCT_NAME "Fake Pad")\n', encoding="utf-8")
        expect("repo matches its entry", check_repo(repo, load_toml(p)) == [])
        (repo / "CMakeLists.txt").write_text((repo / "CMakeLists.txt").read_text().replace("Fkpd", "Fkpx"), encoding="utf-8")
        expect("wrong PLUGIN_CODE fails", any("PLUGIN_CODE" in x for x in check_repo(repo, load_toml(p))))
        (repo / "ship.toml").write_text((repo / "ship.toml").read_text().replace("fake-pad", "nope"), encoding="utf-8")
        expect("unknown slug fails", any("not in the registry" in x for x in check_repo(repo, load_toml(p))))
    if fails:
        print("registry selftest FAILED:\n  " + "\n  ".join(fails), file=sys.stderr)
        return 1
    print("registry selftest OK: dotted-section parser, consistency, derived names, free code and accent, "
          "duplicates and off-sheet accents fail, add refuses a taken slug, code or accent and an exhausted sheet, "
          "a repo's ship.toml and CMakeLists.txt are checked against its entry")
    return 0


# ----------------------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", help="path to plugins.toml (default: see --help)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    sub.add_parser("selftest")
    c = sub.add_parser("check")
    c.add_argument("repo")
    pr = sub.add_parser("propose")
    pr.add_argument("--name", required=True)
    ad = sub.add_parser("add")
    ad.add_argument("--name", required=True)
    ad.add_argument("--kind", required=True, choices=sorted(KINDS))
    ad.add_argument("--code")
    ad.add_argument("--accent")
    ad.add_argument("--repo")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if not a.cmd:
        ap.print_help()
        return 2
    path = find_registry(a.registry)
    if path is None:
        print("registry: no plugins.toml found (set OBERLI_REGISTRY or registry.plugins in ~/.config/oberli/tools.toml)", file=sys.stderr)
        return 2
    reg = load_toml(path)
    if a.cmd == "list":
        errs = check_registry(reg)
        print("registry: %s" % path)
        for slug, p in reg.get("plugin", {}).items():
            print("  %-16s %-14s code %s  accent %-8s %s%s" % (slug, p.get("name"), p.get("code"), p.get("accent"), p.get("kind"),
                                                              "  released " + p["first_release"] if p.get("first_release") else ""))
        for e in errs:
            print("ERROR: " + e)
        return 1 if errs else 0
    if a.cmd == "check":
        errs = check_repo(a.repo, reg)
        for e in errs:
            print("ERROR: " + e)
        if errs:
            print("registry check: %d error(s)" % len(errs))
            return 1
        print("registry check OK: %s matches %s" % (a.repo, path))
        return 0
    if a.cmd == "propose":
        print("code %s, accent %s, slug %s" % (propose_code(a.name, reg), propose_accent(reg), derive(a.name)["slug"]))
        return 0
    if a.cmd == "add":
        try:
            e = add(path, a.name, a.kind, a.code, a.accent, a.repo)
        except ValueError as ex:
            print("registry add: %s" % ex, file=sys.stderr)
            return 1
        print("registry: added %s (%s, code %s, accent %s) to %s" % (e["slug"], e["kind"], e["code"], e["accent"], path))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
