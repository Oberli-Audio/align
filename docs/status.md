# Status - Align 0.1.0 (2026-11-03)
Tier P, track E (effect): G3 18/19 with one open exception (Track settling), G5 closed (null, bank, golden); next the editor (plugin-ui-bob), then G6. Recipe D.8.1.

## Waiting for Björn
Newest first; one line each. Everything else keeps moving.
- 2026-11-03: **Track's speed, decide.** G1 says Track settles within 3 s of a 2 ms step; with the sketch's tau 1 s and a 1 s analysis frame it is 92 % there at 3 s and within 5 % at 3.5 s (`g3_metrics.py`). Keep tau 1 s and amend the criterion to 4 s (calmer), or shorten tau to about 0.7 s (meets 3 s, follows a moving player faster and wobbles more). Open exception below until then.
- 2026-11-03: **The factory bank is a proposal, listen to it.** Eight source pairs plus Init (`docs/presets.md`): Kick In vs Overheads, Snare vs Overheads, Room Mics Wide Window (50 ms), Bass DI vs Amp, Guitar DI vs Cab, Piano Close vs Room, Lead Vocal vs Room (the one Track preset), Live Stream Zero Latency (Window 0). Delay, Polarity and Rotate stay 0 in every preset: Detect measures them per session. Init is filed under Drums because the brief's category list has no neutral one. Names, Windows and Below starting points are yours to change.
- 2026-11-03: **Two fixes for `presetlint.py` in bob-skills** (sound-design-bob; never edited here). (1) `check_init` compares a choice parameter's normalised echo with its plain index (`want = p["fdefault"]` for choices), so Align's Init reads "window is 0.5, table default 2.0"; `PG.to_normalised` is already right for choices. (2) `render` passes `--notes/--gate`, which an effect harness ignores (contract: instruments only), so every effect preset is rendered from an impulse: max_click 0 dB and loudness under the gate. Proposal: for `--track effect`, a `--signal` (or `--in`/`--sidechain` files) and clicks judged against the input's own. Until then `tools/measure/bank_check.py` does the effect's version (CTest `bank_render`).
- 2026-11-03: **Two DSP defects found and fixed at G3** (docs/failures.md): Rotate/Below glided for seconds and depended on the buffer size; every switch's crossfade stalled short of its target in float32 (Polarity sat at gain -0.99998). Both were in the prototype too; G2's 16 checks pass again after the fix. Nothing to decide, but the G2 listening A/B should be regenerated before you listen (`python3 "sound design/prototype.py" --renders`).
- 2026-11-03: **This Mac's CMake finds Homebrew's Python 3.12, which has no numpy/scipy**, so the suite was not registered. Configured with `cmake --preset release -DPython3_EXECUTABLE=/usr/bin/python3` (the CLT 3.9 that has them). Either `pip3 install numpy scipy` into Homebrew's Python or keep the flag; a machine fact, so not in the repo.
- 2026-11-01: **Rotate is re-parameterised, confirm the words.** The structure stays the sketch's all-pass, but Rotate moves the *corner* (`f_c = Below / tan(Rotate/4)`) instead of a Q, because a second-order all-pass's phase swing is always 360 deg and only the corner can place a chosen angle at a chosen frequency. Rotate is then exactly "the phase shift at Below": 180 deg puts the corner on Below, as the sketch drew it. Two consequences for the words plugin-ui-bob owns: Below's tooltip "The frequency under which Rotate acts" is better read as "The frequency at which Rotate's angle is reached"; and Rotate turns the band *around* Below rather than everything below it (the phase is 0 at DC, -Rotate at Below, and back to 0 - as -360 deg - above roughly 10 x the corner). Rotate only ever makes the low end arrive *later*: a causal filter cannot advance it, so when the low end has to go the other way the pair is aligned from the other mic.
- 2026-11-01: **Delay clamp is asymmetric, confirm.** Internal delay = Window + clamp(Delay, -Window, +200 ms); the positive side is not clamped to the Window. A symmetric clamp would pin Delay to 0 at Window "0 (live)", which the sketch's own 2026-11-01 decision ("zero latency, positive delay only") forbids (G1 decision 6).
- 2026-11-01: **Two new rows for `dsp-selection.md` in bob-skills** (S.0: a family that is not in the tables is added afterwards). Text in Decisions below; never edited from this repo.
- 2026-11-01: **Test material.** The multi-mic drum loop, the DI/amp pair and the 1.2 s RT60 room pair live in OneDrive, not in git. The prototype and the suite use synthetic material (`sound design/material.py`, seeded); the brief's accuracy numbers on *real* material need those files once.
- 2026-11-01: **Listening checkpoint after G3** (init patch and the first presets, level-matched renders).

## Gates
| Gate | State | Evidence (command -> number, test name, log) |
|---|---|---|
| G0 | closed 2026-11-01 | `docs/brief.md` owner-confirmed, from `docs/sketch.md`; `parameters.csv` in the repo |
| G1 | closed 2026-11-01 | families chosen against the brief with `dsp-selection.md` S.2/S.4/S.5; three departures, each with the measurement that would reject it (Decisions) |
| G2 | closed 2026-11-01, re-run 2026-11-03 | `python3 "sound design/prototype.py" --all --kernel-search --seed 1` -> 16/16 pass after the two fixes (`sound design/g2.json`). Unchanged to the last digits: accuracy (drum loop 0.0049 ms worst over six rates, confidence 92.5 % worst; room pair 0.0083 ms; DI/amp 0.055 ms), fractional delay 0.00088 dB to 18 kHz, Rotate structure, nulls, latency, block sizes (-312 dBFS), comb notch. Moved: Rotate's switch-in overshoot 0.040 -> 0.072 dB (it now really glides in 20 ms; the click criterion, max_click within +1 dB of the sine's own -17.69 dB, holds at -17.74). **Listening checkpoint open** |
| G3 | 18/19, one open exception | `python3 tools/measure/g3_metrics.py --json build/g3.json` -> 18/19 within target (the table is the script's output; re-run on a quiet machine 2026-11-03, the same 18/19; Detect 77 ms; CPU below): latency = impulse = Window, 0 samples error at all five; null at neutral -156.5 dBFS; bypass null -156.5 dBFS; fractional delay 0.00066 dB (44.1 k) / 0.00023 dB (48 k) to 18 kHz; Rotate magnitude 7.1e-4 dB and phase at Below 0.093 deg worst of 20 settings; Detect drum loop 0.0046 ms, flipped, 92.9 % worst of 6 rates; Detect 90 ms press to result (M3 Pro); room pair 0.0086 ms; DI/amp 0.0545 ms (confidence 48 %, the readout will say low confidence); comb notch -39.5 -> -0.2 dB; Rotate suggestion +0.42 low-band correlation, other-mic said, delay-only silent; Delay sweep overshoot 0.0000 dB; switches max_click at the sine's own -17.69 dB; mono L == R exactly; 60 s silence clean, DC -300 dBFS; CPU x86_64 48 k/64 Track + 200 ms p99.9 0.60 %, max 0.82 % (2.77 % in the first run, taken on a battery at 3 %); **Track 2 ms step: within 5 % at 3.5 s (fail, exception)**. Earlier the same day: `ctest --preset fast` -> 9/9 (suite_fast 27 tests, harness_contract, parameter_table, bounce_null, preset_bank, the shared code's four), 51 s. `ctest --test-dir build -L render` -> suite_render 3 pass, goldens skipped (none yet), 25 s. The suite (`tools/tests/test_plugin.py`) asserts on the port: latency = impulse = Window at all five Windows; null at Delay 0 / Polarity off / Rotate 0 below -140 dBFS at every Window; bypass nulls against the compensated input; Window 0 has zero latency and no negative delay; fractional delay flat within 0.05 dB to 18 kHz at 44.1 and 48 k; Rotate magnitude within 0.05 dB and phase at Below within 1 deg at three settings; mono stays mono; Delay sweep overshoot <= 0.01 dB; Detect on the drum loop within 0.02 ms, flipped, > 80 % at all six rates; room pair within 0.1 ms; DI/amp within 0.1 ms; comb notch < -10 dB before Detect and > -1.5 dB after. **Next: `tools/measure/g3_metrics.py` to print the metric table's numbers (the tests assert thresholds, the table needs the values)**, Detect time, CPU on the x86_64 slice |
| G4 | rebuilt 2026-11-03 | `cmake --preset release && cmake --build --preset release` on the Mac (universal, LTO): green, no warnings in project code |
| G5 | closed 2026-11-03 | Null: `python3 tools/measure/g5_null.py --rates all` -> 36/36 within -100 dBFS (F.8: float with IIR state), worst peak -120.9 dBFS, latency equal in every case; six settings x six rates. Bank: `presetlint.py bank presets.csv --tier P --track effect --categories ...` OK (CTest `preset_bank`); `python3 tools/measure/bank_check.py --md docs/presets.md` -> 9 presets, 0 errors: Init = table, loudness farthest 0.022 LU from the median (+/-1 LU), true peak -9.23 dBTP, no click added (max_click -3.32 dB = the drum loop's own), state round trip bytewise and render-identical, p99.9 0.81 % worst (CTest `bank_render`). Golden: `tools/tests/golden/full-path` (x86_64, every stage engaged): same slice bit-identical, arm64 -145.1 dBFS peak against F.8's -100 (`Goldens.test_goldens_match`). Defining features by name: the readout (`test_readout_in_words_with_distance`), the Sum well's comb (`test_sum_comb_disappears_after_detect`), the well's sign (`inverted`; the signed curve itself reaches the editor with the Strip wiring) |
| G6 | - | `validate_plugin.py full`, `paramgen.py check --frozen`, `presetlint.py render --tier P`, hosts |
| G7 | - | bank and table final, documents current, release gate green, then ship-bob |

## Listening debt
- 2026-11-01: G2's whole prototype is measured but **not heard**. The A/B to listen to is
  `sound design/renders/g2_listen_ab_misaligned_then_aligned.wav` (the *sum* of the pair: four bars
  combed, half a second of silence, four bars aligned, level-matched - the processed track alone is
  inaudible by itself). Regenerate with `python3 "sound design/prototype.py" --renders`.
- 2026-11-03: the port has not been heard either; the Standalone and the VST3 are built
  (`build/Align_artefacts/Release/`), the editor is still the template stub.

## Open exceptions
- 2026-11-03: Track, 2 ms step, settles (within 5 %) at 3.5 s against G1's 3 s; `python3 tools/measure/g3_metrics.py` row "Track, 2 ms step". Owner decision pending (Waiting for Björn).

## Handoff
Task: build Align to Tier P from G1. Plan: 1. [x] G1 families and departures 2. [x] G2 numpy
prototype, 16 checks, renders 3. [x] G4 port, build green 4. [x] harness sidechain bus,
`--detect-at`, product metrics 5. [x] `tools/tests/test_plugin.py` 6. [x] G3 metric table
(`tools/measure/g3_metrics.py`; Track's exception open) 7. [x] G5 null vs the prototype 8. [x] presets (8 + Init,
the brief's categories), the bank's loudness, one golden 9. [ ] editor on the Strip frame (plugin-ui-bob) 10. [ ]
G6 validate 11. [ ] G7 documents.

**This session (Mac, 2026-11-03).** `toolchain.py check` OK. `Source/oberli/` refreshed from
plugin-template 0e7d4f4 with its own tool (`python3 tools/refresh_oberli.py`, sage #33B679): the
shared code, its tests (`oberli_loudness`, `oberli_shared`, `oberli_copy`), the snapshot target, the
bounce null test, Rubik and Nunito in `notices.toml`. The kit copies (`scripts/dsp-kit/`) refreshed
from bob-skills sound-design-bob 5.3.0 (harness-contract.md: the impulse is 0.5; paramgen.py: int
value strings; perf.py: idle on the cells' slice; test_template.py: the every-parameter state round
trip, p99.9 judged only on the budget machine). The harness took the template's generic fixes it
was missing (the integer `sample_rate` echo that `dspkit smoke` compares as text, `--block=0`, blocks
larger than announced, the ASan-aware malloc trap, `--non-realtime`, the tail's last sample) and
gained `product.params_plain`, the raw values the DSP read.

**Track** (later the same session) was scheduled in wall-clock time and confused the absolute lag
with its offset - the third defect, fixed with `test_track_follows_a_step_and_bounces_reproducibly`.
The harness's detect log now carries `elapsed_ms`.

**What G3 found.** Two defects in both the port and the prototype, now fixed with regression tests
shown failing first (docs/failures.md). And three things in the measuring, not the DSP: Detect's
`delay_ms` is the Delay to apply (the negative of the pair's truth, as the prototype); the
prototype's fast direct-form Rotate is not the port's structure while the coefficient glides
(G5 now runs the TPT form: -78 -> -126 dBFS); and on arm64 JUCE's 0..1 -> plain conversion is one
FMA, so Delay 1.75 ms arrives as 1.7499924 ms (G5 now feeds the prototype the plain values the port
read). The prototype's delay crossfade also started one step late and ended one short (a 1/L jump,
-64 dBFS against the port); it now ramps as `SincDelay.h` does.

**The editor.** The template's editor is now the Strip frame (`oberli::ui::StripEditor`); Align's is
still the slider stub. Wiring it is plugin-ui-bob's work (G2 of the UI gates): the correlation well
needs the signed GCC curve published by the detector, which `Detector::Result` does not carry yet
(it has `peak` as a magnitude and `inverted` for the sign).

Working tree: clean after this checkpoint's commit. Tests: `ctest --preset fast` 9/9 in 43 s; `ctest --test-dir build -L render` 2/2 (suite_render with the golden, bank_render).
Open questions for the owner: the "Waiting for Björn" lines above; two are decisions (Rotate's
re-parameterisation, the asymmetric Delay clamp).
Next: the editor on the Strip frame (plugin-ui-bob: its gates, the parameter table's naming columns, the
correlation well and Sum well, the readout, Apply for Rotate); the detector has to publish its signed curve first.

## Decisions
- 2026-11-03: **Rotate and Below run on a 0.16 ms control grid** fixed to the stream, not once per
  block (rule 2's "sub-blocks of <= 32 samples": 7 at 44.1 k, 31 at 192 k; rule 12: set in seconds).
  A block whose smoothers sit on their targets runs in one piece, so the steady state costs nothing.
- 2026-11-03: **One crossfade law for every switch**: `LinearFade` (`Source/dsp/Fade.h`), the
  closed form `start + step * done`, landing exactly; a target change mid-fade restarts the full
  length from the current position. Listen's three fades stay amplitude-complementary by
  construction (their steps sum to zero).
- 2026-11-03: **G5 compares DSP, not the parameter conversion.** The prototype gets the plain values
  the port read (`product.params_plain`). The conversion's own error (7.6e-6 ms on Delay at 1.75 ms
  on arm64) is far below the 0.01 ms the readout shows and is not a defect.
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
