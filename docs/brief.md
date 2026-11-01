# Sonic brief (owner-confirmed <date>; amend below, never edit the YAML)

```yaml
name:
track:           # instrument | effect | control | analysis  -- which playbook file leads
stages:          # the signal-flow stages it owns (F.0): control, generation, processing,
                 # mix, output, analysis - each brings its contract and tests
type:            # synth | acoustic-emulation | dynamics | eq | creative-fx | utility | meter | midi-fx
musical_role:    # rhythm | bass | harmonic-bed | melodic | texture | effect  -- briefs I.7
tier:            # S (sketch) | P (product) | F (flagship)  -- tiers.md, F.0.1
one_sentence:
references:      # 2-3 named products and how this differs
must_do:
defining_features:  # the audible features that make it *this* product; each one
                    # gets a presence test (rule 13), e.g. "Expanse carries a +1 oct shimmer"
out_of_scope:
core_controls:   # 3-5, with what each does sonically
signal_flow:     # ASCII block diagram
cpu_budget:      # rule 20, per instance: { p999_pct: 25, max_pct: 50, idle_pct: 2,
                 #   at: 48k/64 (F adds 44.1k/32), slice: x86_64-rosetta, preset: heaviest }
cpu_reference_machine:  # the concrete machine the budget is written for (F.14.4)
instances_expected:     # realistic count per project / live rig
latency_budget:  # samples, and whether latency is acceptable at all
sample_rates:    [44100, 48000, 88200, 96000, 176400, 192000]
channels:        # mono | stereo | mono-to-stereo
register:        # instruments: the lowest and highest key it plays, e.g. C0-C7 - set by
                 # listening at P and F (I.2.3), silent outside it; re-asked after any
                 # sound-design pass that moves the bass or the top
register_intent: # per register, what the sound should do (I.2, F.4), e.g.
                 #   below C3: tight, mono, dark - foundation, no phasing
                 #   C3-C5: the voiced sound
                 #   above C5: opens but never shrill
presets:         # F.14.3
  bank_size:          # P: 12-20 instrument / 8-12 effect; F: 30-60
  categories:         # the fixed list, e.g. [Bed, Motion, Dark, Bright, Keys-like, FX]
  reference_chord:    # default C3-E3-G3-C4, velocity 100, 4 s hold, 4 s tail
  loudness_window:    # default short-term max over the hold; pads: from end of attack to note-off
  edge_presets:       # the 3-4 the translation battery runs on (widest, darkest, most reverb, loudest bass)
  naming:             # ships in English; voice of the product
mix_context:     # what it plays with, and the band it must leave free, e.g.
                 #   "under acoustic guitar, piano, group vocals: leave 1-4 kHz,
                 #    keep 200-500 Hz no hotter than the voiced default"
quality_targets: # every target is a pair: the threshold AND the method that
                 # measures it on this instrument. A target with no working method
                 # is found out at G3, which is too late.
  alias_floor_db:     { target: , method: }   # ASR/NMR only for harmonic output; else B.5 rate comparison
  thd_n_db:           { target: , method: }
  response_error_db:  { target: , method: }
  loudness:           { target: , method: }   # e.g. presets -18 LUFS +/-1 LU, F.13.9 protocol
  keyboard_span_lu:   { target: , method: }   # e.g. < 6 LU per layer over the register, F.13.10
  low_register:       { target: , method: }   # e.g. roughness at C2 no worse than 3x C4, register battery 1.4
  other:
open_questions:
```

## Amendments
- <date>: <what changed, why, which gates re-open>
