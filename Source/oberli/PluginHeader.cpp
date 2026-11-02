#include "PluginHeader.h"

namespace oberli::ui
{

namespace
{
    constexpr int kSide = 16;          // space-4
    constexpr int kGap = 12;           // space-3, between header items
    constexpr int kControlHeight = 28;
    constexpr int kHit = 24;           // hit-min
    constexpr int kNameMinWidth = 148;

    const juce::String editedMark (" *");
}

//==============================================================================
/** The preset's name inside the pill; a click opens the drawer. */
class PluginHeader::PresetNameButton final : public FlatButton
{
public:
    PresetNameButton() : FlatButton ("Presets")
    {
        setTooltip ("All presets: browse, search and audition them.");
    }

    void set (const juce::String& newName, bool isEdited, bool isEmpty)
    {
        // Called every frame: only a change repaints.
        if (newName == name && isEdited == edited && isEmpty == empty)
            return;

        name = newName;
        edited = isEdited;
        empty = isEmpty;
        setTitle ("Preset: " + name + (edited ? ", edited" : "") + ". Opens the preset list.");
        repaint();
    }

    int getPreferredWidth() const
    {
        const auto nameWidth = type::width (type::control(), name + (edited ? editedMark : juce::String()));
        return juce::jmax (kNameMinWidth, juce::roundToInt (std::ceil (nameWidth)) + 16);
    }

    float getCorner() const override { return Tokens::radiusSm; }

    void paintButton (juce::Graphics& g, bool highlighted, bool down) override
    {
        const auto bounds = getLocalBounds().toFloat();

        if (highlighted || down)
        {
            g.setColour (front().hover);
            g.fillRoundedRectangle (bounds, Tokens::radiusSm);
        }

        const auto font = type::control();
        const auto nameWidth = type::width (font, name);
        const auto markWidth = edited ? type::width (font, editedMark) : 0.0f;
        auto line = bounds.withSizeKeepingCentre (nameWidth + markWidth, bounds.getHeight());

        type::draw (g, name, line.removeFromLeft (nameWidth), font, empty ? front().inkMuted : front().ink);

        if (edited)
            type::draw (g, editedMark, line, font, front().accentInk);
    }

private:
    juce::String name;
    bool edited = false, empty = false;
};

//==============================================================================
PluginHeader::PluginHeader (PresetHost& host, const juce::String& name, const juce::String& versionText)
    : presets (host),
      productName (name),
      version (versionText),
      mark (logo::nameOnly (front())),
      presetName (std::make_unique<PresetNameButton>())
{
    setOpaque (true);

    previousButton.onClick = [this] { presets.step (-1); refresh(); };
    nextButton.onClick = [this] { presets.step (1); refresh(); };
    nextButton.setTooltip ("Next preset: the factory presets, then your own");

    presetName->onClick = [this] { if (onPresetNameClicked != nullptr) onPresetNameClicked(); };
    menuButton.onClick = [this] { if (onMenuClicked != nullptr) onMenuClicked(); };

    for (juce::Component* c : { (juce::Component*) &previousButton, (juce::Component*) presetName.get(),
                                (juce::Component*) &nextButton, (juce::Component*) &menuButton })
        addAndMakeVisible (c);

    refresh();
}

PluginHeader::~PluginHeader() = default;

juce::Component& PluginHeader::getMenuButton() noexcept        { return menuButton; }
juce::Component& PluginHeader::getPresetNameButton() noexcept  { return *presetName; }

void PluginHeader::setExtra (juce::Component* component, int width)
{
    if (extra != nullptr)
        removeChildComponent (extra);

    extra = component;
    extraWidth = width;

    if (extra != nullptr)
        addAndMakeVisible (extra);

    resized();
    repaint();
}

int PluginHeader::getMinimumWidth() const
{
    const auto nameWidth = juce::roundToInt (std::ceil (type::width (type::pluginName(), productName))) + 2;
    const auto versionWidth = juce::roundToInt (std::ceil (type::width (type::meta(), version))) + 1;
    return kSide + 69 + 5 + kGap + 1 + kGap + nameWidth + kGap + (2 + kHit + kNameMinWidth + kHit + 2) + kGap + versionWidth
         + kGap + kHit + kSide + (extra != nullptr ? kGap + extraWidth : 0) + kGap;
}

void PluginHeader::setDrawerOpen (bool isOpen)
{
    if (drawerOpen != isOpen)
    {
        drawerOpen = isOpen;
        repaint (pillBounds.expanded (1));
    }
}

void PluginHeader::setMenuOpen (bool isOpen)
{
    menuButton.setActive (isOpen);
}

void PluginHeader::refresh()
{
    auto name = presets.activeName();
    const auto none = name.isEmpty() || presets.activeKind() == PresetHost::Kind::none;

    if (none)
        name = "No preset";

    const auto edited = ! none && presets.isActiveModified();
    const auto previousWidth = presetName->getPreferredWidth();

    presetName->set (name, edited, none);

    if (presetName->getPreferredWidth() != previousWidth)
    {
        resized();
        repaint();
    }
}

void PluginHeader::resized()
{
    auto r = getLocalBounds().withTrimmedBottom (1).reduced (kSide, 0);
    const auto centreY = (float) r.getCentreY();

    // --- Left: the mark (its drawing is 2932 x 763 units), a hairline, the plugin's name.
    markBounds = juce::Rectangle<float> ((float) r.getX(), centreY - 9.0f, 69.0f, 18.0f);
    r.removeFromLeft (69 + 5 + kGap);
    dividerBounds = r.removeFromLeft (1).withSizeKeepingCentre (1, 20);
    r.removeFromLeft (kGap);
    nameBounds = r.removeFromLeft (juce::roundToInt (std::ceil (type::width (type::pluginName(), productName))) + 2);

    // --- Right, from the edge in: menu, version, preset pill, the plugin's own group.
    const auto centred = [&] (juce::Rectangle<int> column, int height) { return column.withSizeKeepingCentre (column.getWidth(), height); };

    menuButton.setBounds (centred (r.removeFromRight (kHit), kHit));
    r.removeFromRight (kGap);

    versionBounds = r.removeFromRight (juce::roundToInt (std::ceil (type::width (type::meta(), version))) + 1);
    r.removeFromRight (kGap);

    const auto nameWidth = presetName->getPreferredWidth();
    pillBounds = centred (r.removeFromRight (2 + kHit + nameWidth + kHit + 2), kControlHeight);
    {
        auto pill = pillBounds.reduced (2, 0);
        previousButton.setBounds (centred (pill.removeFromLeft (kHit), kHit));
        nextButton.setBounds (centred (pill.removeFromRight (kHit), kHit));
        presetName->setBounds (centred (pill, kHit));
    }

    if (extra != nullptr)
    {
        r.removeFromRight (kGap);
        extra->setBounds (centred (r.removeFromRight (extraWidth), kControlHeight));
    }
}

void PluginHeader::paint (juce::Graphics& g)
{
    const auto& t = front();
    g.fillAll (t.surfaceRaised);

    g.setColour (t.line);
    g.fillRect (getLocalBounds().removeFromBottom (1));
    g.fillRect (dividerBounds);

    if (mark != nullptr)
        mark->drawWithin (g, markBounds, juce::RectanglePlacement::centred, 1.0f);

    type::draw (g, productName, nameBounds.toFloat(), type::pluginName(), t.ink);
    type::draw (g, version, versionBounds.toFloat(), type::meta(), t.inkSubtle);

    // The preset pill.
    const auto pill = pillBounds.toFloat();
    g.setColour (t.surfaceSunken);
    g.fillRoundedRectangle (pill, pill.getHeight() * 0.5f);
    g.setColour (drawerOpen ? t.ink : t.lineControl);
    g.drawRoundedRectangle (pill.reduced (0.5f), pill.getHeight() * 0.5f - 0.5f, 1.0f);
}

void PluginHeader::paintOverChildren (juce::Graphics& g)
{
    drawChildFocusRings (g, *this);
}

} // namespace oberli::ui
