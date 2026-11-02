#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "AboutPanel.h"
#include "Diagnostics.h"
#include "HeaderMenu.h"
#include "PluginHeader.h"
#include "PresetDrawer.h"
#include "ReadoutBubble.h"
#include "SavePresetCard.h"

/*  The Strip frame (PluginWindow card), Horizon Pad's editor frame made the
    family's: the PluginHeader (48 px) on top, the plugin's body below it with
    28 px padding, and the overlays that never open a window - the menu
    dropping from the header, the preset drawer from the left, the Save preset
    card, About turning the panel round, the drag readout and confirmations.
    Esc or a click elsewhere closes the open overlay.

    One layout drawn at a chosen size: the menu's GUI scale (MachineSettings,
    machine-local, never in the session) multiplies the host's own scale.
    Everything is vector, so no size blurs.

    One frame callback (advanceFrame) drives all motion, from the display's
    vertical blank while the editor is on screen (a 30 Hz timer stands in when
    there is none), capped near 75 fps; the body's own motion goes in
    advanceBody(). A preset recall calls presetRecalled() once, so the body
    can start its knobs' wave.

    A plugin's editor derives from StripEditor, adds its controls in its
    constructor, lays them out in layoutBody() and sets its size with
    setBodySize(). */
namespace oberli::ui
{

class StripEditor : public juce::AudioProcessorEditor,
                    public juce::FileDragAndDropTarget,
                    public ReadoutHost,
                    private juce::Timer
{
public:
    struct Info
    {
        juce::String productName;     // JucePlugin_Name
        juce::String version;         // PRODUCT_VERSION
        juce::String what;            // About: one or two sentences of what the plugin is
        juce::String ownLine;         // About: optional line of the plugin's own
        juce::String licences;        // About: LICENSE and THIRD_PARTY_NOTICES.md, compiled in
        int soundVersion = 1;         // the state's dspVersion
    };

    StripEditor (juce::AudioProcessor&, PresetHost&, Info);
    ~StripEditor() override;

    /** The body's size at 100 %, without the header and the 28 px padding. The window is never
        narrower than the header needs nor lower than 360 px (About's compact page). */
    void setBodySize (int width, int height);

    // The overlays, for the menu and for the snapshot tool.
    void showMenu (bool scaleSubmenu = false);
    void showPresetDrawer();
    void showSavePresetCard();
    void showAbout (bool openLicences = false);
    void closeOverlays();

    /** A confirmation readout under `anchorInEditor` that fades after a moment. */
    void showToast (const juce::String& text, juce::Rectangle<int> anchorInEditor);

    /** One animation frame at `nowSeconds` (Time::getMillisecondCounterHiRes()
        timebase). Public so the snapshot tool can step it with its own clock. */
    void advanceFrame (double nowSeconds);

    /** Shows a knob's drag readout without a mouse (the snapshot tool); false for an unknown ID. */
    virtual bool previewDrag (const juce::String& parameterId) { juce::ignoreUnused (parameterId); return false; }

    PluginHeader& getHeader() noexcept { return header; }
    PresetHost& getPresets() noexcept { return presets; }
    const Info& getInfo() const noexcept { return info; }

    // juce::AudioProcessorEditor
    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;
    void setScaleFactor (float newScale) override;

    // A .oberlipreset dropped on the editor is imported (D.6.5).
    bool isInterestedInFileDrag (const juce::StringArray& files) override;
    void filesDropped (const juce::StringArray& files, int x, int y) override;

    // ReadoutHost: a knob's value above its cap while it is dragged.
    void showDragReadout (juce::Component& source, juce::Rectangle<float> capInSource, const juce::String& text) override;
    void hideDragReadout() override;

protected:
    /** Lay out the body inside `area` (editor coordinates, padding removed). */
    virtual void layoutBody (juce::Rectangle<int> area) { juce::ignoreUnused (area); }

    /** One frame for the body's own motion (knob glides, meters). */
    virtual void advanceBody (double now, float dt) { juce::ignoreUnused (now, dt); }

    /** A preset was recalled since the last frame: start the knobs' wave. */
    virtual void presetRecalled (double now) { juce::ignoreUnused (now); }

    /** The diagnostics block; the default covers the fourteen fields. */
    virtual juce::StringArray diagnostics();

    static double clockNow() noexcept { return juce::Time::getMillisecondCounterHiRes() * 0.001; }

private:
    void timerCallback() override;
    void applyScale();
    void toggleMenu();
    void togglePresetDrawer();
    void importPreset (const juce::File&);
    void importPresetFile();
    void exportPresetFile();
    void reportProblem();

    PresetHost& presets;
    const Info info;

    LookAndFeel lookAndFeel;

    PluginHeader header;
    PresetDrawer drawer;
    HeaderMenu menu;
    SavePresetCard saveCard;
    AboutPanel about;
    ReadoutBubble dragReadout, toast;

    // Without a TooltipWindow in the tree, setTooltip() text is never shown. 600 ms (Tooltip card).
    juce::TooltipWindow tooltipWindow;
    std::unique_ptr<juce::FileChooser> fileChooser;

    int bodyWidth = 400, bodyHeight = 200;
    float hostScale = 1.0f;
    double lastFrameTime = -1.0, lastVBlankTime = -1.0;
    int seenRecallCount = 0;

    // Last, so it only calls advanceFrame() once everything above exists.
    juce::VBlankAttachment vblank;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (StripEditor)
};

} // namespace oberli::ui
