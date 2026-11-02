#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_audio_processors/juce_audio_processors.h>

#include <cmath>

/*  Rendering offline (a bounce, a freeze, an export) must give the same audio as playing
    (sound-design-bob D.5: hosts render faster than real time and some call
    setNonRealtime()). Two rules follow, and the harness proves both:

      1. The audio path never depends on isNonRealtime(). Only work nobody hears may: the
         display copy (Analyser, meters) is skipped offline, because a bounce runs
         faster than the analysis thread drains and nobody watches it.
      2. A wire - a plugin that measures and passes the audio unchanged (Bench Line,
         A B see with the reference off) - is bit-exact: output == input, sample for
         sample, at every block size.

    The bounce null test: tools/tests/check_bounce.py renders the same input with and
    without the harness's --non-realtime and requires the two outputs to be identical
    (--wire: and equal to the input). It runs in the fast label.

    In processBlock:

        const auto mode = oberli::render::modeFor (*this);
        ... the audio path, the same in both modes ...
        if (mode.feedDisplay)
            analyser.push (buffer, 0, buffer.getNumSamples());
*/
namespace oberli::render
{

struct BlockMode
{
    bool offline = false;       // the host renders faster than real time
    bool feedDisplay = true;    // hand audio to the display copy and the meters' taps
};

inline BlockMode modeFor (const juce::AudioProcessor& p) noexcept
{
    BlockMode m;
    m.offline = p.isNonRealtime();
    m.feedDisplay = ! m.offline;
    return m;
}

/** The largest sample difference between two buffers, linear (0 when bit-identical over
    the shared channels and length). For tests and the harness, never the audio path. */
inline float maxDifference (const juce::AudioBuffer<float>& a, const juce::AudioBuffer<float>& b) noexcept
{
    const auto channels = juce::jmin (a.getNumChannels(), b.getNumChannels());
    const auto n = juce::jmin (a.getNumSamples(), b.getNumSamples());
    float worst = 0.0f;

    for (int ch = 0; ch < channels; ++ch)
        for (int i = 0; i < n; ++i)
            worst = juce::jmax (worst, std::abs (a.getSample (ch, i) - b.getSample (ch, i)));

    return worst;
}

/** A wire's debug check: copy the input in prepare-sized storage before the block, compare
    after it. Debug builds only (jassert); the harness's --wire test is the release check. */
class WireCheck
{
public:
    void prepare (int numChannels, int maxBlock) { copy.setSize (numChannels, juce::jmax (1, maxBlock), false, true, false); }

    void before (const juce::AudioBuffer<float>& buffer) noexcept
    {
       #if JUCE_DEBUG
        const auto n = juce::jmin (buffer.getNumSamples(), copy.getNumSamples());
        for (int ch = 0; ch < juce::jmin (buffer.getNumChannels(), copy.getNumChannels()); ++ch)
            copy.copyFrom (ch, 0, buffer, ch, 0, n);
       #else
        juce::ignoreUnused (buffer);
       #endif
    }

    void after (const juce::AudioBuffer<float>& buffer) noexcept
    {
       #if JUCE_DEBUG
        const auto n = juce::jmin (buffer.getNumSamples(), copy.getNumSamples());
        for (int ch = 0; ch < juce::jmin (buffer.getNumChannels(), copy.getNumChannels()); ++ch)
            for (int i = 0; i < n; ++i)
                jassert (juce::exactlyEqual (buffer.getSample (ch, i), copy.getSample (ch, i)));   // a wire changed the audio
       #else
        juce::ignoreUnused (buffer);
       #endif
    }

private:
    juce::AudioBuffer<float> copy;
};

} // namespace oberli::render
