#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "State.h"
#include "oberli/RenderSafety.h"

#include <ProductData.h>

#include <cmath>

namespace
{
/** A file compiled into the plugin (CMakeLists.txt: ProductData) by its name, or an empty block. */
juce::MemoryBlock productFile (const juce::String& fileName)
{
    for (int i = 0; i < ProductData::namedResourceListSize; ++i)
        if (fileName == ProductData::getNamedResourceOriginalFilename (ProductData::namedResourceList[i]))
        {
            int size = 0;
            const auto* data = ProductData::getNamedResource (ProductData::namedResourceList[i], size);
            return { data, (size_t) size };
        }
    return {};
}

std::atomic<float>* rawParam (juce::AudioProcessorValueTreeState& apvts, const char* id)
{
    auto* p = apvts.getRawParameterValue (id);
    jassert (p != nullptr);   // the table and the code disagree: parameters.csv is the source
    return p;
}
} // namespace

//==============================================================================
/*  The detect worker. Polls a flag rather than waiting on an event, so the audio thread's whole
    contribution to the handshake is one relaxed atomic store (rule 1). kWorkerPollMs of latency on
    a 200 ms measurement is not worth a syscall on the audio thread. */
class AlignAudioProcessor::Worker final : public juce::Thread
{
public:
    explicit Worker (AlignAudioProcessor& p) : juce::Thread ("Align detect"), owner (p) {}

    void run() override
    {
        while (! threadShouldExit())
        {
            // a request stays pending while the audio thread holds the detector (offline Track)
            if (owner.detectRequested.load (std::memory_order_acquire) && owner.tryClaimAnalysis())
            {
                owner.detectRequested.store (false, std::memory_order_relaxed);
                owner.runDetectOnce (false);
                owner.releaseAnalysis();
            }
            else if (owner.trackRequested.load (std::memory_order_acquire) && owner.tryClaimAnalysis())
            {
                owner.trackRequested.store (false, std::memory_order_relaxed);
                owner.runDetectOnce (true);
                owner.releaseAnalysis();
            }
            wait (kWorkerPollMs);
        }
    }

private:
    AlignAudioProcessor& owner;
};

//==============================================================================
AlignAudioProcessor::AlignAudioProcessor()
    : AudioProcessor (BusesProperties()
                          .withInput ("Input", juce::AudioChannelSet::stereo(), true)
                          .withInput ("Sidechain", juce::AudioChannelSet::stereo(), true)
                          .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "PARAMETERS", Params::createParameterLayout())
{
    delayParam = rawParam (apvts, Params::delay);
    polarityParam = rawParam (apvts, Params::polarity);
    windowParam = rawParam (apvts, Params::window);
    rotateParam = rawParam (apvts, Params::rotate);
    belowParam = rawParam (apvts, Params::below);
    modeParam = rawParam (apvts, Params::mode);
    holdParam = rawParam (apvts, Params::hold);
    listenParam = rawParam (apvts, Params::listen);
    trimParam = rawParam (apvts, Params::trim);
    bypassParam = rawParam (apvts, Params::bypassParameterId);

    // Detect is a momentary host parameter, so a controller button or a MIDI map can trigger it
    // (sketch 3); the editor's button sets the same parameter.
    apvts.addParameterListener (Params::detect, this);

    // The factory bank (presets.csv and presets/, compiled in) and the User folder, in the
    // family's format (State.h); the Strip frame's header, drawer and menu work on it.
    presets = std::make_unique<oberli::PresetLibrary> (
        productFile ("presets.csv").toString(), productFile,
        [this] (const juce::String& name, const juce::String& category, const juce::String& description, bool factory)
        {
            return align::State::presetXml (apvts, name, "", category, description, factory);
        },
        [this] (const juce::XmlElement& document)
        {
            auto* state = align::State::stateOf (document);
            return state != nullptr && align::State::fromXml (*state, apvts);
        });
    // A new instance holds the parameter table's defaults: the Init preset, the bank's first.
    if (! presets->factoryPresets().empty())
        presets->restoreActive ("factory:" + presets->factoryPresets().front().slug);

    worker = std::make_unique<Worker> (*this);
    worker->startThread (juce::Thread::Priority::low);
}

AlignAudioProcessor::~AlignAudioProcessor()
{
    cancelPendingUpdate();
    apvts.removeParameterListener (Params::detect, this);
    if (worker != nullptr)
        worker->stopThread (1000);
}

//==============================================================================
void AlignAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    currentSampleRate = sampleRate;
    engine.prepare (sampleRate, samplesPerBlock, currentParams());
    reportedLatency = engine.latencySamples();
    setLatencySamples (reportedLatency);

    const int frame = engine.inputRing().capacity();
    detector.prepare (engine.inputRing().rate(), frame);
    frameRef.assign ((size_t) frame, 0.0f);
    frameIn.assign ((size_t) frame, 0.0f);

    // the editor's taps: the correlation meter's 400 ms window (sketch 4.5), the Sum well at 1/6
    // octave, and the reference delayed by the longest latency a Window can report
    peaks.reset();
    correlationTap.prepare (sampleRate, 0.4);
    beforeAnalyser.prepare (sampleRate, oberli::BandLayout::Resolution::sixth);
    afterAnalyser.prepare (sampleRate, oberli::BandLayout::Resolution::sixth);
    displayScratch.setSize (4, juce::jmax (1, samplesPerBlock), false, true, false);
    const auto longest = (double) align::dsp::AlignEngine::kWindowMs[align::dsp::AlignEngine::kNumWindows - 1];
    referenceDelay.assign ((size_t) std::ceil (longest * 1.0e-3 * sampleRate) + 2, 0.0f);
    referenceWrite = 0;
    trackOffset.store (0.0f);
    trackIntervalSamples = juce::jmax ((juce::int64) 1, (juce::int64) std::llround (kTrackIntervalMs * 1.0e-3 * sampleRate));
    samplesToNextTrack = 0;
    trackRequested.store (false);
}

void AlignAudioProcessor::releaseResources() {}

bool AlignAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;
    const auto in = layouts.getMainInputChannelSet();
    if (in != juce::AudioChannelSet::stereo() && in != juce::AudioChannelSet::mono())
        return false;
    if (layouts.inputBuses.size() > 1)
    {
        const auto side = layouts.getChannelSet (true, 1);
        if (! side.isDisabled() && side != juce::AudioChannelSet::stereo()
            && side != juce::AudioChannelSet::mono())
            return false;
    }
    return true;
}

double AlignAudioProcessor::getTailLengthSeconds() const
{
    // the deepest the line can be asked to hold: the widest Window plus the full positive Delay
    return (double) (align::dsp::AlignEngine::kWindowMs[align::dsp::AlignEngine::kNumWindows - 1]
                     + align::dsp::AlignEngine::kDelayMaxMs) * 1.0e-3;
}

juce::AudioProcessorParameter* AlignAudioProcessor::getBypassParameter() const
{
    return apvts.getParameter (Params::bypassParameterId);
}

void AlignAudioProcessor::processBlockBypassed (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    // the host's hard bypass still has to come out latency-compensated (rule 7), so it runs the
    // same path with the bypass crossfade pinned on; the chain keeps its state warm
    render (buffer, midi, true);
}

//==============================================================================
align::dsp::AlignEngine::Params AlignAudioProcessor::currentParams() const noexcept
{
    align::dsp::AlignEngine::Params p;
    p.delayMs = delayParam != nullptr ? delayParam->load() : 0.0f;
    p.polarity = polarityParam != nullptr && polarityParam->load() >= 0.5f;
    p.window = windowParam != nullptr ? (int) std::lround (windowParam->load()) : 2;
    p.rotateDeg = rotateParam != nullptr ? rotateParam->load() : 0.0f;
    p.belowHz = belowParam != nullptr ? belowParam->load() : 120.0f;
    p.listen = listenParam != nullptr ? (int) std::lround (listenParam->load()) : 0;
    p.trimDb = trimParam != nullptr ? trimParam->load() : 0.0f;
    const bool tracking = modeParam != nullptr && modeParam->load() >= 0.5f;
    p.trackOffsetMs = tracking ? trackOffset.load (std::memory_order_relaxed) : 0.0f;
    return p;
}

void AlignAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    render (buffer, midi, bypassParam->load() >= 0.5f);
}

void AlignAudioProcessor::render (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi,
                                  bool bypassed)
{
    juce::ScopedNoDenormals noDenormals;
    juce::ignoreUnused (midi);
    const int numSamples = buffer.getNumSamples();

    auto mainBus = getBusBuffer (buffer, true, 0);
    auto outBus = getBusBuffer (buffer, false, 0);
    for (int ch = mainBus.getNumChannels(); ch < outBus.getNumChannels(); ++ch)
    {
        if (mainBus.getNumChannels() > 0)
            outBus.copyFrom (ch, 0, outBus, 0, 0, numSamples);   // a mono input reaches both sides
        else
            outBus.clear (ch, 0, numSamples);
    }
    if (numSamples == 0)   // a zero-length block is legal (harness contract, D.5.1)
        return;

    const auto params = currentParams();
    engine.setParams (params);
    if (engine.latencySamples() != reportedLatency)
    {
        // Window changed: the host re-measures. Delay never gets here (G1 decision 6), and the
        // manual says to set Window before recording automation.
        reportedLatency = engine.latencySamples();
        setLatencySamples (reportedLatency);
    }

    // the sidechain view only when the buffer really carries its channels (a host or a tool that
    // hands over fewer must not make us read past the channel array)
    const bool sideFits = getBusCount (true) > 1 && getChannelCountOfBus (true, 1) > 0
                       && buffer.getNumChannels() >= getChannelIndexInProcessBlockBuffer (true, 1, 0) + getChannelCountOfBus (true, 1);
    auto sideBus = sideFits ? getBusBuffer (buffer, true, 1) : juce::AudioBuffer<float>();
    const bool haveSide = sideBus.getNumChannels() > 0 && sideBus.getNumSamples() >= numSamples;
    const float* sidePointers[2] { nullptr, nullptr };
    if (haveSide)
        for (int ch = 0; ch < 2; ++ch)
            sidePointers[ch] = sideBus.getReadPointer (juce::jmin (ch, sideBus.getNumChannels() - 1));

    float* mainPointers[2] { nullptr, nullptr };
    const int channels = juce::jlimit (1, 2, outBus.getNumChannels());
    for (int ch = 0; ch < channels; ++ch)
        mainPointers[ch] = outBus.getWritePointer (ch);

    // the reference is "connected" when the bus exists and carries something above -90 dBFS
    if (haveSide)
    {
        float m = 0.0f;
        for (int ch = 0; ch < sideBus.getNumChannels(); ++ch)
            m = juce::jmax (m, sideBus.getMagnitude (ch, 0, numSamples));
        if (m > 3.2e-5f)
            sidechainActive.store (true, std::memory_order_relaxed);
    }
    else
    {
        sidechainActive.store (false, std::memory_order_relaxed);
    }

    // the Sum well's "before" needs the input as it was; the displays run in real time only, while
    // an editor watches, and skip a block larger than announced rather than allocate (rule 1)
    const auto mode = oberli::render::modeFor (*this);
    const bool feed = mode.feedDisplay && numSamples <= displayScratch.getNumSamples();
    const bool watch = feed && displaysActive.load (std::memory_order_relaxed);
    if (feed)
    {
        auto* inMono = displayScratch.getWritePointer (0);
        for (int i = 0; i < numSamples; ++i)
            inMono[i] = channels > 1 ? 0.5f * (mainPointers[0][i] + mainPointers[1][i]) : mainPointers[0][i];
    }

    engine.process (mainPointers, haveSide ? sidePointers : nullptr, channels, numSamples, bypassed);
    scheduleTrack (numSamples);

    // meters and displays, taken after everything so they tell the truth (F.9, stage order)
    if (feed)
    {
        peaks.push (outBus, 0, numSamples);
        auto* inMono = displayScratch.getWritePointer (0);    // the input; then the late reference
        auto* before = displayScratch.getWritePointer (1);
        auto* after = displayScratch.getWritePointer (2);
        auto* outMono = displayScratch.getWritePointer (3);
        const int size = (int) referenceDelay.size();
        const int lag = juce::jlimit (0, size - 1, reportedLatency);
        for (int i = 0; i < numSamples; ++i)
        {
            const float ref = haveSide ? 0.5f * (sidePointers[0][i] + sidePointers[1][i]) : 0.0f;
            const float out = channels > 1 ? 0.5f * (mainPointers[0][i] + mainPointers[1][i]) : mainPointers[0][i];
            referenceWrite = referenceWrite + 1 >= size ? 0 : referenceWrite + 1;
            referenceDelay[(size_t) referenceWrite] = ref;
            int at = referenceWrite - lag;
            if (at < 0)
                at += size;
            // the reference as the host plays it beside this track: delayed by the reported latency
            const float refLate = referenceDelay[(size_t) at];
            before[i] = 0.5f * (inMono[i] + ref);
            after[i] = 0.5f * (out + refLate);
            outMono[i] = out;
            inMono[i] = refLate;
        }
        float* pair[2] { outMono, inMono };
        correlationTap.push (juce::AudioBuffer<float> (pair, 2, numSamples), 0, numSamples);
        if (watch)
        {
            float* b[1] { before };
            float* a[1] { after };
            beforeAnalyser.push (juce::AudioBuffer<float> (b, 1, numSamples), 0, numSamples);
            afterAnalyser.push (juce::AudioBuffer<float> (a, 1, numSamples), 0, numSamples);
        }
    }
}

//==============================================================================
void AlignAudioProcessor::parameterChanged (const juce::String& id, float value)
{
    // called on whichever thread moved the parameter, the audio thread included: one relaxed store
    if (id == Params::detect && value >= 0.5f)
        requestDetect();
}

void AlignAudioProcessor::scheduleTrack (int numSamples) noexcept
{
    // audio time, not wall time: the estimate falls at the first block boundary after every
    // kTrackIntervalMs of audio, the first one as soon as Track is switched on
    const bool tracking = modeParam != nullptr && modeParam->load() >= 0.5f;
    const bool held = holdParam != nullptr && holdParam->load() >= 0.5f;
    if (! tracking || held)
    {
        samplesToNextTrack = 0;
        trackRequested.store (false, std::memory_order_relaxed);
        return;
    }
    samplesToNextTrack -= numSamples;
    if (samplesToNextTrack > 0)
        return;
    samplesToNextTrack = juce::jmax ((juce::int64) 1, samplesToNextTrack + trackIntervalSamples);
    if (isNonRealtime())
    {
        // offline: here and now, so a bounce is reproducible (rule 8). Allocation- and lock-free.
        if (tryClaimAnalysis())
        {
            runDetectOnce (true);
            releaseAnalysis();
        }
    }
    else
    {
        trackRequested.store (true, std::memory_order_release);
    }
}

void AlignAudioProcessor::runDetectOnce (bool tracking)
{
    auto& inRing = engine.inputRing();
    auto& refRing = engine.referenceRing();
    if (! inRing.enoughForDetect() || frameRef.empty())
        return;

    const double analysisRate = inRing.rate();
    const int wanted = tracking ? (int) (kTrackFrameSeconds * analysisRate) : (int) frameRef.size();
    const int n = juce::jmin (refRing.snapshot (frameRef.data(), wanted),
                              inRing.snapshot (frameIn.data(), wanted));
    if (n < 16)
        return;

    float loMs = 0.0f, hiMs = 0.0f;
    const float windowMs = align::dsp::AlignEngine::kWindowMs[
        juce::jlimit (0, align::dsp::AlignEngine::kNumWindows - 1,
                      (int) std::lround (windowParam->load()))];
    if (tracking)
    {
        // Track searches a narrow range around the delay in use, and never touches Polarity: a
        // polarity change mid-take is always wrong (sketch 4.3). The rings hold the input before
        // the delay, so the detector answers in absolute Delay, and so is the range asked for;
        // only the offset handed to the engine is relative to the parameter.
        const float base = delayParam->load() + trackOffset.load (std::memory_order_relaxed);
        loMs = juce::jmax (-windowMs, base - kTrackSearchMs);
        hiMs = juce::jmin (align::dsp::AlignEngine::kDelayMaxMs, base + kTrackSearchMs);
        loMs = juce::jmin (loMs, hiMs - 0.1f);
    }
    else
    {
        align::dsp::Detector::searchRangeMs (windowMs, loMs, hiMs);
    }

    const auto result = detector.detect (frameRef.data(), frameIn.data(), n, loMs, hiMs, ! tracking);
    if (! result.ok)
    {
        if (! tracking)
        {
            const juce::ScopedLock lock (resultLock);
            publishedResult = result;
            resultSequence.fetch_add (1, std::memory_order_release);
        }
        return;
    }

    if (tracking)
    {
        const float tau = std::exp (-kTrackIntervalMs / kTrackTauMs);
        const float target = result.delayMs - delayParam->load();
        const float now = trackOffset.load (std::memory_order_relaxed);
        trackOffset.store (target + tau * (now - target), std::memory_order_relaxed);
        return;
    }

    {
        const juce::ScopedLock lock (resultLock);
        publishedResult = result;
    }
    pendingApply.store (true, std::memory_order_release);
    resultSequence.fetch_add (1, std::memory_order_release);
    triggerAsyncUpdate();
}

align::dsp::Detector::Result AlignAudioProcessor::lastDetect() const
{
    const juce::ScopedLock lock (resultLock);
    return publishedResult;
}

void AlignAudioProcessor::handleAsyncUpdate() { applyPendingDetect(); }

void AlignAudioProcessor::applyPendingDetect()
{
    if (! pendingApply.exchange (false, std::memory_order_acquire))
        return;
    align::dsp::Detector::Result result;
    {
        const juce::ScopedLock lock (resultLock);
        result = publishedResult;
    }
    if (! result.ok)
        return;

    auto* delayP = apvts.getParameter (Params::delay);
    auto* polarityP = apvts.getParameter (Params::polarity);
    if (delayP == nullptr || polarityP == nullptr)
        return;

    // one host edit for both, so a single undo step takes the alignment back (sketch 4.2)
    const float windowMs = align::dsp::AlignEngine::kWindowMs[
        juce::jlimit (0, align::dsp::AlignEngine::kNumWindows - 1,
                      (int) std::lround (windowParam->load()))];
    const float wanted = juce::jlimit (-windowMs, align::dsp::AlignEngine::kDelayMaxMs, result.delayMs);
    delayP->beginChangeGesture();
    delayP->setValueNotifyingHost (delayP->convertTo0to1 (wanted));
    delayP->endChangeGesture();
    polarityP->beginChangeGesture();
    polarityP->setValueNotifyingHost (result.inverted ? 1.0f : 0.0f);
    polarityP->endChangeGesture();

    // the momentary Detect parameter falls back to off, so the next press is a fresh 0 -> 1
    if (auto* detectP = apvts.getParameter (Params::detect))
        if (detectP->getValue() >= 0.5f)
            detectP->setValueNotifyingHost (0.0f);
}

void AlignAudioProcessor::applyRotateSuggestion()
{
    const auto result = lastDetect();
    if (! result.ok || ! result.suggestion.needed)
        return;
    auto* rotateP = apvts.getParameter (Params::rotate);
    auto* belowP = apvts.getParameter (Params::below);
    if (rotateP == nullptr || belowP == nullptr)
        return;
    rotateP->beginChangeGesture();
    rotateP->setValueNotifyingHost (rotateP->convertTo0to1 (result.suggestion.rotateDeg));
    rotateP->endChangeGesture();
    belowP->beginChangeGesture();
    belowP->setValueNotifyingHost (belowP->convertTo0to1 (result.suggestion.belowHz));
    belowP->endChangeGesture();
}

bool AlignAudioProcessor::waitForDetect (int sinceSequence, int timeoutMs)
{
    const auto deadline = juce::Time::getMillisecondCounter() + (juce::uint32) juce::jmax (0, timeoutMs);
    while (resultSequence.load (std::memory_order_acquire) <= sinceSequence)
    {
        if (juce::Time::getMillisecondCounter() >= deadline)
            return false;
        juce::Thread::sleep (2);
    }
    return true;
}

//==============================================================================
juce::AudioProcessorEditor* AlignAudioProcessor::createEditor()
{
    return new AlignAudioProcessorEditor (*this);
}

void AlignAudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    auto xml = align::State::toXml (apvts);
    if (auto* extra = xml->getChildByName ("Extra"); extra != nullptr && presets->activeId().isNotEmpty())
        extra->setAttribute ("preset", presets->activeId());   // which preset the sound came from, for the header
    copyXmlToBinary (*xml, destData);
}

void AlignAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    loadState (data, sizeInBytes);
}

bool AlignAudioProcessor::loadState (const void* data, int sizeInBytes)
{
    // arbitrary bytes are refused, never crashed on (D.5.3): a foreign or newer blob leaves the
    // state as it is
    if (data == nullptr || sizeInBytes <= 0)
        return false;
    auto xml = getXmlFromBinary (data, sizeInBytes);
    if (xml == nullptr)
        return false;
    auto* state = align::State::stateOf (*xml);
    if (state == nullptr || ! align::State::fromXml (*state, apvts))
        return false;
    const auto* extra = state->getChildByName ("Extra");
    presets->restoreActive (extra != nullptr ? extra->getStringAttribute ("preset") : juce::String());
    return true;
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new AlignAudioProcessor();
}
