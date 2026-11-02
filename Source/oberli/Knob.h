#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "OberliLookAndFeel.h"
#include "Motion.h"

namespace oberli::ui
{

/**
    The Knob card's rotary control (drawKnob()), whose drawing is animated
    while its value never is: the slider - and through its attachment, the
    parameter - always holds the real value; only what is painted eases
    toward it. The sound never waits for an animation.

      - A change made with the mouse (drag, wheel) is drawn at once:
        instant under the hand.
      - Any other change (host automation, a preset, an A/B switch) glides -
        briskly by default, more slowly and after a delay once the editor
        starts a wave (beginWave): the left-to-right sweep after a recall,
        and the sweep up from zero when the editor opens.
      - While it is dragged, the readout bubble shows the parameter's own
        text above the cap (the editor draws it, ReadoutHost). No hover
        glow: outside the Scene nothing glows.

    Once bound to its parameter (bindParameter()) it behaves like every
    DAW knob: a vertical or horizontal drag, Shift
    for fine, the scroll wheel in steps; double-click resets to the parameter's
    default, right-click opens the host's own menu for that parameter
    (automation, MIDI mapping; a plain "Reset" menu in the standalone), and
    it is reachable by Tab with the arrow keys changing it and the 2 px
    `ink` focus ring around the cap - but a click does not take keyboard
    focus, so the space bar still reaches the host's transport. Screen
    readers read its name and the parameter's own text. Message thread only.
*/
class Knob final : public juce::Slider
{
public:
    Knob();

    /** Call once the attachment exists: default for double-click, the
        accessible name, keyboard focus, and the parameter the host's context
        menu and the readout are asked about. */
    void bindParameter (juce::RangedAudioParameter& parameter, const juce::String& accessibleName);

    /** The value arc from 12 o'clock (a pan, a +/- trim). */
    void setBipolar (bool shouldBeBipolar) { bipolar = shouldBeBipolar; repaint(); }

    /** The modulation range just outside the arc, 0..1 along the sweep (low == high: none). */
    void setModulationRange (float low, float high);

    /** Draws the current value as it is, with no glide. Call once the
        attachment exists: a parameter whose value equals the slider's
        initial 0 never sends the first valueChanged(). */
    void syncDisplay();

    /** Lets the next glide wait until `startTime` (the editor's frame clock,
        seconds) and run at the slower wave speed. With `fromZero` the
        drawing first drops to the bottom of the range (the sunrise on open). */
    void beginWave (double startTime, bool fromZero) noexcept;

    /** Advances the glide by one frame and repaints the knob if it moved.
        Returns true in that case, so the parent can repaint its value. */
    bool advance (double now, float dt);

    /** The value as drawn (eased), in the slider's own units. (Not const:
        Slider::proportionOfLengthToValue() isn't.) */
    double getDisplayValue() { return proportionOfLengthToValue ((double) display.value); }

    /** The parameter's own text for a value in the slider's units (the
        host's text: "48 %", "0.64 s"). */
    juce::String textFor (double sliderValue) const;

    /** The cap, in this component's coordinates. */
    juce::Rectangle<float> capBounds() const noexcept;

    /** Draws the dragged state (the readout) without a mouse: for the
        snapshot tool, which has none. */
    void setDragPreview (bool shouldShow);

    void paint (juce::Graphics&) override;
    void mouseDown (const juce::MouseEvent&) override;
    void mouseDrag (const juce::MouseEvent&) override;
    void mouseUp (const juce::MouseEvent&) override;
    void focusGained (FocusChangeType) override { repaint(); }
    void focusLost (FocusChangeType) override   { repaint(); }
    void enablementChanged() override           { repaint(); }

private:
    void valueChanged() override;
    void showContextMenu();
    void updateReadout (bool show);

    juce::RangedAudioParameter* parameter = nullptr;
    bool bipolar = false;
    float modLow = 0.0f, modHigh = 0.0f;

    motion::Spring display;            // proportion 0..1 along the sweep

    double holdUntil = 0.0;
    bool waveGlide = false;
    bool dragging = false, dragPreview = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (Knob)
};

/**
    A knob bound to a parameter, with its caps `label` under the cap and the
    parameter's own text in `value` under that (Knob card): the column every
    Strip group is made of. `size` is knob-lg 64, knob-md 48 or knob-sm 32;
    the label is the parameter table's `short` name. The attachment is owned,
    so the knob follows the host and the host follows the knob.
*/
class ParameterKnob final : public juce::Component,
                            private juce::Slider::Listener
{
public:
    ParameterKnob (juce::AudioProcessorValueTreeState&, const juce::String& parameterId, const juce::String& label,
                   int size = Tokens::knobMd, const Palette& = front());
    ~ParameterKnob() override;

    Knob& knob() noexcept { return dial; }

    /** Width and height the column needs (the label may be wider than the knob). */
    int getPreferredWidth() const;
    int getPreferredHeight() const { return knobSize + 4 + 12 + 4 + 16; }

    /** One editor frame: the glide (Knob::advance) and the value text. */
    void advance (double now, float dt);

    void resized() override;
    void paint (juce::Graphics&) override;

private:
    void sliderValueChanged (juce::Slider*) override;

    const Palette& colours;
    const juce::String label;
    const int knobSize;
    Knob dial;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> attachment;
    juce::String valueText;
};

} // namespace oberli::ui
