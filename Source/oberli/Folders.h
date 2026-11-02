#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_core/juce_core.h>
#include <juce_data_structures/juce_data_structures.h>

#include <memory>

/*  Where an Oberli Audio plugin keeps its files on a friend's machine (ship-bob
    locations.md, sound-design-bob D.6.4). One company folder, one product folder
    under it; nothing is ever written next to the plugin binary.

      presets     ~/Library/Audio/Presets/Oberli Audio/<Product>/{Factory,User}
                  Documents\VST3 Presets\Oberli Audio\<Product>\{Factory,User}   (the VST3 spec location)
      settings    ~/Library/Application Support/Oberli Audio/<Product>/Settings.xml
                  %APPDATA%\Oberli Audio\<Product>\Settings.xml                   (machine-local: GUI scale)
      references  ~/Music/Oberli Audio/References, Music\Oberli Audio\References  (shared by every plugin)
      cache       ~/Library/Caches/Oberli Audio/<Product>, %LOCALAPPDATA%\...     (safe to delete)

    The environment variable PRESET_ROOT (absolute) moves all four under it - Factory, User,
    Settings, References, Cache - so the harness, the snapshot tool and the tests never touch
    the real folders. */
namespace oberli::folders
{
/** The product's name as the folders spell it (JucePlugin_Name). */
juce::String productName();

juce::File presetRoot();
juce::File factoryFolder();
juce::File userFolder();
juce::File settingsFolder();
juce::File referencesFolder();
juce::File cacheFolder();

/** "Alpenglühen" -> "alpengluehen": ASCII, lowercase, '-' between words (rule 10). */
juce::String slugFor (const juce::String& name);
}

namespace oberli
{
/** The machine-local preferences of this product (Settings.xml in the settings
    folder): the GUI scale every instance opens at, nothing that belongs in a
    session or a preset. Message thread. */
class MachineSettings
{
public:
    static std::unique_ptr<juce::PropertiesFile> open();

    /** The menu's GUI scale choices (Menu card): 75, 100, 125, 150, 200 %. */
    static constexpr float kScales[] { 0.75f, 1.0f, 1.25f, 1.5f, 2.0f };

    static float guiScale();
    static void setGuiScale (float);
};
}
