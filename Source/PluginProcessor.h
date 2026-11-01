#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

#include <atomic>
#include <cstring>
#include <vector>

#include "Params.h"
#include "dsp/AlignEngine.h"
#include "dsp/Detector.h"

/*  Align - the processor.

    Thread model (rule 1, D.1, and docs/status.md's G1 threads decision):
      - the **audio thread** reads parameters through cached atomics, never by string lookup, and
        never allocates, locks or logs. It writes the two analysis rings and runs the engine.
      - the **detect worker** is a juce::Thread that polls a request flag every kWorkerPollMs. It
        owns every buffer the detector uses (allocated in prepareToPlay) and publishes its result
        behind an atomic sequence counter. Polling rather than signalling keeps the audio thread's
        side of the handshake to one relaxed atomic store.
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

    /** What the editor may read from the audio thread: the 20 ms RMS per channel (D.6.2). */
    float outputLevel (int channel) const noexcept
    {
        return channel == 0 ? rmsL.load (std::memory_order_relaxed) : rmsR.load (std::memory_order_relaxed);
    }

    /** Pearson correlation between the reference and the output over the last 400 ms, -1 to +1:
        the number most engineers know from InPhase (sketch 4.5). */
    float correlation() const noexcept { return correlationValue.load (std::memory_order_relaxed); }

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

private:
    class Worker;

    void render (juce::AudioBuffer<float>&, juce::MidiBuffer&, bool bypassed);
    void parameterChanged (const juce::String& id, float value) override;
    void handleAsyncUpdate() override;
    void runDetectOnce (bool tracking);
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
    std::atomic<bool> pendingApply { false };
    std::atomic<int>  resultSequence { 0 };
    std::atomic<float> trackOffset { 0.0f };
    std::atomic<float> rmsL { 0.0f }, rmsR { 0.0f };
    std::atomic<float> correlationValue { 0.0f };
    std::atomic<bool> sidechainActive { false };

    mutable juce::CriticalSection resultLock;   // worker <-> message thread only, never the audio thread
    align::dsp::Detector::Result publishedResult;

    juce::dsp::BallisticsFilter<float> rmsFilterL, rmsFilterR;
    double corrXY = 0.0, corrXX = 0.0, corrYY = 0.0, corrCoefficient = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AlignAudioProcessor)
};
