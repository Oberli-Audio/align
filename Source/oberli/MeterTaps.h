#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_audio_basics/juce_audio_basics.h>

#include <array>
#include <atomic>
#include <cmath>

/*  What the audio thread hands the meters (sound-design-bob D.6.2): plain atomics,
    written once per block from processBlock, read by the editor's frame. No
    allocation, no lock, no system call (rule 1); every push() is O(samples).
    The editor takes the value (take*), so a frame sees everything since the last one
    and no peak between two frames is lost. */
namespace oberli
{

namespace detail
{
    inline void storeMax (std::atomic<float>& a, float v) noexcept
    {
        auto old = a.load (std::memory_order_relaxed);
        while (v > old && ! a.compare_exchange_weak (old, v, std::memory_order_relaxed)) {}
    }
}

/** Sample peak per channel (Meter card: the reading says PEAK) and a clip flag that
    holds until the editor clears it (a click on the CLIP LED). A sample at or above
    0 dBFS counts as a clip. */
class PeakTap
{
public:
    static constexpr int kMaxChannels = 2;

    void reset() noexcept
    {
        for (auto& p : peaks) p.store (0.0f, std::memory_order_relaxed);
        clipped.store (false, std::memory_order_relaxed);
    }

    /** Audio thread, after the block is final. */
    void push (const juce::AudioBuffer<float>& buffer, int start, int numSamples) noexcept
    {
        const auto channels = juce::jmin (kMaxChannels, buffer.getNumChannels());
        auto clip = false;

        for (int ch = 0; ch < channels; ++ch)
        {
            const auto range = juce::FloatVectorOperations::findMinAndMax (buffer.getReadPointer (ch, start), numSamples);
            const auto peak = juce::jmax (std::abs (range.getStart()), std::abs (range.getEnd()));
            detail::storeMax (peaks[(size_t) ch], std::isfinite (peak) ? peak : 1.0e6f);
            clip = clip || ! (peak < 1.0f);
        }

        if (channels == 1)
            detail::storeMax (peaks[1], peaks[0].load (std::memory_order_relaxed));

        if (clip)
            clipped.store (true, std::memory_order_relaxed);
    }

    /** Editor: the highest sample peak (linear) since the last call. */
    float takePeak (int channel) noexcept { return peaks[(size_t) juce::jlimit (0, kMaxChannels - 1, channel)].exchange (0.0f, std::memory_order_relaxed); }

    bool hasClipped() const noexcept { return clipped.load (std::memory_order_relaxed); }
    void clearClip() noexcept        { clipped.store (false, std::memory_order_relaxed); }

private:
    std::array<std::atomic<float>, kMaxChannels> peaks {};
    std::atomic<bool> clipped { false };
};

/** Gain reduction, downward (Meter: GR): the largest reduction in dB (a positive
    number) since the editor last took it. The processor pushes its gain computer's
    smallest gain of the block, linear. */
class GainReductionTap
{
public:
    void reset() noexcept { reduction.store (0.0f, std::memory_order_relaxed); }

    /** Audio thread: `minGain` the smallest gain (linear, 0..1) applied in the block. */
    void push (float minGain) noexcept
    {
        const auto db = minGain > 0.0f ? -juce::Decibels::gainToDecibels (minGain, -120.0f) : 120.0f;
        detail::storeMax (reduction, juce::jmax (0.0f, db));
    }

    float takeReductionDb() noexcept { return reduction.exchange (0.0f, std::memory_order_relaxed); }

private:
    std::atomic<float> reduction { 0.0f };
};

/** Stereo correlation, -1 (out of phase) to +1 (mono): the normalised cross-
    correlation of L and R under an exponential window of `seconds` (rule 12: set in
    prepare). Silence reads 0. */
class CorrelationTap
{
public:
    void prepare (double sampleRate, double seconds = 0.3) noexcept
    {
        coefficient = std::exp (-1.0 / (juce::jmax (1.0e-3, seconds) * sampleRate));
        reset();
    }

    void reset() noexcept
    {
        sxy = sxx = syy = 0.0;
        value.store (0.0f, std::memory_order_relaxed);
    }

    /** Audio thread, after the block is final; a mono buffer reads +1. */
    void push (const juce::AudioBuffer<float>& buffer, int start, int numSamples) noexcept
    {
        if (buffer.getNumChannels() < 2)
        {
            value.store (1.0f, std::memory_order_relaxed);
            return;
        }

        const auto* l = buffer.getReadPointer (0, start);
        const auto* r = buffer.getReadPointer (1, start);
        const auto a = coefficient, b = 1.0 - coefficient;

        for (int i = 0; i < numSamples; ++i)
        {
            const auto x = (double) l[i], y = (double) r[i];
            sxy = a * sxy + b * x * y;
            sxx = a * sxx + b * x * x;
            syy = a * syy + b * y * y;
        }

        if (! std::isfinite (sxy + sxx + syy))
            sxy = sxx = syy = 0.0;

        const auto energy = std::sqrt (sxx * syy);
        value.store (energy > 1.0e-12 ? (float) juce::jlimit (-1.0, 1.0, sxy / energy) : 0.0f, std::memory_order_relaxed);
    }

    float get() const noexcept { return value.load (std::memory_order_relaxed); }

private:
    double coefficient = 0.0, sxy = 0.0, sxx = 0.0, syy = 0.0;
    std::atomic<float> value { 0.0f };
};

} // namespace oberli
