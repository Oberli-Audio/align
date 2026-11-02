// Source/oberli/Loudness against the test signals of EBU Tech 3341 (loudness, true peak) and
// EBU Tech 3342 (loudness range), at 44.1, 48, 96 and 192 kHz (sound-design-bob rule 17).
// Built and run by CTest (label fast): plain C++, no JUCE. Exit 0 when every case passes.
//
//   c++ -std=c++17 -O2 -I Source tools/tests/test_loudness.cpp Source/oberli/Loudness.cpp -o test_loudness && ./test_loudness

#include "oberli/Loudness.h"

#include <cmath>
#include <cstdio>
#include <vector>

namespace
{
constexpr double kPi = 3.14159265358979323846;
int failures = 0;

struct Segment { double seconds, dbfs; };

/** A stereo 1 kHz sine through `segments`, phase continuous; returns the meter after it. */
oberli::Loudness::Readings run (double rate, const std::vector<Segment>& segments, double hz = 1000.0, double phase0 = 0.0)
{
    oberli::Loudness meter;
    meter.prepare (rate, 2);

    const int chunk = 512;
    std::vector<float> l (chunk), r (chunk);
    double phase = phase0;

    for (const auto& s : segments)
    {
        const auto amplitude = std::pow (10.0, s.dbfs / 20.0);
        auto remaining = (long) std::llround (s.seconds * rate);
        while (remaining > 0)
        {
            const int n = (int) std::min<long> (chunk, remaining);
            for (int i = 0; i < n; ++i)
            {
                l[(size_t) i] = r[(size_t) i] = (float) (amplitude * std::sin (phase));
                phase += 2.0 * kPi * hz / rate;
            }
            const float* channels[] { l.data(), r.data() };
            meter.process (channels, 2, n);
            remaining -= n;
        }
    }

    return meter.readings();
}

void expect (const char* what, double rate, double got, double want, double below, double above)
{
    const auto ok = got >= want - below && got <= want + above;
    std::printf ("%-46s %6.1f kHz  got %8.3f  want %7.2f (-%.2f/+%.2f)  %s\n", what, rate / 1000.0, got, want, below, above, ok ? "ok" : "FAILED");
    if (! ok)
        ++failures;
}
} // namespace

int main()
{
    for (const double rate : { 44100.0, 48000.0, 96000.0, 192000.0 })
    {
        // EBU 3341 case 1 and 2: a steady sine; M, S and I all read its level.
        {
            const auto m = run (rate, { { 20.0, -23.0 } });
            expect ("3341-1 -23 dBFS: integrated", rate, m.integrated, -23.0, 0.1, 0.1);
            expect ("3341-1 -23 dBFS: momentary", rate, m.momentary, -23.0, 0.1, 0.1);
            expect ("3341-1 -23 dBFS: short-term", rate, m.shortTerm, -23.0, 0.1, 0.1);
        }
        expect ("3341-2 -33 dBFS: integrated", rate, run (rate, { { 20.0, -33.0 } }).integrated, -33.0, 0.1, 0.1);

        // Case 3 and 4: the relative and the absolute gate.
        expect ("3341-3 -36/-23/-36: integrated", rate,
                run (rate, { { 10.0, -36.0 }, { 60.0, -23.0 }, { 10.0, -36.0 } }).integrated, -23.0, 0.1, 0.1);
        expect ("3341-4 -72/-36/-23/-36/-72: integrated", rate,
                run (rate, { { 10.0, -72.0 }, { 10.0, -36.0 }, { 60.0, -23.0 }, { 10.0, -36.0 }, { 10.0, -72.0 } }).integrated,
                -23.0, 0.1, 0.1);

        // EBU 3342 cases 1 to 3: the loudness range of two steps.
        expect ("3342-1 -20/-30: LRA", rate, run (rate, { { 20.0, -20.0 }, { 20.0, -30.0 } }).range, 10.0, 1.0, 1.0);
        expect ("3342-2 -20/-15: LRA", rate, run (rate, { { 20.0, -20.0 }, { 20.0, -15.0 } }).range, 5.0, 1.0, 1.0);
        expect ("3342-3 -40/-20: LRA", rate, run (rate, { { 20.0, -40.0 }, { 20.0, -20.0 } }).range, 20.0, 1.0, 1.0);

        // True peak (3341 tolerance +0.2 / -0.4 dB): a sine at a quarter of the rate, sampled 45 degrees
        // off its crests, reads 3 dB under its peak as samples; the true peak is the crest. Below 96 kHz
        // only: above, fs/4 is far beyond the audio band and the meter oversamples less (Loudness.h).
        if (rate < 96000.0)
        {
            const auto m = run (rate, { { 1.0, -6.0206 } }, rate / 4.0, kPi / 4.0);
            expect ("true peak, fs/4 sine 45 deg off, -6.02 dB", rate, m.truePeak, -6.02, 0.4, 0.2);
        }
        {
            const auto m = run (rate, { { 1.0, -3.0 } }, 997.0);
            expect ("true peak, 997 Hz at -3 dBFS", rate, m.truePeak, -3.0, 0.4, 0.2);
        }
        // Silence: no reading, below every gate.
        expect ("silence: integrated is no reading", rate, run (rate, { { 5.0, -200.0 } }).integrated <= -1.0e8 ? 1.0 : 0.0, 1.0, 0.0, 0.0);
    }

    std::printf (failures == 0 ? "loudness: all cases pass\n" : "loudness: %d FAILED\n", failures);
    return failures == 0 ? 0 : 1;
}
