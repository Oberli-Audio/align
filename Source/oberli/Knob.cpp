#include "Knob.h"
#include "ReadoutBubble.h"

namespace oberli::ui
{

namespace
{
    // motion::Spring speeds: following automation (~0.15 s, close enough to
    // the sound that the knob never looks late) and the slower wave after a
    // preset recall or on open (~0.45 s per knob).
    constexpr float kFollowOmega = 30.0f;
    constexpr float kWaveOmega = 10.5f;

    // Under 1/2000 of the sweep (0.14 degrees) is below anything visible.
    constexpr float kSettleEpsilon = 5.0e-4f;
}

Knob::Knob()
    : juce::Slider (juce::Slider::RotaryHorizontalVerticalDrag, juce::Slider::NoTextBox)
{
    // knob-sweep: 270 degrees, the gap centred at the bottom.
    setRotaryParameters (juce::MathConstants<float>::pi * 1.25f, juce::MathConstants<float>::pi * 2.75f, true);

    // Shift held: fine adjustment (the Knob card), JUCE's velocity mode at a
    // quarter of the speed instead of its default Ctrl/Alt/Cmd swap.
    setVelocityModeParameters (0.25, 1, 0.0, true, juce::ModifierKeys::shiftModifier);

    // Kept as an image: a knob that has not changed is copied, not drawn
    // again, when the level bars and the meter beside it repaint.
    setBufferedToImage (true);
}

void Knob::bindParameter (juce::RangedAudioParameter& parameterToUse, const juce::String& accessibleName)
{
    parameter = &parameterToUse;

    setDoubleClickReturnValue (true, (double) parameter->convertFrom0to1 (parameter->getDefaultValue()));
    setTitle (accessibleName);
    setWantsKeyboardFocus (true);
    setMouseClickGrabsKeyboardFocus (false);
}

juce::String Knob::textFor (double sliderValue) const
{
    if (parameter == nullptr)
        return juce::String (juce::roundToInt (sliderValue));

    return parameter->getText (parameter->convertTo0to1 ((float) sliderValue), 0);
}

juce::Rectangle<float> Knob::capBounds() const noexcept
{
    const auto box = getLocalBounds().toFloat();
    const auto size = juce::jmin (box.getWidth(), box.getHeight());
    return juce::Rectangle<float> (0.72f * size, 0.72f * size).withCentre (box.getCentre());
}

void Knob::mouseDown (const juce::MouseEvent& e)
{
    if (e.mods.isPopupMenu() && parameter != nullptr)
    {
        showContextMenu();
        return;
    }

    juce::Slider::mouseDown (e);
    dragging = true;
    updateReadout (true);
}

void Knob::mouseDrag (const juce::MouseEvent& e)
{
    juce::Slider::mouseDrag (e);
    updateReadout (dragging);
}

void Knob::mouseUp (const juce::MouseEvent& e)
{
    juce::Slider::mouseUp (e);
    dragging = false;
    updateReadout (dragPreview);
}

void Knob::setDragPreview (bool shouldShow)
{
    dragPreview = shouldShow;
    updateReadout (shouldShow);
}

void Knob::updateReadout (bool show)
{
    if (auto* host = findParentComponentOfClass<ReadoutHost>())
    {
        if (show)
            host->showDragReadout (*this, capBounds(), textFor (getValue()));
        else
            host->hideDragReadout();
    }
}

void Knob::showContextMenu()
{
    if (auto* editor = findParentComponentOfClass<juce::AudioProcessorEditor>())
    {
        if (auto* host = editor->getHostContext())
        {
            if (auto menu = host->getContextMenuForParameter (parameter))
            {
                menu->showNativeMenu (editor->getMouseXYRelative());
                return;
            }
        }
    }

    // No host menu (the standalone, or a host without one): reset is the
    // one thing every knob offers.
    juce::PopupMenu menu;
    menu.addItem ("Reset to default", [safe = juce::Component::SafePointer<Knob> (this)]
    {
        if (safe != nullptr)
            safe->setValue (safe->getDoubleClickReturnValue(), juce::sendNotificationSync);
    });
    menu.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (this));
}

void Knob::syncDisplay()
{
    display.snapTo ((float) valueToProportionOfLength (getValue()));
    waveGlide = false;
    holdUntil = 0.0;
    repaint();
}

void Knob::valueChanged()
{
    // Anything done by hand (a drag, or the wheel while hovering) is drawn
    // at once; everything else glides from where the drawing is now.
    if (isMouseButtonDown() || isMouseOver())
        syncDisplay();
    else
        display.target = (float) valueToProportionOfLength (getValue());

    if (dragging || dragPreview)
        updateReadout (true);
}

void Knob::beginWave (double startTime, bool fromZero) noexcept
{
    if (fromZero)
    {
        display.value = 0.0f;
        display.velocity = 0.0f;
    }

    display.target = (float) valueToProportionOfLength (getValue());
    holdUntil = startTime;
    waveGlide = true;
}

bool Knob::advance (double now, float dt)
{
    if (now < holdUntil)
        return false;

    const auto moved = display.advance (dt, waveGlide ? kWaveOmega : kFollowOmega, kSettleEpsilon);

    if (display.isSettled())
        waveGlide = false;

    if (moved)
        repaint();

    return moved;
}

void Knob::setModulationRange (float low, float high)
{
    low = juce::jlimit (0.0f, 1.0f, low);
    high = juce::jlimit (0.0f, 1.0f, high);

    if (juce::exactlyEqual (low, modLow) && juce::exactlyEqual (high, modHigh))
        return;

    modLow = juce::jmin (low, high);
    modHigh = juce::jmax (low, high);
    repaint();
}

void Knob::paint (juce::Graphics& g)
{
    KnobLook look;
    look.proportion = display.value;
    look.bipolar = bipolar;
    look.focused = hasKeyboardFocus (false);
    look.enabled = isEnabled();
    look.modLow = modLow;
    look.modHigh = modHigh;
    drawKnob (g, getLocalBounds().toFloat(), look);
}

//==============================================================================
ParameterKnob::ParameterKnob (juce::AudioProcessorValueTreeState& apvts, const juce::String& parameterId, const juce::String& labelText,
                              int size, const Palette& p)
    : colours (p), label (labelText.toUpperCase()), knobSize (size)
{
    auto* parameter = apvts.getParameter (parameterId);
    jassert (parameter != nullptr);   // the table and the editor disagree: parameters.csv is the source

    attachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (apvts, parameterId, dial);

    if (parameter != nullptr)
        dial.bindParameter (*parameter, parameter->getName (64));

    dial.syncDisplay();
    dial.addListener (this);
    addAndMakeVisible (dial);
    valueText = dial.textFor (dial.getValue());
}

ParameterKnob::~ParameterKnob()
{
    dial.removeListener (this);
}

int ParameterKnob::getPreferredWidth() const
{
    const auto labelWidth = juce::roundToInt (std::ceil (type::width (type::label(), label)));
    return juce::jmax (knobSize, labelWidth, 56);
}

void ParameterKnob::sliderValueChanged (juce::Slider*)
{
    const auto text = dial.textFor (dial.getValue());

    if (text != valueText)
    {
        valueText = text;
        repaint (getLocalBounds().removeFromBottom (16));
    }
}

void ParameterKnob::advance (double now, float dt)
{
    dial.advance (now, dt);
}

void ParameterKnob::resized()
{
    dial.setBounds (getLocalBounds().removeFromTop (knobSize).withSizeKeepingCentre (knobSize, knobSize));
}

void ParameterKnob::paint (juce::Graphics& g)
{
    auto r = getLocalBounds().toFloat();
    r.removeFromTop ((float) knobSize + 4.0f);
    type::draw (g, label, r.removeFromTop (12.0f), type::label(), colours.inkMuted, juce::Justification::centred);
    r.removeFromTop (4.0f);
    type::draw (g, valueText, r.removeFromTop (16.0f), type::value(), colours.ink, juce::Justification::centred);
}

} // namespace oberli::ui
