#pragma once

#include <juce_dsp/juce_dsp.h>

#include <atomic>
#include <cmath>
#include <vector>

/*  Align - the analysis ring the audio thread writes and the detect worker reads
    (ported from the rings in "sound design"/engine.py).

    One ring per bus (this track and the sidechain reference), holding the mono sum of the bus for
    kSeconds. The audio thread writes and never allocates, locks or waits; the worker copies a
    snapshot oldest-first. The only race is the newest block at the moment of the copy, which the
    detector cannot notice: it is one block out of four seconds, at the end of the frame the Tukey
    taper is already fading out.

    Decimation. The detector's band stops at 8 kHz, so storing four seconds at 192 kHz would cost a
    2 M-point FFT for nothing. The ring decimates by an integer K chosen so the analysis rate always
    lands in [44.1, 48] kHz:

        44.1 -> 44.1 (K=1)   88.2 -> 44.1 (K=2)   176.4 -> 44.1 (K=4)
        48   -> 48   (K=1)   96   -> 48   (K=2)   192   -> 48   (K=4)

    so the worker's FFT is at most 2^19 at every supported session rate. When K > 1 a 4th-order
    Butterworth low-pass at 0.45 x the analysis rate runs first. Both buses get the *identical*
    filter, so whatever phase it adds cancels in the cross-spectrum and cannot bias the delay
    estimate - which is the reason the same filter instance type is used on both and the reason
    this is safe to do at all.
*/
namespace align::dsp
{
class AnalysisRing
{
public:
    static constexpr double kSeconds = 4.0;
    static constexpr double kMinSeconds = 0.25;
    static constexpr double kDecimateAbove = 64000.0;

    static int decimationFor (double sampleRate) noexcept
    {
        int k = 1;
        while (sampleRate / (double) k > kDecimateAbove)
            k *= 2;
        return k;
    }

    void prepare (double sampleRate)
    {
        decimation = decimationFor (sampleRate);
        analysisRate = sampleRate / (double) decimation;
        buffer.assign ((size_t) std::ceil (kSeconds * analysisRate) + 1, 0.0f);
        // 4th-order Butterworth as two cascaded TPT SVF sections (rule 6: modulated or not, TPT)
        const double fc = 0.45 * analysisRate;
        const double gTan = std::tan (juce::MathConstants<double>::pi * fc / sampleRate);
        for (int s = 0; s < 2; ++s)
        {
            sections[(size_t) s].g = (float) gTan;
            sections[(size_t) s].twoR = (float) (1.0 / kButterworthQ[(size_t) s]);
        }
        reset();
    }

    void reset() noexcept
    {
        std::fill (buffer.begin(), buffer.end(), 0.0f);
        for (auto& s : sections)
        {
            s.ic1 = 0.0f;
            s.ic2 = 0.0f;
        }
        phase = 0;
        writeIndex.store (0, std::memory_order_release);
        filled.store (0, std::memory_order_release);
    }

    /** Audio thread: push one block of one bus, already summed to mono by the caller. */
    void push (const float* mono, int numSamples) noexcept
    {
        int w = writeIndex.load (std::memory_order_relaxed);
        int f = filled.load (std::memory_order_relaxed);
        const int size = (int) buffer.size();
        for (int i = 0; i < numSamples; ++i)
        {
            float v = mono[i];
            if (decimation > 1)
                for (auto& s : sections)
                    v = s.lowpass (v);
            if (++phase < decimation)
                continue;
            phase = 0;
            buffer[(size_t) w] = v;
            w = w + 1 >= size ? 0 : w + 1;
            if (f < size)
                ++f;
        }
        writeIndex.store (w, std::memory_order_release);
        filled.store (f, std::memory_order_release);
    }

    /** Worker thread: copy the newest `maxSamples` oldest-first into `dest`. Returns the count. */
    int snapshot (float* dest, int maxSamples) const noexcept
    {
        const int size = (int) buffer.size();
        const int have = juce::jmin (filled.load (std::memory_order_acquire), size);
        const int n = juce::jmin (have, maxSamples);
        const int w = writeIndex.load (std::memory_order_acquire);
        int from = w - n;
        while (from < 0)
            from += size;
        for (int i = 0; i < n; ++i)
        {
            dest[i] = buffer[(size_t) from];
            from = from + 1 >= size ? 0 : from + 1;
        }
        return n;
    }

    int    capacity() const noexcept { return (int) buffer.size(); }
    int    available() const noexcept { return filled.load (std::memory_order_acquire); }
    double rate() const noexcept { return analysisRate; }
    int    decimationFactor() const noexcept { return decimation; }
    bool   enoughForDetect() const noexcept { return available() >= (int) (kMinSeconds * analysisRate); }

private:
    static constexpr double kButterworthQ[2] = { 0.54119610, 1.30656296 };

    /** Zavalishin's TPT state-variable filter, low-pass output (rule 6). */
    struct Svf
    {
        float g = 0.0f, twoR = 1.0f, ic1 = 0.0f, ic2 = 0.0f;
        float lowpass (float x) noexcept
        {
            const float a1 = 1.0f / (1.0f + g * (g + twoR));
            const float a2 = g * a1;
            const float a3 = g * a2;
            const float v3 = x - ic2;
            const float v1 = a1 * ic1 + a2 * v3;
            const float v2 = ic2 + a2 * ic1 + a3 * v3;
            ic1 = v1 + v1 - ic1;
            ic2 = v2 + v2 - ic2;
            return v2;
        }
    };

    std::vector<float> buffer;
    std::array<Svf, 2> sections {};
    std::atomic<int> writeIndex { 0 }, filled { 0 };
    int decimation = 1, phase = 0;
    double analysisRate = 48000.0;
};
} // namespace align::dsp
