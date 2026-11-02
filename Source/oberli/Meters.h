#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "MeterTaps.h"
#include "Motion.h"
#include "OberliLookAndFeel.h"

#include <limits>

namespace oberli::ui
{

/**
    The Meter card, generalised from Horizon Pad's output column: two 8 px wells
    (left, right), `surface-sunken` with a 1 px `line` border and `radius-xs`;
    the bar in `meter-level` below -6 dBFS and `meter-hot` above, a peak line in
    `ink` that holds 1.2 s and then falls; under them the reading's name (PEAK)
    in `label` and its value in `value` with a real minus sign. The scale is
    logarithmic, -48 dBFS to 0.

    The LED beside the wells is one of two, its word always there:
      Led::clip   outlined, `ink-subtle` text off; `clip` with `ground` text on,
                  held until clicked (PeakTap::clearClip)
      Led::limit  lit in `meter-hot` while `isLimiting()` is true and 1 s after
      Led::none   no LED

    Every frame the editor calls advance(); the meter takes the peaks from its
    PeakTap and repaints at the ambient rate, only what moved by a pixel.
*/
class LevelMeter final : public juce::Component,
                         public juce::SettableTooltipClient
{
public:
    enum class Led { clip, limit, none };

    static constexpr int kColumnWidth = 64;

    LevelMeter (PeakTap&, Led, const Palette& = front());

    /** For Led::limit: true while the plugin's output limiter works. */
    std::function<bool()> isLimiting;

    /** The width the meter needs with its LED. */
    int getPreferredWidth() const;
    static constexpr int kHeight = 88;

    void advance (double now, float dt);

    void paint (juce::Graphics&) override;
    void mouseDown (const juce::MouseEvent&) override;

private:
    struct Channel
    {
        motion::Follower level;
        float peak = 0.0f;
        double peakHoldUntil = 0.0;
        float shownLevel = 0.0f, shownPeak = 0.0f;
    };

    juce::Rectangle<float> wellArea (int channel) const noexcept;
    juce::Rectangle<float> ledArea() const noexcept;
    juce::Rectangle<float> valueBox() const noexcept;
    juce::String ledWord() const;

    PeakTap& tap;
    const Led led;
    const Palette& colours;

    std::array<Channel, 2> channels;
    float heldPeakDb = -std::numeric_limits<float>::infinity();
    double heldPeakUntil = 0.0;
    int shownDb = std::numeric_limits<int>::min();
    double shownAt = 0.0;
    double limitLitUntil = -1.0;
    bool ledShown = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (LevelMeter)
};

/**
    Gain reduction, downward: one 8 px well whose bar grows from the top, 0 to
    `rangeDb` (24 dB by default), in `meter-level` (nothing about reduction is
    "set", so never the accent); under it GR and the value ("−3.2 dB"). Quick
    to show, slow to let go (40 ms up, 300 ms down), like the level meter.
*/
class GainReductionMeter final : public juce::Component,
                                 public juce::SettableTooltipClient
{
public:
    static constexpr int kWidth = 64;
    static constexpr int kHeight = 88;

    GainReductionMeter (GainReductionTap&, float rangeDb = 24.0f, const Palette& = front());

    void advance (double now, float dt);
    void paint (juce::Graphics&) override;

private:
    juce::Rectangle<float> wellArea() const noexcept;

    GainReductionTap& tap;
    const float rangeDb;
    const Palette& colours;
    motion::Follower reduction;   // dB
    float shown = 0.0f;
    double shownAt = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (GainReductionMeter)
};

/**
    Stereo correlation: a horizontal `surface-sunken` well from -1 to +1 with a
    hairline at 0, a 3 px marker in `ink` at the value, and CORRELATION with the
    value ("+0.82") beside it. Below 0 the marker turns `meter-hot` and the value
    keeps its sign, so the warning never rests on colour alone.
*/
class CorrelationMeter final : public juce::Component,
                               public juce::SettableTooltipClient
{
public:
    static constexpr int kHeight = 32;

    CorrelationMeter (CorrelationTap&, const Palette& = front());

    void advance (double now, float dt);
    void paint (juce::Graphics&) override;

private:
    juce::Rectangle<float> wellArea() const noexcept;

    CorrelationTap& tap;
    const Palette& colours;
    motion::Follower value;
    float shown = 0.0f;
    double shownAt = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (CorrelationMeter)
};

/** "−19 dB", "+0.82": the meters' numbers, with a real minus sign. */
juce::String formatDb (float db, int decimals = 0);
juce::String formatSigned (float value, int decimals);

} // namespace oberli::ui
