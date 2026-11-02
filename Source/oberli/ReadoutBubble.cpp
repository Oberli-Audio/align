#include "ReadoutBubble.h"

namespace oberli::ui
{

namespace
{
    constexpr float kFadeOut = 0.25f;
}

ReadoutBubble::ReadoutBubble (const Palette& p)
    : colours (p)
{
    setInterceptsMouseClicks (false, false);
    setVisible (false);
}

void ReadoutBubble::showAt (const juce::String& newText, juce::Rectangle<float> anchor, float gap, bool below)
{
    text = newText;

    const auto w = std::ceil (type::width (type::value(), text)) + 16.0f;
    const auto h = 24.0f;
    const auto y = below ? anchor.getBottom() + gap : anchor.getY() - gap - h;
    auto card = juce::Rectangle<float> (anchor.getCentreX() - w * 0.5f, y, w, h);

    // Kept inside the editor, so a knob near an edge never pushes it off.
    if (auto* parent = getParentComponent())
        card = card.constrainedWithin (parent->getLocalBounds().toFloat().reduced (4.0f));

    setBounds (card.getSmallestIntegerContainer().expanded (kShadowMargin));
    opacity.value = 1.0f;
    timed = false;
    setAlpha (1.0f);
    setVisible (true);
    toFront (false);
    repaint();
}

void ReadoutBubble::flash (const juce::String& newText, juce::Rectangle<float> anchor, double now, double seconds)
{
    showAt (newText, anchor, 8.0f, true);
    timed = true;
    flashSeconds = seconds;
    hideAt = now + seconds;
    startClock = now <= 0.0;   // no clock yet: the next frame starts it
}

void ReadoutBubble::hide()
{
    timed = false;
    setVisible (false);
}

void ReadoutBubble::advance (double now, float dt)
{
    if (! timed || ! isVisible())
        return;

    if (startClock)
    {
        hideAt = now + flashSeconds;
        startClock = false;
    }

    if (now < hideAt)
        return;

    if (opacity.advance (0.0f, dt, kFadeOut, kFadeOut, 2.0e-3f))
        setAlpha (opacity.value);

    if (opacity.value <= 0.0f)
        hide();
}

void ReadoutBubble::paint (juce::Graphics& g)
{
    const auto card = getLocalBounds().reduced (kShadowMargin).toFloat();

    juce::Path shape;
    shape.addRoundedRectangle (card, Tokens::radiusSm);
    Tokens::popShadow (colours).drawForPath (g, shape);

    g.setColour (colours.readout);
    g.fillPath (shape);

    type::draw (g, text, card, type::value(), colours.onReadout, juce::Justification::centred);
}

} // namespace oberli::ui
