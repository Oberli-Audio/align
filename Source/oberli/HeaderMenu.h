#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "Buttons.h"

namespace oberli::ui
{

/**
    The Menu card, dropped from the header's menu button - the same items in
    the same order in every Oberli Audio plugin: Load preset…, Save preset…
    | GUI scale › | Report a problem…, About [plugin]. 220 px of
    `surface-raised` with a `line-control` border, `radius-md` and
    `shadow-pop`; 28 px rows in `control` text with 14 px thin-line icons;
    hover and the keyboard's row on `surface-panel`; separators in `line`.
    GUI scale opens its submenu to the side - 75, 100, 125, 150, 200 %
    (MachineSettings::kScales) - its current choice marked with a 6 px
    `accent` dot, the trailing value in `ink-subtle`.

    Drawn inside the editor (never a window of its own), so it scales with
    the GUI scale and shows in the snapshot tool. Keyboard: the arrows move
    through the rows (right opens the submenu, left closes it), Enter
    chooses, Esc closes. Every row is a button with its words as its
    accessible name.
*/
class HeaderMenu final : public juce::Component
{
public:
    HeaderMenu();
    ~HeaderMenu() override;

    std::function<void()> onLoadPreset, onSavePreset, onReportProblem, onAbout, onDismiss;
    std::function<void (float scale)> onScaleChosen;

    /** Opens with the card's top-right corner at `topRight` (parent
        coordinates); `scale` is the current GUI scale. */
    void open (juce::Point<int> topRight, float scale);
    void close();

    /** Opens the GUI scale submenu (hover, the right arrow, or the snapshot). */
    void openScaleSubmenu (bool focusFirst = false);

    bool hitTest (int x, int y) override;
    void paint (juce::Graphics&) override;
    bool keyPressed (const juce::KeyPress&) override;
    void resized() override;

private:
    class Row;

    void choose (Row&);
    void highlight (int index);
    std::vector<Row*> visibleRows() const;

    juce::OwnedArray<Row> rows, scaleRows;
    Row* scaleRow = nullptr;

    juce::Rectangle<int> card, submenu;
    std::array<int, 2> separatorYs {};
    bool submenuOpen = false;
    int highlighted = -1;
    float currentScale = 1.0f;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (HeaderMenu)
};

} // namespace oberli::ui
