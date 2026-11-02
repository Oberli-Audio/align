#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "Buttons.h"

#include "PresetLibrary.h"

namespace oberli::ui
{

/**
    The PluginHeader card, 48 px of `surface-raised` with a `line` below: the
    name-only Oberli mark (18 px high, in the colourway of the theme), a
    hairline, the plugin's name in `plugin-name`; on the right an optional
    group of the plugin's own (A/B: setExtra()), the preset pill, the version
    in `meta` / `ink-subtle`, and the ghost menu button.

    The preset pill (`radius-pill`, `line-control` outline, `surface-sunken`
    fill) steps through the presets with its arrows - the factory bank in
    presets.csv's order, then your own, wrapping round - and opens the preset
    drawer when you click the name; its border turns `ink` while the drawer is
    open. An edited preset (PresetHost::isActiveModified(), compared, not
    tracked) shows " *" in `accent-ink`.

    No button takes keyboard focus on a click, so the space bar keeps reaching
    the host; Tab reaches every one, with the 2 px `ink` ring. refresh() runs
    every editor frame and repaints only what changed.
*/
class PluginHeader final : public juce::Component
{
public:
    static constexpr int kHeight = 48;

    PluginHeader (PresetHost&, const juce::String& productName, const juce::String& version);
    ~PluginHeader() override;

    std::function<void()> onMenuClicked, onPresetNameClicked;

    /** A group of the plugin's own left of the preset pill (the A/B group:
        a SegmentedControl and a copy IconButton), `width` px wide. Not owned. */
    void setExtra (juce::Component* extra, int width);

    /** The narrowest the header can be with every item at its size and a preset name of the
        pill's minimum width: the window is never narrower (StripEditor::setBodySize). */
    int getMinimumWidth() const;

    /** Re-reads the preset and the edited mark. */
    void refresh();

    void setDrawerOpen (bool isOpen);
    void setMenuOpen (bool isOpen);

    /** The controls that open the overlays: a click on them toggles their
        overlay rather than counting as a click outside it. */
    juce::Component& getMenuButton() noexcept;
    juce::Component& getPresetNameButton() noexcept;

    void paint (juce::Graphics&) override;
    void paintOverChildren (juce::Graphics&) override;
    void resized() override;

private:
    class PresetNameButton;

    PresetHost& presets;
    const juce::String productName, version;
    std::unique_ptr<juce::Drawable> mark;

    juce::Component* extra = nullptr;
    int extraWidth = 0;

    IconButton previousButton { icons::Id::chevronLeft, "Previous preset", true };
    IconButton nextButton { icons::Id::chevronRight, "Next preset", true };
    IconButton menuButton { icons::Id::menu, "Menu" };
    std::unique_ptr<PresetNameButton> presetName;

    juce::Rectangle<float> markBounds;
    juce::Rectangle<int> dividerBounds, nameBounds, pillBounds, versionBounds;
    bool drawerOpen = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginHeader)
};

} // namespace oberli::ui
