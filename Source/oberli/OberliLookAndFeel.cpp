#include "OberliLookAndFeel.h"

#include <OberliUiData.h>

#include <array>
#include <map>
#include <tuple>

namespace oberli::ui
{

//==============================================================================
const Palette& charcoal()
{
    static const Palette p {
        false,
        juce::Colour (0xff1c1b19),   // ground
        juce::Colour (0xff232220),   // surface-raised
        juce::Colour (0xff171614),   // surface-sunken
        juce::Colour (0xff2a2826),   // surface-panel
        juce::Colour (0xff2a2826),   // hover
        juce::Colour (0xff3a3836),   // line
        juce::Colour (0xff4a4844),   // line-strong
        juce::Colour (0xff716b62),   // line-control (3.0:1 on surface-raised; #6B665D before 2026-10-28)
        juce::Colour (0xffede8df),   // ink
        juce::Colour (0xffbdb6aa),   // ink-muted
        juce::Colour (0xff9c968b),   // ink-subtle
        juce::Colour ((juce::uint32) OBERLI_ACCENT),   // accent-ink: the accent itself
        juce::Colour (0xff8fb8ff),   // mod
        juce::Colour (0xffede8df),   // meter-level
        juce::Colour (0xfff6bf26),   // meter-hot
        juce::Colour (0xffff5a4e),   // clip
        juce::Colour (0xffede8df),   // readout
        juce::Colour (0xff1c1b19),   // on-readout
        0.45f
    };
    return p;
}

const Palette& bone()
{
    static const Palette p {
        true,
        juce::Colour (0xffede8df),   // ground
        juce::Colour (0xfff6f2eb),   // surface-raised
        juce::Colour (0xffe6e0d6),   // surface-sunken
        juce::Colour (0xff1c1b19),   // surface-panel: the knob cap stays dark
        juce::Colour (0xffe6e0d6),   // hover: surface-sunken (surface-panel is charcoal here)
        juce::Colour (0xffd3ccc0),   // line
        juce::Colour (0xffbdb6aa),   // line-strong
        juce::Colour (0xff77726a),   // line-control (3.9:1)
        juce::Colour (0xff1c1b19),   // ink
        juce::Colour (0xff45423e),   // ink-muted
        juce::Colour (0xff5c574f),   // ink-subtle
        juce::Colour (0xff1c1b19),   // accent-ink: charcoal, no bright accent reaches 3:1 on bone
        juce::Colour (0xff2a5bb8),   // mod
        juce::Colour (0xff1c1b19),   // meter-level
        juce::Colour (0xff7d5c00),   // meter-hot
        juce::Colour (0xffb02a24),   // clip
        juce::Colour (0xff1c1b19),   // readout
        juce::Colour (0xffede8df),   // on-readout
        0.18f
    };
    return p;
}

juce::DropShadow Tokens::popShadow (const Palette& p)
{
    const auto colour = p.isBone ? juce::Colour (0xff1c1b19) : juce::Colours::black;
    return { colour.withAlpha (p.shadowAlpha), 24, { 0, 8 } };
}

//==============================================================================
namespace
{
    /** The five Rubik weights, registered once and kept while any LookAndFeel lives. */
    struct Typefaces
    {
        Typefaces()
        {
            const std::pair<const char*, int> files[] {
                { OberliUiData::RubikRegular_ttf,   OberliUiData::RubikRegular_ttfSize },
                { OberliUiData::RubikMedium_ttf,    OberliUiData::RubikMedium_ttfSize },
                { OberliUiData::RubikSemiBold_ttf,  OberliUiData::RubikSemiBold_ttfSize },
                { OberliUiData::RubikBold_ttf,      OberliUiData::RubikBold_ttfSize },
                { OberliUiData::RubikExtraBold_ttf, OberliUiData::RubikExtraBold_ttfSize },
            };

            for (size_t i = 0; i < faces.size(); ++i)
                faces[i] = juce::Typeface::createSystemTypefaceFor (files[i].first, (size_t) files[i].second);

            textFaces[0] = juce::Typeface::createSystemTypefaceFor (OberliUiData::NunitoRegular_ttf, (size_t) OberliUiData::NunitoRegular_ttfSize);
            textFaces[1] = juce::Typeface::createSystemTypefaceFor (OberliUiData::NunitoSemiBold_ttf, (size_t) OberliUiData::NunitoSemiBold_ttfSize);
        }

        std::array<juce::Typeface::Ptr, 5> faces;       // Rubik 400 to 800
        std::array<juce::Typeface::Ptr, 2> textFaces;   // Nunito 400, 600

        // Every style drawn, built once: a copy of a Font shares its shaped native font,
        // so paint() never builds one again. Message thread.
        std::map<std::tuple<int, int, int, bool>, juce::Font> fonts;
    };

    juce::Typeface::Ptr typefaceFor (type::Weight weight)
    {
        const juce::SharedResourcePointer<Typefaces> typefaces;
        return typefaces->faces[(size_t) weight];
    }

    juce::Font buildFont (juce::Typeface::Ptr face, float px, float trackingEm, bool tabular)
    {
        auto options = juce::FontOptions (face).withPointHeight (px);

        if (tabular)
            options = options.withFeatureEnabled ("tnum");

        juce::Font f (options);

        // JUCE adds tracking as a multiple of the line height; the tokens give it in em.
        if (! juce::exactlyEqual (trackingEm, 0.0f))
            f.setExtraKerningFactor (trackingEm * px / f.getHeight());

        return f;
    }

    std::unique_ptr<juce::Drawable> drawableFrom (const char* data, int size)
    {
        return juce::Drawable::createFromImageData (data, (size_t) size);
    }

    // The Icon card's paths on the 16-unit grid.
    const char* iconPath (icons::Id id)
    {
        switch (id)
        {
            case icons::Id::chevronLeft:  return "M10 3.5 5.5 8l4.5 4.5";
            case icons::Id::chevronRight: return "M6 3.5 10.5 8 6 12.5";
            case icons::Id::menu:         return "M3 4.5h10M3 8h10M3 11.5h10";
            case icons::Id::copy:         return "M2.5 5.5h9M9 3l2.5 2.5L9 8M13.5 10.5h-9M7 8l-2.5 2.5L7 13";
            case icons::Id::load:         return "M8 9.5v-7M5 5.5l3-3 3 3M3 11v2.5h10V11";
            case icons::Id::save:         return "M8 2.5v7M5 6.5l3 3 3-3M3 11v2.5h10V11";
            case icons::Id::about:        return "M8 7.5v3.5M8 5h.01";
            case icons::Id::close:        return "M4.5 4.5l7 7M11.5 4.5l-7 7";
            case icons::Id::undo:         return "M5.5 3.5 2.5 6.5l3 3M2.5 6.5H10a3.5 3.5 0 0 1 0 7H7";
            case icons::Id::redo:         return "M10.5 3.5l3 3-3 3M13.5 6.5H6a3.5 3.5 0 0 0 0 7h3";
            case icons::Id::compare:      return "M8 2v12M2.5 4.5h3v7h-3zM10.5 4.5h3v7h-3z";
            case icons::Id::settings:     return "M2.5 4.5h7M12.5 4.5h1M2.5 11.5h1M6.5 11.5h7M11 3v3M5 10v3";
            case icons::Id::bypass:       return "M8 2.5v5M4.8 4.5a4.5 4.5 0 1 0 6.4 0";
            case icons::Id::random:       return "M2.5 4.5h2.5l6 7h2.5M2.5 11.5h2.5l6-7h2.5M12 3l1.5 1.5L12 6M12 10l1.5 1.5L12 13";
            case icons::Id::folder:       return "M2.5 4.5v8h11v-6.5H8L6.5 4.5z";
        }

        return "";
    }
} // namespace

//==============================================================================
juce::Font type::font (Weight weight, float px, float trackingEm, bool tabular)
{
    const juce::SharedResourcePointer<Typefaces> typefaces;
    const auto key = std::make_tuple ((int) weight, juce::roundToInt (px * 100.0f), juce::roundToInt (trackingEm * 1000.0f), tabular);

    if (const auto found = typefaces->fonts.find (key); found != typefaces->fonts.end())
        return found->second;

    return typefaces->fonts.emplace (key, buildFont (typefaces->faces[(size_t) weight], px, trackingEm, tabular)).first->second;
}

juce::Font type::text (bool semibold, float px)
{
    jassert (px >= 13.0f);   // Nunito's x-height is small: never below 13 px at 100 % (brand sheet)
    const juce::SharedResourcePointer<Typefaces> typefaces;
    const auto key = std::make_tuple (semibold ? -2 : -1, juce::roundToInt (px * 100.0f), 0, false);

    if (const auto found = typefaces->fonts.find (key); found != typefaces->fonts.end())
        return found->second;

    return typefaces->fonts.emplace (key, buildFont (typefaces->textFaces[semibold ? 1 : 0], px, 0.0f, false)).first->second;
}

void type::draw (juce::Graphics& g, const juce::String& text, juce::Rectangle<float> lineBox,
                 const juce::Font& f, juce::Colour colour, juce::Justification justification)
{
    g.setFont (f);
    g.setColour (colour);
    g.drawText (text, lineBox, justification, false);
}

float type::width (const juce::Font& f, const juce::String& text)
{
    return juce::GlyphArrangement::getStringWidth (f, text);
}

//==============================================================================
void icons::draw (juce::Graphics& g, Id id, juce::Rectangle<float> area, juce::Colour colour)
{
    const auto scale = juce::jmin (area.getWidth(), area.getHeight()) / 16.0f;
    const auto transform = juce::AffineTransform::scale (scale)
                               .translated (area.getCentreX() - 8.0f * scale, area.getCentreY() - 8.0f * scale);

    auto path = juce::Drawable::parseSVGPath (iconPath (id));

    if (id == Id::about)
        path.addEllipse (2.0f, 2.0f, 12.0f, 12.0f);

    g.setColour (colour);
    g.strokePath (path, juce::PathStrokeType (1.5f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded),
                  transform);
}

//==============================================================================
std::unique_ptr<juce::Drawable> logo::nameOnly (const Palette& forGround)
{
    return forGround.isBone ? drawableFrom (OberliUiData::oberlicharcoal_svg, OberliUiData::oberlicharcoal_svgSize)
                            : drawableFrom (OberliUiData::oberlibone_svg, OberliUiData::oberlibone_svgSize);
}

std::unique_ptr<juce::Drawable> logo::lockup (const Palette& forGround)
{
    return forGround.isBone ? drawableFrom (OberliUiData::oberliaudiocharcoal_svg, OberliUiData::oberliaudiocharcoal_svgSize)
                            : drawableFrom (OberliUiData::oberliaudiobone_svg, OberliUiData::oberliaudiobone_svgSize);
}

//==============================================================================
void drawKnob (juce::Graphics& g, juce::Rectangle<float> box, const KnobLook& look, const Palette& p)
{
    const auto size = juce::jmin (box.getWidth(), box.getHeight());
    const auto centre = box.getCentre();
    const auto v = juce::jlimit (0.0f, 1.0f, look.proportion);

    // Angles clockwise from 12 o'clock, as Path::addCentredArc takes them.
    const auto start = juce::degreesToRadians (-135.0f);
    const auto end = juce::degreesToRadians (135.0f);
    const auto angleAt = [&] (float proportion) { return start + (end - start) * juce::jlimit (0.0f, 1.0f, proportion); };
    const auto angle = angleAt (v);

    juce::Graphics::ScopedSaveState save (g);

    if (! look.enabled)
        g.beginTransparencyLayer (0.45f);

    const auto radius = 0.46f * size;
    const auto stroke = size <= 32.0f ? 2.0f : 3.0f;
    const juce::PathStrokeType arcStroke (stroke, juce::PathStrokeType::curved, juce::PathStrokeType::rounded);

    juce::Path track;
    track.addCentredArc (centre.x, centre.y, radius, radius, 0.0f, start, end, true);
    g.setColour (p.lineStrong);
    g.strokePath (track, arcStroke);

    const auto from = look.bipolar ? 0.0f : start;
    if (std::abs (angle - from) > 0.009f)   // half a degree
    {
        juce::Path arc;
        arc.addCentredArc (centre.x, centre.y, radius, radius, 0.0f, juce::jmin (from, angle), juce::jmax (from, angle), true);
        g.setColour (Tokens::accent());
        g.strokePath (arc, arcStroke);
    }

    if (look.modHigh - look.modLow > 0.002f)
    {
        const auto modRadius = 0.53f * size;
        juce::Path mod;
        mod.addCentredArc (centre.x, centre.y, modRadius, modRadius, 0.0f, angleAt (look.modLow), angleAt (look.modHigh), true);
        g.setColour (p.mod);
        g.strokePath (mod, juce::PathStrokeType (stroke - 1.0f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));
    }

    const auto capRadius = 0.36f * size;
    const auto cap = juce::Rectangle<float> (2.0f * capRadius, 2.0f * capRadius).withCentre (centre);
    g.setColour (p.surfacePanel);
    g.fillEllipse (cap);
    g.setColour (p.lineControl);
    g.drawEllipse (cap, 1.5f);

    // The pointer, from the 100-unit master drawing.
    const auto unit = size / 100.0f;
    juce::Path pointer;
    pointer.addRoundedRectangle (box.getX() + (box.getWidth() - size) * 0.5f + 43.88f * unit,
                                 box.getY() + (box.getHeight() - size) * 0.5f + 19.4f * unit,
                                 12.24f * unit, 24.48f * unit, 6.12f * unit);
    g.setColour (look.enabled ? Tokens::accent() : p.inkSubtle);
    g.fillPath (pointer, juce::AffineTransform::rotation (angle, centre.x, centre.y));

    if (! look.enabled)
        g.endTransparencyLayer();

    if (look.focused)
        drawFocusRing (g, cap, capRadius, p);
}

void drawFocusRing (juce::Graphics& g, juce::Rectangle<float> controlBounds, float corner, const Palette& p)
{
    // 3 px gap, then 2 px of ink: the stroke's centre sits 4 px out.
    g.setColour (p.ink);
    g.drawRoundedRectangle (controlBounds.expanded (4.0f), corner + 4.0f, 2.0f);
}

void drawPopCard (juce::Graphics& g, juce::Rectangle<float> bounds, float corner, juce::Colour fill, juce::Colour border,
                  const Palette& p)
{
    juce::Path shape;
    shape.addRoundedRectangle (bounds, corner);
    Tokens::popShadow (p).drawForPath (g, shape);

    g.setColour (fill);
    g.fillPath (shape);
    g.setColour (border);
    g.drawRoundedRectangle (bounds.reduced (0.5f), corner - 0.5f, 1.0f);
}

void drawLed (juce::Graphics& g, juce::Rectangle<float> dot, bool lit, const Palette& p)
{
    g.setColour (lit ? Tokens::accent() : p.lineStrong);
    g.fillEllipse (dot);

    if (lit && p.isBone)
    {
        g.setColour (juce::Colour (0xff1c1b19));
        g.drawEllipse (dot.reduced (0.75f), 1.5f);
    }
}

//==============================================================================
LookAndFeel::LookAndFeel (const Palette& p)
    : colours (p)
{
    // Holds the typefaces for as long as this LookAndFeel lives.
    static_cast<void> (typefaceFor (type::Weight::regular));

    setColour (juce::ResizableWindow::backgroundColourId, p.ground);
    setColour (juce::TextEditor::textColourId,            p.ink);
    setColour (juce::TextEditor::backgroundColourId,      p.surfaceSunken);
    setColour (juce::TextEditor::outlineColourId,         p.lineControl);
    setColour (juce::TextEditor::focusedOutlineColourId,  p.ink);
    setColour (juce::TextEditor::highlightColourId,       p.line);
    setColour (juce::TextEditor::highlightedTextColourId, p.ink);
    setColour (juce::CaretComponent::caretColourId,       p.ink);
    setColour (juce::ScrollBar::thumbColourId,            p.lineControl);
    setColour (juce::TooltipWindow::textColourId,         p.onReadout);
    setColour (juce::AlertWindow::backgroundColourId,     p.surfaceRaised);
    setColour (juce::AlertWindow::textColourId,           p.ink);
    setColour (juce::AlertWindow::outlineColourId,        p.lineControl);
    setColour (juce::TextButton::buttonColourId,          p.surfaceRaised);
    setColour (juce::TextButton::textColourOffId,         p.ink);
    setColour (juce::Label::textColourId,                 p.ink);
    setColour (juce::Slider::textBoxTextColourId,         p.ink);
    setColour (juce::Slider::textBoxOutlineColourId,      juce::Colours::transparentBlack);
    setColour (juce::PopupMenu::backgroundColourId,       p.surfaceRaised);
    setColour (juce::PopupMenu::textColourId,             p.ink);
    setColour (juce::PopupMenu::highlightedBackgroundColourId, p.hover);
    setColour (juce::PopupMenu::highlightedTextColourId,  p.ink);
}

juce::Typeface::Ptr LookAndFeel::getTypefaceForFont (const juce::Font& f)
{
    // Anything asking for the default face gets Rubik: JUCE's own editors, alerts, tooltips.
    if (f.getTypefaceName() == juce::Font::getDefaultSansSerifFontName()
        || f.getTypefaceName() == juce::Font::getDefaultSerifFontName())
        return typefaceFor (f.isBold() ? type::Weight::bold : type::Weight::regular);

    return LookAndFeel_V4::getTypefaceForFont (f);
}

//==============================================================================
std::unique_ptr<juce::TextLayout> LookAndFeel::layoutTooltip (const juce::String& text) const
{
    // The parameter table's sentence, then its generated range and default (" Range ...")
    // on a line of its own at 75 %.
    const auto sentence = text.upToFirstOccurrenceOf (" Range ", false, false).trim();
    const auto range = text.fromFirstOccurrenceOf (" Range ", true, false).trim();

    juce::AttributedString s;
    s.setJustification (juce::Justification::topLeft);
    s.setWordWrap (juce::AttributedString::byWord);
    s.setLineSpacing (1.0f);   // 13/18: Nunito's own line height is about 17 px at 13 px
    s.append (sentence, type::tooltip(), colours.onReadout);

    if (range.isNotEmpty())
        s.append ("\n" + range, type::tooltip(), colours.onReadout.withAlpha (0.75f));

    auto layout = std::make_unique<juce::TextLayout>();
    layout->createLayoutWithBalancedLineLengths (s, 260.0f - 2.0f * 8.0f);
    return layout;
}

juce::Rectangle<int> LookAndFeel::getTooltipBounds (const juce::String& tipText, juce::Point<int> screenPos,
                                                    juce::Rectangle<int> parentArea)
{
    const auto layout = layoutTooltip (tipText);
    const auto w = juce::roundToInt (layout->getWidth() + 16.0f);
    const auto h = juce::roundToInt (layout->getHeight() + 12.0f);

    // Below and right of the pointer, so the control's own value stays visible.
    return juce::Rectangle<int> (screenPos.x > parentArea.getCentreX() ? screenPos.x - (w + 12) : screenPos.x + 12,
                                 screenPos.y > parentArea.getCentreY() ? screenPos.y - (h + 8) : screenPos.y + 20,
                                 w, h).constrainedWithin (parentArea);
}

void LookAndFeel::drawTooltip (juce::Graphics& g, const juce::String& text, int width, int height)
{
    const auto bounds = juce::Rectangle<float> ((float) width, (float) height);

    g.setColour (colours.readout);
    g.fillRoundedRectangle (bounds, Tokens::radiusSm);

    layoutTooltip (text)->draw (g, bounds.reduced (8.0f, 6.0f));
}

//==============================================================================
void LookAndFeel::fillTextEditorBackground (juce::Graphics& g, int width, int height, juce::TextEditor& editor)
{
    g.setColour (editor.findColour (juce::TextEditor::backgroundColourId));
    g.fillRoundedRectangle (juce::Rectangle<float> ((float) width, (float) height), Tokens::radiusMd);
}

void LookAndFeel::drawTextEditorOutline (juce::Graphics& g, int width, int height, juce::TextEditor& editor)
{
    const auto bounds = juce::Rectangle<float> ((float) width, (float) height).reduced (0.5f);
    g.setColour (editor.findColour (editor.hasKeyboardFocus (true) ? juce::TextEditor::focusedOutlineColourId
                                                                   : juce::TextEditor::outlineColourId));
    g.drawRoundedRectangle (bounds, Tokens::radiusMd - 0.5f, 1.0f);
}

void LookAndFeel::drawScrollbar (juce::Graphics& g, juce::ScrollBar&, int x, int y, int width, int height,
                                 bool isScrollbarVertical, int thumbStartPosition, int thumbSize,
                                 bool isMouseOver, bool isMouseDown)
{
    auto thumb = isScrollbarVertical ? juce::Rectangle<int> (x, thumbStartPosition, width, thumbSize)
                                     : juce::Rectangle<int> (thumbStartPosition, y, thumbSize, height);
    thumb = thumb.reduced (2);

    g.setColour ((isMouseOver || isMouseDown) ? colours.inkSubtle : colours.lineControl);
    g.fillRoundedRectangle (thumb.toFloat(), (float) juce::jmin (thumb.getWidth(), thumb.getHeight()) * 0.5f);
}

//==============================================================================
void LookAndFeel::drawLinearSlider (juce::Graphics& g, int x, int y, int width, int height, float sliderPos,
                                    float minSliderPos, float maxSliderPos, juce::Slider::SliderStyle style,
                                    juce::Slider& slider)
{
    if (style != juce::Slider::LinearHorizontal && style != juce::Slider::LinearVertical)
    {
        LookAndFeel_V4::drawLinearSlider (g, x, y, width, height, sliderPos, minSliderPos, maxSliderPos, style, slider);
        return;
    }

    const auto vertical = style == juce::Slider::LinearVertical;
    const auto bounds = juce::Rectangle<float> ((float) x, (float) y, (float) width, (float) height);
    const auto bipolar = (bool) slider.getProperties().getWithDefault ("bipolar", false);
    const auto enabled = slider.isEnabled();

    juce::Graphics::ScopedSaveState save (g);
    if (! enabled)
        g.beginTransparencyLayer (0.45f);

    // 4 px track, accent fill from the minimum (or the centre).
    const auto track = vertical ? bounds.withSizeKeepingCentre (4.0f, bounds.getHeight() - 14.0f)
                                : bounds.withSizeKeepingCentre (bounds.getWidth() - 14.0f, 4.0f);
    g.setColour (colours.lineStrong);
    g.fillRoundedRectangle (track, 2.0f);

    const auto origin = bipolar ? (vertical ? track.getCentreY() : track.getCentreX())
                                : (vertical ? track.getBottom() : track.getX());
    auto fill = vertical ? juce::Rectangle<float>::leftTopRightBottom (track.getX(), juce::jmin (origin, sliderPos), track.getRight(), juce::jmax (origin, sliderPos))
                         : juce::Rectangle<float>::leftTopRightBottom (juce::jmin (origin, sliderPos), track.getY(), juce::jmax (origin, sliderPos), track.getBottom());
    g.setColour (Tokens::accent());
    g.fillRoundedRectangle (fill, 2.0f);

    // 14 px thumb: the knob in miniature.
    const auto centre = vertical ? juce::Point<float> (track.getCentreX(), sliderPos) : juce::Point<float> (sliderPos, track.getCentreY());
    const auto thumb = juce::Rectangle<float> (14.0f, 14.0f).withCentre (centre);
    g.setColour (colours.surfacePanel);
    g.fillEllipse (thumb);
    g.setColour (colours.lineControl);
    g.drawEllipse (thumb.reduced (0.75f), 1.5f);
    g.setColour (enabled ? Tokens::accent() : colours.inkSubtle);
    if (vertical)
        g.fillRoundedRectangle (juce::Rectangle<float> (6.0f, 2.0f).withCentre (centre), 1.0f);
    else
        g.fillRoundedRectangle (juce::Rectangle<float> (2.0f, 6.0f).withCentre (centre), 1.0f);

    if (! enabled)
        g.endTransparencyLayer();

    if (slider.hasKeyboardFocus (false))
        drawFocusRing (g, thumb, 7.0f, colours);
}

void LookAndFeel::drawRotarySlider (juce::Graphics& g, int x, int y, int width, int height, float sliderPosProportional,
                                    float, float, juce::Slider& slider)
{
    KnobLook look;
    look.proportion = sliderPosProportional;
    look.bipolar = (bool) slider.getProperties().getWithDefault ("bipolar", false);
    look.focused = slider.hasKeyboardFocus (false);
    look.enabled = slider.isEnabled();
    drawKnob (g, juce::Rectangle<int> (x, y, width, height).toFloat(), look, colours);
}

} // namespace oberli::ui
