#include "Buttons.h"

namespace oberli::ui
{

FlatButton::FlatButton (const juce::String& name, const Palette& p)
    : juce::Button (name), colours (p)
{
    setMouseClickGrabsKeyboardFocus (false);
    setWantsKeyboardFocus (true);
    setTitle (name);
}

void FlatButton::focusGained (FocusChangeType)
{
    if (auto* parent = getParentComponent())
        parent->repaint (getBounds().expanded (6));
}

void FlatButton::focusLost (FocusChangeType)
{
    if (auto* parent = getParentComponent())
        parent->repaint (getBounds().expanded (6));
}

void drawChildFocusRings (juce::Graphics& g, juce::Component& parent)
{
    for (auto* child : parent.getChildren())
        if (auto* button = dynamic_cast<FlatButton*> (child))
            if (button->isVisible() && button->hasKeyboardFocus (false))
                drawFocusRing (g, button->getBounds().toFloat(), button->getCorner(), button->palette());
}

//==============================================================================
IconButton::IconButton (icons::Id iconToUse, const juce::String& label, bool pillShaped, const Palette& p)
    : FlatButton (label, p), icon (iconToUse), pill (pillShaped)
{
    setTooltip (label);
}

void IconButton::setActive (bool isActive)
{
    if (active != isActive)
    {
        active = isActive;
        repaint();
    }
}

void IconButton::setIconColour (juce::Colour c)
{
    colour = c;
    repaint();
}

void IconButton::paintButton (juce::Graphics& g, bool highlighted, bool down)
{
    const auto bounds = getLocalBounds().toFloat();

    if (active || highlighted || down)
    {
        g.setColour (colours.hover);
        g.fillRoundedRectangle (bounds, getCorner());
    }

    icons::draw (g, icon, bounds.withSizeKeepingCentre (16.0f, 16.0f),
                 colour.value_or (colours.ink).withMultipliedAlpha (isEnabled() ? 1.0f : 0.45f));
}

//==============================================================================
ActionButton::ActionButton (const juce::String& caption, Variant v, const Palette& p, std::optional<icons::Id> icon)
    : FlatButton (caption, p), variant (v), leadingIcon (icon)
{
    setButtonText (caption);
}

int ActionButton::getPreferredWidth() const
{
    const auto textWidth = juce::roundToInt (std::ceil (type::width (type::control(), getButtonText())));
    return textWidth + (leadingIcon ? 4 + 16 + 4 + 8 : 24);
}

void ActionButton::paintButton (juce::Graphics& g, bool highlighted, bool down)
{
    const auto bounds = getLocalBounds().toFloat();
    auto ink = colours.ink;

    switch (variant)
    {
        case Variant::primary:
        {
            const auto accent = Tokens::accent();
            g.setColour (down ? accent.darker (0.15f) : (highlighted ? accent.brighter (0.08f) : accent));
            g.fillRoundedRectangle (bounds, Tokens::radiusMd);
            ink = Tokens::onAccent();
            break;
        }

        case Variant::secondary:
            if (highlighted || down)
            {
                g.setColour (colours.hover);
                g.fillRoundedRectangle (bounds, Tokens::radiusMd);
            }

            g.setColour (colours.lineControl);
            g.drawRoundedRectangle (bounds.reduced (0.5f), Tokens::radiusMd - 0.5f, 1.0f);
            break;

        case Variant::ghost:
            if (highlighted || down)
            {
                g.setColour (colours.hover);
                g.fillRoundedRectangle (bounds, Tokens::radiusSm);
            }
            break;
    }

    if (! isEnabled())
        ink = ink.withMultipliedAlpha (0.45f);

    auto area = bounds;

    if (leadingIcon)
    {
        area.removeFromLeft (4.0f);
        icons::draw (g, *leadingIcon, area.removeFromLeft (16.0f).withSizeKeepingCentre (16.0f, 16.0f), ink);
        area.removeFromLeft (4.0f);
        type::draw (g, getButtonText(), area, type::control(), ink, juce::Justification::centredLeft);
    }
    else
    {
        type::draw (g, getButtonText(), area, type::control(), ink, juce::Justification::centred);
    }
}

//==============================================================================
PillToggle::PillToggle (const juce::String& caption, const Palette& p)
    : FlatButton (caption, p)
{
    setButtonText (caption.toUpperCase());
    setClickingTogglesState (true);
}

int PillToggle::getPreferredWidth() const
{
    // 12 px padding, an 8 px LED, 8 px gap, the caps, 12 px padding.
    return 12 + 8 + 8 + juce::roundToInt (std::ceil (type::width (type::label(), getButtonText()))) + 12;
}

void PillToggle::paintButton (juce::Graphics& g, bool highlighted, bool down)
{
    const auto bounds = getLocalBounds().toFloat();
    const auto corner = bounds.getHeight() * 0.5f;
    const auto on = getToggleState();

    juce::Graphics::ScopedSaveState save (g);
    if (! isEnabled())
        g.beginTransparencyLayer (0.45f);

    if (highlighted || down)
    {
        g.setColour (colours.hover);
        g.fillRoundedRectangle (bounds, corner);
    }

    g.setColour (colours.lineControl);
    g.drawRoundedRectangle (bounds.reduced (0.5f), corner - 0.5f, 1.0f);

    auto r = bounds.reduced (12.0f, 0.0f);
    drawLed (g, r.removeFromLeft (8.0f).withSizeKeepingCentre (8.0f, 8.0f), on, colours);
    r.removeFromLeft (8.0f);
    type::draw (g, getButtonText(), r, type::label(), on ? colours.ink : colours.inkMuted);

    if (! isEnabled())
        g.endTransparencyLayer();
}

//==============================================================================
SegmentedControl::SegmentedControl (const juce::StringArray& optionsToShow, const Palette& p)
    : colours (p), options (optionsToShow)
{
    jassert (options.size() >= 2 && options.size() <= 5);   // more than five: a menu (Segmented card)
    setWantsKeyboardFocus (true);
    setMouseClickGrabsKeyboardFocus (false);
}

SegmentedControl::~SegmentedControl() = default;

void SegmentedControl::setSelected (int index, juce::NotificationType notification)
{
    index = juce::jlimit (0, options.size() - 1, index);

    if (index == selected)
        return;

    selected = index;
    repaint();

    if (auto* handler = getAccessibilityHandler())
        handler->notifyAccessibilityEvent (juce::AccessibilityEvent::valueChanged);

    if (notification != juce::dontSendNotification && onChange != nullptr)
        onChange (selected);
}

void SegmentedControl::attach (juce::RangedAudioParameter& parameter, juce::UndoManager* undo)
{
    attachment = std::make_unique<juce::ParameterAttachment> (parameter, [this, &parameter] (float plain)
    {
        const auto start = parameter.getNormalisableRange().start;
        setSelected (juce::roundToInt (plain - start), juce::dontSendNotification);
    }, undo);

    onChange = [this, &parameter] (int index)
    {
        if (attachment != nullptr)
            attachment->setValueAsCompleteGesture (parameter.getNormalisableRange().start + (float) index);
    };

    setTitle (parameter.getName (64));
    attachment->sendInitialUpdate();
}

int SegmentedControl::getPreferredWidth() const
{
    auto w = 2;
    for (const auto& o : options)
        w += juce::roundToInt (std::ceil (type::width (type::controlStrong(), o))) + 24;
    return w;
}

juce::Rectangle<float> SegmentedControl::segment (int index) const
{
    const auto inner = getLocalBounds().toFloat().reduced (1.0f);
    const auto w = inner.getWidth() / (float) options.size();
    return { inner.getX() + w * (float) index, inner.getY(), w, inner.getHeight() };
}

void SegmentedControl::resized() {}

void SegmentedControl::paint (juce::Graphics& g)
{
    const auto bounds = getLocalBounds().toFloat();

    g.setColour (colours.surfaceSunken);
    g.fillRoundedRectangle (bounds, Tokens::radiusMd);

    for (int i = 0; i < options.size(); ++i)
    {
        const auto r = segment (i);
        const auto on = i == selected;

        if (on)
        {
            juce::Path p;
            const auto first = i == 0, last = i == options.size() - 1;
            p.addRoundedRectangle (r.getX(), r.getY(), r.getWidth(), r.getHeight(), Tokens::radiusMd - 1.0f, Tokens::radiusMd - 1.0f,
                                   first, last, first, last);
            g.setColour (Tokens::accent());
            g.fillPath (p);
        }

        type::draw (g, options[i], r, on ? type::controlStrong() : type::control(), on ? Tokens::onAccent() : colours.inkMuted,
                    juce::Justification::centred);
    }

    g.setColour (colours.lineControl);
    g.drawRoundedRectangle (bounds.reduced (0.5f), Tokens::radiusMd - 0.5f, 1.0f);

    if (hasKeyboardFocus (false))
        drawFocusRing (g, bounds, Tokens::radiusMd, colours);
}

void SegmentedControl::mouseDown (const juce::MouseEvent& e)
{
    for (int i = 0; i < options.size(); ++i)
        if (segment (i).contains (e.position))
            setSelected (i);
}

bool SegmentedControl::keyPressed (const juce::KeyPress& key)
{
    if (key == juce::KeyPress::leftKey || key == juce::KeyPress::upKey)   { setSelected (selected - 1); return true; }
    if (key == juce::KeyPress::rightKey || key == juce::KeyPress::downKey) { setSelected (selected + 1); return true; }
    return false;
}

std::unique_ptr<juce::AccessibilityHandler> SegmentedControl::createAccessibilityHandler()
{
    struct Value final : juce::AccessibilityTextValueInterface
    {
        explicit Value (SegmentedControl& o) : owner (o) {}
        bool isReadOnly() const override { return true; }
        juce::String getCurrentValueAsString() const override { return owner.options[owner.selected]; }
        void setValueAsString (const juce::String&) override {}
        SegmentedControl& owner;
    };

    return std::make_unique<juce::AccessibilityHandler> (*this, juce::AccessibilityRole::group,
                                                         juce::AccessibilityActions(),
                                                         juce::AccessibilityHandler::Interfaces { std::make_unique<Value> (*this) });
}

} // namespace oberli::ui
