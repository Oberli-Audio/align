#include "Meters.h"

namespace oberli::ui
{
namespace
{
    // The level in dB onto the well: ear and eye both track level logarithmically.
    constexpr float kFloorDb = -48.0f;
    constexpr float kHotDb = -6.0f;

    // Ballistics: quick up, slower down; the peak line holds, then falls a third of the well per second.
    constexpr float kRiseSeconds = 0.04f;
    constexpr float kFallSeconds = 0.30f;
    constexpr double kPeakHoldSeconds = 1.2;
    constexpr float kPeakFallPerSecond = 0.33f;
    constexpr double kLimitHoldSeconds = 1.0;
    constexpr double kNumberHoldSeconds = 0.5;   // the reading holds the highest peak this long

    constexpr float kWellWidth = 8.0f;
    constexpr float kWellGap = 4.0f;
    constexpr float kWellHeight = 48.0f;
    constexpr float kColumn = (float) LevelMeter::kColumnWidth;

    juce::String minus() { return juce::String::fromUTF8 ("\xe2\x88\x92"); }

    float proportionFor (float db) { return juce::jlimit (0.0f, 1.0f, (db - kFloorDb) / -kFloorDb); }

    void drawWell (juce::Graphics& g, juce::Rectangle<float> well, const Palette& p)
    {
        g.setColour (p.surfaceSunken);
        g.fillRoundedRectangle (well, Tokens::radiusXs);
    }

    void drawWellBorder (juce::Graphics& g, juce::Rectangle<float> well, const Palette& p)
    {
        g.setColour (p.line);
        g.drawRoundedRectangle (well.reduced (0.5f), Tokens::radiusXs - 0.5f, 1.0f);
    }
}

juce::String formatDb (float db, int decimals)
{
    if (! std::isfinite (db) || db <= -120.0f)
        return minus() + juce::String::fromUTF8 ("\xe2\x88\x9e") + " dB";

    const auto text = juce::String (std::abs (db), decimals);
    const auto isZero = juce::exactlyEqual (text.getDoubleValue(), 0.0);
    return (db < 0.0f && ! isZero ? minus() : juce::String()) + text + " dB";
}

juce::String formatSigned (float value, int decimals)
{
    const auto text = juce::String (std::abs (value), decimals);
    if (juce::exactlyEqual (text.getDoubleValue(), 0.0))
        return text;
    return (value < 0.0f ? minus() : juce::String ("+")) + text;
}

//==============================================================================
LevelMeter::LevelMeter (PeakTap& tapToUse, Led ledToUse, const Palette& p)
    : tap (tapToUse), led (ledToUse), colours (p)
{
    setTitle ("Output level");
    setTooltip (led == Led::limit
                    ? "The output level in dBFS, left and right: the sample peak, with a line holding the recent peak. "
                      "LIMIT lights while the output limiter holds the sound under 0 dBFS."
                    : "The output level in dBFS, left and right: the sample peak, with a line holding the recent peak. "
                      "CLIP lights when a sample reached 0 dBFS and stays lit until you click it.");
    setInterceptsMouseClicks (true, false);
}

int LevelMeter::getPreferredWidth() const
{
    if (led == Led::none)
        return kColumnWidth;

    return kColumnWidth + 1 + juce::roundToInt (std::ceil (type::width (type::label(), ledWord()))) + 10;
}

juce::String LevelMeter::ledWord() const { return led == Led::limit ? "LIMIT" : "CLIP"; }

juce::Rectangle<float> LevelMeter::wellArea (int channel) const noexcept
{
    const auto left = (kColumn - (2.0f * kWellWidth + kWellGap)) * 0.5f;
    return { left + (float) channel * (kWellWidth + kWellGap), 0.0f, kWellWidth, kWellHeight };
}

juce::Rectangle<float> LevelMeter::ledArea() const noexcept
{
    const auto w = std::ceil (type::width (type::label(), ledWord())) + 10.0f;
    return { (float) getWidth() - w, 0.0f, w, 16.0f };
}

juce::Rectangle<float> LevelMeter::valueBox() const noexcept
{
    return { 0.0f, kWellHeight + 4.0f + 12.0f + 8.0f, kColumn, 16.0f };
}

void LevelMeter::advance (double now, float dt)
{
    // --- The LED.
    auto lit = false;
    if (led == Led::clip)
        lit = tap.hasClipped();
    else if (led == Led::limit)
    {
        if (isLimiting != nullptr && isLimiting())
            limitLitUntil = now + kLimitHoldSeconds;
        lit = now < limitLitUntil;
    }

    if (lit != ledShown)
    {
        ledShown = lit;
        repaint (ledArea().getSmallestIntegerContainer());
    }

    // --- Each well and its peak line.
    auto blockPeak = 0.0f;
    for (int ch = 0; ch < (int) channels.size(); ++ch)
    {
        auto& c = channels[(size_t) ch];
        const auto peak = tap.takePeak (ch);
        blockPeak = juce::jmax (blockPeak, peak);
        c.level.advance (proportionFor (juce::Decibels::gainToDecibels (peak, kFloorDb - 1.0f)), dt, kRiseSeconds, kFallSeconds, 1.0e-3f);

        if (c.level.value >= c.peak)
        {
            c.peak = c.level.value;
            c.peakHoldUntil = now + kPeakHoldSeconds;
        }
        else if (now > c.peakHoldUntil)
        {
            c.peak = juce::jmax (c.level.value, c.peak - kPeakFallPerSecond * dt);
        }
    }

    // --- The number: the highest sample peak of both channels, held half a second.
    const auto peakDb = juce::Decibels::gainToDecibels (blockPeak, -120.0f);
    if (peakDb >= heldPeakDb || now > heldPeakUntil)
    {
        heldPeakDb = peakDb;
        heldPeakUntil = now + kNumberHoldSeconds;
    }

    if (now - shownAt < motion::kAmbientFrameSeconds)
        return;

    const auto pixels = kWellHeight - 2.0f;
    const auto peakVisible = [] (float peak, float lvl) { return peak > 0.01f && peak > lvl + 0.004f; };

    for (int ch = 0; ch < (int) channels.size(); ++ch)
    {
        auto& c = channels[(size_t) ch];
        const auto level = c.level.value;
        const auto levelMoved = std::abs (level - c.shownLevel) * pixels >= 1.0f || (level <= 0.0f && c.shownLevel > 0.0f);
        const auto peakMoved = std::abs (c.peak - c.shownPeak) * pixels >= 1.0f
                             || peakVisible (c.peak, level) != peakVisible (c.shownPeak, c.shownLevel);

        if (levelMoved || peakMoved)
        {
            c.shownLevel = level;
            c.shownPeak = c.peak;
            shownAt = now;
            repaint (wellArea (ch).getSmallestIntegerContainer().expanded (1));
        }
    }

    const auto db = heldPeakDb > -120.0f ? juce::roundToInt (heldPeakDb) : std::numeric_limits<int>::min();
    if (db != shownDb)
    {
        shownDb = db;
        shownAt = now;
        repaint (valueBox().getSmallestIntegerContainer());
    }
}

void LevelMeter::mouseDown (const juce::MouseEvent& e)
{
    if (led == Led::clip && ledArea().expanded (4.0f).contains (e.position))
    {
        tap.clearClip();
        ledShown = false;
        repaint (ledArea().getSmallestIntegerContainer());
    }
}

void LevelMeter::paint (juce::Graphics& g)
{
    for (int ch = 0; ch < (int) channels.size(); ++ch)
    {
        const auto& c = channels[(size_t) ch];
        const auto well = wellArea (ch);
        drawWell (g, well, colours);

        const auto inner = well.reduced (1.0f);

        if (c.shownLevel > 0.0f)
        {
            juce::Graphics::ScopedSaveState save (g);
            juce::Path clipPath;
            clipPath.addRoundedRectangle (inner, Tokens::radiusXs - 1.0f);
            g.reduceClipRegion (clipPath);

            const auto top = inner.getBottom() - inner.getHeight() * c.shownLevel;
            const auto hotLine = inner.getBottom() - inner.getHeight() * proportionFor (kHotDb);

            g.setColour (colours.meterLevel);
            g.fillRect (juce::Rectangle<float>::leftTopRightBottom (inner.getX(), juce::jmax (top, hotLine), inner.getRight(), inner.getBottom()));

            if (top < hotLine)
            {
                g.setColour (colours.meterHot);
                g.fillRect (juce::Rectangle<float>::leftTopRightBottom (inner.getX(), top, inner.getRight(), hotLine));
            }
        }

        if (c.shownPeak > 0.01f && c.shownPeak > c.shownLevel + 0.004f)
        {
            const auto y = inner.getBottom() - inner.getHeight() * c.shownPeak;
            g.setColour (colours.ink);
            g.fillRect (juce::Rectangle<float> (inner.getX(), juce::jlimit (inner.getY(), inner.getBottom() - 1.0f, y - 0.5f), inner.getWidth(), 1.0f));
        }

        drawWellBorder (g, well, colours);
    }

    if (led != Led::none)
    {
        const auto box = ledArea();
        const auto onColour = led == Led::clip ? colours.clip : colours.meterHot;

        if (ledShown)
        {
            g.setColour (onColour);
            g.fillRoundedRectangle (box, Tokens::radiusXs);
        }
        else
        {
            g.setColour (colours.lineControl);
            g.drawRoundedRectangle (box.reduced (0.5f), Tokens::radiusXs - 0.5f, 1.0f);
        }

        type::draw (g, ledWord(), box, type::label(), ledShown ? colours.ground : colours.inkSubtle, juce::Justification::centred);
    }

    type::draw (g, "PEAK", { 0.0f, kWellHeight + 4.0f, kColumn, 12.0f }, type::label(), colours.inkMuted, juce::Justification::centred);
    type::draw (g, shownDb == std::numeric_limits<int>::min() ? formatDb (-200.0f) : formatDb ((float) shownDb),
                valueBox(), type::value(), colours.ink, juce::Justification::centred);
}

//==============================================================================
GainReductionMeter::GainReductionMeter (GainReductionTap& tapToUse, float range, const Palette& p)
    : tap (tapToUse), rangeDb (range), colours (p)
{
    setTitle ("Gain reduction");
    setTooltip ("How far the level is turned down right now, in dB.");
}

juce::Rectangle<float> GainReductionMeter::wellArea() const noexcept
{
    return { ((float) kWidth - kWellWidth) * 0.5f, 0.0f, kWellWidth, kWellHeight };
}

void GainReductionMeter::advance (double now, float dt)
{
    reduction.advance (juce::jlimit (0.0f, rangeDb, tap.takeReductionDb()), dt, kRiseSeconds, kFallSeconds, 0.01f);

    if (now - shownAt < motion::kAmbientFrameSeconds)
        return;

    if (std::abs (reduction.value - shown) / rangeDb * (kWellHeight - 2.0f) >= 0.5f
        || juce::String (reduction.value, 1) != juce::String (shown, 1))
    {
        shown = reduction.value;
        shownAt = now;
        repaint();
    }
}

void GainReductionMeter::paint (juce::Graphics& g)
{
    const auto well = wellArea();
    drawWell (g, well, colours);

    const auto inner = well.reduced (1.0f);
    const auto h = inner.getHeight() * juce::jlimit (0.0f, 1.0f, shown / rangeDb);

    if (h > 0.0f)
    {
        juce::Graphics::ScopedSaveState save (g);
        juce::Path clipPath;
        clipPath.addRoundedRectangle (inner, Tokens::radiusXs - 1.0f);
        g.reduceClipRegion (clipPath);
        g.setColour (colours.meterLevel);
        g.fillRect (inner.withHeight (h));
    }

    drawWellBorder (g, well, colours);

    type::draw (g, "GR", { 0.0f, kWellHeight + 4.0f, (float) kWidth, 12.0f }, type::label(), colours.inkMuted, juce::Justification::centred);
    type::draw (g, formatDb (shown > 0.05f ? -shown : 0.0f, 1), { 0.0f, kWellHeight + 24.0f, (float) kWidth, 16.0f },
                type::value(), colours.ink, juce::Justification::centred);
}

//==============================================================================
CorrelationMeter::CorrelationMeter (CorrelationTap& tapToUse, const Palette& p)
    : tap (tapToUse), colours (p)
{
    setTitle ("Correlation");
    setTooltip ("How alike left and right are: +1 is mono, 0 unrelated, below 0 they cancel when summed to mono.");
}

juce::Rectangle<float> CorrelationMeter::wellArea() const noexcept
{
    return getLocalBounds().toFloat().withTrimmedTop (16.0f).withHeight (8.0f);
}

void CorrelationMeter::advance (double now, float dt)
{
    value.advance (tap.get(), dt, 0.1f, 0.1f, 1.0e-3f);

    if (now - shownAt < motion::kAmbientFrameSeconds)
        return;

    if (std::abs (value.value - shown) * wellArea().getWidth() * 0.5f >= 1.0f
        || formatSigned (value.value, 2) != formatSigned (shown, 2))
    {
        shown = value.value;
        shownAt = now;
        repaint();
    }
}

void CorrelationMeter::paint (juce::Graphics& g)
{
    const auto top = getLocalBounds().toFloat().withHeight (12.0f);
    type::draw (g, "CORRELATION", top, type::label(), colours.inkMuted);
    type::draw (g, formatSigned (shown, 2), top, type::value(), colours.ink, juce::Justification::centredRight);

    const auto well = wellArea();
    drawWell (g, well, colours);

    const auto inner = well.reduced (1.0f);
    g.setColour (colours.line);
    g.fillRect (juce::Rectangle<float> (inner.getCentreX() - 0.5f, inner.getY(), 1.0f, inner.getHeight()));

    const auto x = inner.getX() + inner.getWidth() * (juce::jlimit (-1.0f, 1.0f, shown) + 1.0f) * 0.5f;
    g.setColour (shown < 0.0f ? colours.meterHot : colours.ink);
    g.fillRoundedRectangle (juce::Rectangle<float> (3.0f, inner.getHeight()).withCentre ({ juce::jlimit (inner.getX() + 1.5f, inner.getRight() - 1.5f, x), inner.getCentreY() }), 1.0f);

    drawWellBorder (g, well, colours);
}

} // namespace oberli::ui
