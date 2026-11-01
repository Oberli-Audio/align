# sound design/ - the G2 prototype

Design references, never compiled into the product (CLAUDE.md). The brief's track is **effect**
with an analysis stage, so the G2 prototype is **numpy, not Faust**: sound-design-bob F.15.1's
per-track gate table asks for a numpy model for a spectral effect and a numpy/scipy reference
implementation for an analysis stage, and Align's two hard parts - GCC-PHAT and a phase rotation -
are both of that kind. There is no `.dsp` file for the same reason; Faust would have been a
detour, not a shortcut.

Every module is in the structure `Source/dsp/` will mirror, so G5 can null the port against it:

| here | the port | what it is |
|---|---|---|
| `material.py` | - | seeded test material, and the exact FFT fractional shift that *defines* the truth |
| `sinc_delay.py` | `SincDelay.h` | the fractional delay line: kernel table, two taps, crossfade |
| `rotate.py` | `Rotate.h` | the low-end phase rotation: two first-order TPT all-passes |
| `detector.py` | `Detector.h/.cpp` | GCC-PHAT, the readout, the Rotate suggestion |
| `engine.py` | `AlignEngine.h` | the audio path, the latency and clamp rules, the analysis rings |
| `prototype.py` | `tools/measure/` | the CLI: every check, the constants searches, the renders |

```bash
python3 "sound design/prototype.py" --all --kernel-search --seed 1   # everything -> g2.json
python3 "sound design/prototype.py" --check accuracy                 # one check
python3 "sound design/prototype.py" --renders                        # renders + the listening A/B
```

`g2.json` is the committed record: every number with the check that produced it. The exit code is
non-zero if any check fails.

## The reference renders are not committed, on purpose

`.gitignore` keeps `sound design/renders/` out of git (the family's convention: renders and sample
material live in OneDrive). What is committed instead is stronger than a WAV: the **seed**, the
**code** and the **fingerprints** in `g2.json` (peak, RMS, latency, NaN/Inf per render). One
command regenerates every render bit for bit on any machine, and a render that drifted would show
up as a changed fingerprint rather than as a silently replaced file.

For the listening checkpoint, `--renders` also writes
`renders/g2_listen_ab_misaligned_then_aligned.wav`: the **sum** of the pair, four bars combed, half
a second of silence, then the same four bars aligned and level-matched. The processed track alone
tells you nothing - 2.3 ms on one mic is inaudible by itself - so the sum is what gets listened to.

## Prototype-era workarounds, to decide again at G4 (F.8)

1. `sinc_delay.SincDelay` vectorises the read over a chunk, so it writes the chunk into the ring
   before reading it and the ring has to hold the chunk as well as the deepest delay. The C++ port
   reads per sample and needs only the delay. `_chunk` keeps the output independent of the caller's
   block size, which `--check rates-blocks` asserts to -300 dBFS.
2. `rotate.FAST` renders through a direct-form realisation (`scipy.signal.lfilter`) instead of the
   per-sample TPT loop, for speed. `--check rotate-structure` measures the two against each other
   (-308 dBFS) and both against the analytic response, so the port's TPT form is held to a measured
   claim, not an assumed one.
3. The prototype is float64 and the port is float32. G5's threshold comes from F.8's table
   accordingly: the path has one-pole state in the all-passes but no long feedback.
