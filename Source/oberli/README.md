# Source/oberli: the family's shared plugin code

Every Oberli Audio plugin carries this folder as a byte copy. It is written in `~/bob-skills`
(`tools/template-src/Source/oberli`), published in `Oberli-Audio/plugin-template`, and refreshed
into a plugin with `python3 tools/refresh_oberli.py`. **Never edit it in a plugin repo**: CTest
`oberli_copy` (`refresh_oberli.py --check`) fails on any edit. A change, a fix or a new module is
made in bob-skills, released with skills-bob, and refreshed into each plugin.

| Module | What it is | Threads |
|---|---|---|
| `Loudness` | ITU-R BS.1770-4: momentary, short-term, integrated (gated), LRA (EBU Tech 3342), true peak 4x; plain C++ | `process` on one thread, `readings` any thread |
| `Analysis` | `AudioCopy` (lock-free ring), `BandLayout` (1/3 and 1/6 octave, IEC 61260 base 2), `Spectrum` (Hann FFT, fast and long-term band averages), `Analyser` (the background thread), `ui::DisplayTimer` (30 Hz, stops when idle) | `push` audio thread, FFT background, read any thread |
| `References` | The shared `Oberli Audio/References/` folder: `list`, `load` (decode, windowed-sinc resample), `analyse`, `ReferenceCache` (path, size, mtime), `Loader` (background), `TrackSlot` (hand-off to the audio thread) | never the audio thread, except `TrackSlot::get` |
| `RenderSafety` | `render::modeFor` (the display copy is skipped offline, the audio path never differs), `WireCheck`, `maxDifference`; the bounce null test is `tools/tests/check_bounce.py` | audio thread |
| `MeterTaps` | `PeakTap` (sample peak, latched clip), `GainReductionTap`, `CorrelationTap`: atomics from `processBlock` to the meters | push audio thread, take editor |
| `Folders` | Preset, settings, references and cache folders (`PRESET_ROOT` moves them all for tests); `MachineSettings` (the GUI scale); `slugFor` | message thread |
| `OberliLookAndFeel` | The brand sheet in code: `Palette` (Charcoal, Bone; `front()` the plugin's theme, `back()` the About page's), `Tokens` (accent, radii, sizes, shadow-pop), `type` (Rubik, the type scale, tabular figures), `icons`, `logo`, `drawKnob` (the logo's knob), `drawLed`, `LookAndFeel` (tooltips, text fields, scrollbars, JUCE sliders) | message thread |
| `Knob`, `Buttons`, `ReadoutBubble`, `Motion`, `Meters` | `Knob` (glides, Shift for fine, double-click default, the host's menu, drag readout), `ParameterKnob` (knob, caps label, value), `IconButton`, `ActionButton`, `PillToggle` (LED), `SegmentedControl`, `LevelMeter` (sample peak, CLIP or LIMIT), `GainReductionMeter`, `CorrelationMeter` | message thread |
| `StripEditor` and the frame | `StripEditor` (the base of every editor: header, body, overlays, GUI scale, frame clock), `PluginHeader`, `HeaderMenu`, `PresetDrawer`, `SavePresetCard`, `AboutPanel` (wide and compact), `Diagnostics`, `PresetLibrary` (`PresetHost`: the factory bank, the User folder, the edited mark) | message thread |

The plugin's CMakeLists.txt sets `OBERLI_THEME_BONE` (effects 1, instruments 0) and `OBERLI_ACCENT`
(0xFF + the category's accent from the registry), and compiles the assets into `OberliUiData`
(Rubik's five weights, the four marks). The snapshot tool (`tools/gui_snapshot`, target
`<Id>GuiSnapshot`) renders any editor built on `StripEditor` to PNG at any scale and state.

Tests: `tools/tests/test_loudness.cpp` (EBU Tech 3341 and 3342 at 44.1 to 192 kHz) and
`tools/tests/test_oberli.cpp` (Analysis, References, RenderSafety), both CTest label `fast`.

`MANIFEST.sha256` lists every file's hash; `build_template.py` writes it.

## Refreshing a plugin

In the plugin repo:

```bash
python3 tools/refresh_oberli.py
```

A repo made before Source/oberli/ existed (bench-line, a-b-see, less-s, align, clean-up) has no
copy of the tool yet; fetch the template once and run its copy:

```bash
git clone --depth 1 https://github.com/Oberli-Audio/plugin-template /tmp/plugin-template
```

```bash
python3 /tmp/plugin-template/tools/refresh_oberli.py --from /tmp/plugin-template --accent "#039BE5"
```

`--accent` is the plugin's category accent (plugin-ui-bob brand sheet: instruments tangerine
#F4511E, creative effects banana #F6BF26, mix tools sage #33B679, analysis and monitoring peacock
#039BE5). Without it the tool takes the one CMakeLists.txt already sets, else the registry's
entry (on the Mac, where `~/bob-skills` is); a cloud session passes it.

It replaces `Source/oberli/`, copies the tests and itself, adds the missing CMake blocks
(`tools/init/oberli-cmake.txt` of the template) and the harness's `--non-realtime`, and prints
what it changed. Then build, `ctest --preset fast`, and commit.
