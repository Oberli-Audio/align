#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

#include <atomic>
#include <cstring>
#include <vector>

#include "Params.h"
#include "dsp/AlignEngine.h"
#include "dsp/Detector.h"
#include "oberli/Analysis.h"
#include "oberli/MeterTaps.h"
#include "oberli/PresetLibrary.h"

/*  Align - the processor.

    Thread model (rule 1, D.1, and docs/status.md's G1 threads decision):
      - the **audio thread** reads parameters through cached atomics, never by string lookup, and
        never allocates, locks or logs. It writes the two analysis rings and runs the engine.
      - the **detect worker** is a juce::Thread that polls a request flag every kWorkerPollMs. It
        owns every buffer the detector uses (allocated in prepareToPlay) and publishes its result
        behind an atomic sequence counter. Polling rather than signalling keeps the audio thread's
        side of the handshake to one relaxed atomic store.
      - **Track mode** is scheduled in *audio* time: every kTrackIntervalMs of audio the audio thread
        raises a request (one relaxed store) and the worker serves it. Offline (isNonRealtime(),
        a bounce) the audio thread runs the estimate itself at that sample position - the detector
        allocates nothing and the Track path takes no lock (rule 1), and a bounce then renders the
        same every time and does not depend on how fast the host renders (rule 8; docs/failures.md
        2026-11-03). `analysisBusy` is a try-claim on the detector's buffers, never a wait: whoever
        does not get it skips that turn.
      - the **message thread** writes the parameters, through an AsyncUpdater, with
        begin/perform/endChangeGesture, so the host records one edit and the editor's knobs move.

    The harness drives the same path. A console app runs no message loop, so after the worker has
    published it calls applyPendingDetect() directly - the same function handleAsyncUpdate() calls.

    Buses: a stereo main pair plus a stereo **sidechain** aux input, which is where the reference
    mic goes (Ableton Live shows its sidechain chooser in the device title bar). Without a
    sidechain connected Detect has nothing to measure and says so.
*/
class AlignAudioProcessor final : public juce::AudioProcessor,
                                  private juce::AudioProcessorValueTreeState::Listener,
                                  private juce::AsyncUpdater
{
public:
    static constexpr int   kWorkerPollMs = 20;
    static constexpr float kTrackIntervalMs = 250.0f;   // Track mode re-estimates this often
    static constexpr float kTrackFrameSeconds = 1.0f;   // over this much audio
    static constexpr float kTrackSearchMs = 2.0f;       // +/- this far around the current value
    static constexpr float kTrackTauMs = 1000.0f;       // one-pole smoothing of the tracked offset

    AlignAudioProcessor();
    ~AlignAudioProcessor() override;

    // AudioProcessor
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    void processBlockBypassed (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    using juce::AudioProcessor::processBlock;            // the double overloads stay visible
    using juce::AudioProcessor::processBlockBypassed;    // (the base class asserts if one is used)

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override;
    juce::AudioProcessorParameter* getBypassParameter() const override;

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    /** setStateInformation's work, with a verdict: false when the bytes are not a state of this
        plugin (foreign, truncated, newer); the state is then unchanged. The harness reports it. */
    bool loadState (const void* data, int sizeInBytes);

    /** The parameter tree; the editor attaches to it, the harness sets values through it. */
    juce::AudioProcessorValueTreeState& parameters() { return apvts; }

    /** The factory bank and the User folder (Source/oberli/PresetLibrary.h); the Strip frame's
        header, drawer and menu work on it. */
    oberli::PresetLibrary& presetLibrary() noexcept { return *presets; }
    oberli::PresetHost& presetHost() noexcept { return *presets; }

    // ---- the editor's taps (Source/oberli/MeterTaps.h, Analysis.h); fed in real time while an
    // editor is open, never offline (RenderSafety.h), so a bounce does no display work ------------
    /** The output's sample peak and clip flag. */
    oberli::PeakTap& outputPeaks() noexcept { return peaks; }
    /** Reference against output: channel 0 the output's mono sum, channel 1 the reference's. */
    oberli::CorrelationTap& referenceCorrelation() noexcept { return correlationTap; }
    /** The Sum well (sketch 4.5): this track plus the reference as they meet in the mix, before
        Align (the input) and after it (the output, against the reference delayed by the reported
        latency, which is what the host's compensation plays). */
    oberli::Analyser& sumBefore() noexcept { return beforeAnalyser; }
    oberli::Analyser& sumAfter() noexcept { return afterAnalyser; }
    /** The editor says whether anything is watching; the audio thread reads it once per block. */
    void setDisplaysActive (bool active) noexcept { displaysActive.store (active, std::memory_order_relaxed); }

    /** Pearson correlation between the reference and the output over the last 400 ms, -1 to +1:
        the number most engineers know from InPhase (sketch 4.5). */
    float correlation() const noexcept { return correlationTap.get(); }

    /** True while a stereo sidechain is connected and carrying something. */
    bool sidechainConnected() const noexcept { return sidechainActive.load (std::memory_order_relaxed); }

    // ---- Detect, for the editor, the tests and the harness -------------------------------
    /** Ask for a detect. Safe from any thread; the audio thread's side is one relaxed store. */
    void requestDetect() noexcept { detectRequested.store (true, std::memory_order_relaxed); }

    /** The sequence counter the worker bumps after publishing; 0 until the first result. */
    int detectSequence() const noexcept { return resultSequence.load (std::memory_order_acquire); }

    /** The last result the worker published. */
    align::dsp::Detector::Result lastDetect() const;

    /** Writes the published delay and polarity to the parameters as one host edit. Idempotent:
        the second call does nothing. Called by handleAsyncUpdate() in a host and directly by the
        harness, which has no message loop. */
    void applyPendingDetect();

    /** Writes the published Rotate suggestion to the parameters as one host edit - the Apply
        button. Detect never does this on its own (brief: automatic phase shaping is a sound
        decision, so it stays a suggestion). */
    void applyRotateSuggestion();

    /** Blocks up to `timeoutMs` for the worker to publish a result newer than `sinceSequence`.
        For tests and the harness only; never called from the audio or message thread of a host. */
    bool waitForDetect (int sinceSequence, int timeoutMs);

    /** What Track mode currently adds to Delay, in ms (never written to the parameter). */
    float trackOffsetMs() const noexcept { return trackOffset.load (std::memory_order_relaxed); }

    /** The rate the analysis rings and the detector run at: the session rate decimated to land in
        [44.1, 48] kHz, so the worker's FFT stays bounded (AnalysisRing.h). */
    double analysisRate() const noexcept { return engine.inputRing().rate(); }

    /** How much audio the rings hold right now, in seconds at the analysis rate. */
    double analysisSecondsAvailable() const noexcept
    {
        return (double) engine.inputRing().available() / juce::jmax (1.0, engine.inputRing().rate());
    }

private:
    class Worker;

    void render (juce::AudioBuffer<float>&, juce::MidiBuffer&, bool bypassed);
    void parameterChanged (const juce::String& id, float value) override;
    void handleAsyncUpdate() override;
    void runDetectOnce (bool tracking);
    void scheduleTrack (int numSamples) noexcept;
    void feedDisplays (const float* const* in, int inChannels, const float* const* out, int outChannels,
                       const float* const* side, int numSamples) noexcept;
    bool tryClaimAnalysis() noexcept
    {
        bool expected = false;
        return analysisBusy.compare_exchange_strong (expected, true, std::memory_order_acquire);
    }
    void releaseAnalysis() noexcept { analysisBusy.store (false, std::memory_order_release); }
    align::dsp::AlignEngine::Params currentParams() const noexcept;

    juce::AudioProcessorValueTreeState apvts;

    // cached parameter pointers (never string lookups on the audio thread)
    std::atomic<float>* delayParam = nullptr;
    std::atomic<float>* polarityParam = nullptr;
    std::atomic<float>* windowParam = nullptr;
    std::atomic<float>* rotateParam = nullptr;
    std::atomic<float>* belowParam = nullptr;
    std::atomic<float>* modeParam = nullptr;
    std::atomic<float>* holdParam = nullptr;
    std::atomic<float>* listenParam = nullptr;
    std::atomic<float>* trimParam = nullptr;
    std::atomic<float>* bypassParam = nullptr;

    align::dsp::AlignEngine engine;
    align::dsp::Detector detector;
    std::vector<float> frameRef, frameIn;
    std::unique_ptr<Worker> worker;

    double currentSampleRate = 48000.0;
    int reportedLatency = 0;

    std::atomic<bool> detectRequested { false };
    std::atomic<bool> trackRequested { false };
    std::atomic<bool> analysisBusy { false };   // the detector and its frames: worker or (offline) audio thread
    juce::int64 trackIntervalSamples = 12000, samplesToNextTrack = 0;   // audio thread only
    std::atomic<bool> pendingApply { false };
    std::atomic<int>  resultSequence { 0 };
    std::atomic<float> trackOffset { 0.0f };
    std::atomic<bool> sidechainActive { false };

    mutable juce::CriticalSection resultLock;   // worker <-> message thread only, never the audio thread
    align::dsp::Detector::Result publishedResult;

    std::unique_ptr<oberli::PresetLibrary> presets;
    oberli::PeakTap peaks;
    oberli::CorrelationTap correlationTap;
    oberli::Analyser beforeAnalyser, afterAnalyser;
    std::atomic<bool> displaysActive { false };
    juce::AudioBuffer<float> displayScratch;        // 0: input mono, 1: before, 2: after, 3: output mono
    std::vector<float> referenceDelay;              // the reference's mono sum, delayed by the latency
    int referenceWrite = 0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AlignAudioProcessor)
};
