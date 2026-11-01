/*  {{ProductId}}Harness - the offline renderer of the harness contract (scripts/dsp-kit/harness-contract.md, v3).

    Links the real plugin sources, renders without a host, an audio device or the editor, and prints
    one JSON object on stdout; diagnostics go to stderr. `dspkit.render()`, the test suite
    (tools/tests/test_plugin.py), presetlint.py, perf.py and paramgen.py check drive it. The
    template's harness is generic over juce::AudioProcessor: product-specific flags (`--solo`) and
    metrics (the `product` object) are the two TODO hooks at the end of this file. Horizon Pad's
    sound tool (tools/sound_tool/Main.cpp there) is the reference implementation with a product's
    descriptors added.

    Usage: {{ProductId}}Harness --help

    Exit codes: 0 rendered; 2 a flag or value was refused (message on stderr); 3 the render produced
    NaN or Inf (the JSON is still printed). */

#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

#include "PluginProcessor.h"
#include "State.h"
#include "BuildInfo.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <random>
#include <vector>

//==============================================================================
// Real-time safety (rule 1, D.1.6). With PRODUCT_RTSAN (the rtsan preset, LLVM 20+) every
// processBlock runs inside a [[clang::nonblocking]] function: any allocation, lock or system call
// aborts with a stack trace. PRODUCT_RTSAN_SELFTEST=1 allocates once inside and must abort (the
// check is live). In every other macOS build the malloc trap below is the Tier P check.
#if defined(__has_feature)
 #if __has_feature(realtime_sanitizer)
  #define PRODUCT_NONBLOCKING [[clang::nonblocking]]
  #define PRODUCT_HAS_RTSAN 1
 #endif
#endif
#ifndef PRODUCT_NONBLOCKING
 #define PRODUCT_NONBLOCKING
 #define PRODUCT_HAS_RTSAN 0
#endif

#if PRODUCT_HAS_RTSAN
static const bool rtsanSelfTest = std::getenv ("PRODUCT_RTSAN_SELFTEST") != nullptr;
static void* volatile rtsanSelfTestSink = nullptr;
static void rtsanSelfTestAllocation() { rtsanSelfTestSink = std::malloc (64); std::free (rtsanSelfTestSink); }
#endif

// The malloc trap: this executable defines malloc, calloc, realloc, posix_memalign and operator
// new/delete, forwarding to the default zone; an allocation by the thread inside processBlock
// aborts the run. The plugin and JUCE are linked statically, so their calls bind here.
// PRODUCT_MALLOC_TRAP=0 switches it off, PRODUCT_MALLOC_TRAP_SELFTEST=1 allocates once inside the
// armed region and must abort. It misses locks, system calls, page faults and unbounded loops.
#if JUCE_MAC && ! PRODUCT_HAS_RTSAN
 #include <malloc/malloc.h>
 #include <pthread.h>
 #include <unistd.h>
 #include <cerrno>

namespace mallocTrap
{
    static std::atomic<bool> armed { false };
    static pthread_t owner;

    [[noreturn]] static void trip (const char* what) noexcept
    {
        armed.store (false);
        static const char prefix[] = "malloc trap: ";
        static const char suffix[] = " inside processBlock (rule 1: no allocation on the audio thread)\n";
        ::write (2, prefix, sizeof (prefix) - 1);
        ::write (2, what, std::strlen (what));
        ::write (2, suffix, sizeof (suffix) - 1);
        std::abort();
    }
    static inline void check (const char* what) noexcept
    {
        if (armed.load (std::memory_order_relaxed) && pthread_equal (pthread_self(), owner))
            trip (what);
    }
    static bool enabled() { const char* v = std::getenv ("PRODUCT_MALLOC_TRAP"); return v == nullptr || std::strcmp (v, "0") != 0; }
    static const bool selfTest = std::getenv ("PRODUCT_MALLOC_TRAP_SELFTEST") != nullptr;
    static void* volatile selfTestSink = nullptr;
}

extern "C"
{
    void* malloc (size_t n)            { mallocTrap::check ("malloc");  return malloc_zone_malloc (malloc_default_zone(), n); }
    void* calloc (size_t c, size_t n)  { mallocTrap::check ("calloc");  return malloc_zone_calloc (malloc_default_zone(), c, n); }
    void* realloc (void* p, size_t n)  { mallocTrap::check ("realloc"); return malloc_zone_realloc (malloc_default_zone(), p, n); }
    int posix_memalign (void** out, size_t alignment, size_t n)
    {
        mallocTrap::check ("posix_memalign");
        *out = malloc_zone_memalign (malloc_default_zone(), alignment, n);
        return *out != nullptr ? 0 : ENOMEM;
    }
}
void* operator new (size_t n)                  { mallocTrap::check ("operator new");   if (auto* p = malloc_zone_malloc (malloc_default_zone(), n ? n : 1)) return p; throw std::bad_alloc(); }
void* operator new[] (size_t n)                { mallocTrap::check ("operator new[]"); if (auto* p = malloc_zone_malloc (malloc_default_zone(), n ? n : 1)) return p; throw std::bad_alloc(); }
void* operator new (size_t n, const std::nothrow_t&) noexcept   { mallocTrap::check ("operator new");   return malloc_zone_malloc (malloc_default_zone(), n ? n : 1); }
void* operator new[] (size_t n, const std::nothrow_t&) noexcept { mallocTrap::check ("operator new[]"); return malloc_zone_malloc (malloc_default_zone(), n ? n : 1); }
void operator delete (void* p) noexcept                { std::free (p); }
void operator delete[] (void* p) noexcept              { std::free (p); }
void operator delete (void* p, size_t) noexcept        { std::free (p); }
void operator delete[] (void* p, size_t) noexcept      { std::free (p); }
#endif

static void processBlockRealtime (juce::AudioProcessor& processor, juce::AudioBuffer<float>& block, juce::MidiBuffer& midi) PRODUCT_NONBLOCKING
{
   #if PRODUCT_HAS_RTSAN
    if (rtsanSelfTest)
        rtsanSelfTestAllocation();
   #endif
   #if JUCE_MAC && ! PRODUCT_HAS_RTSAN
    static const bool trapOn = mallocTrap::enabled();
    if (trapOn)
    {
        mallocTrap::owner = pthread_self();
        mallocTrap::armed.store (true, std::memory_order_relaxed);
        if (mallocTrap::selfTest)
            mallocTrap::selfTestSink = std::malloc (64);
        processor.processBlock (block, midi);
        mallocTrap::armed.store (false, std::memory_order_relaxed);
        return;
    }
   #endif
    processor.processBlock (block, midi);
}

//==============================================================================
namespace
{
using Clock = std::chrono::steady_clock;

const char* const kUsage =
    "{{ProductId}}Harness - offline renderer (harness contract v3)\n"
    "  --seed=<int>                 seeds every random source (default 1)\n"
    "  --sample-rate=<Hz>           default 48000\n"
    "  --block=<n>|random:<seed>    block size, or random sizes from 0 to --max-block (default 512)\n"
    "  --max-block=<n>              size announced to prepareToPlay (default = --block)\n"
    "  --seconds=<s>                render length (default 2)\n"
    "  --preset=<slug>              a factory preset from presets/ (FACTORY_PRESETS overrides the folder)\n"
    "  --param=<id>=<0..1>          normalised value by ID, repeatable, in order\n"
    "  --automate=<id>:<t0>=<v0>,<t1>=<v1>,...   linear ramp, once per block; repeatable\n"
    "  --notes=<n>[,<n>...]         instruments: a chord from t = 0;  --midi=<file.mid> a MIDI file\n"
    "  --gate=<s>                   instruments: note-off at t seconds (default: held to the end)\n"
    "  --bend=<t>:<v>[,...]  --mod=<t>:<v>[,...]   pitch wheel (-1..1) and mod wheel (0..1) at t\n"
    "  --in=<file.wav> | --signal=impulse|logsweep|sine:<Hz>:<dBFS>|noise:pink:<dBFS>|silence   effects: the input\n"
    "  --out=<file.wav>             write the output (float32)\n"
    "  --state-in=<file> --state-out=<file>   plugin state (any bytes in; a refused blob exits 2)\n"
    "  --reprepare-at=<t>:<rate>/<block>      prepareToPlay again mid-render; repeatable\n"
    "  --preset-at=<t>:<slug>       load a factory preset at t seconds; repeatable\n"
    "  --profile --warmup=<n>       time every processBlock; exclude n blocks from the distribution\n"
    "  --solo=<part>                product-specific isolation (see the hooks at the end of Main.cpp)\n"
    "  --list-params | --list-presets   JSON lists; exit\n";

struct Args
{
    std::map<juce::String, juce::StringArray> values;   // repeatable flags keep every value
    bool has (const juce::String& k) const { return values.count (k) > 0; }
    juce::String get (const juce::String& k, const juce::String& def = {}) const
    {
        auto it = values.find (k);
        return it == values.end() || it->second.isEmpty() ? def : it->second[it->second.size() - 1];
    }
    juce::StringArray all (const juce::String& k) const { auto it = values.find (k); return it == values.end() ? juce::StringArray() : it->second; }
};

[[noreturn]] void refuse (const juce::String& msg)
{
    std::cerr << "error: " << msg << std::endl;
    std::exit (2);
}

Args parseArgs (int argc, char* argv[])
{
    static const juce::StringArray known { "help", "seed", "sample-rate", "block", "max-block", "seconds", "preset", "param",
        "automate", "bend", "mod", "notes", "midi", "gate", "reprepare-at", "in", "signal", "out", "state-in", "state-out",
        "profile", "preset-at", "warmup", "solo", "list-params", "list-presets" };
    Args a;
    for (int i = 1; i < argc; ++i)
    {
        juce::String s (argv[i]);
        if (! s.startsWith ("--"))
            refuse ("unexpected argument " + s);
        s = s.substring (2);
        const auto key = s.upToFirstOccurrenceOf ("=", false, false);
        const auto val = s.contains ("=") ? s.fromFirstOccurrenceOf ("=", false, false) : juce::String();
        if (! known.contains (key))
            refuse ("unknown flag --" + key + " (--help)");
        a.values[key].add (val);
    }
    return a;
}

double numberOr (const juce::String& s, const char* what)
{
    if (s.isEmpty() || ! s.containsOnly ("0123456789.-+eE"))
        refuse (juce::String (what) + ": not a number: " + s);
    return s.getDoubleValue();
}

//------------------------------------------------------------------------------ presets
juce::File factoryFolder()
{
    if (const char* env = std::getenv ("FACTORY_PRESETS"))
        return juce::File (juce::String (env));
    return juce::File::getCurrentWorkingDirectory().getChildFile ("presets");
}

juce::File presetsCsv()
{
    if (const char* env = std::getenv ("PRESETS_CSV"))
        return juce::File (juce::String (env));
    auto beside = factoryFolder().getSiblingFile ("presets.csv");
    return beside.existsAsFile() ? beside : juce::File::getCurrentWorkingDirectory().getChildFile ("presets.csv");
}

struct PresetRow { juce::String slug, name, category; };

std::vector<PresetRow> presetRows()
{
    std::vector<PresetRow> rows;
    juce::StringArray lines;
    presetsCsv().readLines (lines);
    bool header = true;
    for (auto& line : lines)
    {
        if (line.trim().isEmpty()) continue;
        if (header) { header = false; continue; }
        auto cells = juce::StringArray::fromTokens (line, ",", "\"");
        if (cells.size() >= 3)
            rows.push_back ({ cells[0].trim(), cells[1].trim().unquoted(), cells[2].trim() });
    }
    return rows;
}

bool loadPreset (juce::AudioProcessorValueTreeState& apvts, const juce::String& slug)
{
    auto file = factoryFolder().getChildFile (slug + {{bundle}}::State::kPresetExtension);
    if (! file.existsAsFile())
        return false;
    auto xml = juce::XmlDocument::parse (file);
    if (xml == nullptr)
        return false;
    auto* state = {{bundle}}::State::stateOf (*xml);
    return state != nullptr && {{bundle}}::State::fromXml (*state, apvts);
}

//------------------------------------------------------------------------------ signals
struct Signal
{
    juce::String kind = "silence";
    double hz = 1000.0, dbfs = -12.0;
    juce::AudioBuffer<float> file;   // --in
    double phase = 0.0;
    std::mt19937 rng { 1 };
    float pinkB0 = 0, pinkB1 = 0, pinkB2 = 0;

    void fill (juce::AudioBuffer<float>& out, juce::int64 startSample, double rate)
    {
        const int n = out.getNumSamples();
        out.clear();
        if (kind == "file")
        {
            for (int ch = 0; ch < out.getNumChannels(); ++ch)
            {
                const int src = juce::jmin (ch, file.getNumChannels() - 1);
                for (int i = 0; i < n; ++i)
                {
                    const juce::int64 at = startSample + i;
                    out.setSample (ch, i, at < file.getNumSamples() && src >= 0 ? file.getSample (src, (int) at) : 0.0f);
                }
            }
            return;
        }
        const float gain = (float) juce::Decibels::decibelsToGain (dbfs);
        std::uniform_real_distribution<float> uni (-1.0f, 1.0f);
        for (int i = 0; i < n; ++i)
        {
            const juce::int64 at = startSample + i;
            float v = 0.0f;
            if (kind == "impulse")       v = at == 0 ? 1.0f : 0.0f;
            else if (kind == "sine")     { v = gain * (float) std::sin (phase); phase += juce::MathConstants<double>::twoPi * hz / rate; if (phase > juce::MathConstants<double>::twoPi) phase -= juce::MathConstants<double>::twoPi; }
            else if (kind == "logsweep")
            {
                const double len = 2.0, f0 = 20.0, f1 = 20000.0, t = (double) at / rate;
                if (t < len)
                {
                    const double k = std::log (f1 / f0);
                    v = (float) (0.5 * std::sin (juce::MathConstants<double>::twoPi * f0 * len / k * (std::exp (t * k / len) - 1.0)));
                }
            }
            else if (kind == "noise")
            {
                const float w = uni (rng);   // Paul Kellet's pink approximation
                pinkB0 = 0.99765f * pinkB0 + w * 0.0990460f;
                pinkB1 = 0.96300f * pinkB1 + w * 0.2965164f;
                pinkB2 = 0.57000f * pinkB2 + w * 1.0526913f;
                v = gain * 0.18f * (pinkB0 + pinkB1 + pinkB2 + w * 0.1848f);
            }
            for (int ch = 0; ch < out.getNumChannels(); ++ch)
                out.setSample (ch, i, v);
        }
    }
};

//------------------------------------------------------------------------------ events
struct TimedValue { double t; double v; };

std::vector<TimedValue> parseTimedList (const juce::String& spec, const char* what)
{
    std::vector<TimedValue> out;
    for (auto item : juce::StringArray::fromTokens (spec, ",", ""))
    {
        item = item.trim();
        if (item.isEmpty()) continue;
        if (! item.contains (":")) refuse (juce::String (what) + ": need <t>:<v>, got " + item);
        out.push_back ({ numberOr (item.upToFirstOccurrenceOf (":", false, false), what), numberOr (item.fromFirstOccurrenceOf (":", false, false), what) });
    }
    std::sort (out.begin(), out.end(), [] (auto& x, auto& y) { return x.t < y.t; });
    return out;
}

struct Ramp { juce::String id; std::vector<TimedValue> points; };

double rampValue (const Ramp& r, double t)
{
    const auto& p = r.points;
    if (t <= p.front().t) return p.front().v;
    if (t >= p.back().t) return p.back().v;
    for (size_t i = 1; i < p.size(); ++i)
        if (t <= p[i].t)
        {
            const double span = p[i].t - p[i - 1].t;
            const double f = span > 0.0 ? (t - p[i - 1].t) / span : 1.0;
            return p[i - 1].v + f * (p[i].v - p[i - 1].v);
        }
    return p.back().v;
}

//------------------------------------------------------------------------------ metrics
struct Biquad
{
    double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0, x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    double process (double x) noexcept { const double y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x; y2 = y1; y1 = y; return y; }
};

void makeKWeighting (double rate, Biquad& shelf, Biquad& hp)   // ITU-R BS.1770-4, coefficients per rate (libebur128 derivation)
{
    {
        const double f0 = 1681.974450955533, G = 3.999843853973347, Q = 0.7071752369554196;
        const double K = std::tan (juce::MathConstants<double>::pi * f0 / rate);
        const double Vh = std::pow (10.0, G / 20.0), Vb = std::pow (Vh, 0.4996667741545416), a0 = 1.0 + K / Q + K * K;
        shelf.b0 = (Vh + Vb * K / Q + K * K) / a0; shelf.b1 = 2.0 * (K * K - Vh) / a0; shelf.b2 = (Vh - Vb * K / Q + K * K) / a0;
        shelf.a1 = 2.0 * (K * K - 1.0) / a0; shelf.a2 = (1.0 - K / Q + K * K) / a0;
    }
    {
        const double f0 = 38.13547087602444, Q = 0.5003270373238773;
        const double K = std::tan (juce::MathConstants<double>::pi * f0 / rate), a0 = 1.0 + K / Q + K * K;
        hp.b0 = 1.0; hp.b1 = -2.0; hp.b2 = 1.0; hp.a1 = 2.0 * (K * K - 1.0) / a0; hp.a2 = (1.0 - K / Q + K * K) / a0;
    }
}

struct Loudness { double integrated = -300.0, momentaryMax = -300.0; };

Loudness measureLoudness (const juce::AudioBuffer<float>& b, double rate)
{
    Loudness r;
    const int numCh = juce::jmin (2, b.getNumChannels()), total = b.getNumSamples();
    const int blockSamples = (int) std::round (0.4 * rate), hop = (int) std::round (0.1 * rate);
    if (numCh < 1 || total < blockSamples || hop < 1) return r;
    std::vector<std::vector<double>> w ((size_t) numCh, std::vector<double> ((size_t) total));
    for (int ch = 0; ch < numCh; ++ch)
    {
        Biquad shelf, hp; makeKWeighting (rate, shelf, hp);
        const auto* d = b.getReadPointer (ch);
        for (int n = 0; n < total; ++n) w[(size_t) ch][(size_t) n] = hp.process (shelf.process ((double) d[n]));
    }
    const auto toLufs = [] (double p) { return p > 0.0 ? -0.691 + 10.0 * std::log10 (p) : -300.0; };
    std::vector<double> power;
    for (int start = 0; start + blockSamples <= total; start += hop)
    {
        double sum = 0.0;
        for (int ch = 0; ch < numCh; ++ch)
        {
            double ss = 0.0;
            for (int n = start; n < start + blockSamples; ++n) ss += w[(size_t) ch][(size_t) n] * w[(size_t) ch][(size_t) n];
            sum += ss / (double) blockSamples;
        }
        power.push_back (sum);
        r.momentaryMax = juce::jmax (r.momentaryMax, toLufs (sum));
    }
    const auto mean = [] (const std::vector<double>& v) { double s = 0; for (auto x : v) s += x; return v.empty() ? 0.0 : s / (double) v.size(); };
    std::vector<double> p1; for (auto p : power) if (toLufs (p) > -70.0) p1.push_back (p);
    if (p1.empty()) return r;
    const double rel = toLufs (mean (p1)) - 10.0;
    std::vector<double> p2; for (auto p : p1) if (toLufs (p) > rel) p2.push_back (p);
    if (! p2.empty()) r.integrated = toLufs (mean (p2));
    return r;
}

double truePeak (const juce::AudioBuffer<float>& b)   // 4x windowed-sinc (BS.1770 Annex 2)
{
    double tp = 0.0;
    const int up = b.getNumSamples() * 4;
    if (up <= 0) return tp;
    std::vector<float> buf ((size_t) up, 0.0f);
    for (int ch = 0; ch < b.getNumChannels(); ++ch)
    {
        juce::Interpolators::WindowedSinc interp; interp.reset();
        interp.process (0.25, b.getReadPointer (ch), buf.data(), up);
        for (auto v : buf) tp = juce::jmax (tp, (double) std::abs (v));
    }
    return tp;
}

double percentile (std::vector<double> v, double q)
{
    if (v.empty()) return 0.0;
    std::sort (v.begin(), v.end());
    const double idx = q * (double) (v.size() - 1);
    const size_t lo = (size_t) std::floor (idx), hi = juce::jmin (v.size() - 1, lo + 1);
    return v[lo] + (idx - (double) lo) * (v[hi] - v[lo]);
}

juce::var obj() { return juce::var (new juce::DynamicObject()); }
void set (juce::var& o, const char* k, juce::var v) { o.getDynamicObject()->setProperty (k, v); }
double dbOf (double lin) { return lin > 0.0 ? 20.0 * std::log10 (lin) : -300.0; }
} // namespace

//==============================================================================
// Product hooks (the two TODOs of the contract). The skeleton has no solo parts and no product
// metrics; a product fills these in beside its DSP (Horizon Pad: layers, keyboard, mix pocket).
static bool applySolo (juce::AudioProcessor&, const juce::String& part)
{
    juce::ignoreUnused (part);
    return false;   // unknown part: refused with exit 2
}

static juce::var productMetrics (const juce::AudioBuffer<float>&, double)
{
    return obj();
}

//==============================================================================
static int run (int argc, char* argv[])
{
    const Args args = parseArgs (argc, argv);
    if (args.has ("help")) { std::cout << kUsage; return 0; }

    juce::ScopedJuceInitialiser_GUI juceInit;   // the processor may touch message-thread objects at construction
    std::unique_ptr<juce::AudioProcessor> processor (createPluginFilter());
    auto* product = dynamic_cast<{{ProductId}}AudioProcessor*> (processor.get());
    if (product == nullptr) refuse ("createPluginFilter() did not return the product's processor");
    auto& apvts = product->parameters();

    if (args.has ("list-presets"))
    {
        juce::var list;
        for (const auto& r : presetRows()) { auto o = obj(); set (o, "slug", r.slug); set (o, "name", r.name); set (o, "category", r.category); list.append (o); }
        std::cout << juce::JSON::toString (list, true) << std::endl;
        return 0;
    }
    if (args.has ("list-params"))
    {
        juce::var list;
        for (auto* p : processor->getParameters())
            if (auto* ranged = dynamic_cast<juce::RangedAudioParameter*> (p))
            {
                auto o = obj();
                set (o, "id", ranged->paramID);
                set (o, "default", (double) ranged->getDefaultValue());
                set (o, "steps", ranged->isDiscrete() ? ranged->getNumSteps() : 0);
                set (o, "automatable", ranged->isAutomatable());
                list.append (o);
            }
        std::cout << juce::JSON::toString (list, true) << std::endl;
        return 0;
    }

    // -------- configuration
    const int seed = (int) numberOr (args.get ("seed", "1"), "--seed");
    double rate = numberOr (args.get ("sample-rate", "48000"), "--sample-rate");
    const juce::String blockArg = args.get ("block", "512");
    const bool randomBlocks = blockArg.startsWith ("random:");
    int block = randomBlocks ? 0 : (int) numberOr (blockArg, "--block");
    int maxBlock = args.has ("max-block") ? (int) numberOr (args.get ("max-block"), "--max-block") : (randomBlocks ? 512 : block);
    if (randomBlocks && ! args.has ("max-block")) maxBlock = 512;
    if (rate <= 0 || (! randomBlocks && block <= 0) || maxBlock <= 0) refuse ("--sample-rate, --block and --max-block must be positive (or --block=random:<seed>)");
    const double seconds = numberOr (args.get ("seconds", "2"), "--seconds");
    if (seconds <= 0) refuse ("--seconds must be positive");
    std::mt19937 blockRng ((unsigned) (randomBlocks ? numberOr (blockArg.fromFirstOccurrenceOf (":", false, false), "--block=random") : 0));

    const bool isInstrument = PRODUCT_IS_INSTRUMENT != 0;
    const int inChannels = isInstrument ? 0 : 2;
    juce::AudioProcessor::BusesLayout layout;
    if (! isInstrument) layout.inputBuses.add (juce::AudioChannelSet::stereo());
    layout.outputBuses.add (juce::AudioChannelSet::stereo());
    if (! processor->setBusesLayout (layout)) refuse ("the processor refuses the stereo layout");
    processor->setNonRealtime (false);
    processor->prepareToPlay (rate, maxBlock);

    // -------- state in
    juce::String stateRefused;
    if (args.has ("state-in"))
    {
        auto file = juce::File::getCurrentWorkingDirectory().getChildFile (args.get ("state-in"));
        juce::MemoryBlock bytes;
        if (! file.loadFileAsData (bytes)) refuse ("cannot read --state-in " + file.getFullPathName());
        if (! product->loadState (bytes.getData(), (int) bytes.getSize()))
            stateRefused = "not a state of this plugin (" + juce::String ((int) bytes.getSize()) + " bytes); the plugin keeps processing with its state unchanged";
    }

    // -------- preset, solo, params, automation (in that order, each overriding the previous)
    juce::String presetName;
    if (args.has ("preset"))
    {
        presetName = args.get ("preset");
        if (! loadPreset (apvts, presetName)) refuse ("no factory preset " + presetName + " in " + factoryFolder().getFullPathName() + " (see --list-presets)");
    }
    juce::String solo;
    if (args.has ("solo"))
    {
        solo = args.get ("solo");
        if (! applySolo (*processor, solo)) refuse ("--solo=" + solo + ": this product has no such part");
    }
    auto paramById = [&] (const juce::String& id) -> juce::RangedAudioParameter*
    {
        auto* p = apvts.getParameter (id);
        if (p == nullptr) refuse ("unknown parameter id " + id + " (see --list-params)");
        return p;
    };
    for (auto spec : args.all ("param"))
    {
        if (! spec.contains ("=")) refuse ("--param needs <id>=<value>: " + spec);
        auto* p = paramById (spec.upToFirstOccurrenceOf ("=", false, false));
        const double v = numberOr (spec.fromFirstOccurrenceOf ("=", false, false), "--param");
        if (v < 0.0 || v > 1.0) refuse ("--param values are normalised 0..1: " + spec);
        p->setValueNotifyingHost ((float) v);
    }
    std::vector<Ramp> ramps;
    for (auto spec : args.all ("automate"))
    {
        if (! spec.contains (":")) refuse ("--automate needs <id>:<t0>=<v0>,...: " + spec);
        Ramp r;
        r.id = spec.upToFirstOccurrenceOf (":", false, false);
        paramById (r.id);
        for (auto pt : juce::StringArray::fromTokens (spec.fromFirstOccurrenceOf (":", false, false), ",", ""))
        {
            if (! pt.contains ("=")) refuse ("--automate point needs <t>=<v>: " + pt);
            r.points.push_back ({ numberOr (pt.upToFirstOccurrenceOf ("=", false, false), "--automate"), numberOr (pt.fromFirstOccurrenceOf ("=", false, false), "--automate") });
        }
        if (r.points.empty()) refuse ("--automate without points: " + spec);
        std::sort (r.points.begin(), r.points.end(), [] (auto& x, auto& y) { return x.t < y.t; });
        ramps.push_back (r);
    }

    // -------- MIDI and input
    std::vector<int> notes;
    for (auto n : juce::StringArray::fromTokens (args.get ("notes"), ",", ""))
        if (n.trim().isNotEmpty()) notes.push_back ((int) numberOr (n.trim(), "--notes"));
    const double gate = args.has ("gate") ? numberOr (args.get ("gate"), "--gate") : -1.0;
    auto bends = parseTimedList (args.get ("bend"), "--bend");
    auto mods = parseTimedList (args.get ("mod"), "--mod");
    juce::MidiMessageSequence midiFile;
    if (args.has ("midi"))
    {
        juce::MidiFile mf;
        juce::FileInputStream in (juce::File::getCurrentWorkingDirectory().getChildFile (args.get ("midi")));
        if (! in.openedOk() || ! mf.readFrom (in)) refuse ("cannot read --midi " + args.get ("midi"));
        mf.convertTimestampTicksToSeconds();
        for (int t = 0; t < mf.getNumTracks(); ++t) midiFile.addSequence (*mf.getTrack (t), 0.0);
        midiFile.updateMatchedPairs();
    }
    Signal signal;
    signal.rng.seed ((unsigned) seed);
    if (args.has ("in"))
    {
        juce::AudioFormatManager fm; fm.registerBasicFormats();
        std::unique_ptr<juce::AudioFormatReader> reader (fm.createReaderFor (juce::File::getCurrentWorkingDirectory().getChildFile (args.get ("in"))));
        if (reader == nullptr) refuse ("cannot read --in " + args.get ("in"));
        signal.kind = "file";
        signal.file.setSize ((int) reader->numChannels, (int) reader->lengthInSamples);
        reader->read (&signal.file, 0, (int) reader->lengthInSamples, 0, true, true);
    }
    else if (args.has ("signal"))
    {
        auto parts = juce::StringArray::fromTokens (args.get ("signal"), ":", "");
        signal.kind = parts[0];
        if (signal.kind == "sine") { if (parts.size() > 1) signal.hz = numberOr (parts[1], "--signal"); if (parts.size() > 2) signal.dbfs = numberOr (parts[2], "--signal"); }
        else if (signal.kind == "noise") { if (parts.size() > 2) signal.dbfs = numberOr (parts[2], "--signal"); }
        else if (signal.kind != "impulse" && signal.kind != "logsweep" && signal.kind != "silence") refuse ("unknown --signal " + args.get ("signal"));
    }
    else if (! isInstrument)
        signal.kind = "impulse";

    // -------- mid-render events
    struct Reprepare { double t; double rate; int block; };
    std::vector<Reprepare> reprepares;
    for (auto spec : args.all ("reprepare-at"))
    {
        if (! spec.contains (":") || ! spec.contains ("/")) refuse ("--reprepare-at needs <t>:<rate>/<block>: " + spec);
        const auto rest = spec.fromFirstOccurrenceOf (":", false, false);
        reprepares.push_back ({ numberOr (spec.upToFirstOccurrenceOf (":", false, false), "--reprepare-at"),
                                numberOr (rest.upToFirstOccurrenceOf ("/", false, false), "--reprepare-at"),
                                (int) numberOr (rest.fromFirstOccurrenceOf ("/", false, false), "--reprepare-at") });
    }
    std::sort (reprepares.begin(), reprepares.end(), [] (auto& x, auto& y) { return x.t < y.t; });
    struct PresetAt { double t; juce::String slug; };
    std::vector<PresetAt> presetAts;
    for (auto spec : args.all ("preset-at"))
    {
        if (! spec.contains (":")) refuse ("--preset-at needs <t>:<slug>: " + spec);
        PresetAt p { numberOr (spec.upToFirstOccurrenceOf (":", false, false), "--preset-at"), spec.fromFirstOccurrenceOf (":", false, false) };
        if (! factoryFolder().getChildFile (p.slug + {{bundle}}::State::kPresetExtension).existsAsFile()) refuse ("--preset-at: no factory preset " + p.slug);
        presetAts.push_back (p);
    }
    std::sort (presetAts.begin(), presetAts.end(), [] (auto& x, auto& y) { return x.t < y.t; });

    // -------- render
    const bool profile = args.has ("profile");
    const int warmup = (int) numberOr (args.get ("warmup", "0"), "--warmup");
    juce::AudioBuffer<float> out (2, 0);
    std::vector<double> blockTimesUs;
    double firstBlockPct = 0.0;
    int blocksRendered = 0, overDeadline = 0;
    double worstUs = 0.0, worstAt = 0.0;
    bool notesOn = false, notesOff = false;
    size_t nextBend = 0, nextMod = 0, nextRe = 0, nextPreset = 0;
    int midiFileIndex = 0;
    juce::int64 pos = 0;
    juce::int64 total = (juce::int64) std::llround (seconds * rate);
    juce::AudioBuffer<float> work (2, maxBlock);
    juce::MidiBuffer midi;

    while (pos < total)
    {
        const double now = (double) pos / rate;
        while (nextRe < reprepares.size() && reprepares[nextRe].t <= now)
        {
            const auto& r = reprepares[nextRe++];
            const double remaining = seconds - now;
            rate = r.rate; maxBlock = r.block; if (! randomBlocks) block = r.block;
            total = pos + (juce::int64) std::llround (remaining * rate);
            work.setSize (2, maxBlock, false, false, true);
            processor->prepareToPlay (rate, maxBlock);   // no releaseResources: pluginval's non-releasing case
        }
        while (nextPreset < presetAts.size() && presetAts[nextPreset].t <= now)
            loadPreset (apvts, presetAts[nextPreset++].slug);

        int n = randomBlocks ? (int) (blockRng() % (unsigned) (maxBlock + 1)) : block;
        n = (int) juce::jmin ((juce::int64) n, total - pos);
        for (const auto& r : ramps)
            paramById (r.id)->setValueNotifyingHost ((float) juce::jlimit (0.0, 1.0, rampValue (r, now)));

        midi.clear();
        if (isInstrument)
        {
            if (! notesOn && ! notes.empty()) { for (int note : notes) midi.addEvent (juce::MidiMessage::noteOn (1, note, 0.8f), 0); notesOn = true; }
            if (gate >= 0.0 && ! notesOff && now + (double) n / rate > gate)
            {
                const int at = juce::jlimit (0, juce::jmax (0, n - 1), (int) std::llround ((gate - now) * rate));
                for (int note : notes) midi.addEvent (juce::MidiMessage::noteOff (1, note), at);
                notesOff = true;
            }
            while (nextBend < bends.size() && bends[nextBend].t < now + (double) n / rate)
            {
                const int at = juce::jlimit (0, juce::jmax (0, n - 1), (int) std::llround ((bends[nextBend].t - now) * rate));
                midi.addEvent (juce::MidiMessage::pitchWheel (1, juce::jlimit (0, 16383, 8192 + (int) std::lround (bends[nextBend].v * 8191.0))), at);
                ++nextBend;
            }
            while (nextMod < mods.size() && mods[nextMod].t < now + (double) n / rate)
            {
                const int at = juce::jlimit (0, juce::jmax (0, n - 1), (int) std::llround ((mods[nextMod].t - now) * rate));
                midi.addEvent (juce::MidiMessage::controllerEvent (1, 1, juce::jlimit (0, 127, (int) std::lround (mods[nextMod].v * 127.0))), at);
                ++nextMod;
            }
            while (midiFileIndex < midiFile.getNumEvents() && midiFile.getEventTime (midiFileIndex) < now + (double) n / rate)
            {
                const auto* ev = midiFile.getEventPointer (midiFileIndex++);
                const int at = juce::jlimit (0, juce::jmax (0, n - 1), (int) std::llround ((ev->message.getTimeStamp() - now) * rate));
                midi.addEvent (ev->message, at);
            }
        }
        juce::AudioBuffer<float> blockBuf (work.getArrayOfWritePointers(), 2, n);
        if (inChannels > 0) signal.fill (blockBuf, pos, rate); else blockBuf.clear();

        const auto t0 = Clock::now();
        processBlockRealtime (*processor, blockBuf, midi);
        const double us = std::chrono::duration<double, std::micro> (Clock::now() - t0).count();
        if (profile)
        {
            const double deadlineUs = 1.0e6 * (double) juce::jmax (1, n) / rate;
            if (blocksRendered == 0) firstBlockPct = 100.0 * us / deadlineUs;
            else if (blocksRendered > warmup)
            {
                blockTimesUs.push_back (100.0 * us / deadlineUs);
                if (us > deadlineUs) ++overDeadline;
                if (us > worstUs) { worstUs = us; worstAt = now; }
            }
        }
        ++blocksRendered;
        const int had = out.getNumSamples();
        out.setSize (2, had + n, true, false, true);
        for (int ch = 0; ch < 2; ++ch) out.copyFrom (ch, had, blockBuf, ch, 0, n);
        pos += n;
    }
    processor->releaseResources();

    // -------- state out
    if (args.has ("state-out"))
    {
        juce::MemoryBlock bytes;
        processor->getStateInformation (bytes);
        if (! juce::File::getCurrentWorkingDirectory().getChildFile (args.get ("state-out")).replaceWithData (bytes.getData(), bytes.getSize()))
            refuse ("cannot write --state-out");
    }
    if (args.has ("out"))
    {
        auto file = juce::File::getCurrentWorkingDirectory().getChildFile (args.get ("out"));
        file.deleteFile();
        juce::WavAudioFormat wav;
        std::unique_ptr<juce::AudioFormatWriter> writer (wav.createWriterFor (new juce::FileOutputStream (file), rate, 2, 32, {}, 0));
        if (writer == nullptr || ! writer->writeFromAudioSampleBuffer (out, 0, out.getNumSamples())) refuse ("cannot write --out " + file.getFullPathName());
    }

    // -------- metrics
    const int N = out.getNumSamples();
    double peak = 0.0, sumSq = 0.0, dc = 0.0, maxStep = 0.0;
    int nans = 0, infs = 0, clipped = 0;
    juce::int64 lastAudible = -1;
    const float audible = (float) juce::Decibels::decibelsToGain (-90.0);
    for (int ch = 0; ch < 2; ++ch)
    {
        const auto* d = out.getReadPointer (ch);
        float prev = 0.0f;
        for (int i = 0; i < N; ++i)
        {
            const float v = d[i];
            if (std::isnan (v)) { ++nans; continue; }
            if (std::isinf (v)) { ++infs; continue; }
            const double a = std::abs ((double) v);
            peak = juce::jmax (peak, a); sumSq += (double) v * v; dc += v;
            if (a > 1.0) ++clipped;
            maxStep = juce::jmax (maxStep, (double) std::abs (v - prev)); prev = v;
            if (a > audible) lastAudible = juce::jmax (lastAudible, (juce::int64) i);
        }
    }
    const double rms = N > 0 ? std::sqrt (sumSq / (2.0 * N)) : 0.0;
    const double dcMean = N > 0 ? dc / (2.0 * N) : 0.0;
    const Loudness loud = measureLoudness (out, rate);
    const double tp = (nans + infs) == 0 ? truePeak (out) : 0.0;
    const double sourceEnd = isInstrument ? (gate >= 0.0 ? gate : seconds) : (signal.kind == "file" ? (double) signal.file.getNumSamples() / rate : (signal.kind == "impulse" ? 0.0 : seconds));
    const double tail = lastAudible >= 0 ? juce::jmax (0.0, (double) lastAudible / rate - sourceEnd) : 0.0;

    juce::var root = obj();
    set (root, "contract", 3);
    {
        auto applied = obj();
        set (applied, "seed", seed); set (applied, "sample_rate", rate); set (applied, "block", randomBlocks ? juce::var (blockArg) : juce::var (block));
        set (applied, "max_block", maxBlock); set (applied, "seconds", seconds);
        set (applied, "preset", presetName.isEmpty() ? juce::var() : juce::var (presetName)); set (applied, "solo", solo.isEmpty() ? juce::var() : juce::var (solo));
        auto params = obj();
        for (auto* p : processor->getParameters())
            if (auto* ranged = dynamic_cast<juce::RangedAudioParameter*> (p))
                set (params, ranged->paramID.toRawUTF8(), (double) ranged->getValue());
        set (applied, "params", params);
        juce::var noteList; for (int n : notes) noteList.append (n);
        set (applied, "notes", noteList); set (applied, "gate", gate >= 0.0 ? juce::var (gate) : juce::var());
        set (applied, "latency_samples", processor->getLatencySamples()); set (applied, "tail_seconds", tail);
        auto build = obj();
        set (build, "commit", BUILD_SHA);
       #if JUCE_DEBUG
        set (build, "config", "Debug");
       #else
        set (build, "config", "Release");
       #endif
       #if JUCE_ARM
        set (build, "arch", "arm64");
       #else
        set (build, "arch", "x86_64");
       #endif
        set (applied, "build", build);
        set (root, "applied", applied);
    }
    {
        auto levels = obj();
        set (levels, "peak_dbfs", dbOf (peak)); set (levels, "rms_dbfs", dbOf (rms)); set (levels, "true_peak_dbtp", dbOf (tp)); set (levels, "dc_dbfs", dbOf (std::abs (dcMean)));
        set (root, "levels", levels);
        auto health = obj();
        set (health, "nan", nans); set (health, "inf", infs); set (health, "clipped_samples", clipped);
        set (health, "max_click_db", peak > 0.0 && maxStep > 0.0 ? 20.0 * std::log10 (maxStep / peak) : -300.0);
        set (root, "health", health);
        auto loudness = obj();
        set (loudness, "integrated_lufs", loud.integrated); set (loudness, "momentary_max_lufs", loud.momentaryMax);
        set (root, "loudness", loudness);
    }
    if (profile)
    {
        auto pr = obj();
        set (pr, "deadline_ms", 1000.0 * (double) juce::jmax (1, randomBlocks ? maxBlock : block) / rate);
        set (pr, "p50_pct", percentile (blockTimesUs, 0.5)); set (pr, "p99_pct", percentile (blockTimesUs, 0.99));
        set (pr, "p999_pct", percentile (blockTimesUs, 0.999)); set (pr, "max_pct", blockTimesUs.empty() ? 0.0 : *std::max_element (blockTimesUs.begin(), blockTimesUs.end()));
        set (pr, "worst_block_at_s", worstAt); set (pr, "over_deadline", overDeadline); set (pr, "blocks", (int) blockTimesUs.size());
        set (pr, "first_block_pct", firstBlockPct); set (pr, "warmup_blocks", warmup);
        set (root, "profile", pr);
    }
    set (root, "product", productMetrics (out, rate));
    std::cout << juce::JSON::toString (root, true) << std::endl;

    if (stateRefused.isNotEmpty()) { std::cerr << "error: --state-in " << stateRefused << std::endl; return 2; }
    return (nans + infs) > 0 ? 3 : 0;
}

#if JUCE_WINDOWS
int wmain (int argc, wchar_t* argv[])
{
    std::vector<std::string> utf8; std::vector<char*> ptrs;
    for (int i = 0; i < argc; ++i) utf8.push_back (juce::String (argv[i]).toStdString());
    for (auto& s : utf8) ptrs.push_back (s.data());
    return run (argc, ptrs.data());
}
#else
int main (int argc, char* argv[]) { return run (argc, argv); }
#endif
