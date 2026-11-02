#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_core/juce_core.h>

#include <atomic>
#include <functional>
#include <memory>
#include <vector>

namespace oberli
{

/** One preset as the drawer and the header show it. Everything shown is read
    from the file (D.6.5). */
struct PresetInfo
{
    juce::String slug;          // the file name without extension, ASCII (rule 10)
    juce::String name, category, description, author;
    bool user = false;
    juce::File file;            // user presets: where the file lives
    std::shared_ptr<const juce::XmlElement> document;   // the whole <OberliPreset>
};

/**
    What the Strip frame (PluginHeader, PresetDrawer, the menu) needs from a
    plugin's presets. PresetLibrary implements it for any plugin whose presets
    are <OberliPreset> documents (the template's State.h); a plugin with its own
    preset logic implements it itself. Message thread only.
*/
class PresetHost
{
public:
    enum class Kind { none, factory, user };

    virtual ~PresetHost() = default;

    virtual const std::vector<PresetInfo>& factoryPresets() const = 0;   // presets.csv's order
    virtual const std::vector<PresetInfo>& userPresets() const = 0;      // oldest first

    virtual Kind activeKind() const = 0;
    virtual int activeIndex() const = 0;               // into the list of activeKind(), or -1
    virtual juce::String activeName() const = 0;
    virtual bool isActiveModified() const = 0;         // compared, not tracked

    virtual void loadFactory (int index) = 0;
    virtual void loadUser (int index) = 0;
    virtual void refreshUserPresets() = 0;             // reads the User folder again
    virtual bool deleteUser (int index) = 0;           // to the Trash, never deleted outright

    /** Each returns an empty string, or the reason in plain words. */
    virtual juce::String saveUser (const juce::String& name) = 0;
    virtual juce::String importFile (const juce::File&) = 0;
    virtual juce::String exportFile (const juce::File&) = 0;

    /** Bumped on every recall, so the editor can start the knobs' wave. Any thread. */
    virtual int recallCount() const noexcept = 0;

    /** The next or previous preset: the factory bank, then the user's, wrapping. */
    void step (int delta);
};

/**
    The family's preset library: the factory bank compiled into the plugin
    (presets.csv plus one .oberlipreset per row), the User folder
    (folders::userFolder()), the active preset and the "edited" mark.

    The plugin supplies two functions and owns the format:
      capture (name, category, description, factory) -> a full <OberliPreset> of the current state
      apply (document) -> true when the document was this plugin's and is now loaded

    "Edited" compares the PARAM values (id, value) of the current state with
    the active preset's, numerically, so a file written by hand still matches.
*/
class PresetLibrary final : public PresetHost
{
public:
    using Capture = std::function<std::unique_ptr<juce::XmlElement> (const juce::String& name, const juce::String& category,
                                                                      const juce::String& description, bool factory)>;
    using Apply = std::function<bool (const juce::XmlElement& document)>;

    /** `presetsCsv` is the text of presets.csv; `factoryFile` returns the bytes
        of a factory file by name ("init.oberlipreset"), or an empty block. */
    PresetLibrary (const juce::String& presetsCsv, std::function<juce::MemoryBlock (const juce::String& fileName)> factoryFile,
                   Capture capture, Apply apply);

    const std::vector<PresetInfo>& factoryPresets() const override { return factory; }
    const std::vector<PresetInfo>& userPresets() const override    { return user; }

    Kind activeKind() const override { return kind; }
    int activeIndex() const override { return index; }
    juce::String activeName() const override;
    bool isActiveModified() const override;

    void loadFactory (int index) override;
    void loadUser (int index) override;
    void refreshUserPresets() override;
    bool deleteUser (int index) override;

    juce::String saveUser (const juce::String& name) override;
    juce::String importFile (const juce::File&) override;
    juce::String exportFile (const juce::File&) override;

    int recallCount() const noexcept override { return recalls.load (std::memory_order_acquire); }

    /** For the session state: which preset the sound came from ("factory:init",
        "user:my-pad", or empty), and back. restoreActive() never loads anything. */
    juce::String activeId() const;
    void restoreActive (const juce::String& id);

    /** Forget the active preset (the state was set from outside: a session, a host program). */
    void clearActive();

    /** Writes the bank into the Factory folder on the first run of each plugin
        version (Factory/.version), so a friend sees the files; once per process. */
    void writeFactoryFolder() const;

    /** Reads one preset document; nullptr and `error` for anything else. */
    static std::unique_ptr<juce::XmlElement> readDocument (const juce::File&, juce::String& error);

private:
    static PresetInfo infoFrom (std::shared_ptr<const juce::XmlElement>, const juce::String& slug);
    bool loadDocument (const PresetInfo&, Kind, int);

    std::vector<PresetInfo> factory, user;
    std::vector<std::pair<juce::String, juce::MemoryBlock>> factoryFiles;
    Capture capture;
    Apply apply;

    Kind kind = Kind::none;
    int index = -1;
    std::atomic<int> recalls { 0 };

    mutable juce::uint32 modifiedCheckedAt = 0;
    mutable bool modifiedCached = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PresetLibrary)
};

} // namespace oberli
