#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_audio_processors/juce_audio_processors.h>

namespace oberli
{
/** What the diagnostics block needs beyond the processor. */
struct DiagnosticsInput
{
    int soundVersion = 1;                 // the state's dspVersion (State.h)
    juce::String presetName;              // empty: none
    bool presetEdited = false;
    float guiScale = 1.0f;
};

/** The About panel's diagnostics block (plugin-ui-bob audio-plugins.md 14, ship-bob
    feedback-loop.md 3): the fourteen fields every support document cites, one
    "Label: value" line each, nothing else - no user name, no paths. A friend pastes it
    into a report. Needs BuildInfo.h (CMakeLists.txt generates it). Message thread. */
juce::StringArray diagnosticsLines (const juce::AudioProcessor&, const DiagnosticsInput&);

inline juce::String diagnosticsText (const juce::AudioProcessor& p, const DiagnosticsInput& in)
{
    return diagnosticsLines (p, in).joinIntoString ("\n");
}
}
