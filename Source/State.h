#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

/*  The product's state and preset format (sound-design-bob D.5.3, D.6.5).

    Session state and every preset file carry one <{{ProductId}}State version="N" dspVersion="M">
    element with the parameters by ID in plain units (the parameter table's) under <PARAMETERS>,
    and anything that is not a parameter under <Extra>. A newer file is refused, an older one
    migrated; IDs and the format freeze at the first release (rule 19). Preset files are
    <OberliPreset> documents (.oberlipreset) wrapping that element, as plugin-ui-bob's drawer
    writes and reads them. */
namespace {{bundle}}::State
{
inline constexpr int kStateVersion = 1;   // bump with a migration and a changelog line
inline constexpr int kDspVersion = 1;     // bump when a factory sound changes on purpose (Sounds different)
inline constexpr const char* kStateTag = "{{ProductId}}State";
inline constexpr const char* kPresetTag = "OberliPreset";
inline constexpr const char* kPresetExtension = ".oberlipreset";

/** The state element for the current parameter values. Plain units, shortest round-trip text. */
inline std::unique_ptr<juce::XmlElement> toXml (const juce::AudioProcessorValueTreeState& apvts)
{
    auto root = std::make_unique<juce::XmlElement> (kStateTag);
    root->setAttribute ("version", kStateVersion);
    root->setAttribute ("dspVersion", kDspVersion);
    auto* params = root->createNewChildElement ("PARAMETERS");
    for (auto* p : apvts.processor.getParameters())
        if (auto* withId = dynamic_cast<juce::AudioProcessorParameterWithID*> (p))
        {
            auto* e = params->createNewChildElement ("PARAM");
            e->setAttribute ("id", withId->paramID);
            auto* ranged = dynamic_cast<juce::RangedAudioParameter*> (p);
            e->setAttribute ("value", ranged != nullptr ? (double) ranged->convertFrom0to1 (p->getValue()) : (double) p->getValue());
        }
    root->createNewChildElement ("Extra");
    return root;
}

/** Applies a state element. Returns false (and leaves the state untouched) for a foreign or
    newer document; a missing, non-numeric or non-finite value takes the default, every value is
    clamped. Migrations from older versions go here, one `if (version < N)` block each. */
inline bool fromXml (const juce::XmlElement& root, juce::AudioProcessorValueTreeState& apvts)
{
    if (! root.hasTagName (kStateTag))
        return false;
    const int version = root.getIntAttribute ("version", 0);
    if (version < 1 || version > kStateVersion)
        return false;
    auto* params = root.getChildByName ("PARAMETERS");
    for (auto* p : apvts.processor.getParameters())
    {
        auto* ranged = dynamic_cast<juce::RangedAudioParameter*> (p);
        if (ranged == nullptr)
            continue;
        double plain = ranged->convertFrom0to1 (ranged->getDefaultValue());
        if (params != nullptr)
            for (auto* e : params->getChildWithTagNameIterator ("PARAM"))
                if (e->getStringAttribute ("id") == ranged->paramID && e->hasAttribute ("value"))
                {
                    const double v = e->getDoubleAttribute ("value", plain);
                    if (std::isfinite (v))
                        plain = v;
                }
        const auto range = ranged->getNormalisableRange();
        plain = juce::jlimit ((double) range.start, (double) range.end, plain);
        ranged->setValueNotifyingHost (ranged->convertTo0to1 ((float) plain));
    }
    return true;
}

/** An <OberliPreset> document around the state element; `factory` marks the bank's own files. */
inline std::unique_ptr<juce::XmlElement> presetXml (const juce::AudioProcessorValueTreeState& apvts, const juce::String& name,
                                                    const juce::String& author, const juce::String& category,
                                                    const juce::String& description, bool factory)
{
    auto doc = std::make_unique<juce::XmlElement> (kPresetTag);
    doc->setAttribute ("name", name);
    doc->setAttribute ("author", author);
    doc->setAttribute ("category", category);
    doc->setAttribute ("description", description);
    doc->setAttribute ("pluginVersion", JucePlugin_VersionString);
    doc->setAttribute ("created", juce::Time::getCurrentTime().formatted ("%Y-%m-%d"));
    doc->setAttribute ("factory", factory);
    doc->addChildElement (toXml (apvts).release());
    return doc;
}

/** The state element inside a preset document, or the element itself when given one. */
inline const juce::XmlElement* stateOf (const juce::XmlElement& doc)
{
    if (doc.hasTagName (kStateTag))
        return &doc;
    if (doc.hasTagName (kPresetTag))
        return doc.getChildByName (kStateTag);
    return nullptr;
}
} // namespace {{bundle}}::State
