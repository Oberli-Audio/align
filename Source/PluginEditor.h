#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include "AlignDisplays.h"
#include "PluginProcessor.h"
#include "oberli/Buttons.h"
#include "oberli/Knob.h"
#include "oberli/Meters.h"
#include "oberli/StripEditor.h"

/*  Align - the editor, on the family's Strip frame (Source/oberli/StripEditor.h: header, preset
    drawer, Save preset, About on the back, GUI scale), Bone with the sage accent of the mix tools.

    The body is the sketch's (docs/sketch.md 2, docs/sketch@1x.png), in signal-flow order:
      ALIGN    Delay (64, the hero knob), Detect (the one primary button) and the readout in words
               under it, Polarity and Hold, WINDOW, MODE, LISTEN;
      ROTATE   Rotate and Below, Detect's suggestion in words and Apply (secondary) while the
               suggestion differs from what is set;
      the two wells across the bottom: CORRELATION (signed, the found peak in the accent) and SUM
               (before dashed, after ink), with their legends;
      OUTPUT   last on the right: Trim (64), the level meter with CLIP, the correlation meter.
    Group (sketch 4.4) is Tier F and not here.

    States (sketch 2.5): no sidechain - Detect disabled and the readout says how to route it;
    detecting - a hairline under Detect until the result arrives; Track - the Delay knob shows the
    tracked offset as a `mod` range beside the user's value. */
class AlignAudioProcessorEditor final : public oberli::ui::StripEditor
{
public:
    explicit AlignAudioProcessorEditor (AlignAudioProcessor&);
    ~AlignAudioProcessorEditor() override;

    void paint (juce::Graphics&) override;

    /** Shows a knob's drag readout without a mouse (the snapshot tool). False for an unknown ID. */
    bool previewDrag (const juce::String& parameterId) override;

private:
    void layoutBody (juce::Rectangle<int> area) override;
    void advanceBody (double now, float dt) override;
    void presetRecalled (double now) override;

    void pressDetect();
    void refreshDetect (bool force);
    void refreshSuggestion();
    void refreshTrack();

    AlignAudioProcessor& audioProcessor;   // not `processor`: AudioProcessorEditor has one (-Wshadow)

    oberli::ui::ParameterKnob delayKnob, rotateKnob, belowKnob, trimKnob;
    oberli::ui::ActionButton detectButton, applyButton;
    oberli::ui::PillToggle polarityPill, holdPill;
    juce::AudioProcessorValueTreeState::ButtonAttachment polarityAttachment, holdAttachment;
    oberli::ui::SegmentedControl windowSegments, modeSegments, listenSegments;
    oberli::ui::LevelMeter meter;
    oberli::ui::CorrelationMeter correlationMeter;
    align::ui::CorrelationWell correlationWell;
    align::ui::SumWell sumWell;

    // the words, drawn in paint()
    juce::String readout[2], suggestion[2];
    juce::Colour readoutColour;

    juce::Rectangle<int> alignTitle, rotateTitle, outputTitle, windowTitle, modeTitle, listenTitle,
                         correlationTitle, sumTitle, outputRule, readoutBox, suggestionBox, progressBox,
                         correlationLegend, sumLegend;

    align::dsp::Detector::Result lastResult;
    int seenSequence = -1;
    bool hadSidechain = false, hasResult = false;
    double detectPressedAt = -1.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AlignAudioProcessorEditor)
};
