# Align: kickoff

Build order 4 of 5. Effect, Bone theme, accent saffron, plugin code `Algn`, Tier P. Repo created from the template and initialised on 2026-11-01; parameter table and sketch are in.

## Prompt for the cloud session (started on Oberli-Audio/align, VST3 project attached)

```
Build Align for Oberli Audio, Tier P.
G0 is closed: docs/brief.md is owner-confirmed (2026-11-01), from the decided
sketch docs/sketch.md; parameters.csv is in the repo. Start at G1. Use
sound-design-bob and plugin-ui-bob (ship-bob for CI and releases).

Working rules:
- Pass a gate on your own when its evidence is green (tests, paramgen,
  pluginval, null and latency tests); log it in docs/status.md and go on.
- Stop for me only for: listening checkpoints, Ableton host checks (Live
  10.1 under Rosetta, Live on Windows), a conflict with a structural
  decision in the sketch, and before any release (run the release gate).
- Everything that needs me goes in a section "Waiting for Björn" at the
  top of docs/status.md, one line each, newest first; keep working on
  whatever is not blocked.
- Shared code (LookAndFeel, Strip frame, meters, Loudness, Analysis/FFT,
  References, RenderSafety) is built in Oberli-Audio/bob-skills as
  template Source/oberli/. Never write your own version and never edit
  bob-skills. Until it lands, keep the editor as the template stub and
  work on the DSP, harness and tests; then refresh Source/oberli/ from
  plugin-template and wire it in. A missing shared piece is a "Waiting
  for Björn" line.
- Commit and push at every checkpoint.
```

## Prompt for the Visual Studio session (taking over at G3, after the cloud session)

The cloud session closed G0-G2 and ported the DSP (G4's code) with a green build. It could not
measure the port, because pluginval, the Steinberg validator, auval, Plugalyzer, RTSan and both
Ableton hosts need Björn's machines. Paste this into a Claude Code session in Visual Studio opened
on the repository.

```
Continue Align for Oberli Audio, Tier P. Branch: claude/align-oberli-audio-tier-p-bbzb8w
(already on origin; start from it, do not restart from main).

Read first, in this order: docs/status.md (its "Waiting for Björn", "Handoff" and
"Decisions" sections are the whole state), docs/brief.md (owner-confirmed, amendments
beneath the YAML), "sound design"/README.md (why the G2 prototype is numpy and not
Faust, and the three prototype-era workarounds to decide again), docs/sketch.md.
Use sound-design-bob and plugin-ui-bob, ship-bob from the release gate on.
State the tier and the current gate at the start of every answer.

Where it stands. G0, G1 and G2 are closed, with every number in docs/status.md next to
the command that produced it. The G4 port is in Source/dsp/ (SincDelay, Rotate,
AnalysisRing, Detector, AlignEngine) with PluginProcessor rewritten around it, and
`cmake --build --preset release -j4` is green and warning-free on Linux.
**The G2 numbers are the prototype's, not the port's.** Nothing in the C++ has been
measured. Do not copy a prototype number into a G3 row.

Do these in order:
1. tools/tests/test_plugin.py from scripts/dsp-kit/test_template.py: the fast label
   under 60 s, then the render label. Cover, as named tests: the brief's null (Delay 0,
   Polarity off, Rotate 0, at Window 0 and after compensating Window 20 ms), reported
   latency equals measured for all five Windows, the Delay clamp and the search range,
   bit-identical runs from reset, every rate in the brief x blocks 0/1/13/32/64/512/4096
   and one above the announced size, the Track click test, mono in stays mono, Rotate's
   magnitude and its angle at Below, the detector's sign convention, Detect on the
   drum-loop pair within 0.02 ms with confidence above 80 %, the Rotate suggestion's
   three cases, state round trip and a corrupted-state load. Each test gets the same
   number the prototype produced as its expectation, so a port error shows as a
   difference rather than as a new baseline.
2. The G5 null: port against the prototype's seeded renders. Regenerate them with
   `python3 "sound design/prototype.py" --renders --seed 1` (they are gitignored on
   purpose; the seed, the code and the fingerprints in "sound design"/g2.json are what
   is committed). Drive the harness with --sidechain and the same settings, and judge
   against F.8's table: the path has one-pole all-pass state but no long feedback, and
   the prototype is float64 against the port's float32. Characterise anything that does
   not null instead of loosening the threshold.
3. tools/measure/ for the G3 battery on the real plugin, each script on dspkit.render(),
   each writing one docs/status.md row with its command: the fractional delay's response
   to 18 kHz, Rotate's magnitude and phase, the accuracy and confidence on all three
   pairs at all six rates, the latency table, the click tests, the detect time against
   the brief's "under 200 ms on the reference machine".
4. Then the machine-only evidence, which is why this session exists: RTSan on the harness
   (the rtsan preset, LLVM 20+ from ~/.config/oberli/tools.toml - run
   `eval "$(python3 scripts/dsp-kit/toolchain.py env)"` first), ASan+UBSan on the suite,
   perf.py one row at 48 k/64 on the x86_64 slice, pluginval L10 and the Steinberg
   validator via validate_plugin.py, the Plugalyzer bundle null test, and the arm64
   smoke. Report, do not judge, over_deadline.
5. G7's documents and the preset bank (8 presets, the brief's categories, Init =
   defaults, presetlint.py).

Harness extensions this product added, because contract v3 has neither and Align cannot
be measured without them (documented in docs/status.md): --sidechain=<file.wav> and
--sidechain-signal=<spec> fill the reference bus; --detect-at=<t> presses Detect as a
host would, waits for the worker and calls applyPendingDetect() directly, because a
console app runs no message loop; --detect-timeout=<ms> bounds that wait. The product
object carries a detects log with the readout in words, the Rotate suggestion, the
correlation, the Track offset and the analysis rate.

Working rules, unchanged:
- Pass a gate on your own when its evidence is green; log it in docs/status.md with the
  command behind every number, and go on.
- Stop for me only for: listening checkpoints, the Ableton host checks (Live 10.1 under
  Rosetta, Live on Windows), a conflict with a structural decision in the sketch, and
  before any release (run the release gate).
- Everything that needs me goes in "Waiting for Björn" at the top of docs/status.md, one
  line each, newest first; keep working on whatever is not blocked.
- Shared code (LookAndFeel, Strip frame, meters, Loudness, Analysis/FFT, References,
  RenderSafety) is built in Oberli-Audio/bob-skills as template Source/oberli/. Never
  write your own version and never edit bob-skills. Until it lands, keep the editor as
  the template stub and work on the DSP, harness and tests; then refresh Source/oberli/
  from plugin-template and wire it in. A missing shared piece is a "Waiting for Björn"
  line. The accent is sage #33B679 (category accent, mix tools).
- Add a regression test whenever a DSP defect is fixed, show it failing on the build that
  has the defect, and add its row to docs/failures.md.
- Commit and push to the branch above at every checkpoint.

Two decisions of mine are still open at the top of docs/status.md (Rotate's
re-parameterisation and the asymmetric Delay clamp). Both are implemented as described;
ask me once and carry on either way.

Two things the cloud could not have and you can: the real test material (the multi-mic
drum loop, the DI/amp pair and the 1.2 s RT60 room pair live in OneDrive, not in git -
the suite uses seeded synthetic material, so run the accuracy numbers on the real files
once and record both), and the two Ableton hosts for the 15-minute list per host.
```
