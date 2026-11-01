#!/usr/bin/env python3
"""Write the two project documents of the playbook into a product's docs/ folder.

A product keeps two documents for its own work (D.9): `docs/brief.md`, the sonic brief
(the F.15.2 YAML, owner-confirmed, amended beneath), and `docs/status.md`, the one-page
view (gate status, listening debt, open exceptions, handoff, decisions; template D.9.2).
Both templates live in the playbook text, so there is one source and no copies to
drift; this script extracts them. `docs/failures.md` starts as the D.9.3 table header.

    python3 new_project_docs.py <project>/docs            # writes missing files only
    python3 new_project_docs.py <project>/docs --list     # show what it would write
    python3 new_project_docs.py <project>/docs --force    # overwrite existing files
"""
import argparse
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "references"   # the skill's playbook files
# output file -> (playbook file, heading whose first fenced block is the template)
TEMPLATES = {
    "brief.md": ("dsp-foundations.md", "### F.15.2"),
    "status.md": ("dsp-development.md", "### D.9.2"),
    "failures.md": ("dsp-development.md", "### D.9.3"),
}


def template(fname, heading):
    text = (DOCS / fname).read_text(encoding="utf-8")
    start = text.index(heading)
    # the template is the first fenced block after the heading (templates contain their
    # own "## " lines, so the section cannot be cut at the next heading)
    m = re.search(r"```(?:markdown|yaml|toml)\n(.*?)\n```", text[start:], re.S)
    if not m:
        sys.exit("no template code block under %s in %s" % (heading, fname))
    body = m.group(1) + "\n"
    if heading.endswith("F.15.2"):
        body = ("# Sonic brief (owner-confirmed <date>; amend below, never edit the YAML)\n\n```yaml\n"
                + body + "```\n\n## Amendments\n- <date>: <what changed, why, which gates re-open>\n")
    if heading.endswith("D.9.3"):
        body = "# Failures - the product's own rows (D.9.3)\n\n" + body + "|---|---|---|---|---|\n"
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", help="the product's docs/ folder (created if missing)")
    ap.add_argument("--list", action="store_true", help="show what would be written, write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite files that exist")
    a = ap.parse_args(argv)
    target = Path(a.docs)
    target.mkdir(parents=True, exist_ok=True)
    for out, (fname, heading) in TEMPLATES.items():
        body = template(fname, heading)
        path = target / out
        if a.list:
            print("%-12s <- %s %s (%d lines)" % (out, fname, heading, body.count("\n")))
            continue
        if path.exists() and not a.force:
            print("kept     %s (exists)" % path)
            continue
        path.write_text(body, encoding="utf-8")
        print("written  %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
