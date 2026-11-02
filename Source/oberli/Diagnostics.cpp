// The system headers first: CoreFoundation's Point and juce::Point collide once the
// juce namespace is open.
#if defined (__APPLE__)
 #include <CoreFoundation/CoreFoundation.h>
 #include <sys/sysctl.h>
#endif

#include "Diagnostics.h"
#include "Folders.h"

#include <BuildInfo.h>

namespace oberli
{

namespace
{
    /** The host's own version: JUCE's host enum stops at Ableton Live 11, so it is read
        from the host application itself (its bundle on macOS, the executable's
        version resource on Windows). */
    juce::String hostVersion()
    {
        const juce::File exe (juce::PluginHostType::getHostPath());

       #if JUCE_MAC
        auto bundle = exe;
        while (bundle != juce::File() && ! bundle.hasFileExtension ("app") && bundle.getParentDirectory() != bundle)
            bundle = bundle.getParentDirectory();

        if (bundle.hasFileExtension ("app"))
        {
            juce::String version;
            const auto path = bundle.getFullPathName();

            if (auto url = CFURLCreateFromFileSystemRepresentation (nullptr, (const UInt8*) path.toRawUTF8(),
                                                                     (CFIndex) path.getNumBytesAsUTF8(), true))
            {
                if (auto cfBundle = CFBundleCreate (nullptr, url))
                {
                    if (auto value = CFBundleGetValueForInfoDictionaryKey (cfBundle, CFSTR ("CFBundleShortVersionString"));
                        value != nullptr && CFGetTypeID (value) == CFStringGetTypeID())
                    {
                        char buffer[64] = {};
                        if (CFStringGetCString ((CFStringRef) value, buffer, sizeof (buffer), kCFStringEncodingUTF8))
                            version = juce::String::fromUTF8 (buffer);
                    }

                    CFRelease (cfBundle);
                }

                CFRelease (url);
            }

            return version;
        }

        return {};
       #elif JUCE_WINDOWS
        return exe.existsAsFile() ? exe.getVersion() : juce::String();
       #else
        return {};
       #endif
    }

    bool runsUnderRosetta()
    {
       #if JUCE_MAC
        int translated = 0;
        size_t size = sizeof (translated);
        return sysctlbyname ("sysctl.proc_translated", &translated, &size, nullptr, 0) == 0 && translated == 1;
       #else
        return false;
       #endif
    }

    const char* architecture()
    {
       #if defined (__aarch64__) || defined (__arm64__) || defined (_M_ARM64)
        return "arm64";
       #elif defined (__x86_64__) || defined (_M_X64)
        return "x86_64";
       #else
        return "unknown";
       #endif
    }
}

juce::StringArray diagnosticsLines (const juce::AudioProcessor& processor, const DiagnosticsInput& in)
{
    const juce::PluginHostType host;
    const juce::String hostName (host.getHostDescription());
    const auto version = hostVersion();

    juce::StringArray lines;
    lines.add ("Product: " + folders::productName());
    lines.add (juce::String ("Version: ") + PRODUCT_VERSION);
    lines.add ("Sound version: " + juce::String (in.soundVersion));
    lines.add (juce::String ("Build: ") + BUILD_SHA + (BUILD_DIRTY ? " (uncommitted changes)" : ""));
    lines.add (juce::String ("Build date: ") + BUILD_DATE);
    lines.add ("Format: " + juce::String (juce::AudioProcessor::getWrapperTypeDescription (processor.wrapperType)));
    lines.add ("Host: " + hostName + (version.isNotEmpty() ? " " + version : juce::String()));
    lines.add ("OS: " + juce::SystemStats::getOperatingSystemName());
    lines.add (juce::String ("Architecture: ") + architecture());
    lines.add (juce::String ("Rosetta: ") + (runsUnderRosetta() ? "yes" : "no"));
    lines.add ("Sample rate: " + juce::String (juce::roundToInt (processor.getSampleRate())) + " Hz");
    lines.add ("Buffer size: " + juce::String (processor.getBlockSize()) + " samples");
    lines.add ("GUI scale: " + juce::String (juce::roundToInt (in.guiScale * 100.0f)) + " %");
    lines.add ("Preset: " + (in.presetName.isNotEmpty() ? in.presetName + (in.presetEdited ? " (edited)" : "") : juce::String ("none")));
    return lines;
}

} // namespace oberli
