#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

#include <array>
#include <atomic>
#include <cstring>

#include "Params.h"

/*  {{Product}} - the processor.

    Thread model (sound-design-bob rule 1, D.1): the audio thread reads parameters through cached
    atomics, never by string lookup; nothing on the audio thread allocates, locks or logs; every
    parameter that reaches the audio path is smoothed with the table's tau (Params::smoothing).
    State is State.h's format. The editor reads what the processor publishes as atomics only.

    This is the template's skeleton: {{kind}} with the parameters of parameters.csv (outGain and,
    for an effect, bypass and mix). sound-design-bob replaces the DSP at G4 behind the same
    contract; plugin-ui-bob replaces the editor at G2. Keep the lifecycle calls as they are. */
class {{ProductId}}AudioProcessor final : public juce::AudioProcessor
{
public:
    {{ProductId}}AudioProcessor();
    ~{{ProductId}}AudioProcessor() override = default;

    // AudioProcessor
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    void processBlockBypassed (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return PRODUCT_IS_INSTRUMENT != 0; }
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
    float outputLevel (int channel) const noexcept { return channel == 0 ? rmsL.load (std::memory_order_relaxed) : rmsR.load (std::memory_order_relaxed); }

private:
    juce::AudioProcessorValueTreeState apvts;

    // cached parameter pointers (never string lookups on the audio thread)
    std::atomic<float>* outGainParam = nullptr;
#if ! PRODUCT_IS_INSTRUMENT
    std::atomic<float>* mixParam = nullptr;
    std::atomic<float>* bypassParam = nullptr;
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> mixSmoothed;
    juce::AudioBuffer<float> dryBuffer;
#else
    // the skeleton instrument: a tiny polyphonic sine with an ADSR, replaced at G4
    struct Voice
    {
        int note = -1;
        float phase = 0.0f, increment = 0.0f, velocity = 0.0f;
        juce::ADSR env;
        bool active() const noexcept { return note >= 0; }
    };
    static constexpr int kMaxVoices = 8;
    std::array<Voice, kMaxVoices> voices;
    bool sustainDown = false;
    float pitchBendSemitones = 0.0f;   // from the wheel, +/- 2 st
    float modWheel = 0.0f;
    void noteOn (int note, float velocity);
    void noteOff (int note);
    void renderVoices (juce::AudioBuffer<float>& out, int start, int numSamples);
#endif
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Multiplicative> gainSmoothed;
    double currentSampleRate = 48000.0;
    std::atomic<float> rmsL { 0.0f }, rmsR { 0.0f };
    juce::dsp::BallisticsFilter<float> rmsFilterL, rmsFilterR;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR ({{ProductId}}AudioProcessor)
};
