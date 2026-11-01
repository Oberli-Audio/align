# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

{{Product}} (Oberli Audio), an {{kind}} plugin (VST3; the formats ship.toml lists), built with
JUCE pinned by commit (CMakeLists.txt) and started from the family template
(Oberli-Audio/plugin-template). Theme {{theme}}, accent {{accent}} ({{AccentHex}}), plugin code
`{{Code}}`, bundle id `{{BundleId}}`: all from the family registry (ship-bob
`registry/plugins.toml`), never changed after the first release.

## Tier and process

The project runs at **Tier {{Tier}}** (`scripts/dsp-kit/../references`: the tier definition is
`tiers.md` in every bob skill). Sound: the **sound-design-bob** skill (gates G0-G7, the DSP
playbook in its `references/`, grep them, never read them whole; the textbook half is
**dsp-reference-bob**). Editor: **plugin-ui-bob**, on the same tier, gates and parameter table,
from the Oberli Audio brand sheet. Releases, README, notices, feedback loop: **ship-bob**, from
the release gate (`joint-plugin-workflow.md`, section "Release gate") on. State the tier and
the current gate at the start of every answer.

The project documents (sound-design-bob D.9): `docs/brief.md` (owner-confirmed; amend beneath
the YAML, never edit it), `docs/status.md` (one page, rewritten at every checkpoint: gates with
the command behind every number, listening debt, open exceptions as dated lines, handoff,
decisions) and `docs/failures.md` (one row per fixed defect with its regression test). A failed
measurement is fixed or gets a dated exception line; the README's Known issues are generated
from the open lines (`python3 scripts/ship/shipcheck.py known-issues . --write`).

## Single sources

- `parameters.csv` is the parameter table (joint-plugin-workflow.md). `Source/Params.h` and
  `docs/parameters.md` are generated from it: `python3 scripts/dsp-kit/paramgen.py juce
  parameters.csv -o Source/Params.h` and `... manual parameters.csv -o docs/parameters.md`. A
  parameter change starts in the CSV; `paramgen.py check` runs in the tests.
- `presets.csv` and `presets/<slug>.oberlipreset` are the factory bank (presetlint.py); the
  harness's `--list-presets` must equal the CSV in order.
- `VERSION` feeds CMake, the About panel and the release; the tag is `v` + VERSION.
- `ship.toml` names the product and the shipped format set; `notices.toml` the third-party
  components (`THIRD_PARTY_NOTICES.md` is generated).
- `scripts/dsp-kit/` and `scripts/ship/` are byte copies of the kits in `~/bob-skills`
  (sound-design-bob and ship-bob): refresh them from there, never edit them here.
- Machine paths (LLVM, Faust, pluginval, the hosts) are in `~/.config/oberli/tools.toml`
  (`python3 scripts/dsp-kit/toolchain.py check`), never in this repo.

## Build, harness, tests

DEVELOPING.md has every command. The short form:

```bash
cmake --preset release && cmake --build --preset release      # VST3, Standalone, the harness
ctest --preset fast                                           # the inner loop, under 60 s
./build/{{ProductId}}Harness_artefacts/Release/{{ProductId}}Harness --help   # the offline renderer (harness contract v3)
```

`{{ProductId}}Harness` (`tools/harness/Main.cpp`) renders the real plugin code without a host and
prints one JSON object; every measurement script drives it. The Tier P realtime check is the
malloc trap inside it (every render is an allocation test); the `rtsan` preset builds it with
RealtimeSanitizer. `tools/tests/test_plugin.py` is the suite (labels `fast`, `render`); **add a
regression test whenever a DSP defect is fixed, show it failing on the build that has the
defect, and add its row to `docs/failures.md`.**

## DSP work

The invariants (`rules/dsp-invariants.md`, installed to `~/.claude/rules/` by
`~/bob-skills/install.sh`) hold for `Source/**` and `*.dsp`. The Faust prototype and the
reference renders live under `sound design/` (design references, never compiled into the
product); large sample material stays in OneDrive, not in git (`.gitignore`).
