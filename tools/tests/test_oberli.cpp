// The shared code (Source/oberli/) that needs JUCE, tested without a host: Analysis (the band
// layout, the band reading of a sine and of pink noise, the audio copy), References (decode,
// resample, analyse, the cache and its key), RenderSafety. Built as OberliTests and run by
// CTest (label fast); Loudness has its own plain C++ test (test_loudness.cpp).
// PRESET_ROOT is pointed at a scratch folder, so nothing touches the real folders.

#include "oberli/Analysis.h"
#include "oberli/Folders.h"
#include "oberli/References.h"
#include "oberli/RenderSafety.h"

#include <cmath>
#include <cstdio>
#include <random>

namespace
{
int failures = 0;

void expect (const juce::String& what, bool ok, const juce::String& detail = {})
{
    std::printf ("%-56s %s\n", what.toRawUTF8(), ok ? "ok" : ("FAILED " + detail).toRawUTF8());
    if (! ok)
        ++failures;
}

juce::AudioBuffer<float> sine (double rate, double seconds, double hz, double dbfs)
{
    juce::AudioBuffer<float> b (2, (int) std::lround (rate * seconds));
    const auto a = std::pow (10.0, dbfs / 20.0);
    for (int i = 0; i < b.getNumSamples(); ++i)
        b.setSample (0, i, (float) (a * std::sin (juce::MathConstants<double>::twoPi * hz * i / rate)));
    b.copyFrom (1, 0, b, 0, 0, b.getNumSamples());
    return b;
}

int bandNear (const oberli::Spectrum& s, float hz)
{
    int best = 0;
    for (int b = 0; b < s.numBands(); ++b)
        if (std::abs (std::log (s.layout().bands[(size_t) b].centre / hz)) < std::abs (std::log (s.layout().bands[(size_t) best].centre / hz)))
            best = b;
    return best;
}

void testBands()
{
    const auto third = oberli::BandLayout::make (oberli::BandLayout::Resolution::third, 48000.0);
    const auto sixth = oberli::BandLayout::make (oberli::BandLayout::Resolution::sixth, 48000.0);
    expect ("1/3 octave, 20 Hz to 20 kHz: 31 bands", third.bands.size() == 31, juce::String ((int) third.bands.size()));
    expect ("1/6 octave: 61 bands", sixth.bands.size() == 61, juce::String ((int) sixth.bands.size()));
    expect ("labels 31.5, 1k, 12.5k",
            oberli::BandLayout::label (1000.0f * std::pow (2.0f, -15.0f / 3.0f)) == "31.5" && oberli::BandLayout::label (1000.0f) == "1k"
                && oberli::BandLayout::label (1000.0f * std::pow (2.0f, 11.0f / 3.0f)) == "12.5k",
            oberli::BandLayout::label (1000.0f * std::pow (2.0f, -15.0f / 3.0f)));
    const auto low = oberli::BandLayout::make (oberli::BandLayout::Resolution::third, 22050.0);
    expect ("bands stop below Nyquist at 22.05 kHz", low.bands.back().high <= 11025.0f);
}

void testSpectrum()
{
    for (const double rate : { 44100.0, 48000.0, 96000.0 })
    {
        oberli::Spectrum s;
        s.prepare (rate, oberli::BandLayout::Resolution::third, 13);
        const auto b = sine (rate, 4.0, 1000.0, -6.0);
        s.push (b.getReadPointer (0), b.getReadPointer (1), b.getNumSamples());
        const auto k = bandNear (s, 1000.0f);
        expect ("sine 1 kHz -6 dBFS reads -6 dB in its band at " + juce::String (rate / 1000.0, 1) + " kHz",
                std::abs (s.longTermDb (k) + 6.0f) < 0.3f, juce::String (s.longTermDb (k), 2));
        expect ("  and the bands a third away are 40 dB under it", s.longTermDb (k + 2) < -46.0f && s.longTermDb (k - 2) < -46.0f,
                juce::String (s.longTermDb (k - 2), 1) + " / " + juce::String (s.longTermDb (k + 2), 1));
    }

    // Pink noise (Paul Kellet's filter) is flat in fractional-octave bands.
    oberli::Spectrum s;
    s.prepare (48000.0, oberli::BandLayout::Resolution::third, 13);
    std::mt19937 rng (3);
    std::normal_distribution<float> white (0.0f, 0.05f);
    float b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    std::vector<float> l (48000 * 20);
    for (auto& x : l)
    {
        const auto w = white (rng);
        b0 = 0.99886f * b0 + w * 0.0555179f; b1 = 0.99332f * b1 + w * 0.0750759f; b2 = 0.96900f * b2 + w * 0.1538520f;
        b3 = 0.86650f * b3 + w * 0.3104856f; b4 = 0.55000f * b4 + w * 0.5329522f; b5 = -0.7616f * b5 - w * 0.0168980f;
        x = b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362f;
        b6 = w * 0.115926f;
    }
    s.push (l.data(), l.data(), (int) l.size());
    float lo = 1000.0f, hi = -1000.0f;
    for (int b = 0; b < s.numBands(); ++b)
        if (s.layout().bands[(size_t) b].centre > 40.0f && s.layout().bands[(size_t) b].centre < 16000.0f)
        {
            lo = juce::jmin (lo, s.longTermDb (b));
            hi = juce::jmax (hi, s.longTermDb (b));
        }
    expect ("pink noise is flat in 1/3 octaves, 40 Hz to 16 kHz (within 2 dB)", hi - lo < 2.0f, juce::String (hi - lo, 2) + " dB");
}

void testAudioCopy()
{
    oberli::AudioCopy copy;
    copy.prepare (1000.0, 2.048);   // 2048 frames
    const auto b = sine (48000.0, 0.02, 440.0, -6.0);   // 960 frames
    copy.push (b, 0, b.getNumSamples());
    copy.push (b, 0, b.getNumSamples());
    copy.push (b, 0, b.getNumSamples());   // 2880 > capacity: the newest are dropped
    std::vector<float> l (4096), r (4096);
    const auto n = copy.pop (l.data(), r.data(), 4096);
    expect ("audio copy: what fits arrives, the rest is counted", n == 2047 && copy.dropped() == 2880 - 2047,
            juce::String (n) + " / " + juce::String (copy.dropped()));
    expect ("audio copy: the samples arrive unchanged", juce::exactlyEqual (l[100], b.getSample (0, 100)) && juce::exactlyEqual (l[1000], b.getSample (0, 40)));
}

void testReferences (const juce::File& root)
{
    namespace refs = oberli::references;
    const auto folder = refs::folder();
    expect ("the references folder follows PRESET_ROOT", folder == root.getChildFile ("References"), folder.getFullPathName());
    folder.createDirectory();

    // A 44.1 kHz stereo WAV, 1 kHz at -20 dBFS for 10 s.
    const auto wav = folder.getChildFile ("Reference 1.wav");
    {
        const auto audio = sine (44100.0, 10.0, 1000.0, -20.0);
        juce::WavAudioFormat format;
        std::unique_ptr<juce::OutputStream> stream (wav.createOutputStream());
        auto writer = format.createWriterFor (stream, juce::AudioFormatWriterOptions{}.withSampleRate (44100.0).withNumChannels (2).withBitsPerSample (24));
        expect ("wrote the test reference", writer != nullptr && writer->writeFromAudioSampleBuffer (audio, 0, audio.getNumSamples()));
    }
    folder.getChildFile ("notes.txt").replaceWithText ("not audio");

    const auto files = refs::list();
    expect ("list() finds the audio file and only it", files.size() == 1 && files[0] == wav, juce::String (files.size()));

    juce::String error;
    const auto track = refs::load (wav, 48000.0, error);
    expect ("load() decodes and resamples 44.1 -> 48 kHz", track != nullptr && std::abs (track->audio.getNumSamples() - 480000) <= 2,
            error + " " + juce::String (track != nullptr ? track->audio.getNumSamples() : -1));

    if (track != nullptr)
    {
        // The resampled sine keeps its level and has no images: compare 1 kHz and the rest.
        const auto a = refs::analyse (*track);
        expect ("analyse(): integrated -20 LUFS (+/- 0.1)", std::abs (a.integratedLufs + 20.0) < 0.1, juce::String (a.integratedLufs, 3));
        expect ("analyse(): true peak -20 dBTP (+0.2 / -0.4)", a.truePeakDb > -20.4 && a.truePeakDb < -19.8, juce::String (a.truePeakDb, 3));
        expect ("analyse(): LRA 0 LU", a.rangeLu < 0.1, juce::String (a.rangeLu, 3));
        expect ("analyse(): 61 sixth-octave bands", a.bandDb.size() == 61, juce::String ((int) a.bandDb.size()));
        float atTone = -200.0f, worstOther = -200.0f;
        for (size_t b = 0; b < a.bandDb.size(); ++b)
        {
            if (std::abs (std::log2 (a.bandCentres[b] / 1000.0f)) < 0.05f) atTone = a.bandDb[b];
            else if (std::abs (std::log2 (a.bandCentres[b] / 1000.0f)) > 0.5f) worstOther = juce::jmax (worstOther, a.bandDb[b]);
        }
        expect ("resampled sine: -20 dB at 1 kHz, every band an octave away 70 dB under it", std::abs (atTone + 20.0f) < 0.3f && worstOther < -90.0f,
                juce::String (atTone, 2) + " / " + juce::String (worstOther, 1));

        // The cache: written, read back, refused once the file changes.
        expect ("cache: written", refs::ReferenceCache::write (wav, a));
        const auto back = refs::ReferenceCache::read (wav);
        expect ("cache: read back with the same numbers", back.has_value() && std::abs (back->integratedLufs - a.integratedLufs) < 1.0e-9
                                                                && back->bandDb.size() == a.bandDb.size());
        wav.setLastModificationTime (juce::Time::getCurrentTime() + juce::RelativeTime::seconds (10.0));
        expect ("cache: a changed modification time misses", ! refs::ReferenceCache::read (wav).has_value());
    }

    expect ("load() refuses a file that is not audio", refs::load (folder.getChildFile ("notes.txt"), 48000.0, error) == nullptr && error.isNotEmpty(), error);
}

void testRenderSafety()
{
    const auto a = sine (48000.0, 0.1, 100.0, -6.0);
    auto b = a;
    expect ("maxDifference of identical buffers is 0", juce::exactlyEqual (oberli::render::maxDifference (a, b), 0.0f));
    b.setSample (1, 77, b.getSample (1, 77) + 0.25f);
    expect ("maxDifference finds one changed sample", std::abs (oberli::render::maxDifference (a, b) - 0.25f) < 1.0e-6f);
}
} // namespace

int main()
{
    juce::ScopedJuceInitialiser_GUI juce;   // the message manager, for the folders and the formats

    juce::TemporaryFile scratch;
    const auto root = scratch.getFile();
    root.createDirectory();
   #if JUCE_WINDOWS
    _putenv_s ("PRESET_ROOT", root.getFullPathName().toRawUTF8());
   #else
    setenv ("PRESET_ROOT", root.getFullPathName().toRawUTF8(), 1);
   #endif

    testBands();
    testSpectrum();
    testAudioCopy();
    testReferences (root);
    testRenderSafety();

    root.deleteRecursively();
    std::printf (failures == 0 ? "oberli: all cases pass\n" : "oberli: %d FAILED\n", failures);
    return failures == 0 ? 0 : 1;
}
