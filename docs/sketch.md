# Align - automatic phase alignment (Tier S sketch)

Tier S, gate G0-G2 sketch. Oberli Audio effect, Bone theme, accent Sage #33B679 (mix tools, category scheme confirmed 2026-11-01). Static frame: `align@1x.png` (880 x 600 at 100 %), `align@2x.png` for Retina viewing. Sound side: sound-design-bob is needed for the correlation estimator, the fractional delay and the all-pass; this sketch states what the DSP must do and the evidence that proves it.

## 1. G0 brief

**Users.** Björn on multi-mic recordings from the church sessions (drum kit with overheads, kick in and out, snare top and bottom, room pair; DI plus amp mic on bass and guitar; two mics on the grand piano; two mics on the same singer for the live stream). Friends who get the build.

**Why it is a gap.** Nothing free does it; Ableton has Utility's polarity switch and a Track Delay in ms, but no measurement, no sub-sample delay and no negative delay. The paid references are Sound Radix Auto-Align 2 (static and dynamic, spectral phase), MAutoAlign (Melda) and Waves InPhase (manual with correlation meter).

**Core jobs.**
1. Line up this mic to a reference mic: press Detect, get delay, polarity and a confidence, applied.
2. Fix what a delay cannot: the low-end phase smear between kick in and overheads, with a tunable all-pass.
3. See it before trusting it: the correlation curve with the found peak and the summed spectrum before and after (comb notches gone).
4. Align a whole kit at once: a group of instances with one reference, one "Align group" action.
5. Keep up with a moving singer: Track mode re-estimates slowly while the take runs.

**Context.** One instance per aligned track, the reference mic routed into the sidechain input (Ableton Live's plugin sidechain chooser). Used once per session during setup, then left in place. Latency is acceptable here (Live compensates), except in the live-stream mix where the zero-latency window is chosen.

**Success.** A kick-in track delayed by 2.3 ms and flipped against the overheads is found within 0.02 ms and the right polarity in one press on a 4-bar loop; the summed spectrum's first comb notch disappears; the correlation meter goes from 0.2 to above 0.9; the group action aligns four instances in one go; a bounce with the plugin at Delay 0, Polarity off, Rotate 0 nulls against the dry track.

**The five core controls.** Delay, Polarity, Detect, Window, Rotate. Mode, Listen, Below and Trim are the second row.

**CPU and latency budget.** Static mode playing: 0.3 % on an M1 at 48 kHz, 128 samples. Detect runs on a background thread over the last 4 s, under 200 ms to a result. Reported latency equals the Window (5, 20, 50 or 200 ms) so a negative delay is possible; the "0 (live)" window reports zero latency and allows positive delay only, for the live-stream mix (decided 2026-11-01).

**Three structural decisions (sound side).**
1. Measure with GCC-PHAT, apply with a fractional delay. The cross-correlation between the sidechain (reference) and this track uses the phase transform (whitened), which gives a sharp peak on reverberant and tonal material where plain correlation smears; the peak is refined by parabolic interpolation to 0.01 ms; the sign of the peak gives polarity; confidence = peak height over the second-highest peak, in percent. The delay is applied with a windowed-sinc fractional delay (zero phase distortion in the audible band), never an all-pass approximation.
2. Negative delay through reported latency. The plugin always delays by Window plus Delay internally and reports Window to the host; Live's compensation pulls everything back, so Delay reads and behaves as a signed value. Changing Window changes the reported latency once; Delay never does.
3. Rotate is a separate stage, off by default, and Detect only proposes it. A second-order all-pass below the Below frequency rotates the low end 0 to 180° so kick-in against overheads lines up where the sources are too far apart for one delay to fit all frequencies. After the delay and polarity are applied, Detect runs a second fit on the band below 300 Hz and shows the Rotate and Below values that would raise the low-band correlation most, with the before and after number; nothing moves until the user presses Apply. Automatic timing is safe to apply; automatic phase shaping is a sound decision, so it stays a suggestion.

## 2. G1 design plan (five lines)

1. **Window** 880 x 600 at 100 %, Bone, compact; two display wells side by side.
2. **Hero** is what the ear cannot judge: the correlation curve with the found peak (a downward peak means the polarity is flipped, and the display shows it as such) and the summed spectrum before (dashed) and after (ink), where the comb notches vanish. The numbers under Detect say it in words: "Peak +2.31 ms · 79 cm · polarity flipped · confidence 94 %".
3. **Accent** Sage on the set and active only: Delay's value arc and pointer, the Detect primary button, lit LEDs, selected segments, the found-peak marker. The correlation meter is ink.
4. **Sections** in signal-flow order from the table's groups: Align, Rotate, the displays (Correlation, Sum, no parameters), Group (one row with a drawer), Output (Trim 64 px, correlation and level meters; no Mix knob: utility plugin without a wet path, the line the A B see sketch proposes for the brand sheet).
5. **States**: suggestion (the Rotate section shows the proposed value and an Apply secondary button after a Detect; after Apply the button disappears and the knobs carry the value), modified (pill dims), drawer (presets from the left; the Group drawer from the right, 380 px, lists the instances of the group with name, delay, polarity, confidence, reference marker and "Align group"), About (charcoal page), bypass, no sidechain (Detect disabled, the readout says "Route the reference mic into the sidechain input", correlation well empty), detecting (a hairline progress under the Detect button, 200 ms), Track mode (the Delay knob moves on its own and shows a small `mod`-coloured ring segment for the tracked offset around the user's base value, so the user sees what Track adds), Listen Ref or Sum (header pill shows "Listening: Ref" / "Sum" in `ink-subtle`).

## 3. Parameter table (sketch, six columns)

| id | type | name | group | unit / choices | min / max / default |
|---|---|---|---|---|---|
| delay | float | Delay | Align | ms, bipolar, 0.01 steps | -200 / +200 / 0 |
| polarity | bool | Polarity | Align | - | 0 / 1 / 0 |
| window | choice | Window | Align | 0 (live) \| ±5 \| ±20 \| ±50 \| ±200 ms | 0 / 4 / 2 |
| mode | choice | Mode | Align | Static \| Track | 0 / 1 / 0 |
| hold | bool | Hold | Align | - | 0 / 1 / 0 |
| rotate | float | Rotate | Rotate | ° | 0 / 180 / 0 |
| below | float | Below | Rotate | Hz, centre 150 | 30 / 1000 / 120 |
| listen | choice | Listen | Align | Off \| Ref \| Sum | 0 / 2 / 0 |
| trim | float | Trim | Output | dB, bipolar | -24 / +24 / 0 |
| detect | bool | Detect | Align | momentary | 0 / 1 / 0 |
| bypass | bool | Bypass | - | - | 0 / 1 / 0 |

Delay is clamped to the Window at runtime; a Delay outside the current Window shows the value in `ink-subtle` with the tooltip "Outside the window; widen Window or the delay is clipped". Detect is a momentary host parameter so a controller button or a MIDI map can trigger it; the editor's button calls the same parameter. Group membership, group name, reference flag and the Detect analysis length are plugin state, not parameters.

Tooltips:
- Delay: "Moves this track against the reference; positive later, negative earlier."
- Polarity: "Flips the signal when the two mics face each other."
- Window: "How far Detect searches and how much latency the plugin reports; 0 is zero latency with positive delay only, wider for room mics."
- Mode: "Static keeps the found value; Track keeps re-measuring slowly for a moving source."
- Hold: "Freezes Track's value where it is."
- Rotate: "Turns the phase of the low end where a delay cannot line up two mics."
- Below: "The frequency under which Rotate acts."
- Listen: "Ref plays the sidechain, Sum plays both summed to mono so you hear the comb."
- Trim: "Level of this track after alignment."
- Detect: "Measures delay and polarity against the reference and applies them."

## 4. Approach and best practice

### 4.1 Signal path
```
sidechain (reference) ──► analysis buffer (4 s ring) ──┐
                                                       ├─► Detect (background): GCC-PHAT → peak → delay, polarity, confidence
in ──► analysis buffer ────────────────────────────────┘
in ──► polarity ──► fractional delay (Window + Delay) ──► all-pass (Rotate, Below) ──► Trim ──► out
                                                       meters: correlation(ref, out), out level; Sum display (ref + out)
```
- The audio path is a wire plus three operations, each individually nullable: Polarity off, Delay 0 (the Window delay is compensated by the host), Rotate 0 (the all-pass is bypassed, not set to 0°, so there is no residual phase).
- Fractional delay: 32-tap windowed sinc, coefficients recomputed on a parameter change on the message thread and swapped atomically; delay changes crossfade over 10 ms so Track mode does not click.
- Rotate: second-order all-pass with its corner at Below and Q chosen so the shift reaches the set degrees at the corner and returns to 0 above about 4x Below; above that the path is untouched.

### 4.2 Detect
- Runs on the last 4 s of both buffers (2 s if the transport has run less), on a background thread, result posted to the message thread, parameters written through begin/perform/end edit so the host records them as one edit.
- GCC-PHAT over the Window, FFT size the next power of two above 2 x window length at the session rate; parabolic interpolation around the peak; polarity from the peak's sign; confidence = (|peak| - |second peak|) / |peak| in percent, shown and also colour-free in words ("confidence 94 %", "low confidence 38 %: play a louder section").
- Distance is shown next to the time (343 m/s at 20 °C) because that is how an engineer checks plausibility: 79 cm between kick-in and overheads is right, 7.9 m is not.
- If the sidechain is silent (below -60 dBFS for the whole buffer), Detect does nothing and says "Reference is silent".
- Rotate suggestion: after applying delay and polarity, Detect takes the aligned pair, low-passes both at 300 Hz and searches Rotate 0-180° in 2° steps and Below over 60, 80, 110, 150 and 200 Hz for the highest low-band correlation; if the gain over the unrotated pair is at least 0.05, the Rotate section shows "Detect suggests 48° below 110 Hz · correlation below 150 Hz 0.62 → 0.88" and an Apply button; otherwise it shows "No rotation needed". Apply writes both parameters through begin/perform/end edit as one host edit; the suggestion stays visible until the next Detect so the user can compare by ear with Rotate at 0 and at the suggested value.

### 4.3 Track mode
- Every 250 ms a Detect over the last 1 s with a ±2 ms window around the current value; the result is smoothed (1 s time constant) and applied as an offset to the user's Delay base; Hold freezes it. A singer moving between two mics stays coherent without the editor open.
- Track never touches Polarity; a polarity change mid-take is always wrong.

### 4.4 Group
- Instances of Align in the same process register with a shared, lock-free registry (name from the host track name where the host provides it, else "Align n"). The Group drawer lists them; the user names a group, marks one instance as reference and presses "Align group": every member runs Detect against the reference's analysis buffer.
- This needs the reference's audio in each member without sidechain routing: the reference instance publishes its last 4 s into shared memory in the registry. Only the reference publishes; members read once on Align group. Tier P ships single-instance sidechain only; the group is Tier F because inter-instance sharing is the one thing pluginval cannot test.

### 4.5 Displays
- Correlation well: the GCC-PHAT output over the Window, the found peak marked; a downward peak shows polarity inversion directly, the sign is kept on purpose.
- Sum well: 1/6-octave spectrum of reference plus this track, before (dashed, with the delay and polarity undone) and after; comb notches read as the teeth that disappear.
- Correlation meter: Pearson correlation between reference and output over a 400 ms window, -1 to +1, ink; the number is the one most engineers know from Waves InPhase.
- 30 Hz timer, stopped when the transport stands still.

### 4.6 Hosts and quirks
- Sidechain in Ableton Live: the plugin declares a stereo aux input bus; Live shows the sidechain chooser in the device's title bar. The readme explains the routing in two lines.
- Latency changes on Window change: `setLatencySamples`, Live re-measures; the manual says to set Window before recording automation.
- 11 parameters, all visible in Live 10.1's panel; Detect appears as a switch there and works as a momentary.
- Live on Windows auto-scale note (ship-bob).

### 4.7 Deliberately not in it
- No automatic Rotate: it is suggested with its measured gain and applied only on Apply, because a phase fit on real drums is a sound decision, not a timing fact.
- No spectral (per-band) alignment: it changes the sound, not just the timing.
- No time-stretching of one mic to another.

## 5. Manual outline
1. One paragraph and the sentence "Reported latency equals the Window; choose 0 (live) for zero latency in a stream mix."
2. Setup: insert on the mic to align, route the reference into the sidechain, press Detect.
3. Reading the result: peak, distance, polarity, confidence.
4. When a delay is not enough: Rotate and Below with the Sum well.
5. Track mode for moving sources; Hold.
6. Aligning a kit: the Group drawer (Tier F).
7. Parameters (generated).
8. Troubleshooting: low confidence (play a louder or drier section, widen Window), result flips between two values (two reflections; narrow Window), bounce differs (it cannot; here is the null test).

## 6. Acceptance tests for promotion to P
1. Null: Delay 0, Polarity off, Rotate 0, any Window: output nulls to the input after host compensation.
2. Accuracy: a track delayed by 2.317 ms and inverted against the reference is found within 0.02 ms and the right polarity on a 4-bar drum loop, confidence above 80 %.
3. Reverberant material: the same on a room-mic pair with 1.2 s RT60, within 0.1 ms.
4. Latency: reported equals measured (Plugalyzer) for each Window.
5. Click test: Track mode sweeping 2 ms over 1 s on a 1 kHz sine, no sample above the sine's peak by more than 0.01 dB.
6. CPU: under 0.5 % playing; Detect under 200 ms on an M1.
7. Sum display: the first comb notch of a 2.3 ms offset (217 Hz) is visible before and gone after.

## 7. Open decisions for Björn
- Decided 2026-11-01: name Align (slug `align`, plugin ID `Align`).
- Accent: Sage #33B679, by the category scheme (decided 2026-11-01): one accent per category, mix tools.
- Decided 2026-11-01: Window gets "0 (live)" (zero latency, positive delay only) for the live-stream mix; Group is Tier F, P ships sidechain only.
- Decided 2026-11-01: Detect proposes Rotate and Below with the measured low-band gain; Apply accepts it.

## 8. Report
```
Tier: S, gate: G0-G2 sketch
Hosts: n/a at S
Brand sheet: deviates: output column without Mix knob (utility plugin without wet path, same line as A B see); Delay knob shows a mod-coloured ring segment in Track mode (brand reserves mod for modulation, which this is); logo is a CSS stand-in
What works well: negative delay via reported latency makes Delay a plain signed knob; the correlation well keeps the sign so polarity is visible, not inferred; Rotate is a separate nullable stage that Detect proposes but never applies on its own
Findings: none at S
Open / recommended: accent (Schwere 1)
Evidence: align@1x.png at 100 %, align@2x.png
```
