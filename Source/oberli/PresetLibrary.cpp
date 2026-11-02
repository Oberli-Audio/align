#include "PresetLibrary.h"
#include "Folders.h"

#include <cmath>
#include <map>
#include <mutex>

namespace oberli
{
namespace
{
    constexpr const char* kExtension = ".oberlipreset";
    constexpr const char* kPresetTag = "OberliPreset";

    /** Every <PARAM id value> under `e`, by id. */
    void collectParams (const juce::XmlElement& e, std::map<juce::String, double>& into)
    {
        for (auto* child : e.getChildIterator())
        {
            if (child->hasTagName ("PARAM") && child->hasAttribute ("id"))
                into[child->getStringAttribute ("id")] = child->getDoubleAttribute ("value");
            else
                collectParams (*child, into);
        }
    }

    bool sameValues (const juce::XmlElement& a, const juce::XmlElement& b)
    {
        std::map<juce::String, double> pa, pb;
        collectParams (a, pa);
        collectParams (b, pb);

        // A parameter missing from the preset counts as its default only if the
        // state agrees; simplest and strict: the preset's ids must match the state's values.
        for (const auto& [id, value] : pb)
        {
            const auto found = pa.find (id);
            if (found == pa.end())
                continue;   // the state has no such parameter (an older file): not an edit
            const auto tolerance = 1.0e-6 * juce::jmax (1.0, std::abs (value));
            if (std::abs (found->second - value) > tolerance)
                return false;
        }

        return true;
    }

    /** The first child element: the plugin's state element inside <OberliPreset>. */
    const juce::XmlElement* stateElement (const juce::XmlElement& doc)
    {
        return doc.getFirstChildElement();
    }
} // namespace

//==============================================================================
void PresetHost::step (int delta)
{
    const auto numFactory = (int) factoryPresets().size();
    const auto total = numFactory + (int) userPresets().size();

    if (total <= 0)
        return;

    auto position = -1;

    switch (activeKind())
    {
        case Kind::factory: position = activeIndex(); break;
        case Kind::user:    position = numFactory + activeIndex(); break;
        case Kind::none:    break;
    }

    const auto target = position < 0 ? (delta > 0 ? 0 : total - 1)
                                     : ((position + delta) % total + total) % total;

    if (target < numFactory)
        loadFactory (target);
    else
        loadUser (target - numFactory);
}

//==============================================================================
PresetLibrary::PresetLibrary (const juce::String& presetsCsv, std::function<juce::MemoryBlock (const juce::String&)> factoryFile,
                              Capture captureToUse, Apply applyToUse)
    : capture (std::move (captureToUse)), apply (std::move (applyToUse))
{
    auto header = true;

    for (const auto& line : juce::StringArray::fromLines (presetsCsv))
    {
        if (line.trim().isEmpty())
            continue;

        if (header)
        {
            header = false;
            continue;
        }

        const auto cells = juce::StringArray::fromTokens (line, ",", "\"");
        if (cells.isEmpty())
            continue;

        const auto slug = cells[0].trim();
        const auto fileName = slug + kExtension;
        const auto bytes = factoryFile (fileName);
        auto xml = juce::parseXML (bytes.toString());

        if (xml == nullptr || ! xml->hasTagName (kPresetTag))
        {
            jassertfalse;   // presets.csv names a file the bank does not hold (presetlint.py bank)
            continue;
        }

        auto info = infoFrom (std::shared_ptr<const juce::XmlElement> (xml.release()), slug);

        if (info.category.isEmpty() && cells.size() > 2)
            info.category = cells[2].trim();

        factory.push_back (std::move (info));
        factoryFiles.emplace_back (fileName, bytes);
    }

    refreshUserPresets();
}

PresetInfo PresetLibrary::infoFrom (std::shared_ptr<const juce::XmlElement> doc, const juce::String& slug)
{
    PresetInfo info;
    info.slug = slug;
    info.name = doc->getStringAttribute ("name", slug);
    info.category = doc->getStringAttribute ("category");
    info.description = doc->getStringAttribute ("description");
    info.author = doc->getStringAttribute ("author");
    info.document = std::move (doc);
    return info;
}

std::unique_ptr<juce::XmlElement> PresetLibrary::readDocument (const juce::File& file, juce::String& error)
{
    if (! file.existsAsFile())
    {
        error = "The file is not there any more.";
        return nullptr;
    }

    auto xml = juce::XmlDocument::parse (file);

    if (xml == nullptr || ! xml->hasTagName (kPresetTag) || stateElement (*xml) == nullptr)
    {
        error = "This is not an Oberli Audio preset.";
        return nullptr;
    }

    return xml;
}

juce::String PresetLibrary::activeName() const
{
    const auto& list = kind == Kind::user ? user : factory;
    return kind != Kind::none && juce::isPositiveAndBelow (index, (int) list.size()) ? list[(size_t) index].name : juce::String();
}

bool PresetLibrary::isActiveModified() const
{
    // Called every editor frame: the comparison builds the state, so at most every 150 ms.
    const auto now = juce::Time::getMillisecondCounter();
    if (now - modifiedCheckedAt < 150)
        return modifiedCached;
    modifiedCheckedAt = now;

    const auto& list = kind == Kind::user ? user : factory;

    if (kind == Kind::none || ! juce::isPositiveAndBelow (index, (int) list.size()) || capture == nullptr)
        return modifiedCached = false;

    const auto current = capture ({}, {}, {}, false);
    const auto* presetState = stateElement (*list[(size_t) index].document);
    const auto* currentState = current != nullptr ? stateElement (*current) : nullptr;

    return modifiedCached = presetState != nullptr && currentState != nullptr && ! sameValues (*currentState, *presetState);
}

bool PresetLibrary::loadDocument (const PresetInfo& info, Kind newKind, int newIndex)
{
    if (info.document == nullptr || apply == nullptr || ! apply (*info.document))
        return false;

    kind = newKind;
    index = newIndex;
    modifiedCheckedAt = 0;
    recalls.fetch_add (1, std::memory_order_release);
    return true;
}

void PresetLibrary::loadFactory (int i)
{
    if (juce::isPositiveAndBelow (i, (int) factory.size()))
        loadDocument (factory[(size_t) i], Kind::factory, i);
}

void PresetLibrary::loadUser (int i)
{
    if (juce::isPositiveAndBelow (i, (int) user.size()))
        loadDocument (user[(size_t) i], Kind::user, i);
}

void PresetLibrary::refreshUserPresets()
{
    const auto activeSlug = kind == Kind::user && juce::isPositiveAndBelow (index, (int) user.size()) ? user[(size_t) index].slug : juce::String();

    user.clear();

    for (const auto& file : folders::userFolder().findChildFiles (juce::File::findFiles, false, juce::String ("*") + kExtension))
    {
        juce::String error;

        if (auto xml = readDocument (file, error))
        {
            auto info = infoFrom (std::shared_ptr<const juce::XmlElement> (xml.release()), file.getFileNameWithoutExtension());
            info.user = true;
            info.file = file;
            user.push_back (std::move (info));
        }
    }

    std::stable_sort (user.begin(), user.end(), [] (const PresetInfo& a, const PresetInfo& b)
    {
        const auto ta = a.file.getCreationTime(), tb = b.file.getCreationTime();
        return ta != tb ? ta < tb : a.slug.compareNatural (b.slug) < 0;
    });

    if (kind == Kind::user)
    {
        index = -1;
        for (size_t i = 0; i < user.size(); ++i)
            if (user[i].slug == activeSlug)
                index = (int) i;
        if (index < 0)
            kind = Kind::none;
    }
}

bool PresetLibrary::deleteUser (int i)
{
    if (! juce::isPositiveAndBelow (i, (int) user.size()))
        return false;

    const auto file = user[(size_t) i].file;
    const auto removed = file.existsAsFile() && (file.moveToTrash() || file.deleteFile());

    if (kind == Kind::user && index == i)
        clearActive();

    refreshUserPresets();
    return removed;
}

juce::String PresetLibrary::saveUser (const juce::String& requestedName)
{
    const auto folder = folders::userFolder();

    if (! folder.createDirectory())
        return "I could not create the folder " + folder.getFullPathName() + ".";

    const auto name = requestedName.trim().isEmpty() ? juce::String ("Untitled") : requestedName.trim();
    const auto base = folders::slugFor (name);
    auto slug = base;

    for (int n = 2; folder.getChildFile (slug + kExtension).exists(); ++n)
        slug = base + "-" + juce::String (n);

    const auto file = folder.getChildFile (slug + kExtension);
    const auto doc = capture (name, "Yours", {}, false);

    if (doc == nullptr || ! doc->writeTo (file))
        return "I could not write " + file.getFullPathName() + ".";

    refreshUserPresets();

    for (size_t i = 0; i < user.size(); ++i)
        if (user[i].slug == slug)
        {
            kind = Kind::user;
            index = (int) i;
            modifiedCheckedAt = 0;
        }

    return {};
}

juce::String PresetLibrary::importFile (const juce::File& source)
{
    juce::String error;
    auto doc = readDocument (source, error);

    if (doc == nullptr)
        return error;

    // Only this plugin's presets: the state element must be the one capture() writes.
    if (const auto mine = capture ({}, {}, {}, false); mine != nullptr && stateElement (*mine) != nullptr
        && ! stateElement (*doc)->hasTagName (stateElement (*mine)->getTagName()))
        return "This preset is for another plugin.";

    const auto folder = folders::userFolder();
    if (! folder.createDirectory())
        return "I could not create the folder " + folder.getFullPathName() + ".";

    const auto base = folders::slugFor (doc->getStringAttribute ("name", source.getFileNameWithoutExtension()));
    auto slug = base;
    for (int n = 2; folder.getChildFile (slug + kExtension).exists(); ++n)
        slug = base + "-" + juce::String (n);

    doc->setAttribute ("factory", false);
    if (! doc->writeTo (folder.getChildFile (slug + kExtension)))
        return "I could not copy the preset into " + folder.getFullPathName() + ".";

    refreshUserPresets();

    for (size_t i = 0; i < user.size(); ++i)
        if (user[i].slug == slug)
            loadUser ((int) i);

    return {};
}

juce::String PresetLibrary::exportFile (const juce::File& target)
{
    const auto name = activeName().isNotEmpty() ? activeName() : target.getFileNameWithoutExtension();
    const auto doc = capture (name, kind == Kind::factory ? factory[(size_t) index].category : juce::String ("Yours"), {}, false);

    if (doc == nullptr || ! doc->writeTo (target.withFileExtension (kExtension)))
        return "I could not write " + target.getFullPathName() + ".";

    return {};
}

juce::String PresetLibrary::activeId() const
{
    const auto& list = kind == Kind::user ? user : factory;

    if (kind == Kind::none || ! juce::isPositiveAndBelow (index, (int) list.size()))
        return {};

    return juce::String (kind == Kind::user ? "user:" : "factory:") + list[(size_t) index].slug;
}

void PresetLibrary::restoreActive (const juce::String& id)
{
    clearActive();

    const auto slug = id.fromFirstOccurrenceOf (":", false, false);
    const auto isUser = id.startsWith ("user:");
    const auto& list = isUser ? user : factory;

    for (size_t i = 0; i < list.size(); ++i)
        if (list[i].slug == slug && (isUser || id.startsWith ("factory:")))
        {
            kind = isUser ? Kind::user : Kind::factory;
            index = (int) i;
        }
}

void PresetLibrary::clearActive()
{
    kind = Kind::none;
    index = -1;
    modifiedCheckedAt = 0;
}

void PresetLibrary::writeFactoryFolder() const
{
    static std::once_flag once;

    std::call_once (once, [this]
    {
        const auto folder = folders::factoryFolder();
        const auto stamp = folder.getChildFile (".version");

       #ifdef JucePlugin_VersionString
        const juce::String version (JucePlugin_VersionString);
       #else
        const juce::String version ("0");
       #endif

        if (stamp.loadFileAsString().trim() == version || ! folder.createDirectory())
            return;

        for (const auto& old : folder.findChildFiles (juce::File::findFiles, false, juce::String ("*") + kExtension))
            old.deleteFile();

        for (const auto& [fileName, data] : factoryFiles)
            folder.getChildFile (fileName).replaceWithData (data.getData(), data.getSize());

        stamp.replaceWithText (version);
    });
}

} // namespace oberli
