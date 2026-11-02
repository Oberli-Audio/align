#include "Folders.h"

namespace oberli::folders
{
namespace
{
    constexpr const char* kCompany = "Oberli Audio";

    juce::File overrideRoot()
    {
        const auto path = juce::SystemStats::getEnvironmentVariable ("PRESET_ROOT", {});
        return path.isNotEmpty() && juce::File::isAbsolutePath (path) ? juce::File (path) : juce::File();
    }

    juce::File home (juce::File::SpecialLocationType type) { return juce::File::getSpecialLocation (type); }
}

juce::String productName()
{
   #ifdef JucePlugin_Name
    return JucePlugin_Name;
   #else
    return "Oberli Plugin";
   #endif
}

juce::File presetRoot()
{
    if (const auto root = overrideRoot(); root != juce::File())
        return root;

   #if JUCE_MAC
    return home (juce::File::userHomeDirectory).getChildFile ("Library/Audio/Presets").getChildFile (kCompany).getChildFile (productName());
   #elif JUCE_WINDOWS
    return home (juce::File::userDocumentsDirectory).getChildFile ("VST3 Presets").getChildFile (kCompany).getChildFile (productName());
   #else
    return home (juce::File::userHomeDirectory).getChildFile (".vst3/presets").getChildFile (kCompany).getChildFile (productName());
   #endif
}

juce::File factoryFolder() { return presetRoot().getChildFile ("Factory"); }
juce::File userFolder()    { return presetRoot().getChildFile ("User"); }

juce::File settingsFolder()
{
    if (const auto root = overrideRoot(); root != juce::File())
        return root.getChildFile ("Settings");

   #if JUCE_MAC
    return home (juce::File::userApplicationDataDirectory).getChildFile ("Application Support").getChildFile (kCompany).getChildFile (productName());
   #else
    return home (juce::File::userApplicationDataDirectory).getChildFile (kCompany).getChildFile (productName());
   #endif
}

juce::File referencesFolder()
{
    if (const auto root = overrideRoot(); root != juce::File())
        return root.getChildFile ("References");

    return home (juce::File::userMusicDirectory).getChildFile (kCompany).getChildFile ("References");
}

juce::File cacheFolder()
{
    if (const auto root = overrideRoot(); root != juce::File())
        return root.getChildFile ("Cache");

   #if JUCE_MAC
    return home (juce::File::userHomeDirectory).getChildFile ("Library/Caches").getChildFile (kCompany).getChildFile (productName());
   #elif JUCE_WINDOWS
    return juce::File (juce::SystemStats::getEnvironmentVariable ("LOCALAPPDATA", home (juce::File::userApplicationDataDirectory).getFullPathName()))
               .getChildFile (kCompany).getChildFile (productName()).getChildFile ("Cache");
   #else
    return home (juce::File::userHomeDirectory).getChildFile (".cache").getChildFile (kCompany).getChildFile (productName());
   #endif
}

juce::String slugFor (const juce::String& name)
{
    juce::String slug;
    bool dash = false;

    const auto append = [&] (const char* ascii)
    {
        if (dash && slug.isNotEmpty())
            slug << "-";
        dash = false;
        slug << ascii;
    };

    for (auto c : name.toLowerCase())
    {
        switch (c)
        {
            case 0xe4: append ("ae"); continue;   // ä
            case 0xf6: append ("oe"); continue;   // ö
            case 0xfc: append ("ue"); continue;   // ü
            case 0xdf: append ("ss"); continue;   // ß
            case 0xe0: case 0xe1: case 0xe2: case 0xe3: case 0xe5: append ("a"); continue;
            case 0xe8: case 0xe9: case 0xea: case 0xeb: append ("e"); continue;
            case 0xec: case 0xed: case 0xee: case 0xef: append ("i"); continue;
            case 0xf2: case 0xf3: case 0xf4: case 0xf5: case 0xf8: append ("o"); continue;
            case 0xf9: case 0xfa: case 0xfb: append ("u"); continue;
            case 0xe7: append ("c"); continue;
            case 0xf1: append ("n"); continue;
            default: break;
        }

        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))
        {
            const char ascii[2] { (char) c, 0 };
            append (ascii);
        }
        else
        {
            dash = true;
        }
    }

    return slug.isEmpty() ? juce::String ("preset") : slug;
}
} // namespace oberli::folders

namespace oberli
{
std::unique_ptr<juce::PropertiesFile> MachineSettings::open()
{
    juce::PropertiesFile::Options o;
    o.storageFormat = juce::PropertiesFile::storeAsXML;
    o.millisecondsBeforeSaving = 0;
    return std::make_unique<juce::PropertiesFile> (folders::settingsFolder().getChildFile ("Settings.xml"), o);
}

float MachineSettings::guiScale()
{
    const auto stored = (float) open()->getDoubleValue ("guiScale", 1.0);

    for (auto s : kScales)
        if (std::abs (s - stored) < 0.01f)
            return s;

    return 1.0f;
}

void MachineSettings::setGuiScale (float scale)
{
    auto settings = open();
    settings->setValue ("guiScale", (double) scale);
    settings->saveIfNeeded();
}
} // namespace oberli
