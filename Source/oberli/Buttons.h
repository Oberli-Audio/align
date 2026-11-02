#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "OberliLookAndFeel.h"

#include <optional>

namespace oberli::ui
{

/**
    The base of every button: it never takes keyboard focus on a click (the
    space bar keeps reaching the host's transport), Tab still reaches it, and
    on a focus change it asks its parent to repaint, because the 2 px `ink`
    focus ring sits 3 px outside its bounds and the parent draws it
    (drawChildFocusRings(), from paintOverChildren()).
*/
class FlatButton : public juce::Button
{
public:
    explicit FlatButton (const juce::String& name, const Palette& = front());

    /** The corner of the button's shape, for its focus ring. */
    virtual float getCorner() const { return Tokens::radiusSm; }

    void focusGained (FocusChangeType) override;
    void focusLost (FocusChangeType) override;

    const Palette& palette() const noexcept { return colours; }

protected:
    const Palette& colours;
};

/** Draws the focus ring of whichever direct child FlatButton has keyboard
    focus, in that button's palette. Call from the parent's paintOverChildren(). */
void drawChildFocusRings (juce::Graphics&, juce::Component& parent);

/** A ghost icon button (Icon card): a 16 px icon in a 24 px hit area, `hover`
    under the pointer or while its menu is open. Tooltip and accessible name are
    the same words. */
class IconButton final : public FlatButton
{
public:
    IconButton (icons::Id, const juce::String& label, bool pillShaped = false, const Palette& = front());

    void setActive (bool isActive);
    void setIconColour (juce::Colour);

    float getCorner() const override { return pill ? (float) getHeight() * 0.5f : Tokens::radiusSm; }
    void paintButton (juce::Graphics&, bool highlighted, bool down) override;

private:
    const icons::Id icon;
    const bool pill;
    bool active = false;
    std::optional<juce::Colour> colour;
};

/** A text button (Button card): `control` text, 28 px or more, `radius-md`,
    12 px side padding. Primary: `accent` fill, `on-accent` text, one per view.
    Secondary: a `line-control` outline. Ghost: no border, for Cancel and quiet
    actions. */
class ActionButton final : public FlatButton
{
public:
    enum class Variant { primary, secondary, ghost };

    ActionButton (const juce::String& caption, Variant, const Palette& = front(), std::optional<icons::Id> leadingIcon = {});

    /** The width the label needs, padding included. */
    int getPreferredWidth() const;

    float getCorner() const override { return Tokens::radiusMd; }
    void paintButton (juce::Graphics&, bool highlighted, bool down) override;

private:
    const Variant variant;
    const std::optional<icons::Id> leadingIcon;
};

/** The Toggle card: an on/off mode (Shimmer, Freeze, Bypass) as a 28 px pill
    with a `line-control` outline, an LED (drawLed) and a caps `label`. Off: LED
    `line-strong`, text `ink-muted`; on: LED `accent`, text `ink`. The word never
    changes, so the pill keeps its width. Toggles its own state; attach it with
    juce::AudioProcessorValueTreeState::ButtonAttachment. Accessible as a toggle. */
class PillToggle final : public FlatButton
{
public:
    explicit PillToggle (const juce::String& caption, const Palette& = front());

    int getPreferredWidth() const;

    float getCorner() const override { return (float) getHeight() * 0.5f; }
    void paintButton (juce::Graphics&, bool highlighted, bool down) override;
};

/**
    The Segmented card: two to five exclusive options side by side - a choice
    parameter, the A/B group. A `surface-sunken` well with a `line-control`
    border and `radius-md`; options in `control` text, `ink-muted`; the selected
    one filled with `accent` under `on-accent` text at 600. Each option at least
    24 px high. Keyboard: Tab reaches it, the arrows move the choice.

    Bind it to a choice or int parameter with attach() (one undoable gesture per
    click), or drive it yourself with setSelected() and onChange.
*/
class SegmentedControl final : public juce::Component,
                               public juce::SettableTooltipClient
{
public:
    explicit SegmentedControl (const juce::StringArray& options, const Palette& = front());
    ~SegmentedControl() override;

    void setSelected (int index, juce::NotificationType = juce::sendNotificationSync);
    int getSelected() const noexcept { return selected; }
    std::function<void (int)> onChange;

    /** Follows and sets `parameter` (a choice or int parameter whose range
        covers the options); detaches when this control is deleted. */
    void attach (juce::RangedAudioParameter& parameter, juce::UndoManager* = nullptr);

    /** The width the labels need, padding included. */
    int getPreferredWidth() const;

    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;
    bool keyPressed (const juce::KeyPress&) override;
    void focusGained (FocusChangeType) override { repaint(); }
    void focusLost (FocusChangeType) override   { repaint(); }
    std::unique_ptr<juce::AccessibilityHandler> createAccessibilityHandler() override;

private:
    juce::Rectangle<float> segment (int index) const;

    const Palette& colours;
    juce::StringArray options;
    int selected = 0;
    std::unique_ptr<juce::ParameterAttachment> attachment;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SegmentedControl)
};

} // namespace oberli::ui
