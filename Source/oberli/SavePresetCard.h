#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "Buttons.h"

namespace oberli::ui
{

/**
    "Save preset…" from the menu: a small floating card under the header
    (the old row's inline name field, moved): a name field, Cancel and Save.
    Enter saves, Esc cancels; an empty name saves nothing. The new preset
    lands in Yours and becomes the current one.
*/
class SavePresetCard final : public juce::Component
{
public:
    SavePresetCard();

    std::function<void (const juce::String& name)> onSave;
    std::function<void()> onDismiss;

    /** Opens with its top-right corner at `topRight` (parent coordinates). */
    void open (juce::Point<int> topRight);
    void close();

    bool hitTest (int x, int y) override;
    void paint (juce::Graphics&) override;
    void paintOverChildren (juce::Graphics&) override;
    void resized() override;
    bool keyPressed (const juce::KeyPress&) override;

private:
    void commit();
    void dismiss();

    juce::TextEditor name;
    ActionButton cancelButton { "Cancel", ActionButton::Variant::ghost };
    ActionButton saveButton { "Save", ActionButton::Variant::primary };
    juce::Rectangle<int> card;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SavePresetCard)
};

} // namespace oberli::ui
