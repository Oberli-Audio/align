#pragma once

#include <juce_gui_basics/juce_gui_basics.h>

#include "dsp/Detector.h"
#include "oberli/Analysis.h"
#include "oberli/OberliLookAndFeel.h"

/*  Align - the two display wells (sketch 2 and 4.5, the hero: what the ear cannot judge).

    CorrelationWell: the GCC-PHAT of the last Detect over its search window, signed - an inverted
    pair is a *downward* peak, so the flip is seen, not inferred (defining feature 1) - with the
    found peak marked in the accent (it is what Detect set). The curve is the detector's own
    (Detector::Result::curve, peak-preserving), so the picture and the number cannot disagree
    (rule 9).

    SumWell: this track plus the reference as they meet in the mix, 1/6 octave, before Align
    (dashed) and after it (ink): the comb's teeth that disappear (defining feature 2). Fed by the
    processor's two analysers only while an editor is open, never offline.

    Both are `surface-sunken` wells with `radius-xs` and a `line` border, no parameters, and say in
    words what is missing when they are empty. */
namespace align::ui
{
class CorrelationWell final : public juce::Component
{
public:
    CorrelationWell();

    /** The last published result; `has` false shows `emptyText` instead. */
    void setResult (const align::dsp::Detector::Result&, bool has);
    void setEmptyText (const juce::String&);

    void paint (juce::Graphics&) override;

private:
    align::dsp::Detector::Result result;
    bool hasResult = false;
    juce::String emptyText;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (CorrelationWell)
};

class SumWell final : public juce::Component
{
public:
    SumWell (oberli::Analyser& before, oberli::Analyser& after);

    /** One editor frame: takes the analysers' new results and repaints only then. */
    void advance();

    /** Without a reference the sum is just this track: the well says so instead of drawing it. */
    void setReferencePresent (bool present);

    void paint (juce::Graphics&) override;

private:
    juce::Path curveFor (const std::array<float, oberli::Spectrum::kMaxBands>&, juce::Rectangle<float> plot,
                         float topDb, float spanDb) const;

    oberli::Analyser& before;
    oberli::Analyser& after;
    juce::uint32 seenBefore = 0, seenAfter = 0;
    std::array<float, oberli::Spectrum::kMaxBands> beforeDb {}, afterDb {}, centres {};
    int bands = 0;
    bool reference = true;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SumWell)
};
} // namespace align::ui
