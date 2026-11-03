#include "PluginEditor.h"
#include "BuildInfo.h"
#include "Params.h"
#include "State.h"

#include <ProductData.h>

namespace
{
using namespace oberli::ui;

constexpr int kGroupGap = Tokens::space6;              // between groups
constexpr int kTitle = 14;                             // a caps section title's line box
constexpr int kTitleGap = Tokens::space3;
constexpr int kOutputWidth = 136;                      // the output column: Trim, the meters
constexpr int kAlignWidth = 330;                       // WINDOW's five segments decide it
constexpr int kTopHeight = 298;                        // the control rows (sketch 2)
constexpr int kWellHeight = 120;
constexpr int kLegend = 14;

/** A document compiled into the plugin (CMakeLists.txt: ProductData), by its file name. */
juce::String embedded (const char* fileName)
{
    int size = 0;
    for (int i = 0; i < ProductData::namedResourceListSize; ++i)
        if (juce::String (ProductData::getNamedResourceOriginalFilename (ProductData::namedResourceList[i])) == fileName)
            if (const auto* data = ProductData::getNamedResource (ProductData::namedResourceList[i], size))
                return juce::String::fromUTF8 (data, size);
    return {};
}

StripEditor::Info infoFor()
{
    StripEditor::Info info;
    info.productName = JucePlugin_Name;
    info.version = PRODUCT_VERSION;
    info.what = "Lines up a mic against its reference in one press: delay, polarity, and a low-end rotation.";
    info.licences = embedded ("LICENSE") + "\n\n" + embedded ("THIRD_PARTY_NOTICES.md");
    info.soundVersion = align::State::kDspVersion;
    return info;
}

juce::StringArray choicesOf (juce::AudioProcessorValueTreeState& apvts, const char* id)
{
    if (auto* c = dynamic_cast<juce::AudioParameterChoice*> (apvts.getParameter (id)))
        return c->choices;
    return {};
}

juce::String nameOf (juce::AudioProcessorValueTreeState& apvts, const char* id)
{
    auto* p = apvts.getParameter (id);
    return p != nullptr ? p->getName (12) : juce::String (id);
}

/** Splits a "a · b · c · d" readout after its second dot, as the sketch sets it on two lines. */
void twoLines (const juce::String& text, juce::String (&lines)[2])
{
    const juce::String dot = juce::String::fromUTF8 (" \xc2\xb7 ");
    const int first = text.indexOf (dot);
    const int second = first >= 0 ? text.indexOf (first + dot.length(), dot) : -1;
    if (second < 0)
    {
        lines[0] = text;
        lines[1] = {};
        return;
    }
    lines[0] = text.substring (0, second);
    lines[1] = text.substring (second + dot.length());
}

void attachTip (juce::SettableTooltipClient& c, const char* id)
{
    c.setTooltip (Params::tooltipFor (id));
}
} // namespace

AlignAudioProcessorEditor::AlignAudioProcessorEditor (AlignAudioProcessor& p)
    : StripEditor (p, p.presetHost(), infoFor()),
      audioProcessor (p),
      delayKnob (p.parameters(), Params::delay, nameOf (p.parameters(), Params::delay), Tokens::knobLg),
      rotateKnob (p.parameters(), Params::rotate, nameOf (p.parameters(), Params::rotate), Tokens::knobMd),
      belowKnob (p.parameters(), Params::below, nameOf (p.parameters(), Params::below), Tokens::knobMd),
      trimKnob (p.parameters(), Params::trim, nameOf (p.parameters(), Params::trim), Tokens::knobLg),
      detectButton ("Detect", ActionButton::Variant::primary),
      applyButton ("Apply", ActionButton::Variant::secondary),
      polarityPill (nameOf (p.parameters(), Params::polarity)),
      holdPill (nameOf (p.parameters(), Params::hold)),
      polarityAttachment (p.parameters(), Params::polarity, polarityPill),
      holdAttachment (p.parameters(), Params::hold, holdPill),
      windowSegments (choicesOf (p.parameters(), Params::window)),
      modeSegments (choicesOf (p.parameters(), Params::mode)),
      listenSegments (choicesOf (p.parameters(), Params::listen)),
      meter (p.outputPeaks(), LevelMeter::Led::clip),
      correlationMeter (p.referenceCorrelation()),
      sumWell (p.sumBefore(), p.sumAfter())
{
    auto& apvts = audioProcessor.parameters();

    for (auto [k, id] : { std::pair<ParameterKnob*, const char*> { &delayKnob, Params::delay }, { &rotateKnob, Params::rotate },
                          { &belowKnob, Params::below }, { &trimKnob, Params::trim } })
    {
        k->knob().setTooltip (Params::tooltipFor (id));
        k->knob().setHelpText (Params::tooltipFor (id));
        addAndMakeVisible (*k);
    }
    delayKnob.knob().setBipolar (true);   // a signed offset: the arc grows from 12 o'clock
    trimKnob.knob().setBipolar (true);

    for (auto [s, id] : { std::pair<SegmentedControl*, const char*> { &windowSegments, Params::window },
                          { &modeSegments, Params::mode }, { &listenSegments, Params::listen } })
    {
        if (auto* parameter = apvts.getParameter (id))
            s->attach (*parameter);
        attachTip (*s, id);
        addAndMakeVisible (*s);
    }

    attachTip (polarityPill, Params::polarity);
    attachTip (holdPill, Params::hold);
    addAndMakeVisible (polarityPill);
    addAndMakeVisible (holdPill);

    detectButton.setTooltip (Params::tooltipFor (Params::detect));
    detectButton.onClick = [this] { pressDetect(); };
    addAndMakeVisible (detectButton);
    applyButton.setTooltip ("Sets Rotate and Below to Detect's suggestion, as one step you can undo.");
    applyButton.onClick = [this] { audioProcessor.applyRotateSuggestion(); };
    addChildComponent (applyButton);

    meter.setTooltip ("Output peak. CLIP stays lit until you click it.");
    correlationMeter.setTooltip ("Correlation between the reference and this track as the host plays them: "
                                 "+1 is in phase, below 0 they cancel.");
    addAndMakeVisible (meter);
    addAndMakeVisible (correlationMeter);
    addAndMakeVisible (correlationWell);
    addAndMakeVisible (sumWell);

    setBodySize (kAlignWidth + kGroupGap + 278 + kGroupGap + 1 + kGroupGap + kOutputWidth,
                 kTopHeight + Tokens::space5 + kTitle + Tokens::space2 + kWellHeight + Tokens::space2 + kLegend);

    audioProcessor.setDisplaysActive (true);
    audioProcessor.presetLibrary().writeFactoryFolder();   // the bank as files, once per version
    refreshDetect (true);
    refreshSuggestion();
}

AlignAudioProcessorEditor::~AlignAudioProcessorEditor()
{
    audioProcessor.setDisplaysActive (false);
}

//==============================================================================
void AlignAudioProcessorEditor::layoutBody (juce::Rectangle<int> area)
{
    // OUTPUT, last on the right, behind a hairline the full height
    auto output = area.removeFromRight (kOutputWidth);
    area.removeFromRight (kGroupGap);
    outputRule = area.removeFromRight (1);
    area.removeFromRight (kGroupGap);

    outputTitle = output.removeFromTop (kTitle);
    output.removeFromTop (kTitleGap);
    trimKnob.setBounds (output.removeFromTop (trimKnob.getPreferredHeight())
                            .withSizeKeepingCentre (trimKnob.getPreferredWidth(), trimKnob.getPreferredHeight()));
    output.removeFromTop (Tokens::space5);
    meter.setBounds (output.removeFromTop (LevelMeter::kHeight).withSizeKeepingCentre (meter.getPreferredWidth(), LevelMeter::kHeight));
    output.removeFromTop (Tokens::space5);
    correlationMeter.setBounds (output.removeFromTop (CorrelationMeter::kHeight));

    // the wells across the bottom
    auto top = area.removeFromTop (kTopHeight);
    area.removeFromTop (Tokens::space5);
    auto titles = area.removeFromTop (kTitle);
    area.removeFromTop (Tokens::space2);
    auto wells = area.removeFromTop (kWellHeight);
    area.removeFromTop (Tokens::space2);
    auto legends = area.removeFromTop (kLegend);
    const int wellWidth = (wells.getWidth() - Tokens::space5) / 2;
    correlationTitle = titles.withWidth (wellWidth);
    sumTitle = titles.withTrimmedLeft (wellWidth + Tokens::space5);
    correlationWell.setBounds (wells.withWidth (wellWidth));
    sumWell.setBounds (wells.withTrimmedLeft (wellWidth + Tokens::space5));
    correlationLegend = legends.withWidth (wellWidth);
    sumLegend = legends.withTrimmedLeft (wellWidth + Tokens::space5);

    // ALIGN
    auto align = top.removeFromLeft (kAlignWidth);
    top.removeFromLeft (kGroupGap);
    alignTitle = align.removeFromTop (kTitle);
    align.removeFromTop (kTitleGap);
    auto row = align.removeFromTop (delayKnob.getPreferredHeight());
    delayKnob.setBounds (row.removeFromLeft (delayKnob.getPreferredWidth()));
    row.removeFromLeft (Tokens::space5);
    const auto detectWidth = juce::jmax (96, detectButton.getPreferredWidth());
    detectButton.setBounds (row.getX(), row.getY() + Tokens::space1, detectWidth, Tokens::controlHeight + 4);
    progressBox = juce::Rectangle<int> (row.getX(), detectButton.getBottom() + 3, detectWidth, 2);
    readoutBox = juce::Rectangle<int> (row.getX(), detectButton.getBottom() + Tokens::space3, row.getWidth(), 32);

    align.removeFromTop (Tokens::space3);
    auto pills = align.removeFromTop (Tokens::controlHeight);
    polarityPill.setBounds (pills.removeFromLeft (polarityPill.getPreferredWidth()));
    pills.removeFromLeft (Tokens::space2);
    holdPill.setBounds (pills.removeFromLeft (holdPill.getPreferredWidth()));

    align.removeFromTop (Tokens::space4);
    windowTitle = align.removeFromTop (kTitle);
    align.removeFromTop (Tokens::space2);
    windowSegments.setBounds (align.removeFromTop (Tokens::controlHeight));

    align.removeFromTop (Tokens::space4);
    auto modeRow = align.removeFromTop (kTitle);
    align.removeFromTop (Tokens::space2);
    auto segRow = align.removeFromTop (Tokens::controlHeight);
    const int modeWidth = juce::jmax (modeSegments.getPreferredWidth(), 144);
    modeTitle = modeRow.withWidth (modeWidth);
    listenTitle = modeRow.withTrimmedLeft (modeWidth + Tokens::space3);
    modeSegments.setBounds (segRow.removeFromLeft (modeWidth));
    segRow.removeFromLeft (Tokens::space3);
    listenSegments.setBounds (segRow);

    // ROTATE
    auto rotate = top;
    rotateTitle = rotate.removeFromTop (kTitle);
    rotate.removeFromTop (kTitleGap);
    auto knobs = rotate.removeFromTop (rotateKnob.getPreferredHeight());
    rotateKnob.setBounds (knobs.removeFromLeft (juce::jmax (72, rotateKnob.getPreferredWidth())));
    knobs.removeFromLeft (Tokens::space4);
    belowKnob.setBounds (knobs.removeFromLeft (juce::jmax (72, belowKnob.getPreferredWidth())));
    rotate.removeFromTop (Tokens::space5);
    suggestionBox = rotate.removeFromTop (32);
    rotate.removeFromTop (Tokens::space3);
    applyButton.setBounds (rotate.getX(), rotate.getY(), juce::jmax (96, applyButton.getPreferredWidth()), Tokens::controlHeight);
}

void AlignAudioProcessorEditor::paint (juce::Graphics& g)
{
    StripEditor::paint (g);
    const auto& t = front();
    for (auto [box, word] : { std::pair<juce::Rectangle<int>, const char*> { alignTitle, "ALIGN" }, { rotateTitle, "ROTATE" },
                              { outputTitle, "OUTPUT" }, { correlationTitle, "CORRELATION" }, { sumTitle, "SUM" } })
        type::draw (g, word, box.toFloat(), type::section(), t.inkMuted);
    for (auto [box, word] : { std::pair<juce::Rectangle<int>, const char*> { windowTitle, "WINDOW" }, { modeTitle, "MODE" },
                              { listenTitle, "LISTEN" } })
        type::draw (g, word, box.toFloat(), type::label(), t.inkMuted);
    g.setColour (t.line);
    g.fillRect (outputRule);

    // the readout in words (defining feature 3) and the suggestion
    for (int i = 0; i < 2; ++i)
    {
        type::draw (g, readout[i], readoutBox.toFloat().withHeight (16.0f).translated (0.0f, 16.0f * (float) i),
                    type::meta(), readoutColour);
        type::draw (g, suggestion[i], suggestionBox.toFloat().withHeight (16.0f).translated (0.0f, 16.0f * (float) i),
                    type::meta(), t.inkMuted);
    }

    // detecting: a hairline under Detect until the worker answers
    if (detectPressedAt >= 0.0)
    {
        const auto phase = (float) std::fmod (clockNow() - detectPressedAt, 0.6) / 0.6f;
        auto bar = progressBox.toFloat();
        g.setColour (t.line);
        g.fillRect (bar);
        g.setColour (Tokens::accent());
        g.fillRect (bar.withWidth (bar.getWidth() * 0.3f).withX (bar.getX() + bar.getWidth() * 0.7f * phase));
    }

    // legends: what the marks mean, never colour alone
    auto legend = [&] (juce::Rectangle<int> box, std::initializer_list<std::pair<int, const char*>> items)
    {
        auto r = box.toFloat();
        for (auto [kind, word] : items)
        {
            auto swatch = r.removeFromLeft (16.0f).withSizeKeepingCentre (16.0f, 2.0f);
            if (kind == 0)      { g.setColour (t.ink); g.fillRect (swatch.withHeight (1.5f)); }
            else if (kind == 1) { g.setColour (t.inkSubtle); for (float x = 0.0f; x < 16.0f; x += 6.0f) g.fillRect (swatch.getX() + x, swatch.getY(), 3.0f, 1.25f); }
            else                { g.setColour (Tokens::accent()); g.fillRect (swatch.withWidth (1.5f).withX (swatch.getCentreX()).withSizeKeepingCentre (1.5f, 10.0f)); }
            r.removeFromLeft (6.0f);
            const auto w = type::width (type::meta(), word);
            type::draw (g, word, r.removeFromLeft (w), type::meta(), t.inkSubtle);
            r.removeFromLeft (16.0f);
        }
    };
    legend (correlationLegend, { { 0, "Correlation" }, { 2, "Found peak; down means flipped" } });
    legend (sumLegend, { { 0, "After" }, { 1, "Before" } });
}

//==============================================================================
void AlignAudioProcessorEditor::pressDetect()
{
    if (auto* detect = audioProcessor.parameters().getParameter (Params::detect))
    {
        // the momentary parameter, as a controller would press it; the processor sets it back
        detect->beginChangeGesture();
        detect->setValueNotifyingHost (1.0f);
        detect->endChangeGesture();
    }
    detectPressedAt = clockNow();
    repaint (progressBox);
}

void AlignAudioProcessorEditor::refreshDetect (bool force)
{
    const auto& t = front();
    const bool side = audioProcessor.sidechainConnected();
    const int sequence = audioProcessor.detectSequence();
    if (! force && side == hadSidechain && sequence == seenSequence)
        return;
    hadSidechain = side;
    if (sequence != seenSequence)
    {
        seenSequence = sequence;
        if (sequence > 0)
        {
            lastResult = audioProcessor.lastDetect();
            hasResult = true;
        }
        detectPressedAt = -1.0;
    }
    detectButton.setEnabled (side);
    sumWell.setReferencePresent (side);

    if (! side)
    {
        readout[0] = "Route the reference mic into";
        readout[1] = "the sidechain input";
        readoutColour = t.inkMuted;
    }
    else if (hasResult)
    {
        twoLines (align::dsp::Detector::words (lastResult), readout);
        readoutColour = lastResult.ok ? t.ink : t.inkMuted;
    }
    else
    {
        readout[0] = "Press Detect while both";
        readout[1] = "mics play";
        readoutColour = t.inkMuted;
    }
    correlationWell.setEmptyText (side ? "Press Detect: the correlation over the window appears here"
                                       : "No reference: route the reference mic into the sidechain input");
    correlationWell.setResult (lastResult, hasResult);
    refreshSuggestion();
    repaint (readoutBox.getUnion (progressBox));
}

void AlignAudioProcessorEditor::refreshSuggestion()
{
    const auto& s = lastResult.suggestion;
    const bool shown = hasResult && lastResult.ok;
    juce::String lines[2];
    if (! shown)
    {
        lines[0] = "Detect proposes an angle here";
    }
    else if (s.otherMic)
    {
        lines[0] = "Rotate cannot help: this track's low end is late.";
        lines[1] = "Put Align on the reference mic instead.";
    }
    else
    {
        // "Detect suggests 48 deg below 110 Hz" over "correlation below 300 Hz 0.58 -> 0.88"
        const juce::String dot = juce::String::fromUTF8 (" \xc2\xb7 ");
        const auto words = align::dsp::Detector::suggestionWords (s);
        lines[0] = words.upToFirstOccurrenceOf (dot, false, false);
        lines[1] = words.fromFirstOccurrenceOf (dot, false, false);
    }
    if (lines[0] != suggestion[0] || lines[1] != suggestion[1])
    {
        suggestion[0] = lines[0];
        suggestion[1] = lines[1];
        repaint (suggestionBox);
    }

    // Apply while the suggestion differs from what is set; after Apply the knobs carry it
    bool offer = shown && s.needed;
    if (offer)
    {
        auto& apvts = audioProcessor.parameters();
        const float rot = apvts.getRawParameterValue (Params::rotate)->load();
        const float below = apvts.getRawParameterValue (Params::below)->load();
        offer = std::abs (rot - s.rotateDeg) > 0.5f || std::abs (below - s.belowHz) > 0.5f;
        const auto caption = "Apply " + juce::String (juce::roundToInt (s.rotateDeg)) + juce::String::fromUTF8 ("\xc2\xb0");
        if (applyButton.getButtonText() != caption)
            applyButton.setButtonText (caption);
    }
    if (applyButton.isVisible() != offer)
        applyButton.setVisible (offer);
}

void AlignAudioProcessorEditor::refreshTrack()
{
    // Track: the offset Track adds, as a `mod` range beside the user's value (sketch 2.5)
    auto& apvts = audioProcessor.parameters();
    const bool tracking = apvts.getRawParameterValue (Params::mode)->load() >= 0.5f;
    auto* delay = apvts.getParameter (Params::delay);
    if (! tracking || delay == nullptr)
    {
        delayKnob.knob().setModulationRange (0.0f, 0.0f);
        return;
    }
    const float base = delay->getValue();
    const float moved = delay->convertTo0to1 (juce::jlimit (-200.0f, 200.0f, apvts.getRawParameterValue (Params::delay)->load()
                                                                               + audioProcessor.trackOffsetMs()));
    delayKnob.knob().setModulationRange (juce::jmin (base, moved), juce::jmax (base, moved));
}

void AlignAudioProcessorEditor::advanceBody (double now, float dt)
{
    for (auto* k : { &delayKnob, &rotateKnob, &belowKnob, &trimKnob })
        k->advance (now, dt);
    meter.advance (now, dt);
    correlationMeter.advance (now, dt);
    sumWell.advance();
    refreshDetect (false);
    refreshSuggestion();
    refreshTrack();
    if (detectPressedAt >= 0.0)
    {
        if (now - detectPressedAt > 2.0)   // the worker always answers; never spin forever
            detectPressedAt = -1.0;
        repaint (progressBox);
    }
}

void AlignAudioProcessorEditor::presetRecalled (double now)
{
    // the knobs glide to the recalled values one after another, in signal-flow order
    auto start = now;
    for (auto* k : { &delayKnob, &rotateKnob, &belowKnob, &trimKnob })
    {
        k->knob().beginWave (start, false);
        start += 0.04;
    }
}

bool AlignAudioProcessorEditor::previewDrag (const juce::String& parameterId)
{
    auto* parameter = audioProcessor.parameters().getParameter (parameterId);
    if (parameter == nullptr)
        return false;
    for (auto* k : { &delayKnob, &rotateKnob, &belowKnob, &trimKnob })
        if (k->knob().getTitle() == parameter->getName (64))
        {
            k->knob().setDragPreview (true);
            return true;
        }
    return false;
}
