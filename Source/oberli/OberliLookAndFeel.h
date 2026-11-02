#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include <memory>

/*  Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills
    tools/template-src/Source/oberli into every plugin and refreshed from there,
    never edited in a plugin repo (README.md beside this file).

    The family's look, lifted from Horizon Pad's HorizonLookAndFeel and made
    theme-neutral. The tokens are the Design System artifact "Oberli Audio"
    (project/tokens.json, v1), which wins over every copy of them. The plugin's
    CMakeLists.txt sets the two things that differ between plugins:

      OBERLI_THEME_BONE  1 for an effect (Bone), 0 for an instrument (Charcoal)
      OBERLI_ACCENT      the plugin's accent as 0xFFRRGGBB (registry, never shared)

    Every colour the editor draws comes from front() (the plugin's theme) or
    back() (the other theme: the About page). Only a Scene (one display per
    plugin, drawn with gradients) may leave the tokens, and it never takes the
    accent. */

#ifndef OBERLI_THEME_BONE
 #define OBERLI_THEME_BONE 0
#endif
#ifndef OBERLI_ACCENT
 #define OBERLI_ACCENT 0xFFF09300   // mango, the brand's own: only for code outside a plugin
#endif

namespace oberli::ui
{

/** One theme's colour tokens (tokens.json, color.tokens). */
struct Palette
{
    bool isBone;
    juce::Colour ground;          // window background
    juce::Colour surfaceRaised;   // header, drawers, menus, cards
    juce::Colour surfaceSunken;   // wells, fields, meter troughs
    juce::Colour surfacePanel;    // knob cap: dark in both themes
    juce::Colour hover;           // hovered and current rows: surface-panel on Charcoal, surface-sunken on Bone
    juce::Colour line;            // hairlines, decorative only
    juce::Colour lineStrong;      // knob and slider tracks, inactive segments
    juce::Colour lineControl;     // outline of an operable control, 3:1 or better
    juce::Colour ink;             // text, values, the focus ring
    juce::Colour inkMuted;        // labels, section titles
    juce::Colour inkSubtle;       // version, captions; never needed to operate
    juce::Colour accentInk;       // the accent as text: the accent on Charcoal, charcoal on Bone
    juce::Colour mod;             // modulation only, never an accent
    juce::Colour meterLevel;      // meter bar below -6 dBFS
    juce::Colour meterHot;        // meter bar from -6 dBFS; a lit LIMIT LED
    juce::Colour clip;            // clip LED and error text, always with a word
    juce::Colour readout;         // drag readout and tooltip fill
    juce::Colour onReadout;       // text on it
    float shadowAlpha;            // shadow-pop: rgba(0,0,0,.45) / rgba(28,27,25,.18)
};

const Palette& charcoal();
const Palette& bone();

/** The plugin's own theme (OBERLI_THEME_BONE) and the other one. */
inline const Palette& front() { return OBERLI_THEME_BONE ? bone() : charcoal(); }
inline const Palette& back()  { return OBERLI_THEME_BONE ? charcoal() : bone(); }

namespace Tokens
{
    inline juce::Colour accent()   { return juce::Colour ((juce::uint32) OBERLI_ACCENT); }
    inline juce::Colour onAccent() { return juce::Colour (0xff1c1b19); }   // 7:1 or better on every accent

    // radius-*, px at 100 %
    constexpr float radiusXs = 4.0f, radiusSm = 6.0f, radiusMd = 10.0f, radiusLg = 14.0f;

    // control sizes, px at 100 %
    constexpr int knobLg = 64, knobMd = 48, knobSm = 32;
    constexpr int headerHeight = 48, hitMin = 24, controlHeight = 28, bodyPadding = 28;
    constexpr int space1 = 4, space2 = 8, space3 = 12, space4 = 16, space5 = 24, space6 = 32;

    /** shadow-pop (0 8px 24px): only for what floats - readout, menu, drawer, tooltip. */
    juce::DropShadow popShadow (const Palette& = front());
}

/** Two families, two jobs (brand sheet, Type). Rubik for the logo, names, titles,
    labels, controls and values: everything a player scans; every value switches on
    `tnum` so digits keep their width while a knob turns (Nunito has no tabular
    figures). Nunito for running text a player reads: the About text, tooltips,
    preset descriptions, messages; never below 13 px. Both bundled from
    Source/oberli/assets/fonts (SIL OFL 1.1, the static instances Google Fonts serves,
    unmodified) and registered once per process. Sizes are CSS px (JUCE's point
    height), tracking in em, as the tokens give them. */
namespace type
{
    enum class Weight { regular, medium, semibold, bold, extrabold };

    /** Rubik. */
    juce::Font font (Weight, float px, float trackingEm = 0.0f, bool tabular = false);

    /** Nunito, 400 or 600 (the two weights bundled); px 13 or more. */
    juce::Font text (bool semibold, float px);

    inline juce::Font pluginName() { return font (Weight::bold, 15.0f); }
    inline juce::Font section()    { return font (Weight::bold, 11.0f, 0.12f); }
    inline juce::Font label()      { return font (Weight::semibold, 11.0f, 0.10f); }   // the smallest text at 100 %
    inline juce::Font value()      { return font (Weight::medium, 12.0f, 0.0f, true); }
    inline juce::Font control()    { return font (Weight::medium, 12.0f); }
    inline juce::Font controlStrong() { return font (Weight::semibold, 12.0f); }      // the selected segment
    inline juce::Font meta()       { return font (Weight::medium, 11.0f, 0.0f, true); }
    inline juce::Font small()      { return text (false, 13.0f); }    // 13/19, Nunito
    inline juce::Font body()       { return text (false, 15.0f); }    // 15/23, Nunito
    inline juce::Font tooltip()    { return text (false, 13.0f); }    // 13/18, Nunito
    inline juce::Font title()      { return font (Weight::bold, 22.0f); }
    inline juce::Font eyebrow()    { return font (Weight::bold, 12.0f, 0.14f); }
    inline juce::Font display()    { return font (Weight::extrabold, 56.0f, -0.02f); }

    /** Draws `text` centred in a line box of the style's line height, as CSS does. */
    void draw (juce::Graphics&, const juce::String& text, juce::Rectangle<float> lineBox,
               const juce::Font&, juce::Colour, juce::Justification = juce::Justification::centredLeft);

    float width (const juce::Font&, const juce::String& text);
}

/** The Icon card's thin-line icons: 16 px grid, 1.5 px strokes, round caps and
    joins, no fills, drawn in `ink` (never the accent). */
namespace icons
{
    enum class Id { chevronLeft, chevronRight, menu, copy, load, save, about, close, undo, redo,
                    compare, settings, bypass, random, folder };

    void draw (juce::Graphics&, Id, juce::Rectangle<float> area, juce::Colour);
}

/** The Oberli marks (the artifact's Logo group), drawn as vectors, never retyped.
    `forGround` is the palette of the surface the mark sits on. */
namespace logo
{
    std::unique_ptr<juce::Drawable> nameOnly (const Palette& forGround);   // oberli-bone.svg / oberli-charcoal.svg
    std::unique_ptr<juce::Drawable> lockup (const Palette& forGround);     // oberli-audio-bone.svg / -charcoal.svg
}

/** The Knob card: cap 72 % of the box with a 1.5 px `line-control` ring, track
    and value arc at 46 % (3 px, 2 px at knob-sm), modulation range at 53 % in
    `mod`, the pointer the 100-unit master's rounded bar (x 43.88 y 19.4 w 12.24
    h 24.48 rx 6.12) turned about the centre, 270 degrees from 7:30. `proportion`
    and the mod range are 0..1 along the sweep; `bipolar` draws the arc from 12.
    Disabled: pointer `ink-subtle`, the whole knob at 45 %. */
struct KnobLook
{
    float proportion = 0.0f;
    bool bipolar = false;
    bool focused = false;
    bool enabled = true;
    float modLow = 0.0f, modHigh = 0.0f;   // equal: no modulation drawn
};

void drawKnob (juce::Graphics&, juce::Rectangle<float> box, const KnobLook&, const Palette& = front());

/** The 2 px `ink` focus ring, 3 px off `controlBounds`. */
void drawFocusRing (juce::Graphics&, juce::Rectangle<float> controlBounds, float corner, const Palette& = front());

/** A floating card: shadow-pop, the fill, a 1 px border. */
void drawPopCard (juce::Graphics&, juce::Rectangle<float> bounds, float corner, juce::Colour fill, juce::Colour border,
                  const Palette& = front());

/** An LED (Toggle card): `line-strong` off, `accent` on; on Bone a lit LED gets
    a 1.5 px charcoal ring, because no bright accent reaches 3:1 on bone. */
void drawLed (juce::Graphics&, juce::Rectangle<float> dot, bool lit, const Palette& = front());

/** The editor's LookAndFeel: Rubik as the default face (JUCE's own text
    editors and alert windows too), the Tooltip card (readout colours, the
    parameter table's sentence, its range line at 75 %), the TextField look
    (28 px, sunken, outlined, radius-md), thin scrollbars, alert windows in the
    tokens. Every Oberli widget otherwise paints itself. */
class LookAndFeel : public juce::LookAndFeel_V4
{
public:
    explicit LookAndFeel (const Palette& = front());

    juce::Typeface::Ptr getTypefaceForFont (const juce::Font&) override;

    juce::Rectangle<int> getTooltipBounds (const juce::String& tipText, juce::Point<int> screenPos,
                                           juce::Rectangle<int> parentArea) override;
    void drawTooltip (juce::Graphics&, const juce::String& text, int width, int height) override;

    void fillTextEditorBackground (juce::Graphics&, int width, int height, juce::TextEditor&) override;
    void drawTextEditorOutline (juce::Graphics&, int width, int height, juce::TextEditor&) override;

    void drawScrollbar (juce::Graphics&, juce::ScrollBar&, int x, int y, int width, int height,
                        bool isScrollbarVertical, int thumbStartPosition, int thumbSize,
                        bool isMouseOver, bool isMouseDown) override;
    int getDefaultScrollbarWidth() override { return 8; }

    /** JUCE sliders (the Slider card): a 4 px `line-strong` track, the accent
        fill from the minimum (bipolar from the centre when the slider's
        "bipolar" property is set) and a 14 px thumb drawn like the knob. */
    void drawLinearSlider (juce::Graphics&, int x, int y, int width, int height, float sliderPos, float minSliderPos,
                           float maxSliderPos, juce::Slider::SliderStyle, juce::Slider&) override;
    void drawRotarySlider (juce::Graphics&, int x, int y, int width, int height, float sliderPosProportional,
                           float rotaryStartAngle, float rotaryEndAngle, juce::Slider&) override;

    const Palette& palette() const noexcept { return colours; }

private:
    std::unique_ptr<juce::TextLayout> layoutTooltip (const juce::String& text) const;

    const Palette& colours;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (LookAndFeel)
};

} // namespace oberli::ui
