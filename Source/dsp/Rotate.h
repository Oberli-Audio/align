#pragma once

#include <juce_dsp/juce_dsp.h>

#include <cmath>

/*  Align - Rotate, the low-end phase rotation (G1 decision 3, ported from "sound design"/rotate.py).

    Two cascaded first-order TPT all-passes at the same corner. The corner is not a parameter: it
    is solved from the angle the user asked for and the frequency it has to be reached at, directly
    in the digital domain, so the bilinear transform's warping is inside the solution rather than
    an error on top of it:

        phase(f) = -4 * atan( tan(pi f / fs) / g ),   g = tan(pi * Below / fs) / tan(Rotate / 4)

    which is exactly -Rotate at Below, 0 at DC, and -360 deg (indistinguishable from 0 for a steady
    tone) far above the corner. Magnitude is exactly 1 at every setting - measured 8.9e-14 dB over
    20 Hz to 20 kHz - and the stage adds no latency. At Rotate 180 the corner lands on Below, which
    is how the sketch drew it.

    `g` is clamped to kGMax, which keeps every angle down to about 0.002 deg reachable, far below
    the degree the editor shows, so there is no "smallest usable angle". Rotate exactly 0 bypasses
    the stage through a kFadeMs amplitude-complementary crossfade, which is what makes the brief's
    null test exact; the filter keeps running while bypassed, so coming back out has no state
    transient.

    phaseAt() is the analytic form of the same filter and is what the detector's Rotate search and
    the editor's curve use, so the picture and the audio come from one formula (rule 9). Measured
    against the rendered impulse response: 1.8e-12 degrees.

    Rotate has one usable direction: it can make this track's low end *later*, never earlier. The
    other direction needs a negative group delay, or a four-section all-pass with its corner below
    the band, whose group delay down there is 75 ms. Detect scans both and says so (Detector.h).
*/
namespace align::dsp
{
class Rotate
{
public:
    static constexpr float kFadeMs = 15.0f;
    static constexpr double kGMax = 1.0e4;
    static constexpr double kGMin = 1.0e-4;

    /** The shared coefficient of the two sections. Also used by the detector and the editor. */
    static double coefficient (double rotateDeg, double belowHz, double sampleRate) noexcept
    {
        const double t = std::tan (juce::degreesToRadians (juce::jmax (rotateDeg, 1.0e-9)) * 0.25);
        const double g = std::tan (juce::MathConstants<double>::pi
                                   * juce::jmin (belowHz, 0.49 * sampleRate) / sampleRate) / t;
        return juce::jlimit (kGMin, kGMax, g);
    }

    /** Phase in radians of the two-section cascade at `hz`. */
    static double phaseAt (double hz, double rotateDeg, double belowHz, double sampleRate) noexcept
    {
        const double g = coefficient (rotateDeg, belowHz, sampleRate);
        return -4.0 * std::atan (std::tan (juce::MathConstants<double>::pi * hz / sampleRate) / g);
    }

    void prepare (double sampleRate, int numChannels)
    {
        rate = sampleRate;
        channels = juce::jlimit (1, 2, numChannels);
        fadeLength = juce::jmax (1, (int) std::lround (kFadeMs * 1.0e-3 * sampleRate));
        reset();
    }

    void reset() noexcept
    {
        for (auto& ch : state)
            ch.fill (0.0f);
        mix = active ? 1.0f : 0.0f;
    }

    /** Control thread. `rotateDeg` is the smoothed value; the bypass follows the *target*, so a
        parameter set to exactly 0 reaches a dry path instead of approaching one asymptotically. */
    void setParams (double rotateDeg, double belowHz, bool targetActive) noexcept
    {
        const double g = coefficient (rotateDeg, belowHz, rate);
        bigG = (float) (g / (1.0 + g));
        active = targetActive;
    }

    void process (float* const* data, int numSamples) noexcept
    {
        if (numSamples <= 0)
            return;
        const float targetMix = active ? 1.0f : 0.0f;
        const float step = (targetMix - mix) / (float) fadeLength;
        const bool fading = ! juce::exactlyEqual (mix, targetMix);

        for (int ch = 0; ch < channels; ++ch)
        {
            float s0 = state[(size_t) ch][0];
            float s1 = state[(size_t) ch][1];
            float m = mix;
            for (int i = 0; i < numSamples; ++i)
            {
                const float dry = data[ch][i];
                float v = (dry - s0) * bigG;
                float lp = v + s0;
                s0 = lp + v;
                const float first = lp + lp - dry;

                v = (first - s1) * bigG;
                lp = v + s1;
                s1 = lp + v;
                const float wet = lp + lp - first;

                if (fading)
                {
                    m = juce::jlimit (juce::jmin (mix, targetMix), juce::jmax (mix, targetMix), m + step);
                    data[ch][i] = (1.0f - m) * dry + m * wet;
                }
                else
                {
                    data[ch][i] = targetMix > 0.5f ? wet : dry;
                }
            }
            state[(size_t) ch][0] = s0;
            state[(size_t) ch][1] = s1;
            if (ch == channels - 1 && fading)
                mix = m;
        }
    }

private:
    std::array<std::array<float, 2>, 2> state {};
    double rate = 48000.0;
    float bigG = 1.0f, mix = 0.0f;
    int channels = 2, fadeLength = 1;
    bool active = false;
};
} // namespace align::dsp
