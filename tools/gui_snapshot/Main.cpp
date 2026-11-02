/*
    AlignGuiSnapshot - renders the real editor offscreen to PNG: no host, no audio device
    (plugin-ui-bob audio-plugins.md 15, after Horizon Pad's HorizonPadGuiSnapshot). It builds the
    real processor and editor, renders audio through processBlock first (so the meters show what
    the DSP produces), steps the editor's frame clock itself at 60 frames per second of simulated
    time, and prints one JSON object echoing what it rendered.

        cmake --build build --target AlignGuiSnapshot
        S=build/AlignGuiSnapshot_artefacts/Release/AlignGuiSnapshot
        $S --out=docs/ui/panel@1x.png
        $S --scale=2 --out=docs/ui/panel@2x.png
        $S --state=menu --out=menu.png        # also: scale-menu, drawer, save, about, licences
        $S --param=mix=0.4 --drag=mix --out=turning.png
        python3 <plugin-ui-bob>/scripts/snapshot_contrast.py docs/ui/panel@1x.png --metrics --theme bone

    On Linux without a display run it under xvfb-run. PRESET_ROOT (default: a scratch folder)
    keeps it away from the real preset, settings and reference folders.
*/

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include "PluginProcessor.h"
#include "oberli/StripEditor.h"

#include <iostream>
#include <random>

namespace
{
[[noreturn]] void refuse (const juce::String& msg)
{
    std::cerr << "error: " << msg << std::endl;
    std::exit (2);
}

const char* const kUsage =
    "AlignGuiSnapshot - renders the editor offscreen to PNG\n"
    "  --out=<png>               output file (required)\n"
    "  --scale=<x>               pixel density: 1, 1.5, 2 (default 1)\n"
    "  --state=<s>               panel (default), menu, scale-menu, drawer, save, about, licences\n"
    "  --param=<id>=<0..1>       a normalised parameter value, repeatable\n"
    "  --preset=<n>              load factory preset n (0 = Init) first\n"
    "  --drag=<id>               show that knob's drag readout\n"
    "  --seconds=<s>             audio rendered and frames stepped before the snapshot (default 1.5)\n";
} // namespace

int main (int argc, char* argv[])
{
    juce::ScopedJuceInitialiser_GUI gui;

    juce::StringPairArray args;
    juce::StringArray params;
    for (int i = 1; i < argc; ++i)
    {
        juce::String a (argv[i]);
        if (a == "--help") { std::cout << kUsage; return 0; }
        if (! a.startsWith ("--")) refuse ("unexpected argument " + a);
        const auto key = a.substring (2).upToFirstOccurrenceOf ("=", false, false);
        const auto value = a.fromFirstOccurrenceOf ("=", false, false);
        if (key == "param") params.add (value);
        else if (juce::StringArray { "out", "scale", "state", "preset", "drag", "seconds" }.contains (key)) args.set (key, value);
        else refuse ("unknown flag --" + key + " (--help)");
    }
    if (args["out"].isEmpty()) refuse ("--out is required (--help)");

    juce::TemporaryFile scratch;
    if (juce::SystemStats::getEnvironmentVariable ("PRESET_ROOT", {}).isEmpty())
    {
        scratch.getFile().createDirectory();
       #if JUCE_WINDOWS
        _putenv_s ("PRESET_ROOT", scratch.getFile().getFullPathName().toRawUTF8());
       #else
        setenv ("PRESET_ROOT", scratch.getFile().getFullPathName().toRawUTF8(), 1);
       #endif
    }

    const auto scale = args["scale"].isNotEmpty() ? args["scale"].getFloatValue() : 1.0f;
    const auto seconds = args["seconds"].isNotEmpty() ? args["seconds"].getDoubleValue() : 1.5;
    const auto state = args["state"].isNotEmpty() ? args["state"] : juce::String ("panel");
    if (! juce::StringArray { "panel", "menu", "scale-menu", "drawer", "save", "about", "licences" }.contains (state))
        refuse ("unknown --state " + state);

    AlignAudioProcessor processor;
    juce::AudioProcessor::BusesLayout layout;
   #if ! PRODUCT_IS_INSTRUMENT
    layout.inputBuses.add (juce::AudioChannelSet::stereo());
   #endif
    layout.outputBuses.add (juce::AudioChannelSet::stereo());
    processor.setBusesLayout (layout);

    const double rate = 48000.0;
    const int block = 512;
    processor.prepareToPlay (rate, block);

    for (const auto& p : params)
    {
        const auto id = p.upToFirstOccurrenceOf ("=", false, false);
        auto* parameter = processor.parameters().getParameter (id);
        if (parameter == nullptr) refuse ("no parameter " + id);
        parameter->setValueNotifyingHost (p.fromFirstOccurrenceOf ("=", false, false).getFloatValue());
    }

    std::unique_ptr<juce::AudioProcessorEditor> editor (processor.createEditorAndMakeActive());
    auto* strip = dynamic_cast<oberli::ui::StripEditor*> (editor.get());
    if (strip == nullptr && (state != "panel" || args["preset"].isNotEmpty() || args["drag"].isNotEmpty()))
        refuse ("--state, --preset and --drag need the Strip frame (oberli::ui::StripEditor)");
    if (strip != nullptr && args["preset"].isNotEmpty())
        strip->getPresets().loadFactory (args["preset"].getIntValue());

    // Audio and frames together: pink-ish noise at -18 dBFS into an effect, a chord into an instrument.
    juce::AudioBuffer<float> buffer (2, block);
    juce::MidiBuffer midi;
    std::mt19937 rng (1);
    std::normal_distribution<float> noise (0.0f, 0.125f);
    double now = 1000.0;
    auto audioBlock = [&] (int b)
    {
        juce::ignoreUnused (b);
        midi.clear();
       #if PRODUCT_IS_INSTRUMENT
        buffer.clear();
        if (b == 0)
            for (int n : { 48, 55, 60, 64 })
                midi.addEvent (juce::MidiMessage::noteOn (1, n, (juce::uint8) 100), 0);
       #else
        for (int ch = 0; ch < 2; ++ch)
            for (int i = 0; i < block; ++i)
                buffer.setSample (ch, i, noise (rng));
       #endif
        processor.processBlock (buffer, midi);
        now += (double) block / rate;
        if (strip != nullptr)
            strip->advanceFrame (now);
    };
    const auto blocks = (int) std::ceil (seconds * rate / block);
    for (int b = 0; b < blocks; ++b)
        audioBlock (b);

    if (strip != nullptr)
    {
        if (state == "menu" || state == "scale-menu") strip->showMenu (state == "scale-menu");
        else if (state == "drawer") strip->showPresetDrawer();
        else if (state == "save") strip->showSavePresetCard();
        else if (state == "about" || state == "licences") strip->showAbout (state == "licences");

        if (args["drag"].isNotEmpty())
            if (! strip->previewDrag (args["drag"]))
                refuse ("no knob for --drag " + args["drag"]);

        for (int b = 0; b < (int) (rate / block); ++b)   // a second more, the audio still running: fades and glides settle
            audioBlock (blocks + b);
    }

    const auto image = editor->createComponentSnapshot (editor->getLocalBounds(), true, scale);
    juce::File out = juce::File::getCurrentWorkingDirectory().getChildFile (args["out"]);
    out.getParentDirectory().createDirectory();
    out.deleteFile();
    juce::FileOutputStream stream (out);
    juce::PNGImageFormat png;
    if (! stream.openedOk() || ! png.writeImageToStream (image, stream))
        refuse ("cannot write " + out.getFullPathName());
    stream.flush();

    std::cout << "{\"out\": \"" << out.getFullPathName() << "\", \"width\": " << image.getWidth() << ", \"height\": " << image.getHeight()
              << ", \"scale\": " << scale << ", \"state\": \"" << state << "\", \"editor\": [" << editor->getWidth() << ", "
              << editor->getHeight() << "], \"strip\": " << (strip != nullptr ? "true" : "false") << "}" << std::endl;

    editor.reset();
    processor.releaseResources();
    return 0;
}
