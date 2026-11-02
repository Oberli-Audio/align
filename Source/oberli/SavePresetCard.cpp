#include "SavePresetCard.h"

namespace oberli::ui
{

namespace
{
    constexpr int kWidth = 260;
    constexpr int kHeight = 12 + 16 + 8 + 28 + 12 + 28 + 12;
    constexpr int kShadowMargin = 32;
}

SavePresetCard::SavePresetCard()
{
    setTitle ("Save preset");
    setWantsKeyboardFocus (true);

    name.setTitle ("Preset name");
    name.setTextToShowWhenEmpty ("Preset name", front().inkSubtle);
    name.setFont (type::control());
    name.setIndents (10, 6);
    name.setJustification (juce::Justification::centredLeft);
    name.onReturnKey = [this] { commit(); };
    name.onEscapeKey = [this] { dismiss(); };
    addAndMakeVisible (name);

    cancelButton.onClick = [this] { dismiss(); };
    saveButton.onClick = [this] { commit(); };
    saveButton.setTooltip ("Save the current sound under this name, in Yours.");
    addAndMakeVisible (cancelButton);
    addAndMakeVisible (saveButton);

    setVisible (false);
}

void SavePresetCard::open (juce::Point<int> topRight)
{
    const auto cardInParent = juce::Rectangle<int> (topRight.x - kWidth, topRight.y, kWidth, kHeight);
    const auto area = cardInParent.expanded (kShadowMargin);
    card = cardInParent - area.getPosition();
    setBounds (area);

    name.clear();
    setVisible (true);
    toFront (false);
    name.grabKeyboardFocus();
}

void SavePresetCard::close()
{
    setVisible (false);
}

void SavePresetCard::commit()
{
    const auto text = name.getText().trim();

    if (text.isEmpty())
        return;

    close();

    if (onSave) onSave (text);
    if (onDismiss) onDismiss();
}

void SavePresetCard::dismiss()
{
    close();

    if (onDismiss) onDismiss();
}

bool SavePresetCard::keyPressed (const juce::KeyPress& key)
{
    if (key == juce::KeyPress::escapeKey)
    {
        dismiss();
        return true;
    }

    return false;
}

void SavePresetCard::resized()
{
    auto r = card.reduced (12);
    r.removeFromTop (16 + 8);
    name.setBounds (r.removeFromTop (28));
    r.removeFromTop (12);

    auto buttons = r.removeFromTop (28);
    saveButton.setBounds (buttons.removeFromRight (saveButton.getPreferredWidth()));
    buttons.removeFromRight (8);
    cancelButton.setBounds (buttons.removeFromRight (cancelButton.getPreferredWidth()));
}

bool SavePresetCard::hitTest (int x, int y)
{
    return card.contains (x, y);
}

void SavePresetCard::paint (juce::Graphics& g)
{
    drawPopCard (g, card.toFloat(), Tokens::radiusMd, front().surfaceRaised, front().lineControl);

    const auto title = card.reduced (12).removeFromTop (16).toFloat();
    type::draw (g, "Save preset", title, type::font (type::Weight::semibold, 12.0f), front().ink);
}

void SavePresetCard::paintOverChildren (juce::Graphics& g)
{
    drawChildFocusRings (g, *this);
}

} // namespace oberli::ui
