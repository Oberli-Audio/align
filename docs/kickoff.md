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
