# Status - Align 0.1.0 (2026-11-01)
Tier P, track E (effect), at gate G1 closed, G2 next. Recipe D.8.1.

## Waiting for Björn
Newest first; one line each. Everything else keeps moving.
- 2026-11-01: **Rotate's structure changed, confirm.** The sketch §4.1 names a "second-order all-pass with its corner at Below ... returns to 0 above about 4x Below". That cannot exist: a real causal filter has 0 deg or 180 deg phase at DC, and a magnitude-flat (all-pass) filter's total phase swing is a multiple of 180 deg, so "48 deg at the low end, 0 deg above Below" is not an all-pass. The sketch's *behaviour* is kept, its *named structure* is replaced by a quadrature low-band rotation with a magnitude-compensating bell (G1 decision 3). The price: up to 0.5 dB of magnitude ripple around Below instead of a perfectly flat all-pass.
- 2026-11-01: **Delay clamp is asymmetric, confirm.** Internal delay = Window + clamp(Delay, -Window, +200 ms); the positive side is not clamped to the Window. A symmetric clamp would pin Delay to 0 at Window "0 (live)", which the sketch's own 2026-11-01 decision ("zero latency, positive delay only") forbids (G1 decision 6).
- 2026-11-01: **Shared `Source/oberli/` is not in the repo or in plugin-template.** LookAndFeel, Strip frame, meters, Loudness, Analysis/FFT, References, RenderSafety. The editor stays the template stub; DSP, harness and tests go on. Refresh `Source/oberli/` from plugin-template and wire the editor when it lands.
- 2026-11-01: **Two new rows for `dsp-selection.md` in bob-skills** (S.0: a family that is not in the tables is added afterwards). Text in Decisions below; never edited from this repo.
- 2026-11-01: **Test material.** The multi-mic drum loop, the DI/amp pair and the 1.2 s RT60 room pair live in OneDrive, not in git. The prototype and the suite use synthetic material (`sound design/material.py`, seeded); the brief's accuracy numbers on *real* material need those files once.
- 2026-11-01: **Listening checkpoint after G3** (init patch and the first presets, level-matched renders).
- 2026-11-01: **Host checks and the macOS/Windows half of the release gate** cannot run in this cloud container: pluginval, Steinberg validator, auval, Plugalyzer, RTSan (needs LLVM 20+ clang), `perf.py` on the x86_64 slice, Live 10.1 under Rosetta, Live on Windows. CI (`.github/workflows/build.yml`) runs the validators on macOS and Windows on push.

## Gates
| Gate | State | Evidence (command -> number, test name, log) |
|---|---|---|
| G0 | closed 2026-11-01 | `docs/brief.md` owner-confirmed, from `docs/sketch.md`; `parameters.csv` in the repo |
| G1 | closed 2026-11-01 | families chosen against the brief with `dsp-selection.md` S.2/S.4/S.5; three departures, each with the measurement that would reject it (Decisions) |
| G2 | open | next: numpy prototype in the port's structure (`sound design/`), seeded reference renders, programmatic checks |
| G3 | - | `tools/measure/` on `dspkit.render()`; metric table |
| G4 | - | clean Release build with the ported DSP; `cmake --build --preset release` |
| G5 | - | null vs the prototype; bank loudness-matched (`presetlint.py`) |
| G6 | - | `validate_plugin.py full`, `paramgen.py check --frozen`, `presetlint.py render --tier P`, hosts |
| G7 | - | bank and table final, documents current, release gate green, then ship-bob |

## Listening debt
- none yet (nothing has been rendered).

## Open exceptions
- none yet.

## Handoff
Task: build Align to Tier P from G1. Plan: 1. [x] G1 families and departures 2. [ ] G2 numpy prototype, seeded material, reference renders (next) 3. [ ] G3 harness sidechain + measurement scripts + metric table 4. [ ] G4 port 5. [ ] G5 null 6. [ ] G6 validate (Linux half) 7. [ ] G7 documents.
Working tree: clean. Build: red on purpose - `Source/Params.h` is regenerated for Align's table but `Source/PluginProcessor.cpp` is still the template's (`Params::outGain`, `Params::mix`); the processor is rewritten at G4. Tests: not registered yet (the build has to compile first).
Open questions for the owner: the "Waiting for Björn" lines above.
Next command: `python3 "sound design/prototype.py" --all --seed 1`

## Decisions
- 2026-11-01: **G1 family - estimator.** GCC-PHAT (generalised cross-correlation with the phase
  transform) over the search window, parabolic interpolation on the peak, sign of the peak for
  polarity, peak-to-second-peak ratio for confidence. Not in `dsp-selection.md` S.4, so the row
  below is added to that file in bob-skills. Trade-off in one paragraph: the brief has to find
  2.317 ms within **0.02 ms** on a 4-bar drum loop and within **0.1 ms** on a room pair with
  1.2 s RT60, from one press, with a confidence a user can read. Plain time-domain
  cross-correlation peaks broadly on reverberant and tonal material (its peak is the
  autocorrelation of the source convolved with the room, which for a 1.2 s tail is tens of
  milliseconds wide), and its peak height depends on the source spectrum, so no threshold
  travels between a kick and a room pair. Whitening each bin (PHAT) turns the estimate into
  something close to a delta plus noise, which makes both the 0.02 ms refinement and a
  source-independent confidence possible; the price is sensitivity to bins with no energy,
  bought back by regularising the denominator and restricting the sum to 60 Hz - 8 kHz. Per-band
  spectral alignment would beat both but is `out_of_scope` in the brief (it changes the sound,
  not only the timing). **Rejected if** the accuracy test on the reverberant pair exceeds 0.1 ms,
  or confidence on the drum loop falls below 80 %.
- 2026-11-01: **G1 family - applying the delay.** A table of Kaiser-windowed-sinc kernels (32
  taps x 512 fractional phases, built in `prepare`), two taps crossfaded over 10 ms on a change.
  **Departure from rule 6** ("modulated delays Lagrange/Hermite; allpass interpolation only for
  static tuning"): the delay here is static between changes - Track mode steps it and crossfades,
  it never sweeps a read pointer - so this is rule 6's static case, where a windowed sinc beats
  Lagrange by an order of magnitude in passband flatness. **Rejected if** the impulse through a
  0.37 ms delay is not flat within 0.05 dB to 18 kHz (the brief's `response_error_db`), or the
  click test (Track sweeping 2 ms over 1 s on a 1 kHz sine) produces a sample above peak +
  0.01 dB.
- 2026-11-01: **G1 - crossfade law.** The two delay taps crossfade **amplitude-complementary**
  (a + b = 1), not equal-power. **Departure from rule 5** ("wet/dry mixes equal-power"): rule 5
  covers a wet path against a dry path, which are only partly correlated; here both taps carry
  the *same* signal, where an equal-power law overshoots by up to +3 dB when the two taps happen
  to be in phase. **Rejected if** the click test shows a sample above peak + 0.01 dB (which an
  amplitude-complementary fade on a coherent pair cannot produce, and an equal-power one can).
- 2026-11-01: **G1 family - Rotate.** `y = x + (cos(th) - 1) * L(x) + sin(th) * Q(x)`, with `L` a
  first-order low-pass at Below, `Q` the same band shifted +90 deg by an IIR allpass-pair Hilbert
  designed over 20 Hz - 4 x Below, followed by a magnitude-compensating broad bell at Below with
  gain `-10 log10(1 + sin th)` and Q 0.23 (from `|y|^2 = 1 + sin(th) * 2s/(1+s^2)`, `s = f/Below`,
  whose peak is `1 + sin th` at `s = 1` and whose -3 dB width is 4.4 octaves). At `th = 0` both
  correction terms and the bell vanish, so the stage is exactly identity and the null test holds;
  at `th = 180` it is a polarity flip of the low band alone. **Departure from the sketch §4.1**,
  which names a second-order all-pass: that structure cannot produce the behaviour the sketch
  describes, because a real causal filter's phase at DC is 0 or 180 deg and a magnitude-flat
  all-pass's total phase swing is a multiple of 180 deg. The behaviour is kept, the structure is
  not. **Rejected if** the magnitude is outside +/-0.5 dB from 20 Hz to 20 kHz at any Rotate, the
  phase is more than 5 deg from the set value between 30 Hz and 0.25 x Below or more than 5 deg
  from zero above 4 x Below, or the null at Rotate 0 is above -120 dBFS.
- 2026-11-01: **G1 - Track mode.** Re-estimate every 250 ms over the last 1 s, searching
  +/-2 ms around the current value; one-pole smoothing with tau = 1 s; applied as an offset to the
  user's Delay base, never written to the parameter; Hold freezes the offset; Polarity is never
  touched. From the sketch §4.3, no departure. **Rejected if** the click test fails or the offset
  does not settle within 3 s of a 2 ms step.
- 2026-11-01: **G1 - threads.** Audio thread writes a 4 s lock-free analysis ring for the input
  and the sidechain and reads parameters through cached `std::atomic<float>*` (S.5); a detect
  worker `juce::Thread` polls a request flag every 20 ms, owns every FFT workspace (allocated in
  `prepareToPlay`), and publishes its result behind an atomic sequence counter; the parameter
  write happens on the message thread through an `AsyncUpdater` with
  begin/perform/endChangeGesture, so the host records one edit. Nothing allocates, locks or logs
  on the audio thread (rule 1). The harness drives the same path and, because a console app runs
  no message loop, calls the processor's `applyPendingDetect()` directly after the worker
  publishes - the same function the `AsyncUpdater` calls.
- 2026-11-01: **G1 - latency and the clamp.** Reported latency `L` = Window (0, 5, 20, 50,
  200 ms); internal delay = `L + clamp(Delay, -L, +200 ms)`; Detect searches
  `[-L, +max(L, 20 ms)]`. One invariant behind all three: **Detect never proposes a delay the
  current Window cannot apply.** The positive side costs buffer, not latency, so it is not
  clamped to the Window; the negative side is exactly the latency the Window buys. Refines the
  sketch's "Delay is clamped to the Window at runtime", which read symmetrically would pin Delay
  to 0 at Window "0 (live)". Worst-case internal delay 400 ms, 192 kHz, stereo: 0.6 MB.
- 2026-11-01: **G1 - what the path does *not* have.** No nonlinearity and no feedback loop
  anywhere (delay, polarity, Hilbert, bell and Trim are all linear), so rule 3 (aliasing,
  oversampling, ADAA) and rule 4 (DC blocker, in-loop saturation) do not apply and the brief's
  `alias_floor_db` is `n/a` for a reason, not by omission. Rule 15 (mono bass) is met by
  construction: both channels get identical coefficients and no modulation, so a mono input stays
  mono - asserted as a test rather than assumed.
- 2026-11-01: **Rows to add to `dsp-selection.md`** (bob-skills, skills-bob; not editable from
  here). S.4: `| delay and polarity between two mics | GCC-PHAT over the search window,
  parabolic peak refinement, sign for polarity, peak-to-second-peak for confidence (A.x) | plain
  time-domain cross-correlation (smears on reverberant and tonal material, source-dependent
  threshold); per-band spectral alignment when only the timing may change |`. S.2:
  `| rotate the phase of one band only | quadrature mix of the band with its +90 deg Hilbert,
  plus a magnitude-compensating bell (E.x) | an all-pass cascade (its phase swing is a multiple
  of 180 deg and its DC phase is 0, so it cannot hold an arbitrary angle at the low end) |`.
</content>
</invoke>
