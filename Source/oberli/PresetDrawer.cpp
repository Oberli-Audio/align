#include "PresetDrawer.h"
#include "Folders.h"

namespace oberli::ui
{

namespace
{
    constexpr int kNavWidth = 120;
    constexpr int kRowHeight = 28;
    constexpr int kShadowMargin = 32;

    const juce::String yours ("Yours");

    /** presets.csv's category, or Yours for the user's own. */
    juce::String categoryLabel (const juce::String& key)
    {
        return key.isEmpty() ? yours : key;
    }
}

//==============================================================================
class PresetDrawer::CategoryButton final : public FlatButton
{
public:
    explicit CategoryButton (const juce::String& label) : FlatButton (label)
    {
        setButtonText (label);
        setTitle (label + " presets");
    }

    void paintButton (juce::Graphics& g, bool over, bool down) override
    {
        const auto bounds = getLocalBounds().toFloat();
        const auto open = getToggleState();

        if (open || over || down)
        {
            g.setColour (front().hover);
            g.fillRoundedRectangle (bounds, Tokens::radiusSm);
        }

        type::draw (g, getButtonText(), bounds.reduced (10.0f, 0.0f), type::control(), open ? front().ink : front().inkMuted);
    }
};

//==============================================================================
class PresetDrawer::Row final : public FlatButton
{
public:
    Row (const juce::String& name, bool isUser)
        : FlatButton (name), user (isUser)
    {
        setButtonText (name);
        setWantsKeyboardFocus (false);   // the drawer's arrow keys move through the rows

        if (user)
        {
            deleteButton = std::make_unique<IconButton> (icons::Id::close, "Delete " + name);
            deleteButton->setTooltip ("Delete \"" + name + "\". It goes to the Trash (the Recycle Bin on Windows), "
                                      "so you can get it back from there.");
            deleteButton->setIconColour (front().inkMuted);
            deleteButton->setWantsKeyboardFocus (false);
            addAndMakeVisible (*deleteButton);
        }
    }

    void setCurrent (bool isCurrent)        { if (current != isCurrent) { current = isCurrent; repaint(); } }
    void setKeyHighlight (bool highlight)   { if (keyHighlight != highlight) { keyHighlight = highlight; repaint(); } }

    void resized() override
    {
        if (deleteButton != nullptr)
            deleteButton->setBounds (getLocalBounds().removeFromRight (kRowHeight).withSizeKeepingCentre (24, 24));
    }

    void paintButton (juce::Graphics& g, bool over, bool down) override
    {
        auto r = getLocalBounds().toFloat();

        if (current || over || down || keyHighlight)
        {
            g.setColour (front().hover);
            g.fillRoundedRectangle (r, Tokens::radiusSm);
        }

        r.removeFromLeft (8.0f);
        const auto dot = r.removeFromLeft (6.0f).withSizeKeepingCentre (6.0f, 6.0f);

        if (current)
        {
            g.setColour (Tokens::accent());
            g.fillEllipse (dot);
        }

        r.removeFromLeft (8.0f);

        if (deleteButton != nullptr)
            r.removeFromRight ((float) kRowHeight);

        type::draw (g, getButtonText(), r, type::control(), front().ink);
    }

    const bool user;
    std::unique_ptr<IconButton> deleteButton;

private:
    bool current = false, keyHighlight = false;
};

//==============================================================================
PresetDrawer::PresetDrawer (PresetHost& host)
    : presets (host),
      exportButton (std::make_unique<CategoryButton> (juce::String::fromUTF8 ("Export\xe2\x80\xa6"))),
      folderButton (std::make_unique<CategoryButton> ("Show folder"))
{
    setTitle ("Presets");
    setWantsKeyboardFocus (true);

    for (const auto& p : presets.factoryPresets())
        categoryKeys.addIfNotAlreadyThere (p.category);

    categoryKeys.add ({});   // Yours
    category = categoryKeys[0];

    for (const auto& key : categoryKeys)
    {
        auto* b = categoryButtons.add (new CategoryButton (categoryLabel (key)));
        b->onClick = [this, key] { selectCategory (key); };
        addAndMakeVisible (b);
    }

    search.setTitle ("Search presets");
    search.setTextToShowWhenEmpty ("Search", front().inkSubtle);
    search.setFont (type::control());
    search.setIndents (10, 6);
    search.setJustification (juce::Justification::centredLeft);
    search.onTextChange = [this] { keyRow = -1; rebuildRows(); };
    search.onEscapeKey = [this] { if (search.isEmpty()) { close(); if (onDismiss) onDismiss(); } else search.clear(); rebuildRows(); };
    search.onReturnKey = [this] { if (! shown.empty()) load (shown[(size_t) juce::jmax (0, keyRow)]); };
    // The arrows move through the list while you type.
    searchKeys.handler = [this] (const juce::KeyPress& key)
    {
        if (key != juce::KeyPress::downKey && key != juce::KeyPress::upKey)
            return false;

        moveKeyHighlight (key == juce::KeyPress::downKey ? 1 : -1);
        return true;
    };
    search.addKeyListener (&searchKeys);
    addAndMakeVisible (search);

    list.setViewedComponent (&listContent, false);
    list.setScrollBarsShown (true, false);
    list.setScrollBarThickness (8);
    addAndMakeVisible (list);

    exportButton->setTitle (exportButton->getButtonText());
    exportButton->setTooltip ("Save the current sound as a .oberlipreset file, to give to a friend.");
    exportButton->onClick = [this] { if (onExport) onExport(); };
    folderButton->setTitle (folderButton->getButtonText());
    folderButton->setTooltip ("Opens the folder where your presets live.");
    folderButton->onClick = []
    {
        const auto root = folders::userFolder();
        root.createDirectory();
        root.revealToUser();
    };
    addAndMakeVisible (*exportButton);
    addAndMakeVisible (*folderButton);

    setVisible (false);
}

PresetDrawer::~PresetDrawer()
{
    search.removeKeyListener (&searchKeys);
}

void PresetDrawer::open (juce::Rectangle<int> panelInParent)
{
    presets.refreshUserPresets();

    // Open on the current preset's category.
    if (presets.activeKind() == PresetHost::Kind::user)
        category = {};
    else if (presets.activeKind() == PresetHost::Kind::factory)
        if (const auto i = presets.activeIndex(); juce::isPositiveAndBelow (i, (int) presets.factoryPresets().size()))
            category = presets.factoryPresets()[(size_t) i].category;

    search.clear();
    keyRow = -1;

    const auto area = panelInParent.withWidth (panelInParent.getWidth() + kShadowMargin)
                                   .withHeight (panelInParent.getHeight() + kShadowMargin);
    panel = panelInParent - area.getPosition();
    setBounds (area);

    setVisible (true);
    rebuildRows();
    toFront (false);
    grabKeyboardFocus();
}

void PresetDrawer::close()
{
    setVisible (false);
}

void PresetDrawer::selectCategory (const juce::String& key)
{
    category = key;
    search.clear();
    keyRow = -1;
    rebuildRows();
}

std::vector<PresetDrawer::Entry> PresetDrawer::entriesToShow() const
{
    const auto query = search.getText().trim();
    std::vector<Entry> result;

    const auto& factory = presets.factoryPresets();
    const auto& user = presets.userPresets();

    for (int i = 0; i < (int) factory.size(); ++i)
        if (query.isNotEmpty() ? factory[(size_t) i].name.containsIgnoreCase (query) : factory[(size_t) i].category == category && category.isNotEmpty())
            result.push_back ({ factory[(size_t) i].name, false, i });

    for (int i = 0; i < (int) user.size(); ++i)
        if (query.isNotEmpty() ? user[(size_t) i].name.containsIgnoreCase (query) : category.isEmpty())
            result.push_back ({ user[(size_t) i].name, true, i });

    std::stable_sort (result.begin(), result.end(), [] (const Entry& a, const Entry& b)
    {
        return a.name.compareNatural (b.name) < 0;
    });

    return result;
}

void PresetDrawer::rebuildRows()
{
    shown = entriesToShow();
    rows.clear();

    for (const auto& entry : shown)
    {
        auto* row = rows.add (new Row (entry.name, entry.user));
        row->setTooltip (entry.user ? juce::String ("Your preset") : presets.factoryPresets()[(size_t) entry.index].description);
        row->onClick = [this, entry] { load (entry); };

        if (row->deleteButton != nullptr)
        {
            // After the click has finished: the rebuild deletes this row.
            row->deleteButton->onClick = [this, index = entry.index]
            {
                // Made here, not as an init-capture of the inner lambda: MSVC reads
                // `this` there as the outer lambda (C2440).
                juce::Component::SafePointer<PresetDrawer> safe (this);

                juce::MessageManager::callAsync ([safe, index]
                {
                    if (safe != nullptr)
                    {
                        safe->presets.deleteUser (index);
                        safe->rebuildRows();
                    }
                });
            };
        }

        listContent.addAndMakeVisible (row);
    }

    const auto query = search.getText().trim();
    emptyText = ! shown.empty() ? juce::String()
              : query.isNotEmpty() ? "No preset is called \"" + query + "\"."
                                   : juce::String::fromUTF8 ("Presets you save show up here. Use Save preset\xe2\x80\xa6 in the menu.");

    for (int i = 0; i < categoryButtons.size(); ++i)
        categoryButtons[i]->setToggleState (query.isEmpty() && categoryKeys[i] == category, juce::dontSendNotification);

    seenUserCount = presets.userPresets().size();
    seenKind = -1;   // the next refresh() marks the current row
    layOutRows();
    refresh();
    repaint();
}

void PresetDrawer::layOutRows()
{
    const auto width = list.getWidth() - (rows.size() * kRowHeight > list.getHeight() ? 10 : 0);

    for (int i = 0; i < rows.size(); ++i)
    {
        rows[i]->setBounds (0, i * kRowHeight, width, kRowHeight);
        rows[i]->setKeyHighlight (i == keyRow);
    }

    listContent.setSize (juce::jmax (1, width), juce::jmax (1, rows.size() * kRowHeight));
}

void PresetDrawer::refresh()
{
    if (! isVisible())
        return;

    if (presets.userPresets().size() != seenUserCount)
    {
        rebuildRows();
        return;
    }

    const auto kind = (int) presets.activeKind();
    const auto index = presets.activeIndex();

    if (kind == seenKind && index == seenIndex)
        return;

    seenKind = kind;
    seenIndex = index;

    for (int i = 0; i < rows.size(); ++i)
    {
        const auto& e = shown[(size_t) i];
        const auto current = (e.user ? PresetHost::Kind::user : PresetHost::Kind::factory) == presets.activeKind()
                             && e.index == index;
        rows[i]->setCurrent (current);
    }
}

void PresetDrawer::load (const Entry& entry)
{
    if (entry.user)
        presets.loadUser (entry.index);
    else
        presets.loadFactory (entry.index);

    seenKind = -1;
    refresh();
}

void PresetDrawer::moveKeyHighlight (int delta)
{
    if (rows.isEmpty())
        return;

    keyRow = keyRow < 0 ? (delta > 0 ? 0 : rows.size() - 1)
                        : juce::jlimit (0, rows.size() - 1, keyRow + delta);

    layOutRows();

    const auto top = keyRow * kRowHeight;
    const auto view = list.getViewPositionY();

    if (top < view)
        list.setViewPosition (0, top);
    else if (top + kRowHeight > view + list.getViewHeight())
        list.setViewPosition (0, top + kRowHeight - list.getViewHeight());
}

bool PresetDrawer::keyPressed (const juce::KeyPress& key)
{
    if (key == juce::KeyPress::downKey || key == juce::KeyPress::upKey)
    {
        moveKeyHighlight (key == juce::KeyPress::downKey ? 1 : -1);
        return true;
    }

    if (key == juce::KeyPress::returnKey && juce::isPositiveAndBelow (keyRow, (int) shown.size()))
    {
        load (shown[(size_t) keyRow]);
        return true;
    }

    if (key == juce::KeyPress::escapeKey)
    {
        close();
        if (onDismiss) onDismiss();
        return true;
    }

    // Typing goes to the search.
    if (! search.hasKeyboardFocus (false) && key.getTextCharacter() >= ' ' && ! key.getModifiers().isCommandDown())
    {
        search.grabKeyboardFocus();
        search.insertTextAtCaret (juce::String::charToString (key.getTextCharacter()));
        return true;
    }

    return false;
}

bool PresetDrawer::hitTest (int x, int y)
{
    return panel.contains (x, y);
}

void PresetDrawer::resized()
{
    nav = panel.withWidth (kNavWidth);
    auto navInner = nav.reduced (8, 12);

    for (auto* b : categoryButtons)
    {
        b->setBounds (navInner.removeFromTop (28));
        navInner.removeFromTop (2);
    }

    folderButton->setBounds (navInner.removeFromBottom (28));
    navInner.removeFromBottom (2);
    exportButton->setBounds (navInner.removeFromBottom (28));

    auto right = panel.withTrimmedLeft (kNavWidth + 1).withTrimmedRight (1).reduced (12);
    search.setBounds (right.removeFromTop (28));
    right.removeFromTop (8);
    listArea = right;
    list.setBounds (right);
    layOutRows();
}

void PresetDrawer::paint (juce::Graphics& g)
{
    const auto p = panel.toFloat();

    juce::Path shape;
    shape.addRectangle (p);
    Tokens::popShadow().drawForPath (g, shape);

    g.setColour (front().surfaceRaised);
    g.fillRect (p);

    g.setColour (front().lineControl);
    g.fillRect (p.withLeft (p.getRight() - 1.0f));

    g.setColour (front().line);
    g.fillRect (juce::Rectangle<float> ((float) nav.getRight(), p.getY(), 1.0f, p.getHeight()));

    if (emptyText.isNotEmpty())
    {
        g.setColour (front().inkMuted);
        g.setFont (type::small());
        g.drawFittedText (emptyText, listArea.reduced (8), juce::Justification::topLeft, 4, 1.0f);
    }
}

void PresetDrawer::paintOverChildren (juce::Graphics& g)
{
    drawChildFocusRings (g, *this);
}

} // namespace oberli::ui
