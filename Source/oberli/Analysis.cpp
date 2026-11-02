#include "Analysis.h"

#include <cmath>

namespace oberli
{

//==============================================================================
void AudioCopy::prepare (double sampleRate, double seconds)
{
    const auto frames = juce::jmax (1024, (int) std::ceil (sampleRate * seconds));
    ring.setSize (2, frames, false, true, false);
    fifo.setTotalSize (frames);
    clear();
}

void AudioCopy::clear() noexcept
{
    fifo.reset();
    droppedFrames.store (0, std::memory_order_relaxed);
}

void AudioCopy::push (const juce::AudioBuffer<float>& buffer, int start, int numSamples) noexcept
{
    if (buffer.getNumChannels() == 0 || numSamples <= 0)
        return;

    const auto room = fifo.getFreeSpace();
    const auto n = juce::jmin (room, numSamples);

    if (n < numSamples)
        droppedFrames.fetch_add (numSamples - n, std::memory_order_relaxed);

    if (n <= 0)
        return;

    const auto* l = buffer.getReadPointer (0, start);
    const auto* r = buffer.getNumChannels() > 1 ? buffer.getReadPointer (1, start) : l;

    const auto scope = fifo.write (n);
    if (scope.blockSize1 > 0)
    {
        ring.copyFrom (0, scope.startIndex1, l, scope.blockSize1);
        ring.copyFrom (1, scope.startIndex1, r, scope.blockSize1);
    }
    if (scope.blockSize2 > 0)
    {
        ring.copyFrom (0, scope.startIndex2, l + scope.blockSize1, scope.blockSize2);
        ring.copyFrom (1, scope.startIndex2, r + scope.blockSize1, scope.blockSize2);
    }
}

int AudioCopy::pop (float* left, float* right, int maxFrames) noexcept
{
    const auto scope = fifo.read (juce::jmin (maxFrames, fifo.getNumReady()));

    if (scope.blockSize1 > 0)
    {
        juce::FloatVectorOperations::copy (left, ring.getReadPointer (0, scope.startIndex1), scope.blockSize1);
        juce::FloatVectorOperations::copy (right, ring.getReadPointer (1, scope.startIndex1), scope.blockSize1);
    }
    if (scope.blockSize2 > 0)
    {
        juce::FloatVectorOperations::copy (left + scope.blockSize1, ring.getReadPointer (0, scope.startIndex2), scope.blockSize2);
        juce::FloatVectorOperations::copy (right + scope.blockSize1, ring.getReadPointer (1, scope.startIndex2), scope.blockSize2);
    }

    return scope.blockSize1 + scope.blockSize2;
}

//==============================================================================
BandLayout BandLayout::make (Resolution resolution, double sampleRate, float lowestHz, float highestHz)
{
    BandLayout layout;
    layout.resolution = resolution;

    const auto b = (double) (int) resolution;
    const auto nyquist = 0.5 * sampleRate;

    // Base-2 exact centres: 1000 * 2^(k / b) (IEC 61260-1 5.2, the base-2 system).
    for (int k = (int) std::floor (b * std::log2 (lowestHz / 1000.0)) - 1; k <= (int) std::ceil (b * std::log2 (highestHz / 1000.0)) + 1; ++k)
    {
        const auto centre = 1000.0 * std::pow (2.0, (double) k / b);
        const auto low = centre * std::pow (2.0, -0.5 / b);
        const auto high = centre * std::pow (2.0, 0.5 / b);

        // The nominal 20 Hz band's exact base-2 centre is 19.7 Hz: a band counts when its centre
        // lies within half a band of the limits.
        if (centre < lowestHz * std::pow (2.0, -0.5 / b) || centre > highestHz * std::pow (2.0, 0.5 / b) || high > nyquist)
            continue;

        if ((int) layout.bands.size() < Spectrum::kMaxBands)
            layout.bands.push_back ({ (float) low, (float) centre, (float) high });
    }

    return layout;
}

juce::String BandLayout::label (float centreHz)
{
    // Three significant figures, then the conventional names (31.5, 63, 125, 1k, 12.5k).
    const auto digits = (int) std::floor (std::log10 (centreHz));
    const auto scale = std::pow (10.0, digits - 2);
    auto nominal = std::round (centreHz / scale) * scale;

    // The base-2 centres sit a little off the nominal ones; the familiar names win.
    static const double names[] { 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800 };
    const auto decade = std::pow (10.0, std::floor (std::log10 (nominal / 20.0)));
    for (auto n : names)
        if (std::abs (n * decade - nominal) / nominal < 0.03)
            nominal = n * decade;

    if (nominal >= 1000.0)
    {
        const auto k = nominal / 1000.0;
        return (std::abs (k - std::round (k)) < 1.0e-6 ? juce::String ((int) std::round (k)) : juce::String (k, 1)) + "k";
    }

    return std::abs (nominal - std::round (nominal)) < 1.0e-6 ? juce::String ((int) std::round (nominal)) : juce::String (nominal, 1);
}

//==============================================================================
float Spectrum::toDb (double meanSquare) noexcept
{
    // Mean square in dB re a full-scale sine (whose mean square is 1/2).
    return meanSquare > 1.0e-12 ? (float) (10.0 * std::log10 (2.0 * meanSquare)) : -120.0f;
}

void Spectrum::prepare (double sampleRate, BandLayout::Resolution resolution, int fftOrder, double fastSeconds)
{
    fftSize = 1 << fftOrder;
    hop = fftSize / 2;
    fft = std::make_unique<juce::dsp::FFT> (fftOrder);
    bands = BandLayout::make (resolution, sampleRate);

    window.resize ((size_t) fftSize);
    double sumSquares = 0.0;
    for (int n = 0; n < fftSize; ++n)
    {
        window[(size_t) n] = 0.5f - 0.5f * std::cos (juce::MathConstants<float>::twoPi * (float) n / (float) fftSize);   // periodic Hann
        sumSquares += (double) window[(size_t) n] * window[(size_t) n];
    }

    // One-sided power of the windowed frame back to the mean square of the signal:
    // sum_k 2 |X_k|^2 / (N * sum w^2) (Parseval).
    normalisation = 2.0 / ((double) fftSize * sumSquares);

    input.assign ((size_t) fftSize, 0.0f);
    work.assign ((size_t) (2 * fftSize), 0.0f);
    fastPower.assign (bands.bands.size(), 0.0);
    sumPower.assign (bands.bands.size(), 0.0);
    framePower.assign (bands.bands.size(), 0.0);

    // Each FFT bin k covers [k - 1/2, k + 1/2] * df; it goes to the bands it overlaps, by share.
    const auto df = sampleRate / (double) fftSize;
    binWeights.assign (bands.bands.size(), {});
    for (size_t b = 0; b < bands.bands.size(); ++b)
    {
        const auto lowBin = bands.bands[b].low / df, highBin = bands.bands[b].high / df;
        for (int k = juce::jmax (1, (int) std::floor (lowBin)); k <= juce::jmin (fftSize / 2 - 1, (int) std::ceil (highBin)); ++k)
        {
            const auto overlap = juce::jmin ((double) k + 0.5, highBin) - juce::jmax ((double) k - 0.5, lowBin);
            if (overlap > 0.0)
                binWeights[b].emplace_back (k, (float) juce::jmin (1.0, overlap));
        }
    }

    const auto frameSeconds = (double) hop / sampleRate;
    fastCoefficient = std::exp (-frameSeconds / juce::jmax (1.0e-3, fastSeconds));
    reset();
}

void Spectrum::reset()
{
    std::fill (input.begin(), input.end(), 0.0f);
    std::fill (fastPower.begin(), fastPower.end(), 0.0);
    std::fill (sumPower.begin(), sumPower.end(), 0.0);
    fill = 0;
    frames = 0;
}

void Spectrum::push (const float* left, const float* right, int numFrames)
{
    for (int i = 0; i < numFrames; ++i)
    {
        input[(size_t) fill] = 0.5f * (left[i] + right[i]);   // the mid signal: what the band display shows

        if (++fill == fftSize)
        {
            runFrame();
            // 50 % overlap: keep the second half as the next frame's first.
            std::copy (input.begin() + hop, input.end(), input.begin());
            fill = fftSize - hop;
        }
    }
}

void Spectrum::runFrame()
{
    for (int n = 0; n < fftSize; ++n)
        work[(size_t) n] = input[(size_t) n] * window[(size_t) n];
    std::fill (work.begin() + fftSize, work.end(), 0.0f);

    fft->performFrequencyOnlyForwardTransform (work.data(), true);   // |X_k| for k < N/2

    for (size_t b = 0; b < binWeights.size(); ++b)
    {
        double power = 0.0;
        for (const auto& [k, w] : binWeights[b])
            power += (double) w * (double) work[(size_t) k] * (double) work[(size_t) k];
        power *= normalisation;

        framePower[b] = power;
        fastPower[b] = frames == 0 ? power : fastCoefficient * fastPower[b] + (1.0 - fastCoefficient) * power;
        sumPower[b] += power;
    }

    ++frames;
}

//==============================================================================
Analyser::Analyser() : juce::Thread ("Oberli analysis") {}

Analyser::~Analyser()
{
    cancelPendingUpdate();
    stopThread (2000);
}

void Analyser::prepare (double sampleRate, BandLayout::Resolution resolution, int fftOrder, double fastSeconds)
{
    stopThread (2000);

    copy.prepare (sampleRate, 1.0);
    spectrum.prepare (sampleRate, resolution, fftOrder, fastSeconds);
    left.assign (4096, 0.0f);
    right.assign (4096, 0.0f);

    const auto n = spectrum.numBands();
    for (int b = 0; b < Spectrum::kMaxBands; ++b)
    {
        fast[(size_t) b].store (-120.0f);
        longTerm[(size_t) b].store (-120.0f);
        centres[(size_t) b].store (b < n ? spectrum.layout().bands[(size_t) b].centre : 0.0f);
    }
    publishedBands.store (n, std::memory_order_release);

    startThread (juce::Thread::Priority::low);
}

void Analyser::run()
{
    while (! threadShouldExit())
    {
        if (resetRequested.exchange (false, std::memory_order_acq_rel))
            spectrum.reset();

        const auto before = spectrum.framesAnalysed();

        while (copy.available() > 0 && ! threadShouldExit())
        {
            const auto n = copy.pop (left.data(), right.data(), (int) left.size());
            spectrum.push (left.data(), right.data(), n);
        }

        if (spectrum.framesAnalysed() != before)
        {
            for (int b = 0; b < spectrum.numBands(); ++b)
            {
                fast[(size_t) b].store (spectrum.fastDb (b), std::memory_order_relaxed);
                longTerm[(size_t) b].store (spectrum.longTermDb (b), std::memory_order_relaxed);
            }
            gen.fetch_add (1, std::memory_order_release);
            triggerAsyncUpdate();
        }

        wait (10);
    }
}

void Analyser::handleAsyncUpdate()
{
    if (onNewResult != nullptr)
        onNewResult();
}

} // namespace oberli

namespace oberli::ui
{
DisplayTimer::DisplayTimer (Analyser& a, juce::Component& c)
    : analyser (a), display (c)
{
    analyser.onNewResult = [this] { wake(); };
    seen = analyser.generation();
}

DisplayTimer::~DisplayTimer()
{
    analyser.onNewResult = nullptr;
    stopTimer();
}

void DisplayTimer::wake()
{
    if (! isTimerRunning() && display.isShowing())
    {
        idleTicks = 0;
        startTimerHz (30);
        timerCallback();
    }
}

void DisplayTimer::timerCallback()
{
    const auto now = analyser.generation();

    if (now == seen || ! display.isShowing())
    {
        if (++idleTicks >= 15 || ! display.isShowing())   // 0.5 s without a new result
            stopTimer();
        return;
    }

    seen = now;
    idleTicks = 0;

    if (onFrame != nullptr)
        onFrame();
    else
        display.repaint();
}
} // namespace oberli::ui
