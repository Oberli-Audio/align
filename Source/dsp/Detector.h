#pragma once

#include <juce_dsp/juce_dsp.h>

#include <memory>
#include <vector>

#include "Rotate.h"

/*  Align - Detect: GCC-PHAT delay and polarity, and the Rotate suggestion
    (G1 decision 1, ported from "sound design"/detector.py).

    Runs on the detect worker thread. Every buffer it touches is allocated in prepare(); detect()
    allocates nothing, so the same code can be called from a test, a worker or the harness without
    a second implementation.

    Sign convention, fixed once and asserted by a test: with `ref` the reference mic and `trk` the
    track being aligned, r = ifft(fft(ref) * conj(fft(trk))) peaks at lag -tau when the track is
    later than the reference by tau. The Delay the plugin must apply is exactly that lag, so the
    refined peak in milliseconds *is* the Delay value, with no sign flip between here and the
    parameter.

    The Rotate suggestion never filters anything. The stage is an all-pass, so rotating the track
    cannot change its norm, only the real part of the inner product:

        corr(th, below) = Re( sum_k C_k exp(-i phase_k(th, below)) ) / sqrt(sum|R|^2 sum|T|^2)

    over the low band's bins, with C_k = R_k conj(T_k) and the phase from Rotate::phaseAt - the same
    formula the audio and the editor's curve use, so a suggestion cannot disagree with what applying
    it does (rule 9). The grid is also scanned in the direction the stage *cannot* produce: Rotate
    can only make this track's low end later, so when only that direction would help the honest
    answer is "put Align on the other mic", not "no rotation needed".
*/
namespace align::dsp
{
class Detector
{
public:
    // Constants, beside the code (G4 port rule). The whitening exponent is the G2 sweep's.
    static constexpr float  kBandLoHz = 60.0f;
    static constexpr float  kBandHiHz = 8000.0f;
    static constexpr float  kWhitenBeta = 1.0f;
    static constexpr float  kWhitenEps = 1.0e-3f;
    static constexpr float  kTaperAlpha = 0.1f;
    static constexpr float  kSecondPeakGuardMs = 1.0f;
    static constexpr float  kSilenceDbfs = -60.0f;
    static constexpr float  kRotateBandHiHz = 300.0f;
    static constexpr float  kRotateGridStepDeg = 2.0f;
    static constexpr float  kRotateMinGain = 0.05f;
    static constexpr float  kRotateOtherMicMinGain = 0.15f;
    static constexpr float  kSpeedOfSound = 343.0f;   // m/s at 20 C, as the readout's distance uses
    static constexpr int    kRotateGridBelowCount = 5;
    static constexpr float  kRotateGridBelowHz[kRotateGridBelowCount] = { 60.0f, 80.0f, 110.0f, 150.0f, 200.0f };

    enum class Reason { ok, notEnoughAudio, referenceSilent, emptyBand, emptyWindow };

    struct Suggestion
    {
        bool  needed = false;
        float rotateDeg = 0.0f;
        float belowHz = 0.0f;
        float corrBefore = 0.0f;
        float corrAfter = 0.0f;
        bool  otherMic = false;
        float otherMicGain = 0.0f;
    };

    struct Result
    {
        bool       ok = false;
        Reason     reason = Reason::notEnoughAudio;
        float      delayMs = 0.0f;
        bool       inverted = false;
        float      confidencePct = 0.0f;
        float      distanceCm = 0.0f;
        float      peak = 0.0f;
        float      secondPeak = 0.0f;
        Suggestion suggestion {};
    };

    /** `maxFrame` is the longest frame detect() will ever be given, in samples at `analysisRate`. */
    void prepare (double analysisRate, int maxFrame)
    {
        rate = analysisRate;
        frameCapacity = juce::jmax (16, maxFrame);
        int order = 1;
        while ((1 << order) < 2 * frameCapacity)
            ++order;
        fftSize = 1 << order;
        fft = std::make_unique<juce::dsp::FFT> (order);
        specA.assign ((size_t) fftSize * 2, 0.0f);
        specB.assign ((size_t) fftSize * 2, 0.0f);
        cross.assign ((size_t) fftSize * 2, 0.0f);
        taper.assign ((size_t) frameCapacity, 1.0f);
        taperedFor = -1;
        // the Rotate search's scratch, sized here so the worker never allocates either
        const size_t lowBins = (size_t) (kRotateBandHiHz / (float) (rate / (double) fftSize)) + 2;
        crossLow.assign (lowBins, 0.0f);
        crossLowImag.assign (lowBins, 0.0f);
        lowTan.assign (lowBins, 0.0f);
    }

    int    frameLimit() const noexcept { return frameCapacity; }
    double analysisRate() const noexcept { return rate; }

    /** Worker thread. `ref` and `trk` are `n` samples at the prepared analysis rate, oldest first.
        `searchLoMs` / `searchHiMs` are the current Window's reachable range. */
    Result detect (const float* ref, const float* trk, int n, float searchLoMs, float searchHiMs,
                   bool withSuggestion = true)
    {
        Result out;
        if (ref == nullptr || trk == nullptr || n < 16 || n > frameCapacity)
        {
            out.reason = Reason::notEnoughAudio;
            return out;
        }

        double sumSq = 0.0;
        for (int i = 0; i < n; ++i)
            sumSq += (double) ref[i] * ref[i];
        const double refRms = std::sqrt (sumSq / (double) n);
        if (juce::Decibels::gainToDecibels ((float) refRms, -200.0f) < kSilenceDbfs)
        {
            out.reason = Reason::referenceSilent;
            return out;
        }

        buildTaper (n);
        loadSpectrum (specA, ref, n);
        loadSpectrum (specB, trk, n);

        const int halfBins = fftSize / 2;
        const float binHz = (float) (rate / (double) fftSize);
        const int loBin = juce::jmax (1, (int) std::ceil (kBandLoHz / binHz));
        const int hiBin = juce::jmin (halfBins, (int) std::floor (juce::jmin ((double) kBandHiHz, 0.49 * rate) / binHz));
        if (hiBin <= loBin)
        {
            out.reason = Reason::emptyBand;
            return out;
        }

        // cross spectrum, then whiten inside the band and leave the rest at zero
        std::fill (cross.begin(), cross.end(), 0.0f);
        double magSum = 0.0;
        for (int k = loBin; k <= hiBin; ++k)
        {
            const float ar = specA[(size_t) (2 * k)], ai = specA[(size_t) (2 * k + 1)];
            const float br = specB[(size_t) (2 * k)], bi = specB[(size_t) (2 * k + 1)];
            const float cr = ar * br + ai * bi;          // A * conj(B)
            const float ci = ai * br - ar * bi;
            cross[(size_t) (2 * k)] = cr;
            cross[(size_t) (2 * k + 1)] = ci;
            magSum += std::sqrt ((double) cr * cr + (double) ci * ci);
        }
        const float eps = kWhitenEps * (float) (magSum / (double) (hiBin - loBin + 1) + 1.0e-30);
        for (int k = loBin; k <= hiBin; ++k)
        {
            const float cr = cross[(size_t) (2 * k)], ci = cross[(size_t) (2 * k + 1)];
            const float mag = std::sqrt (cr * cr + ci * ci);
            const float scale = juce::exactlyEqual (kWhitenBeta, 1.0f) ? 1.0f / (mag + eps)
                                                    : 1.0f / std::pow (mag + eps, kWhitenBeta);
            cross[(size_t) (2 * k)] = cr * scale;
            cross[(size_t) (2 * k + 1)] = ci * scale;
            // conjugate mirror, so the inverse transform is real
            const int m = fftSize - k;
            if (m > halfBins)
            {
                cross[(size_t) (2 * m)] = cr * scale;
                cross[(size_t) (2 * m + 1)] = -ci * scale;
            }
        }
        fft->performRealOnlyInverseTransform (cross.data());

        const int lo = (int) std::floor (searchLoMs * 1.0e-3 * rate);
        const int hi = (int) std::ceil (searchHiMs * 1.0e-3 * rate);
        if (hi - lo < 2)
        {
            out.reason = Reason::emptyWindow;
            return out;
        }
        auto at = [this] (int lag)
        {
            int index = lag % fftSize;
            if (index < 0)
                index += fftSize;
            return cross[(size_t) index];
        };

        int bestLag = lo + 1;
        float bestAbs = -1.0f;
        for (int lag = lo + 1; lag <= hi - 1; ++lag)
        {
            const float a = std::abs (at (lag));
            if (a > bestAbs)
            {
                bestAbs = a;
                bestLag = lag;
            }
        }
        // the parabola is fitted to the magnitudes and the sign comes from the peak sample, so an
        // inverted pair reads as a downward peak and the curve the editor draws shows the flip
        // directly instead of inferring it (defining feature 1)
        const float sign = at (bestLag) >= 0.0f ? 1.0f : -1.0f;
        const float ym = std::abs (at (bestLag - 1));
        const float y0 = std::abs (at (bestLag));
        const float yp = std::abs (at (bestLag + 1));
        float delta = 0.0f, vertex = y0;
        const float denom = ym - 2.0f * y0 + yp;
        if (! juce::exactlyEqual (denom, 0.0f))
        {
            delta = juce::jlimit (-1.0f, 1.0f, 0.5f * (ym - yp) / denom);
            vertex = y0 - 0.25f * (ym - yp) * delta;
        }
        const double refinedLag = (double) bestLag + (double) delta;
        const double delayMs = refinedLag / rate * 1.0e3;

        const int guard = juce::jmax (1, (int) (kSecondPeakGuardMs * 1.0e-3 * rate));
        float second = 0.0f;
        for (int lag = lo + 1; lag <= hi - 1; ++lag)
            if (std::abs (lag - bestLag) > guard)
                second = juce::jmax (second, std::abs (at (lag)));

        out.ok = true;
        out.reason = Reason::ok;
        out.delayMs = (float) delayMs;
        out.inverted = sign < 0.0f;
        out.peak = std::abs (vertex);
        out.secondPeak = second;
        out.confidencePct = out.peak <= 0.0f ? 0.0f
                                             : juce::jlimit (0.0f, 100.0f, (out.peak - second) / out.peak * 100.0f);
        out.distanceCm = std::abs ((float) delayMs) * 1.0e-3f * kSpeedOfSound * 100.0f;
        if (withSuggestion)
            out.suggestion = suggestRotate (out.delayMs, out.inverted, binHz, halfBins);
        return out;
    }

    /** The readout the brief asks for, in words, with the distance (defining feature 3). */
    static juce::String words (const Result& r)
    {
        if (! r.ok)
            return reasonWords (r.reason);
        const juce::String sign = r.delayMs >= 0.0f ? juce::String::fromUTF8 ("+")
                                                    : juce::String::fromUTF8 ("\xe2\x88\x92");
        const juce::String dot = juce::String::fromUTF8 (" \xc2\xb7 ");
        const bool low = r.confidencePct < 50.0f;
        return "Peak " + sign + juce::String (std::abs (r.delayMs), 2) + " ms" + dot
               + juce::String (juce::roundToInt (r.distanceCm)) + " cm" + dot
               + (r.inverted ? "polarity flipped" : "polarity matched") + dot
               + (low ? "low confidence " : "confidence ")
               + juce::String (juce::roundToInt (r.confidencePct)) + " %"
               + (low ? ": play a louder section" : "");
    }

    static juce::String suggestionWords (const Suggestion& s)
    {
        if (s.otherMic)
            return "Rotate cannot help here: this track's low end is late. "
                   "Put Align on the reference mic instead";
        if (! s.needed)
            return "No rotation needed";
        const juce::String dot = juce::String::fromUTF8 (" \xc2\xb7 ");
        return "Detect suggests " + juce::String (juce::roundToInt (s.rotateDeg))
               + juce::String::fromUTF8 ("\xc2\xb0") + " below "
               + juce::String (juce::roundToInt (s.belowHz)) + " Hz" + dot
               + "correlation below " + juce::String (juce::roundToInt (kRotateBandHiHz)) + " Hz "
               + juce::String (s.corrBefore, 2) + juce::String::fromUTF8 (" \xe2\x86\x92 ")
               + juce::String (s.corrAfter, 2);
    }

    static juce::String reasonWords (Reason r)
    {
        switch (r)
        {
            case Reason::referenceSilent: return "Reference is silent";
            case Reason::notEnoughAudio:  return "Not enough audio yet";
            case Reason::emptyBand:       return "Sample rate leaves no analysis band";
            case Reason::emptyWindow:     return "Search window is empty";
            case Reason::ok:              break;
        }
        return {};
    }

    /** [-Window, +max(Window, 20 ms)]: the range the current Window can actually apply, so Detect
        never proposes a delay it cannot apply (docs/status.md, G1 decision 6). */
    static void searchRangeMs (float windowMs, float& loMs, float& hiMs) noexcept
    {
        loMs = -windowMs;
        hiMs = juce::jmax (windowMs, 20.0f);
    }

private:
    void buildTaper (int n)
    {
        if (taperedFor == n)
            return;
        taperedFor = n;
        std::fill (taper.begin(), taper.begin() + n, 1.0f);
        const int edge = (int) (kTaperAlpha * (float) (n - 1) / 2.0f);
        for (int i = 0; i < edge; ++i)
        {
            const float w = 0.5f * (1.0f - std::cos (juce::MathConstants<float>::pi * (float) i / (float) edge));
            taper[(size_t) i] = w;
            taper[(size_t) (n - 1 - i)] = w;
        }
    }

    void loadSpectrum (std::vector<float>& dest, const float* src, int n)
    {
        std::fill (dest.begin(), dest.end(), 0.0f);
        double mean = 0.0;
        for (int i = 0; i < n; ++i)
            mean += src[i];
        mean /= (double) n;
        for (int i = 0; i < n; ++i)
            dest[(size_t) i] = (float) (((double) src[i] - mean) * (double) taper[(size_t) i]);
        fft->performRealOnlyForwardTransform (dest.data());
    }

    Suggestion suggestRotate (float delayMs, bool inverted, float binHz, int halfBins)
    {
        Suggestion s;
        const int loBin = juce::jmax (1, (int) std::ceil (kBandLoHz / 3.0f / binHz));
        const int hiBin = juce::jmin (halfBins, (int) std::floor (kRotateBandHiHz / binHz));
        if (hiBin <= loBin)
            return s;

        // apply the found delay and polarity to the track's spectrum: both are exact in this
        // domain. Shifting later by d seconds multiplies by exp(-2i pi f d), and `delayMs` already
        // is the Delay the plugin will apply, so the sign needs no flip.
        const double shift = -2.0 * juce::MathConstants<double>::pi * (double) delayMs * 1.0e-3;
        const float polarity = inverted ? -1.0f : 1.0f;

        std::vector<float>& cr = crossLow;
        std::vector<float>& ci = crossLowImag;
        const size_t count = (size_t) (hiBin - loBin + 1);
        jassert (count <= cr.size());
        double normR = 0.0, normT = 0.0;
        for (int k = loBin; k <= hiBin; ++k)
        {
            const double hz = (double) k * (double) binHz;
            const double arg = shift * hz;
            const float c = (float) std::cos (arg), sn = (float) std::sin (arg);
            const float ar = specA[(size_t) (2 * k)], ai = specA[(size_t) (2 * k + 1)];
            float br = specB[(size_t) (2 * k)], bi = specB[(size_t) (2 * k + 1)];
            const float rb = (br * c - bi * sn) * polarity;
            const float ib = (br * sn + bi * c) * polarity;
            br = rb;
            bi = ib;
            const size_t at = (size_t) (k - loBin);
            cr[at] = ar * br + ai * bi;     // A * conj(B)
            ci[at] = ai * br - ar * bi;
            lowTan[at] = (float) std::tan (juce::MathConstants<double>::pi * hz / rate);
            normR += (double) ar * ar + (double) ai * ai;
            normT += (double) br * br + (double) bi * bi;
        }
        const double den = std::sqrt (normR * normT);
        if (den <= 0.0)
            return s;

        double before = 0.0;
        for (size_t i = 0; i < count; ++i)
            before += (double) cr[i];
        before /= den;

        double best = before, bestOpposite = before;
        float bestDeg = 0.0f, bestBelow = 0.0f;
        for (int b = 0; b < kRotateGridBelowCount; ++b)
        {
            const float below = kRotateGridBelowHz[b];
            for (float deg = kRotateGridStepDeg; deg <= 180.0f; deg += kRotateGridStepDeg)
            {
                // cos and sin of the stage's phase without a transcendental per bin. The phase is
                // -4 * atan(u / g), so with cos(th) = g / hypot, sin(th) = u / hypot the
                // quadruple-angle identities give cos(4 th) and sin(4 th) from multiplications
                // alone. Algebraically identical to Rotate::phaseAt, which a test asserts, so the
                // search still runs the one formula the audio and the editor's curve use (rule 9).
                const double g = Rotate::coefficient ((double) deg, (double) below, rate);
                double lag = 0.0, lead = 0.0;
                for (size_t i = 0; i < count; ++i)
                {
                    const double u = (double) lowTan[i];
                    const double inv = 1.0 / std::sqrt (g * g + u * u);
                    const double c1 = g * inv, s1 = u * inv;
                    const double c2 = c1 * c1 - s1 * s1, s2 = 2.0 * s1 * c1;
                    const double c4 = c2 * c2 - s2 * s2, s4 = 2.0 * s2 * c2;
                    const double c = c4, sn = -s4;                      // cos/sin of -4 th
                    lag += (double) cr[i] * c + (double) ci[i] * sn;    // Re(C exp(-i phase))
                    lead += (double) cr[i] * c - (double) ci[i] * sn;   // Re(C exp(+i phase))
                }
                lag /= den;
                lead /= den;
                if (lag > best)
                {
                    best = lag;
                    bestDeg = deg;
                    bestBelow = below;
                }
                bestOpposite = juce::jmax (bestOpposite, lead);
            }
        }

        s.corrBefore = (float) before;
        s.otherMicGain = (float) (bestOpposite - before);
        if (best - before >= kRotateMinGain)
        {
            s.needed = true;
            s.rotateDeg = bestDeg;
            s.belowHz = bestBelow;
            s.corrAfter = (float) best;
            return s;
        }
        s.corrAfter = (float) before;
        s.otherMic = s.otherMicGain >= kRotateOtherMicMinGain;
        return s;
    }

    std::unique_ptr<juce::dsp::FFT> fft;
    std::vector<float> specA, specB, cross, taper, crossLow, crossLowImag, lowTan;
    double rate = 48000.0;
    int frameCapacity = 0, fftSize = 2, taperedFor = -1;
};
} // namespace align::dsp
