#include "StripEditor.h"
#include "Folders.h"

namespace oberli::ui
{
namespace
{
    constexpr double kMinFrameInterval = 1.0 / 75.0;
    constexpr double kVBlankTimeout = 0.25;   // no vertical blank this long: the timer drives the frames
    constexpr double kToastSeconds = 2.2;

    // The menu and the save card hang from the header's right end, 4 px up into it.
    constexpr int kOverlayTop = 44;
    constexpr int kOverlayRight = 16;

    constexpr const char* kExtension = ".oberlipreset";
    constexpr int kMinimumHeight = 360;   // the compact About page: lockup, name, buttons and a scrolling card

    bool isWithin (juce::Component& overlay, juce::Component* c)
    {
        return c != nullptr && (&overlay == c || overlay.isParentOf (c));
    }
}

StripEditor::StripEditor (juce::AudioProcessor& processorToUse, PresetHost& presetsToUse, Info infoToUse)
    : AudioProcessorEditor (processorToUse),
      presets (presetsToUse),
      info (std::move (infoToUse)),
      header (presets, info.productName, info.version),
      drawer (presets),
      about (info.productName, info.version, info.what, info.ownLine, info.licences),
      tooltipWindow (this, 600),
      vblank (this, [this]
      {
          lastVBlankTime = clockNow();
          advanceFrame (lastVBlankTime);
      })
{
    setLookAndFeel (&lookAndFeel);
    setWantsKeyboardFocus (false);   // the space bar keeps reaching the host's transport

    addAndMakeVisible (header);
    addChildComponent (drawer);
    addChildComponent (menu);
    addChildComponent (saveCard);
    addChildComponent (about);
    addChildComponent (dragReadout);
    addChildComponent (toast);

    // Overlays close on a click anywhere else.
    addMouseListener (this, true);

    // The ground fills the window edge to edge: the host need not paint behind it.
    setOpaque (true);
    setResizable (false, false);

    seenRecallCount = presets.recallCount();
    setFocusContainerType (FocusContainerType::keyboardFocusContainer);

    header.onMenuClicked = [this] { toggleMenu(); };
    header.onPresetNameClicked = [this] { togglePresetDrawer(); };

    menu.onDismiss = [this] { header.setMenuOpen (false); };
    menu.onLoadPreset = [this] { importPresetFile(); };
    menu.onSavePreset = [this] { showSavePresetCard(); };
    menu.onReportProblem = [this] { reportProblem(); };
    menu.onAbout = [this] { showAbout(); };
    menu.onScaleChosen = [this] (float scale)
    {
        MachineSettings::setGuiScale (scale);
        applyScale();
    };

    drawer.onDismiss = [this] { header.setDrawerOpen (false); };
    drawer.onExport = [this] { exportPresetFile(); };

    saveCard.onSave = [this] (const juce::String& name)
    {
        if (const auto error = presets.saveUser (name); error.isNotEmpty())
            juce::AlertWindow::showMessageBoxAsync (juce::MessageBoxIconType::WarningIcon, "Preset not saved", error);
        header.refresh();
    };

    applyScale();
    startTimerHz (30);
}

StripEditor::~StripEditor()
{
    stopTimer();
    removeMouseListener (this);
    setLookAndFeel (nullptr);
}

void StripEditor::setBodySize (int width, int height)
{
    bodyWidth = width;
    bodyHeight = height;
    // Never narrower than the header needs, never lower than About's compact page needs.
    setSize (juce::jmax (width + 2 * Tokens::bodyPadding, header.getMinimumWidth()),
             juce::jmax (kMinimumHeight, PluginHeader::kHeight + height + 2 * Tokens::bodyPadding));
}

//==============================================================================
void StripEditor::closeOverlays()
{
    if (menu.isVisible())
    {
        menu.close();
        header.setMenuOpen (false);
    }

    if (drawer.isVisible())
    {
        drawer.close();
        header.setDrawerOpen (false);
    }

    if (saveCard.isVisible())
        saveCard.close();
}

void StripEditor::toggleMenu()
{
    if (menu.isVisible())
        closeOverlays();
    else
        showMenu();
}

void StripEditor::showMenu (bool scaleSubmenu)
{
    closeOverlays();
    menu.open ({ getWidth() - kOverlayRight, kOverlayTop }, MachineSettings::guiScale());
    header.setMenuOpen (true);

    if (scaleSubmenu)
        menu.openScaleSubmenu();
}

void StripEditor::togglePresetDrawer()
{
    if (drawer.isVisible())
        closeOverlays();
    else
        showPresetDrawer();
}

void StripEditor::showPresetDrawer()
{
    closeOverlays();
    drawer.open ({ 0, PluginHeader::kHeight, PresetDrawer::kWidth, getHeight() - PluginHeader::kHeight });
    header.setDrawerOpen (true);
}

void StripEditor::showSavePresetCard()
{
    closeOverlays();
    saveCard.open ({ getWidth() - kOverlayRight, kOverlayTop });
}

void StripEditor::showAbout (bool openLicences)
{
    closeOverlays();
    about.setBounds (getLocalBounds());
    about.show (diagnostics(), openLicences);
}

juce::StringArray StripEditor::diagnostics()
{
    DiagnosticsInput in;
    in.soundVersion = info.soundVersion;
    in.presetName = presets.activeName();
    in.presetEdited = presets.isActiveModified();
    in.guiScale = MachineSettings::guiScale();
    return diagnosticsLines (processor, in);
}

void StripEditor::mouseDown (const juce::MouseEvent& e)
{
    // Every click passes here first (addMouseListener): one outside the open
    // overlay - and outside the control that toggles it - closes it.
    auto* c = e.eventComponent;

    if (menu.isVisible() && ! isWithin (menu, c) && ! isWithin (header.getMenuButton(), c))
    {
        menu.close();
        header.setMenuOpen (false);
    }

    if (drawer.isVisible() && ! isWithin (drawer, c) && ! isWithin (header.getPresetNameButton(), c))
    {
        drawer.close();
        header.setDrawerOpen (false);
    }

    if (saveCard.isVisible() && ! isWithin (saveCard, c))
        saveCard.close();
}

//==============================================================================
void StripEditor::showToast (const juce::String& text, juce::Rectangle<int> anchor)
{
    toast.flash (text, anchor.toFloat(), lastFrameTime, kToastSeconds);
}

void StripEditor::reportProblem()
{
    // ship-bob feedback-loop.md: friends report by message, with what About copies.
    // Nothing opens, nothing is sent.
    juce::SystemClipboard::copyTextToClipboard (diagnostics().joinIntoString ("\n"));
    showToast (juce::String::fromUTF8 ("Copied. Paste it into your message to Bj\xc3\xb6" "rn."),
               header.getMenuButton().getBounds() + header.getPosition());
}

void StripEditor::showDragReadout (juce::Component& source, juce::Rectangle<float> capInSource, const juce::String& text)
{
    dragReadout.showAt (text, getLocalArea (&source, capInSource), 6.0f);
}

void StripEditor::hideDragReadout()
{
    dragReadout.hide();
}

//==============================================================================
bool StripEditor::isInterestedInFileDrag (const juce::StringArray& files)
{
    for (const auto& f : files)
        if (f.endsWithIgnoreCase (kExtension))
            return true;

    return false;
}

void StripEditor::filesDropped (const juce::StringArray& files, int, int)
{
    for (const auto& f : files)
        if (f.endsWithIgnoreCase (kExtension))
            importPreset (juce::File (f));
}

void StripEditor::importPreset (const juce::File& file)
{
    const auto error = presets.importFile (file);
    header.refresh();

    if (error.isNotEmpty())
        juce::AlertWindow::showMessageBoxAsync (juce::MessageBoxIconType::WarningIcon, "Preset not imported",
                                                file.getFileName() + ": " + error);
}

void StripEditor::importPresetFile()
{
    fileChooser = std::make_unique<juce::FileChooser> ("Load a " + info.productName + " preset",
                                                       juce::File::getSpecialLocation (juce::File::userDesktopDirectory),
                                                       juce::String ("*") + kExtension);
    fileChooser->launchAsync (juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
                              [safe = juce::Component::SafePointer<StripEditor> (this)] (const juce::FileChooser& chooser)
    {
        if (safe != nullptr && chooser.getResult() != juce::File())
            safe->importPreset (chooser.getResult());
    });
}

void StripEditor::exportPresetFile()
{
    const auto name = presets.activeName().isNotEmpty() ? presets.activeName() : info.productName;
    const auto start = juce::File::getSpecialLocation (juce::File::userDesktopDirectory)
                           .getChildFile (folders::slugFor (name) + kExtension);

    fileChooser = std::make_unique<juce::FileChooser> ("Export the current sound", start, juce::String ("*") + kExtension);
    fileChooser->launchAsync (juce::FileBrowserComponent::saveMode | juce::FileBrowserComponent::canSelectFiles
                                  | juce::FileBrowserComponent::warnAboutOverwriting,
                              [safe = juce::Component::SafePointer<StripEditor> (this)] (const juce::FileChooser& chooser)
    {
        if (safe == nullptr || chooser.getResult() == juce::File())
            return;

        if (const auto error = safe->presets.exportFile (chooser.getResult()); error.isNotEmpty())
            juce::AlertWindow::showMessageBoxAsync (juce::MessageBoxIconType::WarningIcon, "Preset not exported", error);
    });
}

//==============================================================================
void StripEditor::setScaleFactor (float newScale)
{
    hostScale = newScale;
    applyScale();
}

void StripEditor::applyScale()
{
    AudioProcessorEditor::setScaleFactor (hostScale * MachineSettings::guiScale());
}

void StripEditor::timerCallback()
{
    if (! isShowing())
        return;

    const auto now = clockNow();

    if (lastVBlankTime < 0.0 || now - lastVBlankTime > kVBlankTimeout)
        advanceFrame (now);
}

void StripEditor::advanceFrame (double now)
{
    if (lastFrameTime >= 0.0 && now - lastFrameTime < kMinFrameInterval)
        return;

    const auto dt = lastFrameTime < 0.0 ? 1.0f / 60.0f : (float) juce::jmin (0.1, now - lastFrameTime);
    lastFrameTime = now;

    if (const auto recalls = presets.recallCount(); recalls != seenRecallCount)
    {
        seenRecallCount = recalls;
        presetRecalled (now);
    }

    header.refresh();
    advanceBody (now, dt);
    drawer.refresh();
    toast.advance (now, dt);
    about.advance (dt);
}

//==============================================================================
void StripEditor::paint (juce::Graphics& g)
{
    g.fillAll (front().ground);
}

void StripEditor::resized()
{
    auto r = getLocalBounds();
    header.setBounds (r.removeFromTop (PluginHeader::kHeight));
    layoutBody (r.reduced (Tokens::bodyPadding));

    if (about.isVisible())
        about.setBounds (getLocalBounds());
}

} // namespace oberli::ui
