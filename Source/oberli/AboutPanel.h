#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "Buttons.h"
#include "Motion.h"

namespace oberli::ui
{

/**
    About is the back of the panel (AboutBack card): "About [plugin]" in the
    menu turns the body to a page in the other theme - bone behind a Charcoal
    instrument, charcoal behind a Bone effect - with a 150 ms cross-fade. A bar
    across the top holds "Back to the panel". Left: the Oberli Audio lockup in
    the page's colourway, the version line, the name, the brand line "Turn it
    and listen.", what the plugin is, its own line if it has one, Copy details
    and Licences, and the trademark sentence. Right: the DETAILS card - the
    diagnostics block (plugin-ui-bob audio-plugins.md 14, ship-bob
    feedback-loop.md 3), on screen so a screenshot carries it - or, after
    Licences, the bundled LICENSE and THIRD_PARTY_NOTICES.md (compiled in,
    never a URL).

    Esc or "Back to the panel" turns it back.
*/
class AboutPanel final : public juce::Component
{
public:
    /** `what` is one or two sentences of what the plugin is; `ownLine` is
        optional; `licences` the text of LICENSE and THIRD_PARTY_NOTICES.md. */
    AboutPanel (const juce::String& productName, const juce::String& version, const juce::String& what,
                const juce::String& ownLine, const juce::String& licences);
    ~AboutPanel() override;

    std::function<void()> onClosed;

    /** Turns the panel round, showing these diagnostics lines ("Label: value"). */
    void show (const juce::StringArray& diagnostics, bool openLicences = false);
    void hide();

    /** One editor frame: the cross-fade. */
    void advance (float dt);

    void paint (juce::Graphics&) override;
    void paintOverChildren (juce::Graphics&) override;
    void resized() override;
    bool keyPressed (const juce::KeyPress&) override;

private:
    void showLicences (bool shouldShow);
    void updateCardText();

    const juce::String productName, version, what, ownLine;
    juce::String licences;
    juce::StringArray lines;
    bool licencesShown = false, closing = false;
    motion::Follower opacity;

    std::unique_ptr<juce::Drawable> lockup;

    ActionButton backButton, copyButton, licencesButton;
    juce::TextEditor licencesText;

    juce::Rectangle<int> bar, left, detailsCard, lockupBounds;
    bool compact = false;   // a window under 820 x 520: one column, the card scrolls (layoutCompact)

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AboutPanel)
};

} // namespace oberli::ui
