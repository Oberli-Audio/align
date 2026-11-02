#include "Loudness.h"

#include <algorithm>
#include <cmath>

namespace oberli
{
namespace
{
    constexpr double kPi = 3.14159265358979323846;

    // BS.1770-4 Annex 2: the 4x true-peak interpolator, 12 taps per phase.
    constexpr float kTruePeakTaps[4][12] = {
        {  0.0017089843750f,  0.0109863281250f, -0.0196533203125f,  0.0332031250000f, -0.0594482421875f,  0.1373291015625f,
           0.9721679687500f, -0.1022949218750f,  0.0476074218750f, -0.0266113281250f,  0.0148925781250f, -0.0083007812500f },
        { -0.0291748046875f,  0.0292968750000f, -0.0517578125000f,  0.0891113281250f, -0.1665039062500f,  0.4650878906250f,
           0.7797851562500f, -0.2003173828125f,  0.1015625000000f, -0.0582275390625f,  0.0330810546875f, -0.0189208984375f },
        { -0.0189208984375f,  0.0330810546875f, -0.0582275390625f,  0.1015625000000f, -0.2003173828125f,  0.7797851562500f,
           0.4650878906250f, -0.1665039062500f,  0.0891113281250f, -0.0517578125000f,  0.0292968750000f, -0.0291748046875f },
        { -0.0083007812500f,  0.0148925781250f, -0.0266113281250f,  0.0476074218750f, -0.1022949218750f,  0.9721679687500f,
           0.1373291015625f, -0.0594482421875f,  0.0332031250000f, -0.0196533203125f,  0.0109863281250f,  0.0017089843750f },
    };

    double meanOfLast (const std::array<double, 30>& ring, int newest, int available, int n)
    {
        n = std::min (n, available);
        if (n <= 0)
            return 0.0;
        double sum = 0.0;
        for (int k = 0; k < n; ++k)
            sum += ring[(size_t) ((newest - k + 30) % 30)];
        return sum / (double) n;
    }
}

double Loudness::lufsFromEnergy (double meanSquare)
{
    return meanSquare > 0.0 ? -0.691 + 10.0 * std::log10 (meanSquare) : kSilence;
}

//==============================================================================
void Loudness::Histogram::clear()
{
    energy.assign ((size_t) kBins, 0.0);
    count.assign ((size_t) kBins, 0u);
}

void Loudness::Histogram::add (double meanSquare)
{
    const auto lufs = lufsFromEnergy (meanSquare);
    if (lufs < kLowLufs)   // the absolute gate
        return;
    const auto bin = std::min (kBins - 1, (int) ((lufs - kLowLufs) / kStep));
    energy[(size_t) bin] += meanSquare;
    count[(size_t) bin] += 1u;
}

//==============================================================================
void Loudness::prepare (double sampleRate, int numChannels, const float* weights)
{
    rate = sampleRate;
    channelsPrepared = std::clamp (numChannels, 1, kMaxChannels);

    for (int c = 0; c < kMaxChannels; ++c)
        weight[(size_t) c] = weights != nullptr && c < numChannels ? (double) weights[c] : 1.0;

    // Stage 1, the shelf (the head), and stage 2, the RLB high-pass, from their
    // analogue prototypes (BS.1770-4 Annex 1; the derivation of libebur128).
    {
        const double f0 = 1681.974450955533, gainDb = 3.999843853973347, q = 0.7071752369554196;
        const double k = std::tan (kPi * f0 / rate);
        const double vh = std::pow (10.0, gainDb / 20.0);
        const double vb = std::pow (vh, 0.4996667741545416);
        const double a0 = 1.0 + k / q + k * k;
        Biquad s;
        s.b0 = (vh + vb * k / q + k * k) / a0;
        s.b1 = 2.0 * (k * k - vh) / a0;
        s.b2 = (vh - vb * k / q + k * k) / a0;
        s.a1 = 2.0 * (k * k - 1.0) / a0;
        s.a2 = (1.0 - k / q + k * k) / a0;
        shelf.fill (s);
    }
    {
        const double f0 = 38.13547087602444, q = 0.5003270373238773;
        const double k = std::tan (kPi * f0 / rate);
        const double a0 = 1.0 + k / q + k * k;
        Biquad h;
        h.b0 = 1.0;
        h.b1 = -2.0;
        h.b2 = 1.0;
        h.a1 = 2.0 * (k * k - 1.0) / a0;
        h.a2 = (1.0 - k / q + k * k) / a0;
        highpass.fill (h);
    }

    blockLength = std::max (1, (int) std::lround (rate * 0.1));   // rule 12: 100 ms in seconds
    oversampling = rate < 96000.0 ? 4 : (rate < 192000.0 ? 2 : 1);

    gating.clear();
    shortTermValues.clear();
    reset();
}

void Loudness::reset()
{
    for (auto* set : { &shelf, &highpass })
        for (auto& f : *set)
            f.z1 = f.z2 = 0.0;

    blockFill = 0;
    blockEnergy = 0.0;
    subBlocks.fill (0.0);
    subIndex = subCount = 0;

    for (auto& h : history)
        h.fill (0.0f);
    historyPos.fill (0);

    pubMomentary.store (kSilence);
    pubShortTerm.store (kSilence);
    resetIntegrated();
}

void Loudness::resetIntegrated()
{
    std::fill (gating.energy.begin(), gating.energy.end(), 0.0);
    std::fill (gating.count.begin(), gating.count.end(), 0u);
    std::fill (shortTermValues.energy.begin(), shortTermValues.energy.end(), 0.0);
    std::fill (shortTermValues.count.begin(), shortTermValues.count.end(), 0u);
    momentaryMax = shortTermMax = kSilence;
    truePeakLinear = 0.0f;

    pubIntegrated.store (kSilence);
    pubMomentaryMax.store (kSilence);
    pubShortTermMax.store (kSilence);
    pubRange.store (0.0);
    pubTruePeak.store (kSilence);
}

//==============================================================================
void Loudness::processTruePeak (int c, float sample)
{
    auto& h = history[(size_t) c];
    auto& pos = historyPos[(size_t) c];
    h[(size_t) pos] = sample;
    pos = (pos + 1) % 12;

    if (oversampling == 1)
    {
        truePeakLinear = std::max (truePeakLinear, std::abs (sample));
        return;
    }

    const int phaseStep = oversampling == 4 ? 1 : 2;   // 2x: phases 0 and 2, half a sample apart

    for (int phase = 0; phase < 4; phase += phaseStep)
    {
        float y = 0.0f;
        // tap 0 meets the newest sample
        for (int t = 0; t < 12; ++t)
            y += kTruePeakTaps[phase][t] * h[(size_t) ((pos - 1 - t + 24) % 12)];
        truePeakLinear = std::max (truePeakLinear, std::abs (y));
    }
}

void Loudness::process (const float* const* channels, int numChannels, int numSamples)
{
    numChannels = std::min (numChannels, channelsPrepared);

    for (int i = 0; i < numSamples; ++i)
    {
        double sum = 0.0;

        for (int c = 0; c < numChannels; ++c)
        {
            const auto x = channels[c][i];
            processTruePeak (c, x);
            const auto y = highpass[(size_t) c].process (shelf[(size_t) c].process ((double) x));
            sum += weight[(size_t) c] * y * y;
        }

        blockEnergy += sum;

        if (++blockFill == blockLength)
            stepBlock();
    }

    if (! std::isfinite (blockEnergy))   // a NaN in the input must not poison the history
    {
        reset();
        return;
    }

    pubTruePeak.store (truePeakLinear > 0.0f ? 20.0 * std::log10 ((double) truePeakLinear) : kSilence, std::memory_order_relaxed);
}

void Loudness::stepBlock()
{
    subIndex = (subIndex + 1) % 30;
    subBlocks[(size_t) subIndex] = blockEnergy / (double) blockLength;
    subCount = std::min (30, subCount + 1);
    blockEnergy = 0.0;
    blockFill = 0;

    // Momentary: the last four 100 ms blocks, one 400 ms gating block.
    if (subCount >= 4)
    {
        const auto m = meanOfLast (subBlocks, subIndex, subCount, 4);
        gating.add (m);
        const auto lufs = lufsFromEnergy (m);
        momentaryMax = std::max (momentaryMax, lufs);
        pubMomentary.store (lufs, std::memory_order_relaxed);
        pubMomentaryMax.store (momentaryMax, std::memory_order_relaxed);
        pubIntegrated.store (integratedNow(), std::memory_order_relaxed);
    }

    // Short-term: 3 s.
    if (subCount >= 30)
    {
        const auto s = meanOfLast (subBlocks, subIndex, subCount, 30);
        shortTermValues.add (s);
        const auto lufs = lufsFromEnergy (s);
        shortTermMax = std::max (shortTermMax, lufs);
        pubShortTerm.store (lufs, std::memory_order_relaxed);
        pubShortTermMax.store (shortTermMax, std::memory_order_relaxed);
        pubRange.store (rangeNow(), std::memory_order_relaxed);
    }
}

double Loudness::integratedNow() const
{
    double total = 0.0;
    std::uint64_t n = 0;
    for (int b = 0; b < Histogram::kBins; ++b)
    {
        total += gating.energy[(size_t) b];
        n += gating.count[(size_t) b];
    }
    if (n == 0)
        return kSilence;

    const auto relativeGate = lufsFromEnergy (total / (double) n) - 10.0;
    double gatedTotal = 0.0;
    std::uint64_t gatedN = 0;

    for (int b = 0; b < Histogram::kBins; ++b)
    {
        if (gating.count[(size_t) b] == 0)
            continue;
        // The bin's own mean decides: exact for every bin but the one the gate falls in.
        const auto binLufs = lufsFromEnergy (gating.energy[(size_t) b] / (double) gating.count[(size_t) b]);
        if (binLufs > relativeGate)
        {
            gatedTotal += gating.energy[(size_t) b];
            gatedN += gating.count[(size_t) b];
        }
    }

    return gatedN > 0 ? lufsFromEnergy (gatedTotal / (double) gatedN) : kSilence;
}

double Loudness::rangeNow() const
{
    double total = 0.0;
    std::uint64_t n = 0;
    for (int b = 0; b < Histogram::kBins; ++b)
    {
        total += shortTermValues.energy[(size_t) b];
        n += shortTermValues.count[(size_t) b];
    }
    if (n == 0)
        return 0.0;

    const auto relativeGate = lufsFromEnergy (total / (double) n) - 20.0;
    const auto firstBin = std::max (0, (int) std::ceil ((relativeGate - Histogram::kLowLufs) / Histogram::kStep));

    std::uint64_t gatedN = 0;
    for (int b = firstBin; b < Histogram::kBins; ++b)
        gatedN += shortTermValues.count[(size_t) b];
    if (gatedN == 0)
        return 0.0;

    // EBU Tech 3342: the 10th and 95th percentiles of the gated short-term values.
    const auto percentile = [&] (double p)
    {
        const auto target = (std::uint64_t) std::floor (p * (double) (gatedN - 1));
        std::uint64_t seen = 0;
        for (int b = firstBin; b < Histogram::kBins; ++b)
        {
            seen += shortTermValues.count[(size_t) b];
            if (seen > target)
                return Histogram::kLowLufs + ((double) b + 0.5) * Histogram::kStep;
        }
        return Histogram::kHighLufs;
    };

    return std::max (0.0, percentile (0.95) - percentile (0.10));
}

Loudness::Readings Loudness::readings() const
{
    Readings r;
    r.momentary = pubMomentary.load (std::memory_order_relaxed);
    r.shortTerm = pubShortTerm.load (std::memory_order_relaxed);
    r.integrated = pubIntegrated.load (std::memory_order_relaxed);
    r.momentaryMax = pubMomentaryMax.load (std::memory_order_relaxed);
    r.shortTermMax = pubShortTermMax.load (std::memory_order_relaxed);
    r.range = pubRange.load (std::memory_order_relaxed);
    r.truePeak = pubTruePeak.load (std::memory_order_relaxed);
    return r;
}

} // namespace oberli
