# Sonic brief (owner-confirmed 2026-11-01 from the decided Tier S sketch, docs/sketch.md; amend below, never edit the YAML)

```yaml
name: Align
track: effect
stages: [processing, analysis, output]
type: utility
musical_role: effect
tier: P
one_sentence: Lines up a mic against a reference mic in one press (delay, polarity, confidence), proposes a low-end phase rotation, and shows the comb filtering disappear.
references:
  - Sound Radix Auto-Align 2: static and dynamic alignment; Align is free and shows the correlation peak and distance
  - Melda MAutoAlign: similar measurement; Align proposes Rotate instead of applying it
  - Waves InPhase: manual with correlation meter; Align measures for you
must_do:
  - Find delay within 0.02 ms and the right polarity on a 4-bar drum loop, confidence > 80 %
  - Negative delay via reported latency (Window); 0 (live) window reports zero latency
  - Detect proposes Rotate and Below with the measured low-band gain; only Apply sets them
  - Null at Delay 0, Polarity off, Rotate 0 after host compensation
defining_features:
  - GCC-PHAT correlation well that keeps the sign (a downward peak shows the flip)
  - Sum well where the comb notches visibly disappear
  - Readout in words with distance ("Peak +2.31 ms · 79 cm · polarity flipped · confidence 94 %")
out_of_scope: [spectral per-band alignment, time-stretching, automatic Rotate without Apply, Group alignment (Tier F)]
core_controls:
  - Delay: moves this track against the reference
  - Polarity: flips the signal
  - Window: search range and reported latency
  - Detect: measures and applies delay and polarity, proposes Rotate
  - Rotate: low-end all-pass where no single delay fits
signal_flow: |
  sidechain (reference) -> 4 s ring --+
  in -> 4 s ring ---------------------+-> Detect (background): GCC-PHAT -> delay, polarity, confidence, Rotate suggestion
  in -> polarity -> fractional delay (Window + Delay) -> all-pass (Rotate, Below) -> Trim -> out
cpu_budget: { p999_pct: 25, max_pct: 50, idle_pct: 2, at: 48k/64, slice: x86_64-rosetta, preset: Track mode with 200 ms window }
cpu_reference_machine: Apple M3 Pro (Björn's Mac)
instances_expected: 4-8 per project (kit mics, DI and amp, piano pair), 1-2 in the live-stream rig
latency_budget: equals the Window (0, 5, 20, 50 or 200 ms), reported; Delay never changes it
sample_rates: [44100, 48000, 88200, 96000, 176400, 192000]
channels: stereo with a stereo sidechain input
register: n/a (effect)
register_intent: n/a
presets:
  bank_size: 8
  categories: [Drums, Guitar and Bass, Keys, Vocals, Live]
  reference_chord: n/a; test material is a multi-mic drum loop, a DI/amp pair and a room pair with 1.2 s RT60
  loudness_window: n/a
  edge_presets: [Room Mics Wide Window, Live Stream Zero Latency, Kick In vs Overheads]
  naming: English, by source pair ("Kick In vs Overheads", "Bass DI vs Amp")
mix_context: on the spot mic, reference mic in the sidechain; changes timing and low-end phase only
quality_targets:
  alias_floor_db:     { target: n/a, method: n/a }
  thd_n_db:           { target: null at neutral settings, method: harness null after latency compensation }
  response_error_db:  { target: "fractional delay flat within 0.05 dB to 18 kHz", method: impulse through 0.37 ms delay, FFT }
  loudness:           { target: n/a, method: n/a }
  keyboard_span_lu:   { target: n/a, method: n/a }
  low_register:       { target: "Rotate suggestion raises low-band correlation by >= 0.05 or says none needed", method: kick-in/overheads pair test }
  other:
    - "accuracy: 2.317 ms inverted found within 0.02 ms on the drum loop; within 0.1 ms on the reverberant pair"
    - "latency: reported equals measured (Plugalyzer) for each Window"
    - "click: Track sweeping 2 ms over 1 s on a 1 kHz sine, no sample above peak + 0.01 dB"
    - "Detect under 200 ms on the reference machine"
open_questions: []
```

## Amendments
- 2026-11-01: Owner decisions confirmed with the brief: Window includes 0 (live) with zero latency and positive delay only; Group alignment is Tier F, P ships sidechain only; Detect proposes Rotate and Below, Apply accepts. LookAndFeel and meters come from the shared Source/oberli/ code (bob-skills).
- 2026-11-01 (G1, pending owner confirmation - see docs/status.md "Waiting for Björn"): Rotate
  keeps the sketch's all-pass but is parameterised by its corner, `f_c = Below / tan(Rotate/4)`,
  so Rotate is exactly the phase shift at Below (180 deg puts the corner on Below). Magnitude is
  exactly flat and the stage adds no latency; the angle is reached *at* Below rather than held
  below it, and the low end can only be moved later, never earlier. Delay is clamped to
  [-Window, +200 ms]: the negative side is the latency the Window buys, the positive side costs
  buffer only. Detect searches [-Window, +max(Window, 20 ms)], so it never proposes a delay the
  current Window cannot apply.
