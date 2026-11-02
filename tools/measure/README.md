# tools/measure

The product's measurement scripts (sound-design-bob G3 and G5): the alias floor, the metric
battery, the port-versus-prototype null test, the descriptors that say "is it the sound we
designed", the translation battery. Each drives the harness through `dspkit.render()`
(`scripts/dsp-kit/dspkit.py`) and writes its numbers into `docs/status.md`'s gate table with
the command behind them. - `g5_null.py`: G5, the port against the numpy prototype on the seeded drum-loop pair, the six
  settings of the prototype's `reference_renders`, at every rate; F.8's -100 dBFS (float with IIR
  state), no alignment. The prototype gets the plain values the port read (`product.params_plain`).
