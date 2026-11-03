#include "AlignDisplays.h"

namespace align::ui
{
namespace
{
using namespace oberli::ui;

void drawWell (juce::Graphics& g, juce::Rectangle<float> r, const Palette& t)
{
    g.setColour (t.surfaceSunken);
    g.fillRoundedRectangle (r, Tokens::radiusXs);
    g.setColour (t.line);
    g.drawRoundedRectangle (r.reduced (0.5f), Tokens::radiusXs, 1.0f);
}

void drawEmpty (juce::Graphics& g, juce::Rectangle<float> r, const juce::String& text, const Palette& t)
{
    g.setColour (t.inkSubtle);
    g.setFont (type::small());
    g.drawFittedText (text, r.reduced (16.0f).toNearestInt(), juce::Justification::centred, 2);
}

juce::String msText (float ms)
{
    const juce::String minus = juce::String::fromUTF8 ("\xe2\x88\x92");   // a real minus sign
    if (std::abs (ms) < 0.005f)
        return "0";
    return (ms < 0.0f ? minus : juce::String ("+")) + juce::String (juce::roundToInt (std::abs (ms))) + " ms";
}
} // namespace

//==============================================================================
CorrelationWell::CorrelationWell()
{
    setInterceptsMouseClicks (false, false);
    setTitle ("Correlation");
}

void CorrelationWell::setResult (const align::dsp::Detector::Result& r, bool has)
{
    result = r;
    hasResult = has && r.ok;
    repaint();
}

void CorrelationWell::setEmptyText (const juce::String& text)
{
    if (text != emptyText)
    {
        emptyText = text;
        repaint();
    }
}

void CorrelationWell::paint (juce::Graphics& g)
{
    const auto& t = front();
    auto r = getLocalBounds().toFloat();
    drawWell (g, r, t);

    // the lag axis's labels sit inside the well's foot, as in the sketch
    auto plot = r.reduced (8.0f, 6.0f);
    auto axis = plot.removeFromBottom (14.0f);
    if (! hasResult)
    {
        drawEmpty (g, r, emptyText, t);
        return;
    }
    g.setColour (t.line);
    g.fillRect (plot.getX(), plot.getCentreY() - 0.5f, plot.getWidth(), 1.0f);   // zero correlation

    const float lo = result.curveLoMs, hi = juce::jmax (result.curveLoMs + 0.1f, result.curveHiMs);
    auto xAt = [&] (float ms) { return plot.getX() + (ms - lo) / (hi - lo) * plot.getWidth(); };
    if (lo < 0.0f && hi > 0.0f)
        g.fillRect (xAt (0.0f) - 0.5f, plot.getY(), 1.0f, plot.getHeight());       // lag zero

    type::draw (g, msText (lo), axis, type::meta(), t.inkSubtle, juce::Justification::centredLeft);
    type::draw (g, msText (hi), axis, type::meta(), t.inkSubtle, juce::Justification::centredRight);
    if (lo < 0.0f && hi > 0.0f)
        type::draw (g, "0", juce::Rectangle<float> (xAt (0.0f) - 20.0f, axis.getY(), 40.0f, axis.getHeight()),
                    type::meta(), t.inkSubtle, juce::Justification::centred);

    float peak = 0.0f;
    for (auto v : result.curve)
        peak = juce::jmax (peak, std::abs (v));
    if (peak <= 0.0f)
        return;
    const float half = plot.getHeight() * 0.5f - 4.0f;
    auto yAt = [&] (float v) { return plot.getCentreY() - v / peak * half; };

    juce::Path curve;
    const int n = (int) result.curve.size();
    for (int i = 0; i < n; ++i)
    {
        const float x = plot.getX() + ((float) i + 0.5f) / (float) n * plot.getWidth();
        const float y = yAt (result.curve[(size_t) i]);
        if (i == 0) curve.startNewSubPath (x, y); else curve.lineTo (x, y);
    }
    g.setColour (t.ink);
    g.strokePath (curve, juce::PathStrokeType (1.25f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));

    // the found peak, in the accent: what Detect set. Its dot sits on the curve's extreme, up or down.
    const float px = xAt (result.delayMs);
    const float py = yAt (result.inverted ? -peak : peak);
    g.setColour (Tokens::accent());
    g.fillRect (px - 0.75f, plot.getY(), 1.5f, plot.getHeight());
    g.fillEllipse (px - 3.5f, py - 3.5f, 7.0f, 7.0f);
}

//==============================================================================
SumWell::SumWell (oberli::Analyser& b, oberli::Analyser& a) : before (b), after (a)
{
    setInterceptsMouseClicks (false, false);
    setTitle ("Sum");
}

void SumWell::advance()
{
    const auto gb = before.generation(), ga = after.generation();
    if (gb == seenBefore && ga == seenAfter)
        return;
    seenBefore = gb;
    seenAfter = ga;
    bands = juce::jmin (before.numBands(), after.numBands());
    for (int i = 0; i < bands; ++i)
    {
        beforeDb[(size_t) i] = before.fastDb (i);
        afterDb[(size_t) i] = after.fastDb (i);
        centres[(size_t) i] = after.bandCentre (i);
    }
    repaint();
}

void SumWell::setReferencePresent (bool present)
{
    if (present != reference)
    {
        reference = present;
        repaint();
    }
}

juce::Path SumWell::curveFor (const std::array<float, oberli::Spectrum::kMaxBands>& db, juce::Rectangle<float> plot,
                              float topDb, float spanDb) const
{
    juce::Path p;
    const float l0 = std::log10 (20.0f), l1 = std::log10 (20000.0f);
    bool started = false;
    for (int i = 0; i < bands; ++i)
    {
        const float f = centres[(size_t) i];
        if (f < 20.0f || f > 20000.0f)
            continue;
        const float x = plot.getX() + (std::log10 (f) - l0) / (l1 - l0) * plot.getWidth();
        const float v = juce::jlimit (topDb - spanDb, topDb, db[(size_t) i]);
        const float y = plot.getY() + (topDb - v) / spanDb * plot.getHeight();
        if (! started) { p.startNewSubPath (x, y); started = true; } else p.lineTo (x, y);
    }
    return p;
}

void SumWell::paint (juce::Graphics& g)
{
    const auto& t = front();
    auto r = getLocalBounds().toFloat();
    drawWell (g, r, t);
    if (! reference)
    {
        drawEmpty (g, r, "No reference: the sum needs the reference mic on the sidechain", t);
        return;
    }
    auto plot = r.reduced (8.0f, 6.0f);
    auto axis = plot.removeFromBottom (14.0f);

    const float l0 = std::log10 (20.0f), l1 = std::log10 (20000.0f);
    for (auto [hz, label] : { std::pair<float, const char*> { 100.0f, "100" }, { 1000.0f, "1k" }, { 10000.0f, "10k" } })
    {
        const float x = plot.getX() + (std::log10 (hz) - l0) / (l1 - l0) * plot.getWidth();
        g.setColour (t.line);
        g.fillRect (x - 0.5f, plot.getY(), 1.0f, plot.getHeight());
        type::draw (g, label, juce::Rectangle<float> (x - 20.0f, axis.getY(), 40.0f, axis.getHeight()),
                    type::meta(), t.inkSubtle, juce::Justification::centred);
    }

    float top = -200.0f;
    for (int i = 0; i < bands; ++i)
        top = juce::jmax (top, beforeDb[(size_t) i], afterDb[(size_t) i]);
    if (bands == 0 || top < -100.0f)
    {
        drawEmpty (g, r, "The sum appears while the track and the reference play", t);
        return;
    }
    const float topDb = std::ceil ((top + 3.0f) / 6.0f) * 6.0f, spanDb = 42.0f;   // 7 x 6 dB, enough for the comb's teeth

    juce::Path dashed;
    const float dash[] = { 3.0f, 3.0f };
    juce::PathStrokeType (1.25f).createDashedStroke (dashed, curveFor (beforeDb, plot, topDb, spanDb), dash, 2);
    g.setColour (t.inkSubtle);
    g.fillPath (dashed);
    g.setColour (t.ink);
    g.strokePath (curveFor (afterDb, plot, topDb, spanDb),
                  juce::PathStrokeType (1.5f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));
}
} // namespace align::ui
