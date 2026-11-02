#include "HeaderMenu.h"
#include "Folders.h"

namespace oberli::ui
{

namespace
{
    constexpr int kCardWidth = 220;
    constexpr int kSubmenuWidth = 112;
    constexpr int kRowHeight = 28;
    constexpr int kPadding = 4;            // above the first row, below the last
    constexpr int kSeparator = 9;          // 4 px, a 1 px line, 4 px
    constexpr int kShadowMargin = 32;
    constexpr int kTextX = 34;             // 12 px padding, a 14 px icon, 8 px


    juce::String percent (float scale) { return juce::String (juce::roundToInt (scale * 100.0f)) + " %"; }
}

//==============================================================================
class HeaderMenu::Row final : public FlatButton
{
public:
    Row (HeaderMenu& ownerToUse, const juce::String& caption, std::optional<icons::Id> iconToUse = {})
        : FlatButton (caption), owner (ownerToUse), icon (iconToUse)
    {
        setButtonText (caption);
        setWantsKeyboardFocus (false);   // the menu itself takes the keys; its highlight is the focus
    }

    void paintButton (juce::Graphics& g, bool over, bool down) override
    {
        auto r = getLocalBounds().toFloat();

        if (over || down || keyHighlight || (opensSubmenu && owner.submenuOpen))
        {
            g.setColour (front().hover);
            g.fillRect (r);
        }

        r.removeFromLeft (12.0f);
        r.removeFromRight (12.0f);

        if (isScaleChoice)
        {
            if (getToggleState())
            {
                g.setColour (Tokens::accent());
                g.fillEllipse (r.removeFromLeft (6.0f).withSizeKeepingCentre (6.0f, 6.0f));
            }
            else
            {
                r.removeFromLeft (6.0f);
            }

            r.removeFromLeft (8.0f);
            type::draw (g, getButtonText(), r, type::font (type::Weight::medium, 12.0f, 0.0f, true), front().ink);
            return;
        }

        if (icon)
            icons::draw (g, *icon, r.withWidth (14.0f).withSizeKeepingCentre (14.0f, 14.0f), front().ink);

        r.setLeft ((float) kTextX);

        if (opensSubmenu)
        {
            icons::draw (g, icons::Id::chevronRight, r.removeFromRight (14.0f).withSizeKeepingCentre (14.0f, 14.0f), front().ink);
            r.removeFromRight (8.0f);
            const auto trailingFont = type::font (type::Weight::medium, 12.0f, 0.0f, true);
            const auto trailingWidth = std::ceil (type::width (trailingFont, trailing)) + 1.0f;
            type::draw (g, trailing, r.removeFromRight (trailingWidth), trailingFont, front().inkSubtle,
                        juce::Justification::centredRight);
        }

        type::draw (g, getButtonText(), r, type::control(), front().ink);
    }

    void mouseEnter (const juce::MouseEvent& e) override
    {
        FlatButton::mouseEnter (e);

        if (opensSubmenu)
            owner.openScaleSubmenu();
        else if (! isScaleChoice && owner.submenuOpen)
        {
            owner.submenuOpen = false;
            owner.resized();
            owner.repaint();
        }
    }

    void setKeyHighlight (bool shouldHighlight)
    {
        if (keyHighlight != shouldHighlight)
        {
            keyHighlight = shouldHighlight;
            repaint();
        }
    }

    HeaderMenu& owner;
    const std::optional<icons::Id> icon;
    std::function<void()> action;
    juce::String trailing;
    bool opensSubmenu = false, isScaleChoice = false, keyHighlight = false;
    float scale = 1.0f;
};

//==============================================================================
HeaderMenu::HeaderMenu()
{
    setWantsKeyboardFocus (true);
    setTitle (folders::productName() + " menu");

    const auto addRow = [this] (const juce::String& text, std::optional<icons::Id> icon, std::function<void()> action)
    {
        auto* row = rows.add (new Row (*this, text, icon));
        row->action = std::move (action);
        row->onClick = [this, row] { choose (*row); };
        addAndMakeVisible (row);
        return row;
    };

    addRow (juce::String::fromUTF8 ("Load preset\xe2\x80\xa6"), icons::Id::load, [this] { if (onLoadPreset) onLoadPreset(); })
        ->setTooltip ("Import a .oberlipreset file, yours or a friend's.");
    addRow (juce::String::fromUTF8 ("Save preset\xe2\x80\xa6"), icons::Id::save, [this] { if (onSavePreset) onSavePreset(); })
        ->setTooltip ("Save the sound as a preset of your own.");

    scaleRow = addRow ("GUI scale", {}, nullptr);
    scaleRow->opensSubmenu = true;
    scaleRow->setTooltip ("The window's size. Every " + folders::productName() + " on this computer opens at the size you chose last.");

    addRow (juce::String::fromUTF8 ("Report a problem\xe2\x80\xa6"), {}, [this] { if (onReportProblem) onReportProblem(); })
        ->setTooltip ("Copies the details a report needs, to paste into your message.");
    addRow ("About " + folders::productName(), icons::Id::about, [this] { if (onAbout) onAbout(); });

    for (auto s : MachineSettings::kScales)
    {
        auto* row = scaleRows.add (new Row (*this, percent (s)));
        row->isScaleChoice = true;
        row->scale = s;
        row->onClick = [this, row] { choose (*row); };
        addChildComponent (row);
    }

    setVisible (false);
}

HeaderMenu::~HeaderMenu() = default;

void HeaderMenu::open (juce::Point<int> topRight, float scale)
{
    currentScale = scale;
    scaleRow->trailing = percent (scale);

    for (auto* row : scaleRows)
        row->setToggleState (std::abs (row->scale - scale) < 0.01f, juce::dontSendNotification);

    const auto cardHeight = kPadding * 2 + 2 + kRowHeight * rows.size() + kSeparator * 2;
    const auto cardInParent = juce::Rectangle<int> (topRight.x - kCardWidth, topRight.y, kCardWidth, cardHeight);
    const auto submenuHeight = kPadding * 2 + 2 + kRowHeight * scaleRows.size();
    const auto submenuInParent = juce::Rectangle<int> (cardInParent.getX() - 4 - kSubmenuWidth,
                                                       cardInParent.getY() + 1 + kPadding + 2 * kRowHeight + kSeparator - (1 + kPadding),
                                                       kSubmenuWidth, submenuHeight);

    const auto area = cardInParent.getUnion (submenuInParent).expanded (kShadowMargin);
    card = cardInParent - area.getPosition();
    submenu = submenuInParent - area.getPosition();

    submenuOpen = false;
    highlight (-1);
    setBounds (area);
    setVisible (true);
    toFront (false);
    grabKeyboardFocus();
    resized();
}

void HeaderMenu::close()
{
    submenuOpen = false;
    highlight (-1);
    setVisible (false);
}

void HeaderMenu::openScaleSubmenu (bool focusFirst)
{
    if (! submenuOpen)
    {
        submenuOpen = true;
        resized();
        repaint();
    }

    if (focusFirst)
    {
        const auto rowsNow = visibleRows();

        for (size_t i = 0; i < rowsNow.size(); ++i)
            if (rowsNow[i]->isScaleChoice && rowsNow[i]->getToggleState())
                highlight ((int) i);
    }
}

std::vector<HeaderMenu::Row*> HeaderMenu::visibleRows() const
{
    std::vector<Row*> result;

    if (submenuOpen && highlighted >= rows.size())
    {
        for (auto* r : scaleRows)
            result.push_back (r);
    }
    else
    {
        for (auto* r : rows)
            result.push_back (r);

        if (submenuOpen)
            for (auto* r : scaleRows)
                result.push_back (r);
    }

    return result;
}

void HeaderMenu::highlight (int index)
{
    highlighted = index;

    std::vector<Row*> all;
    for (auto* r : rows) all.push_back (r);
    for (auto* r : scaleRows) all.push_back (r);

    for (size_t i = 0; i < all.size(); ++i)
        all[i]->setKeyHighlight ((int) i == index);
}

void HeaderMenu::choose (Row& row)
{
    if (row.opensSubmenu)
    {
        openScaleSubmenu (true);
        return;
    }

    if (row.isScaleChoice)
    {
        const auto scale = row.scale;
        close();

        if (onDismiss) onDismiss();
        if (onScaleChosen) onScaleChosen (scale);
        return;
    }

    const auto action = row.action;
    close();

    if (onDismiss) onDismiss();
    if (action) action();
}

bool HeaderMenu::keyPressed (const juce::KeyPress& key)
{
    // Indices: the main rows first, then the submenu's.
    const auto mainCount = rows.size();
    const auto inSubmenu = submenuOpen && highlighted >= mainCount;
    const auto first = inSubmenu ? mainCount : 0;
    const auto count = inSubmenu ? scaleRows.size() : mainCount;

    if (key == juce::KeyPress::downKey || key == juce::KeyPress::upKey)
    {
        const auto step = key == juce::KeyPress::downKey ? 1 : -1;
        const auto current = highlighted < 0 ? (step > 0 ? -1 : count) : highlighted - first;
        highlight (first + ((current + step) % count + count) % count);
        return true;
    }

    if (key == juce::KeyPress::rightKey && ! inSubmenu && highlighted == rows.indexOf (scaleRow))
    {
        submenuOpen = true;
        resized();
        repaint();

        for (int i = 0; i < scaleRows.size(); ++i)
            if (scaleRows[i]->getToggleState())
                highlight (mainCount + i);

        return true;
    }

    if ((key == juce::KeyPress::leftKey || key == juce::KeyPress::escapeKey) && inSubmenu)
    {
        submenuOpen = false;
        highlight (rows.indexOf (scaleRow));
        resized();
        repaint();
        return true;
    }

    if (key == juce::KeyPress::escapeKey)
    {
        close();
        if (onDismiss) onDismiss();
        return true;
    }

    if ((key == juce::KeyPress::returnKey || key == juce::KeyPress::spaceKey) && highlighted >= 0)
    {
        auto* row = highlighted < mainCount ? rows[highlighted] : scaleRows[highlighted - mainCount];
        choose (*row);
        return true;
    }

    return false;
}

void HeaderMenu::resized()
{
    auto y = card.getY() + 1 + kPadding;
    auto separator = 0;

    for (auto* row : rows)
    {
        // Separators after Save preset… and after GUI scale.
        row->setBounds (card.getX() + 1, y, card.getWidth() - 2, kRowHeight);
        y += kRowHeight;

        if (row == rows[1] || row == scaleRow)
        {
            separatorYs[(size_t) separator++] = y + 4;
            y += kSeparator;
        }
    }

    auto sy = submenu.getY() + 1 + kPadding;

    for (auto* row : scaleRows)
    {
        row->setBounds (submenu.getX() + 1, sy, submenu.getWidth() - 2, kRowHeight);
        row->setVisible (submenuOpen);
        sy += kRowHeight;
    }
}

bool HeaderMenu::hitTest (int x, int y)
{
    return card.contains (x, y) || (submenuOpen && submenu.contains (x, y));
}

void HeaderMenu::paint (juce::Graphics& g)
{
    drawPopCard (g, card.toFloat(), Tokens::radiusMd, front().surfaceRaised, front().lineControl);

    g.setColour (front().line);
    for (auto y : separatorYs)
        g.fillRect (card.getX() + 1, y, card.getWidth() - 2, 1);

    if (submenuOpen)
        drawPopCard (g, submenu.toFloat(), Tokens::radiusMd, front().surfaceRaised, front().lineControl);
}

} // namespace oberli::ui
