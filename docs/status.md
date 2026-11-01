# Status - Align 0.1.0 (2026-11-01)
Tier P, track E (effect), at gate G2 closed, G3 next. Recipe D.8.1.

## Waiting for Björn
Newest first; one line each. Everything else keeps moving.
- 2026-11-01: **Rotate is re-parameterised, confirm the words.** The structure stays the sketch's all-pass, but Rotate moves the *corner* (`f_c = Below / tan(Rotate/4)`) instead of a Q, because a second-order all-pass's phase swing is always 360 deg and only the corner can place a chosen angle at a chosen frequency. Rotate is then exactly "the phase shift at Below": 180 deg puts the corner on Below, as the sketch drew it. Two consequences for the words plugin-ui-bob owns: Below's tooltip "The frequency under which Rotate acts" is better read as "The frequency at which Rotate's angle is reached"; and Rotate turns the band *around* Below rather than everything below it (the phase is 0 at DC, -Rotate at Below, and back to 0 - as -360 deg - above roughly 10 x the corner). Rotate only ever makes the low end arrive *later*: a causal filter cannot advance it, so when the low end has to go the other way the pair is aligned from the other mic.
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
| G2 | closed 2026-11-01 | numpy prototype in the port's structure (`sound design/`, README there says why not Faust); `python3 "sound design/prototype.py" --all --kernel-search --seed 1` -> 16/16 checks pass, `sound design/g2.json`. Accuracy: drum loop 0.0049 ms worst over all six rates (target 0.02), confidence 92.5 % worst (target > 80); room pair 1.2 s RT60 0.0083 ms (target 0.1); bass DI/amp 0.055 ms (reverberant tolerance, see the check). Fractional delay 0.00023 dB to 18 kHz at 48 k, 0.00088 dB at 44.1 k (target 0.05), delay error 4.9e-6 ms. Rotate: magnitude 8.9e-14 dB, measured phase vs the analytic curve 1.8e-12 deg, TPT vs direct form -308 dBFS. Null at Delay 0 / Polarity off / Rotate 0: bit-identical at Window 0 **and** after compensating Window 20 ms. Reported latency = measured, 0 samples error, every Window. Two runs from reset bit-identical. Block size changes nothing (-300 dBFS) over 6 rates x {0,1,13,32,64,512,4096,9000}. Track sweep overshoot 0.000000 dB (target 0.01). Comb notch at 215.8 Hz: -41.5 dB -> -0.8 dB. **Listening checkpoint open** (Waiting for Björn) |
| G3 | open | next: the harness's sidechain bus, `tools/measure/` on `dspkit.render()`, the metric table |
| G4 | - | clean Release build with the ported DSP; `cmake --build --preset release` |
| G5 | - | null vs the prototype; bank loudness-matched (`presetlint.py`) |
| G6 | - | `validate_plugin.py full`, `paramgen.py check --frozen`, `presetlint.py render --tier P`, hosts |
| G7 | - | bank and table final, documents current, release gate green, then ship-bob |

## Listening debt
- 2026-11-01: G2's whole prototype is measured but **not heard**. The A/B to listen to is
  `sound design/renders/g2_listen_ab_misaligned_then_aligned.wav` (the *sum* of the pair: four bars
  combed, half a second of silence, four bars aligned, level-matched - the processed track alone is
  inaudible by itself). Regenerate with `python3 "sound design/prototype.py" --renders`.

## Open exceptions
- none yet.

## Handoff
Task: build Align to Tier P from G1. Plan: 1. [x] G1 families and departures 2. [x] G2 numpy
prototype, 16 checks, renders 3. [x] G4 port, build green 4. [x] harness
sidechain bus, `--detect-at`, product metrics 5. [ ] `tools/tests/test_plugin.py` (next) 6. [ ] G3
measurement scripts and the metric table 7. [ ] G5 null vs the prototype 8. [ ] G6 validate (the
part that runs off a Mac) 9. [ ] G7 documents.

**Where the port stands.** `Source/dsp/` holds the five modules, each mirroring its prototype
module: `SincDelay.h`, `Rotate.h`, `AnalysisRing.h` (the decimating lock-free rings),
`Detector.h` (GCC-PHAT and the Rotate suggestion), `AlignEngine.h` (the audio path, the latency
and clamp rules, and a latency-compensated click-free bypass, rule 7). `PluginProcessor` is
rewritten around them: the stereo sidechain aux bus, cached parameter atomics, the detect worker
thread, the `AsyncUpdater` that writes delay and polarity as one host edit, `applyRotateSuggestion`
for the Apply button, Track mode, and the correlation meter.

Build: **green**, warning-free. `cmake --build --preset release -j4` builds `Align_VST3`,
`Align_Standalone` and `AlignHarness`. The harness runs the real processor with a sidechain:
`AlignHarness --signal=impulse --sidechain-signal=noise:pink:-20 --seconds=0.5 --block=64`
reports latency 960 samples at the default Window, peak 0.0 dBFS through the impulse, no NaN, and
`product.sidechain_connected: true`.

Two things had to be fixed to get there, both worth knowing: `juce_add_plugin` puts the
`JucePlugin_*` definitions on the plugin target only, and this harness compiles the product
sources itself, so the two the sources use are repeated in the harness target from the same single
sources CMake already has; and the eight deliberate exact float comparisons in `Source/dsp/` now
say so with `juce::exactlyEqual`, which is what `-Wfloat-equal` is asking for.

Harness extensions, documented because the contract (v3) has neither: `--sidechain=<file.wav>` and
`--sidechain-signal=<spec>` fill the reference bus; `--detect-at=<t>` presses Detect the way a host
would, waits for the worker and calls `applyPendingDetect()` directly, because a console app runs
no message loop; `--detect-timeout=<ms>` bounds that wait. The `product` object carries a `detects`
log (the result, the readout in words, the suggestion), plus the correlation, the Track offset and
the analysis rate.

Nothing in the port has been **measured** yet - no G3 battery, no G5 null. The G2 numbers above
are the **prototype's**, not the port's.

Still to write: `tools/tests/test_plugin.py` from the kit's `test_template.py`, the `tools/measure/`
scripts that fill the G3 metric table, and the G5 null against the prototype's seeded renders.

Working tree: clean. Tests: not registered yet.
Open questions for the owner: the "Waiting for Björn" lines above; two of them are decisions
(Rotate's re-parameterisation, the asymmetric Delay clamp).
Next command: `ctest --preset fast` (once `tools/tests/test_plugin.py` exists)

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
- 2026-11-01: **G1 family - Rotate.** Two cascaded first-order TPT all-passes at the same corner
  `f_c = Below / tan(Rotate / 4)`, bypassed below the reachable angle with a 15 ms
  amplitude-complementary crossfade. Phase `-4 atan(f / f_c)`: 0 at DC, exactly `-Rotate` at
  Below, `-360 deg` (indistinguishable from 0 for a steady tone) above about 10 x `f_c`;
  magnitude exactly 1 at every setting; no latency. At Rotate 180 the corner lands on Below,
  which is the sketch's drawing. **Keeps the sketch's structure, changes its parameterisation**:
  the sketch sets the angle with a Q, but a second-order all-pass's total phase swing is 360 deg
  whatever the Q - Q only sets the slope - so the angle at a chosen frequency can only be placed
  by moving the corner. Two real poles (Q = 0.5) are also unconditionally well behaved under
  coefficient modulation, which a high-Q pair is not. **Three families were rejected on the way,
  recorded because each looks obvious:** (i) a *dry/wet blend* with an all-pass - not flat, it
  combs; (ii) a *quadrature rotation of the low band* (`x + (cos th - 1) L + sin th * Hilbert(L)`),
  which gives exactly "Rotate at the bottom, nothing at the top" but is unrealisable here: a
  single real IIR filter cannot hold +90 deg over a band (an all-pass's phase only decreases),
  the IIR allpass-*pair* that can leaves its own large phase on the dry path, and an FIR Hilbert
  accurate to 0.1 x Below needs seconds of latency; (iii) the same quadrature rotation with a
  magnitude-compensating bell - self-defeating, because flattening the magnitude of a
  non-monotone phase response removes, by the Bode relation, the phase it was built for.
  Underneath all three: a magnitude-flat filter's phase swing is a multiple of 180 deg and a real
  causal filter's phase at DC is 0 or 180 deg, so "an arbitrary angle held at the low end" does
  not exist - only "an angle reached at a chosen frequency" does, and that is what Rotate now is.
  **Rejected if** the magnitude moves more than 0.05 dB from 20 Hz to 20 kHz at any Rotate, the
  phase at Below is more than 1 deg from the set angle, the null at Rotate 0 is above -120 dBFS,
  or the bypass crossfade clicks.
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
  `| phase rotation between two mics | an even cascade of first-order TPT all-passes, the corner
  solved for the wanted angle at the wanted frequency, bypassed at zero (E.x) | an odd cascade
  (it leaves the top polarity-inverted); a dry/wet blend with an all-pass (it combs); a
  quadrature low-band rotation (no real IIR filter holds +90 deg over a band, and the FIR that
  does costs seconds of latency at these frequencies) |`.
</content>
</invoke>
- 2026-11-01: **G2 - the three constants the measurements set, not taste.** The sinc kernel is 32
  taps, Kaiser beta 9.0, cutoff 1.0 at Nyquist, from `--kernel-search` over 192 designs at 44.1 and
  48 kHz: 107 cleared the brief's 0.05 dB and this is the shortest. Cutoff 1.0 also makes the
  fractional-offset-zero kernel exactly a delta, so a whole-sample delay is a wire - which is what
  the null test at every Window needs, and the read now takes that path explicitly rather than
  relying on the window's shape. The whitening exponent is 1.0 (full PHAT) from `--check whiten`
  over nine values and all three pairs: it was best on every axis, and **below 0.7 the bass DI/amp
  pair locks onto the wrong period of the note and misses by 14 ms** - the failure the G1 trade-off
  paragraph predicted, now measured. `ROTATE_OTHER_MIC_MIN_GAIN` is 0.15 against
  `ROTATE_MIN_GAIN` 0.05, because telling someone to re-route their session is a bigger ask than
  offering them an Apply button.
- 2026-11-01: **G2 - Rotate has one usable direction, and now says so.** The stage can make this
  track's low end later, never earlier; the other direction needs either a negative group delay or
  a four-section all-pass with its corner below the band, whose group delay down there is 75 ms.
  Detect therefore scans both directions and, when only the unreachable one would help by at least
  0.15, says "Rotate cannot help here: this track's low end is late. Put Align on the reference mic
  instead" rather than "No rotation needed". Measured: a pair rotated 70 deg below 110 Hz in the
  reachable direction is recovered to low-band correlation 1.00 from 0.56; the same pair rotated
  the other way gets the other-mic message; an ordinary kick-in/overheads pair (other-mic gain
  0.11) stays silent.
- 2026-11-01: **G2 - the suggestion's (Rotate, Below) is deliberately not unique.** The filter
  depends only on the corner `Below / tan(Rotate/4)`, so 52 deg below 80 Hz and 70 deg below 110 Hz
  are the same filter to within a hertz. Tests assert the correlation reached, never the pair
  returned; a test that pinned the numbers would fail on a correct answer.
- 2026-11-01: **G2 - two findings in the test rig, not the DSP, worth keeping.** The first room
  pair was two *independent* room impulse responses, which made the brief's 0.1 ms target
  unreachable in principle: with independent tails the only correlated part is the direct sound. A
  real pair is two positions in one room, so the tail is now modelled with the frequency-dependent
  coherence a diffuse field has (0.7 below 300 Hz, 0.15 above). And the comb-notch check used the
  tilted pair, whose two mics do not carry the same level at 216 Hz, so the comb was only 3 dB
  deep; the presence test now uses a level-matched pair, where the notch is 41.5 dB and its
  disappearance is unambiguous.
- 2026-11-01: **Accepted `paramgen` warning.** "delay: time parameter with a linear taper (no
  centre); F.14.2 default tapers say log". Intended: Delay is a signed time offset and a log taper
  has no meaning across zero. Recorded in the CSV's `notes`.
