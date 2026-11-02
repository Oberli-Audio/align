#pragma once

#include <juce_dsp/juce_dsp.h>

#include <cmath>
#include <vector>

/*  Align - the fractional delay line (G1 decision 2, ported from "sound design"/sinc_delay.py).

    Two taps read from one ring, crossfaded amplitude-complementary over kFadeMs whenever the
    delay changes. Both taps carry the *same* signal, so an equal-power law would overshoot by up
    to 3 dB where they are in phase; an amplitude-complementary one cannot overshoot at all
    (docs/status.md, G1 crossfade law). Measured: the brief's click test overshoots by 0.000000 dB.

    Fractional part: a table of Kaiser-windowed sinc kernels, kPhases + 1 fractional positions by
    kTaps taps, built in prepare(). The constants are the G2 kernel search's, not taste
    ("sound design"/prototype.py --kernel-search over 192 designs at 44.1 and 48 kHz):

        kTaps 32, kKaiserBeta 9.0, kCutoff 1.0  ->  0.00088 dB to 18 kHz at 44.1 kHz,
                                                    0.00023 dB at 48 kHz (brief target 0.05)

    Three paths, in the order the read tries them:
      - a whole number of samples reads straight from the ring. A cutoff of 1.0 makes the
        fractional-offset-zero kernel a delta anyway, so this is only cheaper - but it also makes
        the identity exact by construction, and the brief's null test lands exactly here, because
        every Window is a whole number of samples by definition.
      - below kMinSincSamples the read is nearest-sample. Reachable only in the "0 (live)" window,
        where the reported latency is zero and the internal delay is the Delay knob alone, so a
        kernel's nominal group delay of kTaps/2 - 1 samples has nowhere to come from. Exactly flat
        in magnitude, exactly linear in phase; the only error is half a sample of delay
        quantisation (0.0104 ms at 48 kHz, 0.0026 ms at 192 kHz, 0.0113 ms at 44.1 kHz).
      - otherwise the kernel table.

    Every length is in seconds and converted here (rule 12). prepare() allocates; reset() and
    process() do not (rule 1).
*/
namespace align::dsp
{
class SincDelay
{
public:
    static constexpr int   kTaps = 32;
    static constexpr int   kPhases = 512;
    static constexpr float kKaiserBeta = 9.0f;
    static constexpr float kCutoff = 1.0f;
    static constexpr float kFadeMs = 10.0f;

    static constexpr int   kCentre = kTaps / 2 - 1;
    static constexpr float kMinSincSamples = (float) (kTaps / 2);

    void prepare (double sampleRate, double maxDelaySamples, int maxBlockSize, int numChannels)
    {
        buildTable();
        size = (int) std::ceil (maxDelaySamples) + kTaps + 2 + juce::jmax (1, maxBlockSize);
        channels = juce::jlimit (1, 2, numChannels);
        for (auto& r : ring)
            r.assign ((size_t) size, 0.0f);
        fadeLength = juce::jmax (1, (int) std::lround (kFadeMs * 1.0e-3 * sampleRate));
        reset();
    }

    void reset() noexcept
    {
        for (auto& r : ring)
            std::fill (r.begin(), r.end(), 0.0f);
        write = 0;
        current = target;
        previous = target;
        fadePosition = 0;
        fading = false;
    }

    /** Control thread: the goal only (F.9, two-speed parameter design). */
    void setDelaySamples (double d) noexcept { target = juce::jmax (0.0, d); }

    double currentDelaySamples() const noexcept { return current; }

    /** Audio thread. `data` is channels x numSamples, processed in place. */
    void process (float* const* data, int numSamples) noexcept
    {
        if (numSamples <= 0)
            return;
        if (! fading && ! juce::exactlyEqual (target, current))
        {
            previous = current;
            fading = true;
            fadePosition = 0;
        }

        if (! fading)
        {
            for (int i = 0; i < numSamples; ++i)
            {
                advance (data, i);
                for (int ch = 0; ch < channels; ++ch)
                    data[ch][i] = read (ch, current);
            }
            return;
        }

        const float step = 1.0f / (float) fadeLength;
        for (int i = 0; i < numSamples; ++i)
        {
            advance (data, i);
            const float b = juce::jlimit (0.0f, 1.0f, (float) (fadePosition + i + 1) * step);
            const float a = 1.0f - b;
            for (int ch = 0; ch < channels; ++ch)
                data[ch][i] = a * read (ch, previous) + b * read (ch, target);
        }
        fadePosition += numSamples;
        if (fadePosition >= fadeLength)
        {
            current = target;
            previous = target;
            fading = false;
            fadePosition = 0;
        }
    }

private:
    void buildTable()
    {
        if (! table.empty())
            return;
        table.assign ((size_t) (kPhases + 1) * kTaps, 0.0f);
        for (int p = 0; p <= kPhases; ++p)
        {
            const double frac = (double) p / (double) kPhases;
            double sum = 0.0;
            auto* row = &table[(size_t) p * kTaps];
            for (int k = 0; k < kTaps; ++k)
            {
                const double x = (double) k - kCentre - frac;
                const double arg = kCutoff * x;
                const double s = std::abs (arg) < 1.0e-12 ? 1.0
                                                          : std::sin (juce::MathConstants<double>::pi * arg)
                                                                / (juce::MathConstants<double>::pi * arg);
                // Kaiser window, the same definition numpy.kaiser uses
                const double r = 2.0 * (double) k / (double) (kTaps - 1) - 1.0;
                const double w = besselI0 (kKaiserBeta * std::sqrt (juce::jmax (0.0, 1.0 - r * r)))
                                 / besselI0 ((double) kKaiserBeta);
                const double v = s * kCutoff * w;
                row[k] = (float) v;
                sum += v;
            }
            for (int k = 0; k < kTaps; ++k)   // DC gain exactly one: no setting shifts the level
                row[k] = (float) ((double) row[k] / sum);
        }
    }

    static double besselI0 (double x) noexcept
    {
        double sum = 1.0, term = 1.0;
        const double half = 0.5 * x;
        for (int k = 1; k < 60; ++k)
        {
            term *= (half / (double) k) * (half / (double) k);
            sum += term;
            if (term < 1.0e-18 * sum)
                break;
        }
        return sum;
    }

    void advance (float* const* data, int i) noexcept
    {
        write = write + 1 >= size ? 0 : write + 1;
        for (int ch = 0; ch < channels; ++ch)
            ring[(size_t) ch][(size_t) write] = data[ch][i];
    }

    int wrap (int index) const noexcept
    {
        while (index < 0)
            index += size;
        while (index >= size)
            index -= size;
        return index;
    }

    float read (int ch, double delay) const noexcept
    {
        const auto& r = ring[(size_t) ch];
        if (delay < (double) kMinSincSamples)
            return r[(size_t) wrap (write - (int) std::lround (delay))];

        const int whole = (int) std::floor (delay);
        const double frac = delay - (double) whole;
        if (juce::exactlyEqual (frac, 0.0))
            return r[(size_t) wrap (write - whole)];

        const auto* row = &table[(size_t) (int) std::lround (frac * kPhases) * kTaps];
        const int base = write - (whole - kCentre);
        float sum = 0.0f;
        for (int k = 0; k < kTaps; ++k)
            sum += row[k] * r[(size_t) wrap (base - k)];
        return sum;
    }

    std::vector<float> table;
    std::array<std::vector<float>, 2> ring;
    int size = 1, channels = 2, write = 0;
    int fadeLength = 1, fadePosition = 0;
    bool fading = false;
    double target = 0.0, current = 0.0, previous = 0.0;
};
} // namespace align::dsp
