#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "OberliLookAndFeel.h"
#include "Motion.h"

namespace oberli::ui
{

/**
    The floating `readout` card: `readout` fill, `on-readout` text in
    `value` type (tabular), `radius-sm`, `shadow-pop`. Two uses: a knob's
    value above its cap while it is dragged (Knob card), and a short
    confirmation that fades after a moment ("Copied A to B", "Copied. Paste
    it into your message to Björn."). It sits above everything in the
    editor and never takes a click.
*/
class ReadoutBubble final : public juce::Component
{
public:
    explicit ReadoutBubble (const Palette& = front());

    /** Shows `text` with its bottom edge centred `gap` px above `anchor`
        (editor coordinates), or below it with `below`. */
    void showAt (const juce::String& text, juce::Rectangle<float> anchor, float gap, bool below = false);

    /** Shown for `seconds` of the editor's frame clock, then faded out. */
    void flash (const juce::String& text, juce::Rectangle<float> anchor, double now, double seconds);

    void hide();

    /** One editor frame: the fade of a flash. */
    void advance (double now, float dt);

    void paint (juce::Graphics&) override;

private:
    static constexpr int kShadowMargin = 32;

    const Palette& colours;

    juce::String text;
    motion::Follower opacity;
    double hideAt = -1.0;
    bool timed = false, startClock = false;
    double flashSeconds = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ReadoutBubble)
};

/** What a knob needs from the editor to show its drag readout above
    everything else. The editor implements it. */
struct ReadoutHost
{
    virtual ~ReadoutHost() = default;
    virtual void showDragReadout (juce::Component& source, juce::Rectangle<float> capInSource, const juce::String& text) = 0;
    virtual void hideDragReadout() = 0;
};

} // namespace oberli::ui
