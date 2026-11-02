#pragma once

#include <juce_dsp/juce_dsp.h>

#include "AnalysisRing.h"
#include "Fade.h"
#include "Rotate.h"
#include "SincDelay.h"

/*  Align - the audio path (ported from "sound design"/engine.py).

        in -> polarity -> fractional delay (Window + Delay) -> Rotate -> Trim -> out
        Listen: Off = out, Ref = the sidechain, Sum = (out + ref) / 2 in mono on both channels

    Every stage is individually nullable, which is what the brief's null test asserts: Polarity off
    is a wire, Delay 0 at Window 0 is a wire, Rotate 0 is a wire (the stage crossfades out), Trim
    0 dB is a wire. With a Window above zero the plugin delays by exactly `round(Window * fs/1000)`
    whole samples and reports that number, so the host's compensation is exact and the null closes
    after it - measured bit-identical in both cases.

    Latency and the clamp (G1 decision 6):
        latencySamples = round(Window_ms * fs / 1000)
        internal delay = latencySamples + clamp(Delay_ms, -Window_ms, +200 ms) * fs / 1000

    Parameter targets are read once per block (the `control_rate` column of parameters.csv) and
    smoothed with the `smoothing` column's tau. prepare() allocates; process() does not (rule 1).
*/
namespace align::dsp
{
class AlignEngine
{
public:
    static constexpr float kWindowMs[5] = { 0.0f, 5.0f, 20.0f, 50.0f, 200.0f };
    static constexpr int   kNumWindows = 5;
    static constexpr float kDelayMaxMs = 200.0f;
    static constexpr float kPolarityFadeMs = 15.0f;
    static constexpr float kListenFadeMs = 15.0f;
    static constexpr float kTrimTauMs = 20.0f;
    static constexpr float kBypassFadeMs = 15.0f;
    static constexpr float kRotateTauMs = 20.0f;
    static constexpr float kBelowTauMs = 20.0f;
    // Rotate and Below move the all-passes' coefficient, so they advance on a control grid of
    // this period, fixed to the stream (rule 2: sub-blocks of at most 32 samples; 7 at 44.1 kHz,
    // 31 at 192 kHz). Neither the smoothing time nor the output depends on the host's block size.
    static constexpr float kControlMs = 0.16f;

    struct Params
    {
        float delayMs = 0.0f;
        bool  polarity = false;
        int   window = 2;
        float rotateDeg = 0.0f;
        float belowHz = 120.0f;
        int   listen = 0;      // 0 Off, 1 Ref, 2 Sum
        float trimDb = 0.0f;
        float trackOffsetMs = 0.0f;   // what Track mode adds; never written to the parameter

        float windowMs() const noexcept { return kWindowMs[juce::jlimit (0, kNumWindows - 1, window)]; }
    };

    void prepare (double sampleRate, int maxBlockSize, const Params& p)
    {
        rate = sampleRate;
        maxBlock = juce::jmax (1, maxBlockSize);
        params = p;
        const double maxDelay = ((double) kDelayMaxMs + (double) kWindowMs[kNumWindows - 1]) * 1.0e-3 * sampleRate;
        delayLine.prepare (sampleRate, maxDelay, maxBlock, 2);
        rotateStage.prepare (sampleRate, 2);
        inRing.prepare (sampleRate);
        refRing.prepare (sampleRate);
        monoScratch.setSize (2, maxBlock, false, false, true);
        polarityFade.prepare ((int) std::lround (kPolarityFadeMs * 1.0e-3 * sampleRate), params.polarity ? 1.0f : 0.0f);
        bypassFade.prepare ((int) std::lround (kBypassFadeMs * 1.0e-3 * sampleRate), 0.0f);
        // Bypass has to be latency-compensated, click-free and null against the input (rule 7), so
        // the dry path runs through its own whole-sample delay of exactly the reported latency and
        // the two are crossfaded. The chain keeps running while bypassed, so coming back out of
        // bypass has no state transient and costs the idle CPU the brief budgets for.
        const int dry = (int) std::ceil ((double) kWindowMs[kNumWindows - 1] * 1.0e-3 * sampleRate) + 2;
        for (auto& r : dryRing)
            r.assign ((size_t) dry, 0.0f);
        for (int s = 0; s < 3; ++s)
            listenFade[s].prepare ((int) std::lround (kListenFadeMs * 1.0e-3 * sampleRate), 0.0f);
        trimCoefficient = tauCoefficient (kTrimTauMs, sampleRate);
        controlPeriod = juce::jlimit (1, 32, (int) std::lround (kControlMs * 1.0e-3 * sampleRate));
        rotateCoefficient = tauCoefficient (kRotateTauMs, sampleRate / controlPeriod);
        belowCoefficient = tauCoefficient (kBelowTauMs, sampleRate / controlPeriod);
        trimSmoothed = juce::Decibels::decibelsToGain (params.trimDb);
        rotateSmoothed = params.rotateDeg;
        belowSmoothed = params.belowHz;
        setParams (params);
        // the Rotate stage learns its bypass state before reset(), so a freshly prepared processor
        // starts at the setting it was given instead of fading into it - and so reset() restores
        // exactly what prepare() produced, which is what rule 8 asks of it
        rotateStage.setParams (rotateSmoothed, belowSmoothed, params.rotateDeg > 0.0f);
        reset();
    }

    void reset() noexcept
    {
        delayLine.reset();
        rotateStage.reset();
        inRing.reset();
        refRing.reset();
        polarityFade.snap (params.polarity ? 1.0f : 0.0f);
        for (auto& r : dryRing)
            std::fill (r.begin(), r.end(), 0.0f);
        dryWrite = 0;
        bypassFade.snap (0.0f);
        for (int s = 0; s < 3; ++s)
            listenFade[s].snap (s == juce::jlimit (0, 2, params.listen) ? 1.0f : 0.0f);
        trimSmoothed = juce::Decibels::decibelsToGain (params.trimDb);
        rotateSmoothed = params.rotateDeg;
        belowSmoothed = params.belowHz;
        controlCountdown = 0;
    }

    void setParams (const Params& p) noexcept
    {
        params = p;
        latency = (int) std::lround ((double) p.windowMs() * 1.0e-3 * rate);
        delayLine.setDelaySamples ((double) latency + (double) clampedDelayMs() * 1.0e-3 * rate);
    }

    int   latencySamples() const noexcept { return latency; }
    float clampedDelayMs() const noexcept
    {
        return juce::jlimit (-params.windowMs(), kDelayMaxMs, params.delayMs + params.trackOffsetMs);
    }

    AnalysisRing&       inputRing() noexcept { return inRing; }
    AnalysisRing&       referenceRing() noexcept { return refRing; }
    const AnalysisRing& inputRing() const noexcept { return inRing; }
    const AnalysisRing& referenceRing() const noexcept { return refRing; }

    /** Audio thread. `main` is processed in place; `ref` is the sidechain bus, read only.
        `bypassTarget` crossfades to the latency-compensated dry path (rule 7). */
    void process (float* const* main, const float* const* ref, int numChannels, int numSamples,
                  bool bypassTarget = false) noexcept
    {
        const int channels = juce::jlimit (1, 2, numChannels);
        if (numSamples <= 0)
            return;

        // the dry path for bypass: a whole number of samples, so it nulls exactly
        const int dryDelay = juce::jmin (latency, (int) dryRing[0].size() - 1);
        const int drySize = (int) dryRing[0].size();
        for (int i = 0; i < numSamples; ++i)
        {
            dryWrite = dryWrite + 1 >= drySize ? 0 : dryWrite + 1;
            for (int ch = 0; ch < channels; ++ch)
                dryRing[(size_t) ch][(size_t) dryWrite] = main[ch][i];
        }
        const int dryStart = dryWrite - numSamples + 1;

        // the rings take the mono sum of each bus, before any processing (sketch 4.1)
        auto* monoIn = monoScratch.getWritePointer (0);
        auto* monoRef = monoScratch.getWritePointer (1);
        const int scratch = monoScratch.getNumSamples();
        for (int at = 0; at < numSamples; at += scratch)   // a block larger than announced is legal
        {
            const int k = juce::jmin (scratch, numSamples - at);
            for (int i = 0; i < k; ++i)
            {
                float a = 0.0f, b = 0.0f;
                for (int ch = 0; ch < channels; ++ch)
                {
                    a += main[ch][at + i];
                    b += ref != nullptr ? ref[ch][at + i] : 0.0f;
                }
                monoIn[i] = a / (float) channels;
                monoRef[i] = b / (float) channels;
            }
            inRing.push (monoIn, k);
            refRing.push (monoRef, k);
        }

        // polarity, crossfaded. A polarity crossfade passes through silence; that is what a
        // polarity switch is, and being amplitude-complementary it cannot overshoot.
        polarityFade.setTarget (params.polarity ? 1.0f : 0.0f);
        if (! polarityFade.idle())
        {
            for (int i = 0; i < numSamples; ++i)
            {
                const float g = 1.0f - 2.0f * polarityFade.next();
                for (int ch = 0; ch < channels; ++ch)
                    main[ch][i] *= g;
            }
        }
        else if (polarityFade.value > 0.5f)
        {
            for (int ch = 0; ch < channels; ++ch)
                juce::FloatVectorOperations::multiply (main[ch], -1.0f, numSamples);
        }

        delayLine.process (main, numSamples);

        processRotate (main, channels, numSamples);

        const double trimTarget = juce::Decibels::decibelsToGain (params.trimDb);
        for (int i = 0; i < numSamples; ++i)
        {
            trimSmoothed = trimTarget + trimCoefficient * (trimSmoothed - trimTarget);
            const float g = (float) trimSmoothed;
            for (int ch = 0; ch < channels; ++ch)
                main[ch][i] *= g;
        }

        // Bypass: crossfade to the latency-compensated dry path
        bypassFade.setTarget (bypassTarget ? 1.0f : 0.0f);
        if (! bypassFade.idle() || bypassFade.value > 0.5f)
        {
            for (int i = 0; i < numSamples; ++i)
            {
                const float m = bypassFade.next();
                int at = dryStart + i - dryDelay;
                while (at < 0)
                    at += drySize;
                while (at >= drySize)
                    at -= drySize;
                for (int ch = 0; ch < channels; ++ch)
                    main[ch][i] = (1.0f - m) * main[ch][i] + m * dryRing[(size_t) ch][(size_t) at];
            }
            if (bypassFade.idle())
                return;                              // fully bypassed: Listen must not touch it
        }

        // Listen: a three-way crossfade, so switching never clicks
        bool fading = false;
        for (int s = 0; s < 3; ++s)
        {
            listenFade[s].setTarget (s == juce::jlimit (0, 2, params.listen) ? 1.0f : 0.0f);
            fading = fading || ! listenFade[s].idle();
        }
        if (! fading && listenFade[0].value > 0.5f)
            return;                                   // Listen Off and settled: nothing to mix

        for (int i = 0; i < numSamples; ++i)
        {
            float m[3];
            for (int s = 0; s < 3; ++s)
                m[s] = listenFade[s].next();
            float wetSum = 0.0f, refSum = 0.0f;
            for (int ch = 0; ch < channels; ++ch)
            {
                wetSum += main[ch][i];
                refSum += ref != nullptr ? ref[ch][i] : 0.0f;
            }
            const float mono = 0.5f * (wetSum / (float) channels + refSum / (float) channels);
            for (int ch = 0; ch < channels; ++ch)
            {
                const float refCh = ref != nullptr ? ref[ch][i] : 0.0f;
                main[ch][i] = m[0] * main[ch][i] + m[1] * refCh + m[2] * mono;
            }
        }
    }

private:
    /** Rotate on the control grid (kControlMs). Once both smoothers sit on their targets the
        coefficient cannot move inside the block (parameters change only between blocks), so the
        block runs in one piece and the grid position is carried forward. */
    void processRotate (float* const* main, int channels, int numSamples) noexcept
    {
        const bool settled = juce::exactlyEqual (rotateSmoothed, (double) params.rotateDeg)
                          && juce::exactlyEqual (belowSmoothed, (double) params.belowHz)
                          && rotateStage.settled (params.rotateDeg > 0.0f);
        if (settled)
        {
            rotateStage.process (main, channels, numSamples);
            controlCountdown = ((controlCountdown - numSamples) % controlPeriod + controlPeriod) % controlPeriod;
            return;
        }
        float* chunk[2] {};
        for (int at = 0; at < numSamples;)
        {
            if (controlCountdown <= 0)
            {
                rotateSmoothed = smoothTowards (rotateSmoothed, (double) params.rotateDeg, rotateCoefficient, 1.0e-4);
                belowSmoothed = smoothTowards (belowSmoothed, (double) params.belowHz, belowCoefficient, 1.0e-4);
                rotateStage.setParams (params.rotateDeg > 0.0f ? rotateSmoothed : 0.0,
                                       belowSmoothed, params.rotateDeg > 0.0f);
                controlCountdown = controlPeriod;
            }
            const int k = juce::jmin (controlCountdown, numSamples - at);
            for (int ch = 0; ch < channels; ++ch)
                chunk[ch] = main[ch] + at;
            rotateStage.process (chunk, channels, k);
            controlCountdown -= k;
            at += k;
        }
    }

    /** One step of a one-pole towards `target`; lands on it exactly once within `snap`, so a
        settled stage is recognisable and the angle reached is the one asked for. */
    static double smoothTowards (double value, double target, double coefficient, double snap) noexcept
    {
        const double next = target + coefficient * (value - target);
        return std::abs (next - target) <= snap ? target : next;
    }

    static double tauCoefficient (double tauMs, double sampleRate) noexcept
    {
        return tauMs <= 0.0 ? 0.0 : std::exp (-1.0 / (tauMs * 1.0e-3 * sampleRate));
    }

    SincDelay delayLine;
    Rotate rotateStage;
    AnalysisRing inRing, refRing;
    juce::AudioBuffer<float> monoScratch;
    std::array<std::vector<float>, 2> dryRing;
    Params params;
    double rate = 48000.0;
    double trimSmoothed = 1.0, rotateSmoothed = 0.0, belowSmoothed = 120.0;
    double trimCoefficient = 0.0, rotateCoefficient = 0.0, belowCoefficient = 0.0;
    LinearFade polarityFade, bypassFade, listenFade[3];
    int controlPeriod = 1, controlCountdown = 0;
    int maxBlock = 512, latency = 0, dryWrite = 0;
};
} // namespace align::dsp
