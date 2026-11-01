# tools/measure

The product's measurement scripts (sound-design-bob G3 and G5): the alias floor, the metric
battery, the port-versus-prototype null test, the descriptors that say "is it the sound we
designed", the translation battery. Each drives the harness through `dspkit.render()`
(`scripts/dsp-kit/dspkit.py`) and writes its numbers into `docs/status.md`'s gate table with
the command behind them. Empty at the start; the first script arrives at G3.
