#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <array>
#include <atomic>
#include <cstdint>
#include <vector>

/*  Loudness after ITU-R BS.1770-4 and EBU Tech 3341 / 3342 (sound-design-bob rule 17:
    a meter that names a standard follows it exactly and passes its test signals at
    every supported rate; dsp-reference-bob A.1 for the textbook).

      K-weighting   the two biquads of BS.1770-4 Annex 1, derived for any rate from the
                    analogue prototype (f0 1681.97 Hz shelf +4.0 dB, f0 38.14 Hz high-pass),
                    so 48 kHz gives the published coefficients and 44.1 / 96 / 192 kHz the
                    same response
      momentary     mean square over 400 ms, updated every 100 ms
      short-term    over 3 s, updated every 100 ms
      integrated    400 ms gating blocks with 75 % overlap, absolute gate -70 LUFS,
                    relative gate -10 LU (BS.1770-4 2.8)
      LRA           short-term values, absolute gate -70 LUFS, relative gate -20 LU,
                    10th to 95th percentile (EBU Tech 3342)
      true peak     BS.1770-4 Annex 2: the 48-tap, 4-phase interpolator below 96 kHz,
                    two of its phases (2x) below 192 kHz, the sample peak above

    The gating history is a histogram of 0.01 LU bins from -70 to +10 LUFS that keeps the
    sum of energies per bin, so integrated loudness is exact to well under 0.01 LU and
    the memory is fixed (allocated in prepare, never in process).

    Threads: process() and resetIntegrated() on one thread (the audio thread or the
    analysis thread that owns this object); readings() from any thread - the values are
    published as atomics at every 100 ms step. Plain C++, no JUCE: the self-test
    (tools/tests/test_loudness.cpp) compiles it on its own. */
namespace oberli
{

class Loudness
{
public:
    static constexpr int kMaxChannels = 8;
    static constexpr double kSilence = -1.0e9;   // "no reading": below every gate (shown as -inf)

    struct Readings
    {
        double momentary = kSilence, shortTerm = kSilence, integrated = kSilence;   // LUFS
        double momentaryMax = kSilence, shortTermMax = kSilence;                     // LUFS since resetIntegrated()
        double range = 0.0;                                                          // LU
        double truePeak = kSilence;                                                  // dBTP since resetIntegrated()
    };

    /** Allocates; `weights` are BS.1770's channel weights (1.0 for L, R, C; 1.41 for
        the surrounds; 0 for LFE), one per channel, default 1. */
    void prepare (double sampleRate, int numChannels, const float* weights = nullptr);

    /** Clears every filter, window and the history (a new measurement). */
    void reset();

    /** Clears the integrated history, the maxima and the true peak, keeps the windows. */
    void resetIntegrated();

    /** Real-time safe. `channels[c][i]`, `numChannels` as prepared or fewer. */
    void process (const float* const* channels, int numChannels, int numSamples);

    Readings readings() const;

    double getSampleRate() const noexcept { return rate; }
    int truePeakOversampling() const noexcept { return oversampling; }

    /** Loudness of a mean square (already K-weighted and summed). */
    static double lufsFromEnergy (double meanSquare);

private:
    struct Biquad
    {
        double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1 = 0, z2 = 0;
        double process (double x) noexcept
        {
            const auto y = b0 * x + z1;
            z1 = b1 * x - a1 * y + z2;
            z2 = b2 * x - a2 * y;
            return y;
        }
    };

    struct Histogram
    {
        static constexpr double kLowLufs = -70.0, kHighLufs = 10.0, kStep = 0.01;
        static constexpr int kBins = (int) ((kHighLufs - kLowLufs) / kStep) + 1;
        std::vector<double> energy;
        std::vector<std::uint32_t> count;
        void clear();
        void add (double meanSquare);
    };

    void stepBlock();
    double integratedNow() const;
    double rangeNow() const;
    void processTruePeak (int channel, float sample);

    double rate = 48000.0;
    int channelsPrepared = 0;
    std::array<double, kMaxChannels> weight {};
    std::array<Biquad, kMaxChannels> shelf {}, highpass {};

    int blockLength = 4800;   // 100 ms
    int blockFill = 0;
    double blockEnergy = 0.0;
    std::array<double, 30> subBlocks {};   // the last 3 s of 100 ms energies, a ring
    int subIndex = 0, subCount = 0;

    Histogram gating, shortTermValues;
    double momentaryMax = kSilence, shortTermMax = kSilence;

    // True peak: the last 12 input samples per channel.
    int oversampling = 4;
    std::array<std::array<float, 12>, kMaxChannels> history {};
    std::array<int, kMaxChannels> historyPos {};
    float truePeakLinear = 0.0f;

    std::atomic<double> pubMomentary { kSilence }, pubShortTerm { kSilence }, pubIntegrated { kSilence },
                        pubMomentaryMax { kSilence }, pubShortTermMax { kSilence }, pubRange { 0.0 }, pubTruePeak { kSilence };
};

} // namespace oberli
