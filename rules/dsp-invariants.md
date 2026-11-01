---
paths:
  - "Source/**/*.{cpp,h,hpp}"
  - "**/*.dsp"
  - "tests/**/*.{cpp,h}"
---

# DSP invariants (Oberli Audio)

These load only when you touch DSP or Faust source. This list mirrors section 3 of
`references/dsp-playbook-core.md` in the sound-design-bob skill (playbook v4.0), which is
the source of truth; `scripts/tools/playbook_lint.py` there fails if the two drift. Tags:
[all] every plugin, [I] instruments, [E] effects, [C] control, [A] analysis. The old rule
numbers (1-37) are in brackets; the map is in the core card. Depth: the skill's
`references/` (grep the heading, never read a file whole) and, for how an algorithm works,
the dsp-reference-bob skill.

## Never ship code that breaks these

1. [all] **Real-time (was 1, 2, 35).** No allocation, locking or I/O in `processBlock`; `ScopedNoDenormals` at its top. Verified by tools: RTSan on the Mac harness where the project has that build, else the malloc trap; the trap on Windows; both at F (D.1.6).
2. [all] **Smoothing and control rate (was 3, 18).** Every parameter smoothed; switches crossfaded over 10-20 ms; control signals driving gain, cutoff or pitch interpolated to sample rate or run in sub-blocks of <= 32 samples.
3. [all] **Aliasing and nonlinearity (was 4, 5, 17, 33).** Every nonlinearity oversampled, ADAA'd, or documented as deliberately aliasing. ADAA has the ill-conditioned-difference fallback (~1e-5 double, ~1e-3 float), never sits in a feedback loop without the stateful formulation, and its half-sample delay is compensated. [E] Every nonlinear model states its operating point and antialiasing and is measured at its worst case, high frequency at maximum drive (dsp-reference-bob E.7).
4. [all] **Feedback loops (was 6, 7, 16, 19).** DC blocker after asymmetric nonlinearities and inside every long loop. [E] A loop with a user-facing gain has a soft saturator inside; every filter in a loop has peak magnitude <= 1, bounded at every coefficient update and checked numerically; non-LTI loops (anything with a pitch shifter) pass the empirical decay-slope test on three signals, never a feedback-number argument (dsp-reference-bob F.16.1, F.16.4).
5. [all] **Level (was 8, 27).** Wet/dry mixes equal-power; character controls level-compensated; a band split recombined after processing one part is power-complementary: first-order subtractive, or verified at 0 and 100 % (F.9).
6. [all] **Structures (was 9, 10).** Modulated filters TPT/ZDF, static EQ matched biquads, not cookbook BLT; modulated delays Lagrange/Hermite, allpass interpolation only for static tuning.
7. [all] **Latency and bypass (was 11, 32).** Latency reported *and* verified by impulse measurement in a test. [E] Bypass is latency-compensated, click-free and nulls against the input; the dry path of every wet/dry mix is delay-compensated (E.0).
8. [all] **Reproducibility (was 12, 23).** `reset()` clears all state including delay memory; every random source draws from an RNG the harness can seed; tests always seed: two runs from reset are bit-identical (F.10, F.13.9).
9. [E] **GUI curves (was 13)** come from the same coefficients as the audio, tested against a sweep.
10. [all] **Code hygiene (was 14, 15).** Non-ASCII text uses `juce::String`; split hex escapes; MSVC `/utf-8`; preset files named by ASCII slug. Never commit throwaway test or preview targets.
11. [I] **Inharmonicity (was 20).** A modelled inharmonic instrument ships with a stretch tuning table from its own B curve (dsp-reference-bob C.5.1).
12. [all] **Seconds (was 21).** Every delay, window, grain, Haas offset, smoothing time and envelope stage is specified in seconds and converted in `prepare`, in Faust too (`ma.SR`). Never a constant in samples (dsp-reference-bob F.2, Law 8).
13. [all] **Presence and proving (was 22, 28).** Every defining feature in the brief has an automated presence test. The harness echoes the state it rendered and every script asserts on it; every new test is shown failing on the build with the defect (F.13.11, D.3.8).
14. [I] **Register, chords, pedal (was 24, 25).** An instrument is verified across its register and in chords, not at one note; at P and F the register is set by listening, stated in the brief, silent outside it (I.2.3). A keyboard instrument handles the sustain pedal (CC64) with a pedalled-note stealing tier (dsp-reference-bob I.7.3, C.0).
15. [I, E] **Mono bass (was 26).** Below ~120-150 Hz the output is mono and unmodulated - no spread, chorus, ensemble or reverb there - unless a measured exception is recorded (I.2).
16. [C] **Control timing and mappings (was 29, 30).** Every time-critical event is applied at its sample offset or the quantisation is documented and measured; every mapping (velocity, bend, CC, pressure) is stated, sensible at both ends, tested with scripted MIDI; every note-on gets a note-off on stop, bypass, preset change and deactivation (C.0, C.8).
17. [A] **Standard meters (was 31).** A meter or detector that names a standard follows it exactly and passes its test signals (EBU Tech 3341/3342, BS.1770-5 true peak) at every supported rate (A.0, A.7).
18. [all] **Translation (was 34).** The translation battery before G7: light at P (mono, phone speaker, level match), full at F (codec round trip, mix context) (F.7).
19. [all] **Frozen identity (was 36).** Parameter IDs, plugin codes and the state format are frozen at first release; state carries a version; a state file from every previous release loads in a test (D.5).
20. [all] **CPU (was 37).** CPU per instance: p99.9 < 25 % and recurring max < 50 % of the deadline at 48 k/64 on the slice the host runs, three runs; `over_deadline` is reported, never judged (an offline normal-priority harness is preempted now and then); the friend playing the heaviest preset at 64 samples is the dropout test; never an average (D.2). Tier F adds 44.1 k/32, both slices and the baseline (D.2.1).

## Project conventions

- Module interface is always `prepare / reset / setParams / process /
  getLatencySamples`. `prepare` may allocate; `reset` and `process` may not.
- Performance gestures (wheels, pedals) are atomics, not host-automatable parameters.
- State crosses threads only by the D.1.4 patterns: atomics for scalars, SPSC FIFOs for
  events, build-off-thread + pointer swap + off-thread reclamation for large objects.
- Faust prototype first, then hand-port the structure, never `faust2juce` output; the
  prototype uses the structure the port must use or the G5 null test cannot close.
- Every DSP defect fixed gets a regression test named after it and a row in the product's
  `docs/failures.md`.
- Character macros map so that the default position reproduces the validated prototype
  sound exactly; a macro mapping changes only with a re-run null test.

## If asked why something sounds wrong

Level-match first, then the seven checks of the core card's section 5 in order, naming
the measurement before theorising; a named symptom goes to the failure libraries (the
sound-design-bob skill, Diagnose mode).
