#include "AboutPanel.h"


namespace oberli::ui
{

namespace
{
    constexpr int kBarHeight = 48;
    constexpr float kFadeSeconds = 0.15f;
    constexpr int kRowHeight = 24;

    /** The licence files are wrapped at 80 columns; the card is narrower, so
        their prose is joined back into paragraphs. Headings, list items,
        table rows and indented lines keep their own line. */
    juce::String reflow (const juce::String& text)
    {
        const auto lines = juce::StringArray::fromLines (text);
        juce::String result;

        const auto standsAlone = [] (const juce::String& line)
        {
            return line.isEmpty() || line.startsWithChar ('#') || line.startsWithChar ('-') || line.startsWithChar ('*')
                || line.startsWithChar ('|') || line.startsWithChar (' ') || line.startsWithChar ('>');
        };

        for (int i = 0; i < lines.size(); ++i)
        {
            result << lines[i];

            if (i + 1 < lines.size())
                result << (! standsAlone (lines[i]) && ! standsAlone (lines[i + 1]) ? " " : "\n");
        }

        return result;
    }

}

AboutPanel::AboutPanel (const juce::String& name, const juce::String& versionText, const juce::String& whatText,
                        const juce::String& ownLineText, const juce::String& licencesToShow)
    : productName (name), version (versionText), what (whatText), ownLine (ownLineText),
      lockup (logo::lockup (back())),
      backButton ("Back to the panel", ActionButton::Variant::ghost, back(), icons::Id::chevronLeft),
      copyButton ("Copy details", ActionButton::Variant::primary, back()),
      licencesButton ("Licences", ActionButton::Variant::secondary, back())
{
    setOpaque (true);
    setWantsKeyboardFocus (true);
    setTitle ("About " + productName);

    backButton.onClick = [this] { hide(); };

    copyButton.setTooltip ("Copies these details as plain text, to paste into a message about a problem.");
    copyButton.onClick = [this]
    {
        juce::SystemClipboard::copyTextToClipboard (lines.joinIntoString ("\n"));
        copyButton.setButtonText ("Copied");

        juce::Component::SafePointer<AboutPanel> safe (this);
        juce::Timer::callAfterDelay (1500, [safe]
        {
            if (safe != nullptr)
                safe->copyButton.setButtonText ("Copy details");
        });
    };

    licencesButton.setTooltip ("The licence of " + productName + " and of the parts it is built with.");
    licencesButton.onClick = [this] { showLicences (! licencesShown); };

    for (auto* b : { &backButton, &copyButton, &licencesButton })
        addAndMakeVisible (b);

    licencesText.setMultiLine (true);
    licencesText.setReadOnly (true);
    licencesText.setScrollbarsShown (true);
    licencesText.setCaretVisible (false);
    licencesText.setFont (type::small());   // long text: Nunito
    licencesText.setColour (juce::TextEditor::backgroundColourId, back().surfaceRaised);
    licencesText.setColour (juce::TextEditor::textColourId, back().ink);
    licencesText.setColour (juce::TextEditor::outlineColourId, juce::Colours::transparentBlack);
    licencesText.setColour (juce::TextEditor::focusedOutlineColourId, juce::Colours::transparentBlack);
    licencesText.setColour (juce::TextEditor::highlightColourId, back().line);
    licencesText.setColour (juce::TextEditor::highlightedTextColourId, back().ink);
    licencesText.setColour (juce::ScrollBar::thumbColourId, back().lineControl);
    licences = licencesToShow;
    licencesText.setTitle ("Licences");
    addChildComponent (licencesText);

    setVisible (false);
}

AboutPanel::~AboutPanel() = default;

void AboutPanel::show (const juce::StringArray& diagnostics, bool openLicences)
{
    lines = diagnostics;
    updateCardText();
    showLicences (openLicences);
    closing = false;

    if (! isVisible())
    {
        opacity.value = 0.0f;
        setAlpha (0.0f);
    }

    setVisible (true);
    toFront (false);
    grabKeyboardFocus();
    repaint();
}

void AboutPanel::hide()
{
    closing = true;
}

void AboutPanel::advance (float dt)
{
    if (! isVisible())
        return;

    if (opacity.advance (closing ? 0.0f : 1.0f, dt, kFadeSeconds / 3.0f, kFadeSeconds / 3.0f, 2.0e-3f))
        setAlpha (opacity.value);

    if (closing && opacity.value <= 0.0f)
    {
        setVisible (false);
        closing = false;

        if (onClosed)
            onClosed();
    }
}

void AboutPanel::updateCardText()
{
    // Wide: the card draws the details itself and the text field holds the licences. Compact: the
    // text field holds whichever the card shows, so a small window scrolls it.
    if (compact && ! licencesShown)
        licencesText.setText (lines.joinIntoString ("\n") + "\n\nVST is a registered trademark of Steinberg Media Technologies GmbH.", false);
    else
        licencesText.setText (reflow (licences), false);
}

void AboutPanel::showLicences (bool shouldShow)
{
    licencesShown = shouldShow;
    updateCardText();
    licencesText.setVisible (shouldShow || compact);
    licencesButton.setButtonText (shouldShow ? "Details" : "Licences");
    resized();
    repaint();
}

void AboutPanel::resized()
{
    auto r = getLocalBounds();
    bar = r.removeFromTop (kBarHeight);

    backButton.setBounds (bar.reduced (16, 0).removeFromLeft (backButton.getPreferredWidth()).withSizeKeepingCentre (backButton.getPreferredWidth(), 28));

    const auto wasCompact = compact;
    compact = getWidth() < 820 || getHeight() < 520;

    if (compact)
    {
        // One column: the lockup, the name, the version line, the brand line, the buttons, then
        // the card with the details or the licences, scrolling.
        auto body = r.reduced (24, 16);
        left = body;
        lockupBounds = body.removeFromTop (24).withWidth (135);
        body.removeFromTop (8 + 28 + 2 + 16 + 4 + 38 + 8);
        auto buttons = body.removeFromTop (28);
        copyButton.setBounds (buttons.removeFromLeft (copyButton.getPreferredWidth()));
        buttons.removeFromLeft (8);
        licencesButton.setBounds (buttons.removeFromLeft (licencesButton.getPreferredWidth()));
        body.removeFromTop (12);
        detailsCard = body;
        licencesText.setBounds (detailsCard.reduced (12, 8));
        if (wasCompact != compact)
            showLicences (licencesShown);
        return;
    }

    if (wasCompact != compact)
        showLicences (licencesShown);

    auto body = r.reduced (48, 40);
    left = body.removeFromLeft ((body.getWidth() - 48) / 2);
    body.removeFromLeft (48);
    detailsCard = body.withHeight (24 + 14 + 12 + kRowHeight * 14 + 24);

    lockupBounds = left.withHeight (40).withWidth (224);

    // Buttons under the text block: lockup 40, 32, eyebrow 16, 12, name 56,
    // 32, brand line 23, 8, two lines of 23, 8, tagline 19, 32.
    const auto buttonsY = left.getY() + 40 + 32 + 16 + 12 + 56 + 32 + 23 + 8 + 46 + 8 + 19 + 32;
    copyButton.setBounds (left.getX(), buttonsY, copyButton.getPreferredWidth(), 32);
    licencesButton.setBounds (copyButton.getRight() + 8, buttonsY, licencesButton.getPreferredWidth(), 32);

    licencesText.setBounds (detailsCard.reduced (24).withTrimmedTop (14 + 12).withTrimmedRight (-12));
}

void AboutPanel::paint (juce::Graphics& g)
{
    g.fillAll (back().ground);

    // --- The bar.
    g.setColour (back().surfaceRaised);
    g.fillRect (bar);
    g.setColour (back().line);
    g.fillRect (bar.removeFromBottom (1));

    if (compact)
    {
        if (lockup != nullptr)
            lockup->drawWithin (g, lockupBounds.toFloat(), juce::RectanglePlacement::xLeft | juce::RectanglePlacement::yMid, 1.0f);

        const auto x = (float) left.getX(), w = (float) left.getWidth();
        auto y = (float) lockupBounds.getBottom() + 8.0f;
        type::draw (g, productName, { x, y, w, 28.0f }, type::title(), back().ink);
        y += 28.0f + 2.0f;
        type::draw (g, "OBERLI AUDIO  " + juce::String::fromUTF8 ("\xc2\xb7") + "  VERSION " + version, { x, y, w, 16.0f },
                    type::eyebrow(), back().inkMuted);
        y += 16.0f + 4.0f;
        g.setColour (back().inkMuted);
        g.setFont (type::small());
        g.drawFittedText ("Turn it and listen. " + what + (ownLine.isNotEmpty() ? " " + ownLine : juce::String()),
                          juce::Rectangle<float> (x, y, w, 38.0f).toNearestInt(), juce::Justification::topLeft, 2, 1.0f);

        const auto card = detailsCard.toFloat();
        g.setColour (back().surfaceRaised);
        g.fillRoundedRectangle (card, Tokens::radiusLg);
        g.setColour (back().line);
        g.drawRoundedRectangle (card.reduced (0.5f), Tokens::radiusLg - 0.5f, 1.0f);
        return;
    }

    // --- Left: who and what.
    if (lockup != nullptr)
        lockup->drawWithin (g, lockupBounds.toFloat(), juce::RectanglePlacement::xLeft | juce::RectanglePlacement::yMid, 1.0f);

    auto y = (float) lockupBounds.getBottom() + 32.0f;
    const auto x = (float) left.getX();
    const auto w = (float) left.getWidth();

    type::draw (g, "OBERLI AUDIO  " + juce::String::fromUTF8 ("\xc2\xb7") + "  VERSION " + version,
                { x, y, w, 16.0f }, type::eyebrow(), back().inkMuted);
    y += 16.0f + 12.0f;

    type::draw (g, productName, { x, y, w, 56.0f }, type::display(), back().ink);
    y += 56.0f + 32.0f;

    type::draw (g, "Turn it and listen.", { x, y, w, 23.0f }, type::font (type::Weight::medium, 15.0f), back().ink);
    y += 23.0f + 8.0f;

    g.setColour (back().inkMuted);
    g.setFont (type::body());
    g.drawFittedText (what,
                      juce::Rectangle<float> (x, y, juce::jmin (w, 420.0f), 46.0f).toNearestInt(),
                      juce::Justification::topLeft, 2, 1.0f);
    y += 46.0f + 8.0f;

    if (ownLine.isNotEmpty())
        type::draw (g, ownLine, { x, y, w, 19.0f }, type::small(), back().inkMuted);

    type::draw (g, "VST is a registered trademark of Steinberg Media Technologies GmbH.",
                { x, (float) left.getBottom() - 19.0f, w, 19.0f }, type::small(), back().inkSubtle);

    // --- Right: the DETAILS card, or the licences in it.
    const auto card = detailsCard.toFloat();
    g.setColour (back().surfaceRaised);
    g.fillRoundedRectangle (card, Tokens::radiusLg);
    g.setColour (back().line);
    g.drawRoundedRectangle (card.reduced (0.5f), Tokens::radiusLg - 0.5f, 1.0f);

    auto inner = detailsCard.reduced (24);
    type::draw (g, licencesShown ? "LICENCES" : "DETAILS", inner.removeFromTop (14).toFloat(), type::section(),
                back().inkMuted);
    inner.removeFromTop (12);

    if (licencesShown)
        return;

    for (const auto& line : lines)
    {
        auto row = inner.removeFromTop (kRowHeight).toFloat();
        g.setColour (back().line);
        g.fillRect (row.removeFromBottom (1.0f).translated (0.0f, 0.0f));

        const auto label = line.upToFirstOccurrenceOf (":", false, false);
        const auto value = line.fromFirstOccurrenceOf (":", false, false).trim();

        type::draw (g, label, row, type::font (type::Weight::regular, 12.0f), back().inkMuted);
        type::draw (g, value, row.withTrimmedLeft (130.0f), type::value(), back().ink, juce::Justification::centredRight);
    }
}

void AboutPanel::paintOverChildren (juce::Graphics& g)
{
    // The focus ring in bone ink.
    for (auto* child : getChildren())
        if (auto* button = dynamic_cast<FlatButton*> (child))
            if (button->hasKeyboardFocus (false))
            {
                g.setColour (back().ink);
                g.drawRoundedRectangle (button->getBounds().toFloat().expanded (4.0f), button->getCorner() + 4.0f, 2.0f);
            }
}

bool AboutPanel::keyPressed (const juce::KeyPress& key)
{
    if (key == juce::KeyPress::escapeKey)
    {
        hide();
        return true;
    }

    return false;
}

} // namespace oberli::ui
