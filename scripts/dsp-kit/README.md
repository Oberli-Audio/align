# dsp-kit - the executable part of the Oberli Audio DSP playbook (v4.0)

## Requirements

- Python 3.9 or newer with `numpy` and `scipy` (`pip3 install numpy scipy`); nothing else
  for the measurement library, the lints and the fakes.
- A C++17 compiler with ASan and UBSan (Apple clang, Homebrew LLVM, or GCC) for
  `code-blocks/test_code_blocks.py`; `sh` for `check_all.sh`.
- For `validate_plugin.py` on a real plugin: CMake, the pinned VST3 SDK commit (built on
  first use) and pluginval 1.0.4 (`--fetch-pluginval`), see its `--help`.
- Run the scripts **from this folder** or by absolute path, with plain `python3`, not
  `python3 -I`: the scripts import `dspkit.py` beside them via `sys.path`.

Everything here is tested. Run every check - kit, compiled code blocks, lint - with one
command after changing anything in the kit or the playbook (about six minutes, most of
it the fake harness rendering in pure Python; set `TMPDIR` to a scratch folder):

    sh <skill>/scripts/tools/check_all.sh   # <skill> = sound-design-bob in ~/bob-skills

| File | What it is | Check |
|---|---|---|
| `dspkit.py` | Measurement library: peak, true peak, RMS, DC, crest; BS.1770 K-weighting at any rate, integrated / momentary / short-term loudness, LRA; null residual and latency; harmonic profile and THD; Schroeder t60; centroid; click score; repeat variation (the "sterile" descriptor, I.1); run statistics (F.13.9); block-time report with p99.9, over-deadline, worst-block position, first block and warm-up (rule 20, contract v3); absolute `max_click_db`; peak and RMS residual; `render()` / `assert_echo()` / `list_presets()` for the harness contract; `dropout_db` (a silent gap against a reference render); `python3 dspkit.py smoke <harness> [--arch x86_64]` proves a real harness against the contract before anything else runs, and `--arch` (or `DSPKIT_ARCH`) starts the harness under `arch -x86_64` while Python stays native | `python3 test_dspkit.py` - 34 tests: BS.1770 coefficients at 48 kHz, EBU Tech 3341 cases 1-4 (case 1 at six rates), EBU Tech 3342 cases 1-3, analytic peak/THD/t60/latency/null checks, the harness contract including a dropped `--param`, exit 3, arch echo, a planted silent gap in an oversized block, and both tools' self-tests |
| `harness-contract.md` | What every product's offline renderer implements (v3): flags incl. `--gate`, `--reprepare-at`, `--preset-at`, `--warmup`, random blocks from 0, state in from any bytes; JSON with `build.arch` and the full `profile`; list formats; exit codes | Implemented by `fake_harness.py` |
| `test_template.py` | Project test scaffold with labels `fast` (echo incl. flags, seeded determinism, the 42-combination rate x block matrix incl. block 0, random blocks, oversized blocks, silence test at 48 k/64 with `--gate`, latency by cross-correlation, tail, state round trip, corrupted state) and `render` (goldens with sidecars and the F.8 tolerances, arch-aware; presence-test stub); per-test seconds, a budget on `fast`; CTest snippet | `HARNESS=$PWD/fake_harness.py FAST_BUDGET_S=120 python3 test_template.py --label fast` |
| `fake_harness.py` | An instrument-shaped renderer implementing contract v3 (three presets, gate, synthetic block times with a first-block and preset-change spike) with environment switches that plant defects, so every kit check is shown failing before it is trusted (D.3.8); `--help` lists the flags | run by `test_dspkit.py` |
| `presetlint.py` | The preset bank as a deliverable (F.14.3, D.8.8): `bank` checks `presets.csv` (slugs, names, one Init first, categories, edge presets, size by tier) and the harness listing; `render` checks Init = table defaults, seeded loudness spread (1 LU at P, 0.35 LU over N at F), true peak, NaN, click on note-off, CPU per preset, state round trip, drift against a baseline; writes `docs/presets.md` | `python3 presetlint.py selftest` (every check fails on a planted defect) |
| `perf.py` | The CPU budget as a measurement (rule 20, D.2.1): presets x configurations x runs, median p50/p99/p99.9, the maximum read as DSP or scheduling by position, first-block and preset-change spikes, idle after the tail, `build.arch` asserted; judged: p99.9, a recurring max, the first block, idle, and (F, `--baseline`) the regression against a baseline of the same machine; `over_deadline` is in the row and the JSON but never judged (an offline harness is preempted now and then) | `python3 perf.py selftest` |
| `toolchain.py`, `tools.toml.example` | The machine file `~/.config/oberli/tools.toml` (`init` copies the example): Homebrew LLVM with RTSan, Faust, the signed pluginval and the ASan / TSan builds, the VST3 SDK, the hosts, the registry; `get`, `env` (export lines the CMake presets read: `LLVM_ROOT`, `PLUGINVAL`, ...), `check` (every set path exists). `validate_plugin.py` reads pluginval from it when `$PLUGINVAL` is unset; the repos carry no machine paths | `python3 toolchain.py selftest` |
| `new_project_docs.py` | Writes the two project documents (`brief.md` from F.15.2, `status.md` from D.9.2) and the `failures.md` header into a product's `docs/`, extracted from the playbook so there is one source; `--help` | `python3 new_project_docs.py /tmp/x --list` |
| `validate_plugin.py` | The unattended part of the release gate (`joint-plugin-workflow.md`) for any VST3: your build and test commands, the Steinberg validator (built from a pinned SDK commit), pluginval pinned to 1.0.4 with tier profiles (`quick` L5, `full` L10 at all rates and block sizes from 1, `soak` repeated and randomised with a fresh logged seed), tests-started count and verdict parsed, Steinberg by exit code and failing on wrong MIDI mapping answers it logs only as Info, `--sanitizer asan|tsan` scaling timeouts for a from-source pluginval (taken from `$PLUGINVAL` only; unset, missing or uninstrumented fails the step, never a fallback) and, on macOS, inserting the plugin's own sanitizer runtime into the Steinberg validator, an optional RTSan command with its self-test; logs + JSON summary; exit 77 = skipped (D.5.7, D.1.6). pluginval 2.0 (beta, 2026-10) changes the syntax: migrate when it ships | `check_all.sh` runs its skip path and `selftest`, `test_dspkit.py` the sanitizer refusal; the full run takes minutes on a real plugin (pluginval L10 at six rates and eight block sizes), ten times that under a sanitizer |
| `code-blocks/` | Compiles and runs the C++ printed in the playbook (dsp-reference-bob F.11 smoother, TPT SVF, ADAA tanh, gain computer and ballistics; dsp-reference-bob E.1 lookahead limiter) at -O2 and under ASan/UBSan | `python3 code-blocks/test_code_blocks.py` |

And for the playbook text itself: `python3 <skill>/scripts/tools/playbook_lint.py`
(cross-references, including that references to the textbook sections name
dsp-reference-bob, legacy references, the invariants mirror, skill routing, versions, the
core card's word budget; `--self-test` proves it catches each defect class).

## Starting a new product

A product starts from the family template (ship-bob SKILL.md, "Starting a plugin"), which
carries this kit, the two project documents, the test scaffold with its TODOs resolved and a
harness implementing `harness-contract.md`; `init_plugin.py` fills in the product. By hand,
for a repo that did not start there:

```bash
python3 <skill>/scripts/dsp-kit/new_project_docs.py <project>/docs
cp <skill>/scripts/dsp-kit/test_template.py <project>/tools/tests/test_<product>.py
# implement the offline renderer to harness-contract.md, then:
HARNESS=<project>/build/<Harness> python3 -m unittest <project>/tools/tests/test_<product>.py
```

## Known limits

- `true_peak_dbtp` interpolates with a Kaiser-windowed polyphase FIR, not BS.1770's
  reference filter: use `oversample=16` to verify a ceiling, and the EBU 3341 true-peak
  signals for a product meter (dsp-reference-bob A.1).
- Loudness supports channel weights but has only been tested in mono and stereo.
- `harmonic_profile` expects a steady tone of at least ~0.5 s; it is not a
  swept-sine (Farina) distortion measurement (F.13.4, appendix dsp-reference-bob B.1).
- `click_score` is relative: compare against a clean render of the same material; `max_click_db` is the absolute measure the contract and `presetlint.py` use.
- `presetlint.py render` and `perf.py run` take as long as the harness renders (a real harness: seconds per preset; the Python fake: about a minute per kit check).
