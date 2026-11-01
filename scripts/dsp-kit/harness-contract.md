# The offline harness contract

Every Oberli Audio plugin has an offline renderer: a CLI target that links the real
plugin sources, renders without a host, audio device or editor, and prints one JSON
object. This file is the contract it implements, so that `dspkit.render()`, the test
scaffold (`test_template.py`) and every measurement script work on any product without
change. Horizon Pad's `HorizonPadSoundTool` is the reference implementation (F.13.2);
where it differs from this contract, the contract wins for new products.

## Flags

| Flag | Meaning | Default |
|---|---|---|
| `--seed=<int>` | Seeds every random source (rule 8). Two runs with the same seed from reset are bit-identical | product-defined, but fixed |
| `--sample-rate=<Hz>` | `prepareToPlay` rate | 48000 |
| `--block=<n>` | Block size; `--block=random:<seed>` varies it per block **from 0** to `--max-block` (D.5.1; a zero-length block must be legal) | 512 |
| `--max-block=<n>` | Size announced to `prepareToPlay`, to test blocks larger than announced | = `--block` |
| `--seconds=<s>` | Render length | product-defined |
| `--preset=<name>` | Load a factory preset | none |
| `--param=<id>=<value>` | Set a parameter by **ID**, normalised 0-1 unless the product documents plain units; **repeatable**, applied in order | - |
| `--automate=<id>:<t0>=<v0>,<t1>=<v1>,...` | Linear parameter ramp over time, applied at the plugin's real automation granularity (once per block for JUCE); repeatable | - |
| `--bend=<t>:<v>[,...]` / `--mod=<t>:<v>[,...]` | Instruments: pitch wheel (-1..+1, sent as 14-bit MIDI) and mod wheel (0..1, CC1) at t seconds, through the real MIDI path (C.8) | - |
| `--notes=<n>[,<n>...]` / `--midi=<file.mid>` | Instruments: a chord held from t = 0, or a MIDI file | - |
| `--gate=<s>` | Instruments: note-off for `--notes` at t seconds; the rest of the render is the tail and then silence (silence test, idle CPU, tail check) | held to the end |
| `--reprepare-at=<t>:<rate>/<block>` | Call `prepareToPlay` again mid-render with the new rate and block, without `releaseResources` (pluginval's "non-releasing" case; D.5.1); repeatable | - |
| `--in=<file.wav>` / `--signal=<name>` | Effects: input file, or a built-in test signal (`impulse`, `logsweep`, `sine:<Hz>:<dBFS>`, `noise:pink:<dBFS>`, `silence`) | - |
| `--out=<file.wav>` | Write the output (float32 WAV) | no file |
| `--state-in=<file>` / `--state-out=<file>` | Load / save plugin state (D.5.3 golden state tests). `--state-in` accepts **arbitrary bytes**: a truncated, flipped, empty or foreign blob is refused with a message and a non-zero exit, or loaded as far as understood; it never crashes and the plugin keeps processing | - |
| `--profile` | Time every `processBlock` **only** (the timer brackets the call, not MIDI building, WAV writing or metrics; normal thread - D.2.1 says why not a real-time one); add `profile` to the JSON | off |
| `--preset-at=<t>:<slug>` | Load a factory preset at t seconds during the render (preset-change spike, D.2.1); repeatable | - |
| `--warmup=<n>` | Blocks excluded from the profile distribution; the first block is still reported as `first_block_pct` | 0 |
| `--solo=<part>` | Product-specific isolation (a layer, a band, a stage) | - |
| `--list-params` | `[{"id", "default" (normalised), "steps", "automatable"}]`, in table order; exit | - |
| `--list-presets` | `[{"slug", "name", "category"}]`, in bank order, `init` first (F.14.3, `presets.csv`); exit | - |

Order of application is fixed and documented: preset, then solo, then params, then
automation. Each overrides the previous.

## Output: one JSON object on stdout

```jsonc
{
  "contract": 3,                     // v3 (2026-10-19): --gate, --reprepare-at, --state-in takes any bytes, random blocks from 0,
                                     //    list formats, max_click_db defined; v2: build.arch, first_block_pct, warmup_blocks, --preset-at, --warmup
  "applied": {                       // rule 13: what was ACTUALLY rendered
    "seed": 1, "sample_rate": 48000, "block": 64, "max_block": 64, "seconds": 4.0,
    "preset": "Lagerfeuer", "solo": null,
    "params": { "rootVol": 0.72, "reverb": 0.5 },   // every parameter, after all overrides
    "notes": [60, 64, 67], "gate": 4.0, "latency_samples": 0, "tail_seconds": 6.2,   // tail: time to -90 dBFS (D.2.5)
    "build": { "commit": "05c3f44", "config": "Release", "arch": "x86_64" }   // the slice that rendered
  },
  "levels":   { "peak_dbfs": -6.1, "rms_dbfs": -19.4, "true_peak_dbtp": -5.8, "dc_dbfs": -112.0 },
  "health":   { "nan": 0, "inf": 0, "clipped_samples": 0, "max_click_db": -71.2 },   // max_click_db: dspkit.max_click_db, see below
  "loudness": { "integrated_lufs": -18.2, "momentary_max_lufs": -15.9 },
  "profile":  { "deadline_ms": 1.333, "p50_pct": 4.1, "p99_pct": 9.8, "p999_pct": 12.0, "max_pct": 21.0,
                "worst_block_at_s": 3.2, "over_deadline": 0, "blocks": 3000,
                "first_block_pct": 31.0, "warmup_blocks": 200 },   // blocks == blocks rendered minus warmup
  "product":  { }                    // product-specific metrics (envelope, spectrum, layers...)
}
```

- `applied.params` lists **every** parameter after all overrides - a dropped or
  misspelled flag shows up as a value that is not the one requested. Unknown parameter
  IDs are an error, not a warning.
- Exit code: 0 on success; 2 on bad arguments or an unknown ID; 3 if any NaN/Inf was
  produced (the JSON is still printed).
- Nothing else on stdout. Diagnostics go to stderr.
- `contract` is this document's version; bump it when a field changes meaning.

## Build rules

- A separate CMake target, never part of the shipped plugin (rule 10 - committed, not
  throwaway).
- Builds in the RTSan configuration as well (D.1.6): `-fsanitize=realtime`, with the
  plugin's process path marked `[[clang::nonblocking]]`.
- Instantiates the `AudioProcessor` directly; calls `prepareToPlay`, `processBlock`,
  `releaseResources`, state get/set exactly as a host would, including the lifecycle
  edge cases the tests ask for (D.5.1).

## Definitions the scripts rely on

- `max_click_db`: 20 log10 of the largest sample-to-sample step divided by the render's
  peak, over all channels (`dspkit.max_click_db`). Absolute, so it compares across presets;
  smooth material at 48 kHz reads below -20 dB, a discontinuity between -6 and +6 dB.
  `presetlint.py` fails a preset above -6 dB by default.
- `profile`: the timer brackets `processBlock` only, never MIDI building, file writing or
  metrics; `blocks` equals the blocks rendered minus `warmup_blocks`; `first_block_pct` is the
  first block after `prepareToPlay`, reported separately and excluded from the distribution;
  `worst_block_at_s` lets `perf.py` tell a recurring (DSP) maximum from a moving (scheduling)
  one (D.2.1); `build.arch` names the slice that rendered, and a golden or perf baseline
  from another slice does not count.
- Exit codes: 0 rendered; 2 a flag or value was refused (message on stderr); 3 the render
  produced NaN or Inf (the JSON is still printed, `health` says how many).
- `presets.csv` beside `parameters.csv`: `slug,name,category,tags,edge,author,notes`
  (`presetlint.py --help` has the rules); `--list-presets` must equal it in order.

Tools that drive this contract: `dspkit.render`, `test_template.py` (the project scaffold),
`presetlint.py` (the bank), `perf.py` (the budget), `paramgen.py check --list-params`.
`fake_harness.py` implements it for the kit's own tests and is the reference for a new
product's renderer.
