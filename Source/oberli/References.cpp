#include "References.h"
#include "Folders.h"

#include <algorithm>
#include <cmath>

namespace oberli::references
{
namespace
{
    juce::AudioFormatManager& formats()
    {
        // Built once, thread-safely (a function-local static), used by the message and the loader thread.
        static const std::unique_ptr<juce::AudioFormatManager> manager = []
        {
            auto m = std::make_unique<juce::AudioFormatManager>();
            m->registerBasicFormats();   // WAV, AIFF, FLAC, Ogg; CoreAudio (MP3, M4A) on macOS, WMF on Windows
            return m;
        }();
        return *manager;
    }

    bool cancelledBy (const std::atomic<bool>* cancel) { return cancel != nullptr && cancel->load (std::memory_order_relaxed); }
}

juce::File folder() { return folders::referencesFolder(); }

juce::Array<juce::File> list()
{
    juce::Array<juce::File> files;
    const auto dir = folder();

    if (! dir.isDirectory())
        return files;

    const auto wildcard = formats().getWildcardForAllFormats();

    for (const auto& f : dir.findChildFiles (juce::File::findFiles, false, wildcard.isNotEmpty() ? wildcard : "*.wav;*.aif;*.aiff;*.flac"))
        if (! f.getFileName().startsWithChar ('.'))
            files.add (f);

    struct ByName { static int compareElements (const juce::File& a, const juce::File& b) { return a.getFileName().compareNatural (b.getFileName()); } };
    ByName sorter;
    files.sort (sorter);
    return files;
}

std::unique_ptr<Track> load (const juce::File& file, double targetRate, juce::String& error, const std::atomic<bool>* cancel)
{
    std::unique_ptr<juce::AudioFormatReader> reader (formats().createReaderFor (file));

    if (reader == nullptr)
    {
        error = file.existsAsFile() ? "I cannot read this kind of audio file." : "The file is not there any more.";
        return nullptr;
    }

    const auto sourceRate = reader->sampleRate;
    if (sourceRate <= 0.0 || reader->lengthInSamples <= 0)
    {
        error = "The file holds no audio.";
        return nullptr;
    }

    if ((double) reader->lengthInSamples / sourceRate > kMaxSeconds)
    {
        error = "The file is longer than 15 minutes.";
        return nullptr;
    }

    const auto length = (int) reader->lengthInSamples;
    juce::AudioBuffer<float> source (2, length);
    const auto channels = (int) reader->numChannels;

    // Read in pieces so a cancel is noticed.
    constexpr int piece = 1 << 16;
    for (int pos = 0; pos < length; pos += piece)
    {
        if (cancelledBy (cancel))
        {
            error = "Cancelled.";
            return nullptr;
        }
        const auto n = juce::jmin (piece, length - pos);
        reader->read (&source, pos, n, (juce::int64) pos, true, channels > 1);
    }

    if (channels == 1)
        source.copyFrom (1, 0, source, 0, 0, length);

    auto track = std::make_unique<Track>();
    track->file = file;
    track->name = file.getFileNameWithoutExtension();
    track->sourceSampleRate = sourceRate;
    track->sampleRate = targetRate;

    if (std::abs (sourceRate - targetRate) < 1.0e-6)
    {
        track->audio = std::move (source);
        return track;
    }

    // Windowed sinc (JUCE's 200-point kernel); `ratio` is input samples per output sample.
    const auto ratio = sourceRate / targetRate;
    const auto outLength = (int) std::floor ((double) length / ratio);
    track->audio.setSize (2, outLength);

    for (int ch = 0; ch < 2; ++ch)
    {
        if (cancelledBy (cancel))
        {
            error = "Cancelled.";
            return nullptr;
        }

        juce::WindowedSincInterpolator interpolator;
        interpolator.process (ratio, source.getReadPointer (ch), track->audio.getWritePointer (ch), outLength, length, 0);
    }

    return track;
}

Analysis analyse (const Track& track, const std::atomic<bool>* cancel)
{
    Analysis a;
    const auto n = track.audio.getNumSamples();
    a.seconds = (double) n / track.sampleRate;

    Loudness loudness;
    loudness.prepare (track.sampleRate, 2);
    Spectrum spectrum;
    spectrum.prepare (track.sampleRate, BandLayout::Resolution::sixth, 13);

    constexpr int chunk = 1 << 14;
    for (int pos = 0; pos < n; pos += chunk)
    {
        if (cancelledBy (cancel))
            return a;

        const auto m = juce::jmin (chunk, n - pos);
        const float* channels[] { track.audio.getReadPointer (0, pos), track.audio.getReadPointer (1, pos) };
        loudness.process (channels, 2, m);
        spectrum.push (channels[0], channels[1], m);
    }

    const auto r = loudness.readings();
    a.integratedLufs = r.integrated;
    a.rangeLu = r.range;
    a.truePeakDb = r.truePeak;
    a.shortTermMaxLufs = r.shortTermMax;

    for (int b = 0; b < spectrum.numBands(); ++b)
    {
        a.bandCentres.push_back (spectrum.layout().bands[(size_t) b].centre);
        a.bandDb.push_back (spectrum.longTermDb (b));
    }

    return a;
}

//==============================================================================
juce::String ReferenceCache::keyFor (const juce::File& f)
{
    return f.getFullPathName() + "|" + juce::String (f.getSize()) + "|" + juce::String (f.getLastModificationTime().toMilliseconds());
}

juce::File ReferenceCache::cacheFileFor (const juce::File& f)
{
    return folders::cacheFolder().getChildFile ("References")
               .getChildFile (juce::String::toHexString (f.getFullPathName().hashCode64()) + ".xml");
}

std::optional<Analysis> ReferenceCache::read (const juce::File& audioFile)
{
    const auto xml = juce::XmlDocument::parse (cacheFileFor (audioFile));

    if (xml == nullptr || ! xml->hasTagName ("ReferenceAnalysis") || xml->getStringAttribute ("key") != keyFor (audioFile)
        || xml->getIntAttribute ("version") != 1)
        return std::nullopt;

    Analysis a;
    a.integratedLufs = xml->getDoubleAttribute ("integrated", Loudness::kSilence);
    a.rangeLu = xml->getDoubleAttribute ("range");
    a.truePeakDb = xml->getDoubleAttribute ("truePeak", Loudness::kSilence);
    a.shortTermMaxLufs = xml->getDoubleAttribute ("shortTermMax", Loudness::kSilence);
    a.seconds = xml->getDoubleAttribute ("seconds");

    for (auto* band : xml->getChildWithTagNameIterator ("Band"))
    {
        a.bandCentres.push_back ((float) band->getDoubleAttribute ("hz"));
        a.bandDb.push_back ((float) band->getDoubleAttribute ("db"));
    }

    return a;
}

bool ReferenceCache::write (const juce::File& audioFile, const Analysis& a)
{
    juce::XmlElement xml ("ReferenceAnalysis");
    xml.setAttribute ("version", 1);
    xml.setAttribute ("key", keyFor (audioFile));
    xml.setAttribute ("integrated", a.integratedLufs);
    xml.setAttribute ("range", a.rangeLu);
    xml.setAttribute ("truePeak", a.truePeakDb);
    xml.setAttribute ("shortTermMax", a.shortTermMaxLufs);
    xml.setAttribute ("seconds", a.seconds);

    for (size_t b = 0; b < a.bandDb.size(); ++b)
    {
        auto* band = xml.createNewChildElement ("Band");
        band->setAttribute ("hz", (double) a.bandCentres[b]);
        band->setAttribute ("db", (double) a.bandDb[b]);
    }

    const auto target = cacheFileFor (audioFile);
    return target.getParentDirectory().createDirectory() && xml.writeTo (target);
}

//==============================================================================
Loader::Loader() : juce::Thread ("Oberli reference loader") {}

Loader::~Loader()
{
    alive->store (false);
    cancel();
}

void Loader::cancel()
{
    cancelled.store (true);
    stopThread (4000);
    cancelled.store (false);
}

void Loader::request (const juce::File& f, double targetRate, std::function<void (Result)> done)
{
    cancel();
    file = f;
    rate = targetRate;
    callback = std::move (done);
    startThread (juce::Thread::Priority::low);
}

void Loader::run()
{
    Result result;
    auto track = load (file, rate, result.error, &cancelled);

    if (track != nullptr && ! threadShouldExit())
    {
        if (auto cached = ReferenceCache::read (file))
            result.analysis = *cached;
        else
        {
            // The cache holds the analysis at the file's own rate: measure an unresampled copy
            // when the session runs at another rate, so the numbers never depend on the session.
            juce::String ignored;
            if (std::abs (track->sourceSampleRate - rate) < 1.0e-6)
                result.analysis = analyse (*track, &cancelled);
            else if (auto native = load (file, track->sourceSampleRate, ignored, &cancelled))
                result.analysis = analyse (*native, &cancelled);

            if (! cancelled.load())
                ReferenceCache::write (file, result.analysis);
        }

        result.track = std::shared_ptr<const Track> (track.release());
    }

    if (cancelled.load() || threadShouldExit())
        return;

    juce::MessageManager::callAsync ([flag = alive, done = callback, r = std::move (result)]() mutable
    {
        if (flag->load() && done != nullptr)
            done (std::move (r));
    });
}

//==============================================================================
TrackSlot::TrackSlot() { startTimer (1000); }

TrackSlot::~TrackSlot()
{
    stopTimer();
    current.store (nullptr);
}

void TrackSlot::set (std::shared_ptr<const Track> track)
{
    if (owner != nullptr)
        retired.emplace_back (owner, juce::Time::getMillisecondCounter());

    owner = std::move (track);
    current.store (owner.get(), std::memory_order_release);
    collect();
}

void TrackSlot::collect()
{
    const auto now = juce::Time::getMillisecondCounter();
    retired.erase (std::remove_if (retired.begin(), retired.end(), [now] (const auto& r) { return now - r.second > 1000; }),
                   retired.end());
}

} // namespace oberli::references
