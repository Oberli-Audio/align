#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "Buttons.h"
#include "PresetLibrary.h"

namespace oberli::ui
{

/**
    The PresetDrawer card: the preset browser, sliding in from the left
    under the header when you click the preset's name. 380 px of
    `surface-raised` with a `line-control` right edge and `shadow-pop`.
    Left, the categories as ghost buttons - the plugin's own, in presets.csv's
    order, then Yours, the open one on `hover` - and below them Export… and
    Show folder. Right, a
    search field and the presets as 28 px rows, A to Z; the current one on
    `surface-panel` with a 6 px `accent` dot.

    One click loads a preset and leaves the drawer open, so you can audition
    one after another. Your own presets carry a delete button. Esc, a click
    on the controls or on the preset name again closes it. Keyboard: the
    arrows move through the list, Enter loads, typing goes to the search.
    The User folder is read again every time the drawer opens (D.6.5).
    It talks to the plugin only through PresetHost.
*/
class PresetDrawer final : public juce::Component
{
public:
    static constexpr int kWidth = 380;

    explicit PresetDrawer (PresetHost&);
    ~PresetDrawer() override;

    std::function<void()> onDismiss;
    std::function<void()> onExport;

    /** Opens with the panel at `panelInParent`. */
    void open (juce::Rectangle<int> panelInParent);
    void close();

    /** Every editor frame while open: follows the current preset and your
        presets as they change elsewhere (the host, a save). */
    void refresh();

    bool hitTest (int x, int y) override;
    void paint (juce::Graphics&) override;
    void paintOverChildren (juce::Graphics&) override;
    void resized() override;
    bool keyPressed (const juce::KeyPress&) override;

private:
    class Row;
    class CategoryButton;

    struct Entry
    {
        juce::String name;
        bool user = false;
        int index = 0;       // into factoryPresets() or userPresets()
    };

    std::vector<Entry> entriesToShow() const;
    void rebuildRows();
    void layOutRows();
    void load (const Entry&);
    void moveKeyHighlight (int delta);
    void selectCategory (const juce::String&);

    PresetHost& presets;

    juce::StringArray categoryKeys;   // presets.csv's categories, then "" for Yours
    juce::OwnedArray<CategoryButton> categoryButtons;
    juce::String category;

    struct KeyForwarder final : juce::KeyListener
    {
        std::function<bool (const juce::KeyPress&)> handler;
        bool keyPressed (const juce::KeyPress& key, juce::Component*) override { return handler != nullptr && handler (key); }
    };

    juce::TextEditor search;
    KeyForwarder searchKeys;
    juce::Viewport list;
    juce::Component listContent;
    juce::OwnedArray<Row> rows;
    std::vector<Entry> shown;
    int keyRow = -1;

    // Quiet actions at the foot of the categories, drawn as they are.
    std::unique_ptr<CategoryButton> exportButton, folderButton;

    juce::Rectangle<int> panel, nav, listArea;
    juce::String emptyText;

    int seenKind = -1, seenIndex = -1;
    size_t seenUserCount = 0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PresetDrawer)
};

} // namespace oberli::ui
