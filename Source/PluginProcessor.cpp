#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "State.h"

#include <cmath>

namespace
{
template <typename T>
T* param (juce::AudioProcessorValueTreeState& apvts, const char* id)
{
    auto* p = apvts.getRawParameterValue (id);
    jassert (p != nullptr);   // the table and the code disagree: parameters.csv is the source
    return p;
}
} // namespace

{{ProductId}}AudioProcessor::{{ProductId}}AudioProcessor()
    : AudioProcessor (BusesProperties()
#if ! PRODUCT_IS_INSTRUMENT
                          .withInput ("Input", juce::AudioChannelSet::stereo(), true)
#endif
                          .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "PARAMETERS", Params::createParameterLayout())
{
    outGainParam = param<std::atomic<float>> (apvts, Params::outGain);
#if ! PRODUCT_IS_INSTRUMENT
    mixParam = param<std::atomic<float>> (apvts, Params::mix);
    bypassParam = param<std::atomic<float>> (apvts, Params::bypassParameterId);
#endif
}

void {{ProductId}}AudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    currentSampleRate = sampleRate;
    // smoothing from the table (Params::smoothing): tau in ms -> JUCE ramp length (settle in about 4.6 tau)
    auto tauMs = [] (const char* id) { for (const auto& s : Params::smoothing) if (std::strcmp (s.id, id) == 0) return s.tauMs; return 0.0f; };
    gainSmoothed.reset (sampleRate, (double) tauMs (Params::outGain) * 4.6 / 1000.0);
    gainSmoothed.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (outGainParam->load()));
#if ! PRODUCT_IS_INSTRUMENT
    mixSmoothed.reset (sampleRate, (double) tauMs (Params::mix) * 4.6 / 1000.0);
    mixSmoothed.setCurrentAndTargetValue (mixParam->load() / 100.0f);
    dryBuffer.setSize (2, juce::jmax (1, samplesPerBlock), false, false, true);
#else
    for (auto& v : voices)
    {
        v = Voice {};
        v.env.setSampleRate (sampleRate);
        v.env.setParameters ({ 0.01f, 0.1f, 0.8f, 0.3f });
    }
    sustainDown = false;
#endif
    juce::dsp::ProcessSpec spec { sampleRate, (juce::uint32) juce::jmax (1, samplesPerBlock), 1 };
    for (auto* f : { &rmsFilterL, &rmsFilterR })
    {
        f->prepare (spec);
        f->setLevelCalculationType (juce::dsp::BallisticsFilterLevelCalculationType::RMS);
        f->setAttackTime (20.0f);
        f->setReleaseTime (20.0f);
    }
    rmsL.store (0.0f);
    rmsR.store (0.0f);
}

void {{ProductId}}AudioProcessor::releaseResources() {}

bool {{ProductId}}AudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;
#if ! PRODUCT_IS_INSTRUMENT
    if (layouts.getMainInputChannelSet() != juce::AudioChannelSet::stereo()
        && layouts.getMainInputChannelSet() != juce::AudioChannelSet::mono())
        return false;
#endif
    return true;
}

double {{ProductId}}AudioProcessor::getTailLengthSeconds() const
{
#if PRODUCT_IS_INSTRUMENT
    return 0.3;   // the release of the skeleton's envelope; the real instrument reports its longest tail (D.2.5)
#else
    return 0.0;
#endif
}

juce::AudioProcessorParameter* {{ProductId}}AudioProcessor::getBypassParameter() const
{
#if PRODUCT_IS_INSTRUMENT
    return nullptr;   // rule 7 does not apply to an instrument
#else
    return apvts.getParameter (Params::bypassParameterId);
#endif
}

void {{ProductId}}AudioProcessor::processBlockBypassed (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    // an effect passes the input through, an instrument is silent; output channels beyond the input are cleared
    for (int ch = getTotalNumInputChannels(); ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear (ch, 0, buffer.getNumSamples());
}

#if PRODUCT_IS_INSTRUMENT
void {{ProductId}}AudioProcessor::noteOn (int note, float velocity)
{
    Voice* slot = nullptr;
    for (auto& v : voices)
        if (v.note == note) { slot = &v; break; }                  // retrigger the same key
    if (slot == nullptr)
        for (auto& v : voices)
            if (! v.active()) { slot = &v; break; }
    if (slot == nullptr)
        for (auto& v : voices)
            if (! v.env.isActive()) { slot = &v; break; }
    if (slot == nullptr)
        slot = &voices[0];                                             // steal the first (the real instrument: oldest released, D.5)
    slot->note = note;
    slot->velocity = velocity;
    slot->phase = 0.0f;
    slot->env.noteOn();
}

void {{ProductId}}AudioProcessor::noteOff (int note)
{
    for (auto& v : voices)
        if (v.note == note)
            v.env.noteOff();
}

void {{ProductId}}AudioProcessor::renderVoices (juce::AudioBuffer<float>& out, int start, int numSamples)
{
    const float bend = std::pow (2.0f, pitchBendSemitones / 12.0f);
    for (auto& v : voices)
    {
        if (! v.active())
            continue;
        if (! v.env.isActive())
        {
            v.note = -1;
            continue;
        }
        const float hz = 440.0f * std::pow (2.0f, (float) (v.note - 69) / 12.0f) * bend;
        v.increment = hz / (float) currentSampleRate;
        auto* l = out.getWritePointer (0);
        auto* r = out.getNumChannels() > 1 ? out.getWritePointer (1) : nullptr;
        const float vibrato = modWheel * 0.005f;
        for (int i = start; i < start + numSamples; ++i)
        {
            const float e = v.env.getNextSample();
            const float s = std::sin (v.phase * juce::MathConstants<float>::twoPi) * v.velocity * 0.2f * e;
            v.phase += v.increment * (1.0f + vibrato * std::sin ((float) i * 0.001f));
            if (v.phase >= 1.0f) v.phase -= 1.0f;
            l[i] += s;
            if (r != nullptr) r[i] += s;
        }
    }
}
#endif

void {{ProductId}}AudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    juce::ScopedNoDenormals noDenormals;
    const int numSamples = buffer.getNumSamples();
    for (int ch = getTotalNumInputChannels(); ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear (ch, 0, numSamples);
    if (numSamples == 0)   // a zero-length block is legal (harness contract, D.5.1)
        return;

    gainSmoothed.setTargetValue (juce::Decibels::decibelsToGain (outGainParam->load()));

#if PRODUCT_IS_INSTRUMENT
    buffer.clear();
    // MIDI at sample offsets (rule 16): split the block at every event
    int pos = 0;
    for (const auto metadata : midi)
    {
        const auto msg = metadata.getMessage();
        const int at = juce::jlimit (0, numSamples, metadata.samplePosition);
        if (at > pos)
        {
            renderVoices (buffer, pos, at - pos);
            pos = at;
        }
        if (msg.isNoteOn())            noteOn (msg.getNoteNumber(), msg.getFloatVelocity());
        else if (msg.isNoteOff())      { if (! sustainDown) noteOff (msg.getNoteNumber()); }
        else if (msg.isSustainPedalOn())  sustainDown = true;
        else if (msg.isSustainPedalOff()) { sustainDown = false; for (auto& v : voices) if (v.active()) v.env.noteOff(); }
        else if (msg.isPitchWheel())   pitchBendSemitones = 2.0f * (float) (msg.getPitchWheelValue() - 8192) / 8192.0f;
        else if (msg.isController() && msg.getControllerNumber() == 1) modWheel = (float) msg.getControllerValue() / 127.0f;
        else if (msg.isAllNotesOff() || msg.isAllSoundOff()) { for (auto& v : voices) v = Voice {}; }
    }
    if (pos < numSamples)
        renderVoices (buffer, pos, numSamples - pos);
    midi.clear();
#else
    juce::ignoreUnused (midi);
    if (bypassParam->load() >= 0.5f)
    {
        processBlockBypassed (buffer, midi);
        return;
    }
    // the skeleton's "wet" path is the input itself; the real effect renders into the buffer here
    const int channels = juce::jmin (2, buffer.getNumChannels());
    for (int ch = 0; ch < channels; ++ch)
        dryBuffer.copyFrom (ch, 0, buffer, ch, 0, numSamples);
    mixSmoothed.setTargetValue (mixParam->load() / 100.0f);
    for (int i = 0; i < numSamples; ++i)
    {
        const float m = mixSmoothed.getNextValue();
        const float dry = std::cos (m * juce::MathConstants<float>::halfPi);   // equal power
        const float wet = std::sin (m * juce::MathConstants<float>::halfPi);
        for (int ch = 0; ch < channels; ++ch)
        {
            auto* out = buffer.getWritePointer (ch);
            out[i] = dryBuffer.getSample (ch, i) * dry + out[i] * wet;
        }
    }
#endif

    // output gain, smoothed per sample (Law 5), then the level the editor shows
    auto* l = buffer.getWritePointer (0);
    auto* r = buffer.getNumChannels() > 1 ? buffer.getWritePointer (1) : nullptr;
    float lastL = 0.0f, lastR = 0.0f;
    for (int i = 0; i < numSamples; ++i)
    {
        const float g = gainSmoothed.getNextValue();
        l[i] *= g;
        lastL = rmsFilterL.processSample (0, l[i]);
        if (r != nullptr)
        {
            r[i] *= g;
            lastR = rmsFilterR.processSample (0, r[i]);
        }
    }
    rmsL.store (lastL, std::memory_order_relaxed);
    rmsR.store (r != nullptr ? lastR : lastL, std::memory_order_relaxed);
}

juce::AudioProcessorEditor* {{ProductId}}AudioProcessor::createEditor()
{
    return new {{ProductId}}AudioProcessorEditor (*this);
}

void {{ProductId}}AudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    copyXmlToBinary (*{{bundle}}::State::toXml (apvts), destData);
}

void {{ProductId}}AudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    loadState (data, sizeInBytes);
}

bool {{ProductId}}AudioProcessor::loadState (const void* data, int sizeInBytes)
{
    // arbitrary bytes are refused, never crashed on (D.5.3): a foreign or newer blob leaves the state as it is
    if (data == nullptr || sizeInBytes <= 0)
        return false;
    auto xml = getXmlFromBinary (data, sizeInBytes);
    if (xml == nullptr)
        return false;
    auto* state = {{bundle}}::State::stateOf (*xml);
    return state != nullptr && {{bundle}}::State::fromXml (*state, apvts);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new {{ProductId}}AudioProcessor();
}
