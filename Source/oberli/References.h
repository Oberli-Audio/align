#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include "Analysis.h"
#include "Loudness.h"

#include <juce_audio_formats/juce_audio_formats.h>

#include <atomic>
#include <memory>
#include <optional>
#include <vector>

/*  The shared reference library: one folder every Oberli Audio plugin reads
    (folders::referencesFolder(): ~/Music/Oberli Audio/References, Music\Oberli
    Audio\References), so a friend drops a reference track in once and A B see and
    Bench Line both find it.

      list()        the audio files in the folder (WAV, AIFF, FLAC, Ogg; MP3 and M4A
                    where the platform decodes them), A to Z
      load()        decodes a file and resamples it to the session rate with JUCE's
                    windowed-sinc interpolator; stereo (mono doubled, more channels:
                    the first two); never on the audio thread
      analyse()     integrated loudness, LRA, true peak and maximum short-term loudness
                    (Loudness), and the long-term 1/6-octave spectrum (Spectrum)
      ReferenceCache  the analysis on disk under folders::cacheFolder()/References, keyed
                    by the file's path, size and modification time: a changed file is
                    analysed again, an unchanged one costs a file read
      Loader        load + analyse on a background thread, the result delivered on the
                    message thread
      TrackSlot     hands a loaded track to the audio thread without a lock; a replaced
                    track is freed on the message thread, never on the audio thread

    A reference longer than kMaxSeconds is refused (memory: 15 min of stereo float at
    192 kHz is 1.4 GB). */
namespace oberli::references
{

constexpr double kMaxSeconds = 15.0 * 60.0;

/** A reference decoded at the session rate. Immutable once loaded. */
struct Track
{
    juce::File file;
    juce::String name;                  // the file name without extension
    double sampleRate = 0.0;            // the rate it was resampled to
    double sourceSampleRate = 0.0;
    juce::AudioBuffer<float> audio;     // two channels
};

/** What the analysis of a reference holds (and the cache stores). */
struct Analysis
{
    double integratedLufs = Loudness::kSilence;
    double rangeLu = 0.0;
    double truePeakDb = Loudness::kSilence;
    double shortTermMaxLufs = Loudness::kSilence;
    double seconds = 0.0;
    std::vector<float> bandCentres;     // Hz, 1/6 octave
    std::vector<float> bandDb;          // long-term, dB re a full-scale sine
};

juce::File folder();
juce::Array<juce::File> list();

/** Decodes and resamples; nullptr and `error` in plain words on failure. Any thread but the audio thread. */
std::unique_ptr<Track> load (const juce::File&, double targetSampleRate, juce::String& error,
                             const std::atomic<bool>* cancel = nullptr);

/** Measures a decoded track at its own rate. */
Analysis analyse (const Track&, const std::atomic<bool>* cancel = nullptr);

class ReferenceCache
{
public:
    /** The cache key: the absolute path, the size in bytes, the modification time in ms. */
    static juce::String keyFor (const juce::File&);

    /** The stored analysis if its key still matches the file. */
    static std::optional<Analysis> read (const juce::File& audioFile);
    static bool write (const juce::File& audioFile, const Analysis&);

    static juce::File cacheFileFor (const juce::File& audioFile);
};

/** Loads (and analyses, from the cache when it can) on its own thread. Message thread API. */
class Loader final : private juce::Thread
{
public:
    struct Result
    {
        std::shared_ptr<const Track> track;      // nullptr on failure
        Analysis analysis;
        juce::String error;
    };

    Loader();
    ~Loader() override;

    /** Replaces any load still running. `done` is called on the message thread. */
    void request (const juce::File&, double targetSampleRate, std::function<void (Result)> done);
    void cancel();
    bool isBusy() const noexcept { return isThreadRunning(); }

private:
    void run() override;

    juce::File file;
    double rate = 48000.0;
    std::function<void (Result)> callback;
    std::atomic<bool> cancelled { false };
    std::shared_ptr<std::atomic<bool>> alive = std::make_shared<std::atomic<bool>> (true);
};

/**
    The track the audio thread plays or measures: set() on the message thread, get()
    on the audio thread (a plain atomic pointer read, no reference counting there).
    The slot keeps every track it ever handed out alive until collect() - called by
    set() and from a message-thread timer - finds it retired for more than a second,
    far longer than any audio callback holds a pointer.
*/
class TrackSlot final : private juce::Timer
{
public:
    TrackSlot();
    ~TrackSlot() override;

    void set (std::shared_ptr<const Track>);
    const Track* get() const noexcept { return current.load (std::memory_order_acquire); }

private:
    void timerCallback() override { collect(); }
    void collect();

    std::atomic<const Track*> current { nullptr };
    std::shared_ptr<const Track> owner;
    std::vector<std::pair<std::shared_ptr<const Track>, juce::uint32>> retired;
};

} // namespace oberli::references
