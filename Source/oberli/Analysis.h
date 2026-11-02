#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_dsp/juce_dsp.h>
#include <juce_events/juce_events.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include <array>
#include <atomic>
#include <functional>
#include <vector>

/*  Analysis for the display (sound-design-bob D.6.2, A.0): the audio thread copies
    samples into a lock-free ring and returns; a background thread runs the FFT and
    the fractional-octave bands; the editor reads the latest result at 30 Hz and
    stops asking when nothing new arrives.

      AudioCopy         single producer (audio thread), single consumer (analysis
                        thread); push() never blocks, never allocates; when the ring is
                        full the newest samples are dropped and counted
      BandLayout        IEC 61260 base-2 fractional-octave bands, 1/3 or 1/6 octave,
                        centred on 1 kHz, from 20 Hz to 20 kHz (and below Nyquist)
      Spectrum          Hann-windowed FFT, 50 % overlap; band power as mean square,
                        read as dB re a full-scale sine (a 0 dBFS sine in its band reads
                        0 dB); two averages: `fast` (exponential, tau in seconds) and
                        `longTerm` (the plain mean since reset, for a target curve)
      Analyser          owns the copy, a Spectrum and the background thread; publishes
                        the bands as atomics with a generation counter
      DisplayTimer      30 Hz while new results arrive, stopped after 0.5 s without one,
                        started again by the analyser's next result

    Everything the display shows comes from Spectrum, so a curve drawn from it and a
    test that reads it agree (rule 9 for analysis: the GUI and the test read one
    object). Time constants are in seconds (rule 12). */
namespace oberli
{

//==============================================================================
class AudioCopy
{
public:
    /** Allocates: room for `seconds` of stereo audio at `sampleRate`. Message thread. */
    void prepare (double sampleRate, double seconds = 1.0);

    /** Audio thread. The first two channels; a mono buffer is copied to both. */
    void push (const juce::AudioBuffer<float>& buffer, int start, int numSamples) noexcept;

    /** Consumer thread: up to `maxFrames` frames into `left` and `right`; returns how many. */
    int pop (float* left, float* right, int maxFrames) noexcept;

    int available() const noexcept { return fifo.getNumReady(); }
    int dropped() const noexcept { return droppedFrames.load (std::memory_order_relaxed); }
    void clear() noexcept;

private:
    juce::AbstractFifo fifo { 1 };
    juce::AudioBuffer<float> ring;
    std::atomic<int> droppedFrames { 0 };
};

//==============================================================================
struct BandLayout
{
    enum class Resolution { third = 3, sixth = 6 };

    struct Band { float low, centre, high; };   // Hz, exact base-2 (IEC 61260-1)

    static BandLayout make (Resolution, double sampleRate, float lowestHz = 20.0f, float highestHz = 20000.0f);

    /** The nominal label of a band ("31.5", "1k", "12.5k"): the exact centre rounded
        to three significant figures, as meters print them. */
    static juce::String label (float centreHz);

    Resolution resolution = Resolution::third;
    std::vector<Band> bands;
};

//==============================================================================
class Spectrum
{
public:
    static constexpr int kMaxBands = 64;

    /** Allocates. `fftOrder` 12 (4096) is enough for 1/6 octave down to about 40 Hz at
        48 kHz; 13 resolves 20 Hz. `fastSeconds` is the fast average's time constant. */
    void prepare (double sampleRate, BandLayout::Resolution, int fftOrder = 13, double fastSeconds = 0.3);

    void reset();

    /** Feeds samples (consumer thread or offline); runs a frame every hop. Real-time
        safe after prepare, but an FFT per hop is too much for the audio thread of a
        plugin that cares about CPU: feed it from Analyser's thread. */
    void push (const float* left, const float* right, int numFrames);

    const BandLayout& layout() const noexcept { return bands; }
    int numBands() const noexcept { return (int) bands.bands.size(); }

    /** dB re a full-scale sine, per band; -120 for no energy. */
    float fastDb (int band) const noexcept     { return toDb (fastPower[(size_t) band]); }
    float longTermDb (int band) const noexcept { return frames > 0 ? toDb (sumPower[(size_t) band] / (double) frames) : -120.0f; }
    juce::int64 framesAnalysed() const noexcept { return frames; }

private:
    void runFrame();
    static float toDb (double meanSquare) noexcept;

    BandLayout bands;
    int fftSize = 8192, hop = 4096, fill = 0;
    std::unique_ptr<juce::dsp::FFT> fft;
    std::vector<float> window, input, work;
    std::vector<double> fastPower, sumPower, framePower;
    std::vector<std::vector<std::pair<int, float>>> binWeights;   // per band: (bin, weight)
    double fastCoefficient = 0.0, normalisation = 1.0;
    juce::int64 frames = 0;
};

//==============================================================================
class Analyser : private juce::Thread, private juce::AsyncUpdater
{
public:
    Analyser();
    ~Analyser() override;

    /** Message thread, from prepareToPlay (stops the thread while it allocates). */
    void prepare (double sampleRate, BandLayout::Resolution, int fftOrder = 13, double fastSeconds = 0.3);

    /** Audio thread: hand the block over and return. */
    void push (const juce::AudioBuffer<float>& buffer, int start, int numSamples) noexcept { copy.push (buffer, start, numSamples); }

    /** Message thread: forget the long-term average (a new measurement). */
    void resetLongTerm() noexcept { resetRequested.store (true, std::memory_order_release); }

    /** Any thread: the latest published bands. */
    int numBands() const noexcept { return publishedBands.load (std::memory_order_acquire); }
    float fastDb (int band) const noexcept     { return fast[(size_t) band].load (std::memory_order_relaxed); }
    float longTermDb (int band) const noexcept { return longTerm[(size_t) band].load (std::memory_order_relaxed); }
    float bandCentre (int band) const noexcept { return centres[(size_t) band].load (std::memory_order_relaxed); }
    juce::uint32 generation() const noexcept   { return gen.load (std::memory_order_acquire); }
    int droppedFrames() const noexcept         { return copy.dropped(); }

    /** Message thread: called after each new result (the DisplayTimer starts on it). */
    std::function<void()> onNewResult;

private:
    void run() override;
    void handleAsyncUpdate() override;

    AudioCopy copy;
    Spectrum spectrum;
    std::vector<float> left, right;
    std::atomic<bool> resetRequested { false };

    std::array<std::atomic<float>, Spectrum::kMaxBands> fast {}, longTerm {}, centres {};
    std::atomic<int> publishedBands { 0 };
    std::atomic<juce::uint32> gen { 0 };
};

} // namespace oberli

namespace oberli::ui
{
/** Repaints a display at 30 Hz while its analyser publishes, and stops after 0.5 s
    without a new result; the analyser's next result starts it again. Also stops while
    the display is not showing. Message thread. */
class DisplayTimer final : private juce::Timer
{
public:
    DisplayTimer (Analyser&, juce::Component& display);
    ~DisplayTimer() override;

    /** Called on each tick with a new result (default: display.repaint()). */
    std::function<void()> onFrame;

    bool isRunning() const noexcept { return isTimerRunning(); }

private:
    void timerCallback() override;
    void wake();

    Analyser& analyser;
    juce::Component& display;
    juce::uint32 seen = 0;
    int idleTicks = 0;
};
} // namespace oberli::ui
