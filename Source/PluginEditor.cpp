#include "PluginEditor.h"
#include "BuildInfo.h"
#include "Params.h"

namespace
{
// Placeholder colours in the brand's two themes (plugin-ui-bob oberli-audio-brand.md); the
// real tokens come with the LookAndFeel at G2.
struct Theme { juce::Colour bg, ink, accent; };
constexpr bool kBone = std::string_view ("{{theme}}") == "bone";
const Theme theme = kBone ? Theme { juce::Colour (0xFFF3EEE4), juce::Colour (0xFF1C1B19), juce::Colour (0xFF{{AccentHexBare}}) }
                          : Theme { juce::Colour (0xFF1C1B19), juce::Colour (0xFFF3EEE4), juce::Colour (0xFF{{AccentHexBare}}) };
} // namespace

{{ProductId}}AudioProcessorEditor::{{ProductId}}AudioProcessorEditor ({{ProductId}}AudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    setWantsKeyboardFocus (false);   // the space bar keeps reaching the host's transport
    title.setText (JucePlugin_Name, juce::dontSendNotification);
    title.setFont (juce::Font (juce::FontOptions (22.0f, juce::Font::bold)));
    title.setColour (juce::Label::textColourId, theme.ink);
    addAndMakeVisible (title);
    version.setText (juce::String ("v") + PRODUCT_VERSION + " " + BUILD_SHA + (BUILD_DIRTY ? " (dirty)" : ""), juce::dontSendNotification);
    version.setFont (juce::Font (juce::FontOptions (12.0f)));
    version.setColour (juce::Label::textColourId, theme.ink.withAlpha (0.6f));
    version.setJustificationType (juce::Justification::centredRight);
    addAndMakeVisible (version);

    for (auto* param : processor.getParameters())
    {
        auto* ranged = dynamic_cast<juce::RangedAudioParameter*> (param);
        if (ranged == nullptr)
            continue;
        auto c = std::make_unique<Control>();
        c->slider.setSliderStyle (juce::Slider::RotaryHorizontalVerticalDrag);
        c->slider.setTextBoxStyle (juce::Slider::TextBoxBelow, false, 90, 18);
        c->slider.setColour (juce::Slider::rotarySliderFillColourId, theme.accent);
        c->slider.setColour (juce::Slider::rotarySliderOutlineColourId, theme.ink.withAlpha (0.25f));
        c->slider.setColour (juce::Slider::textBoxTextColourId, theme.ink);
        c->slider.setColour (juce::Slider::textBoxOutlineColourId, juce::Colours::transparentBlack);
        c->slider.setTooltip (Params::tooltipFor (ranged->paramID.toRawUTF8()));
        c->slider.setHelpText (Params::tooltipFor (ranged->paramID.toRawUTF8()));
        c->slider.setTitle (ranged->getName (32));
        c->slider.setWantsKeyboardFocus (false);
        c->label.setText (ranged->getName (32), juce::dontSendNotification);
        c->label.setJustificationType (juce::Justification::centred);
        c->label.setColour (juce::Label::textColourId, theme.ink);
        c->attachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (processor.parameters(), ranged->paramID, c->slider);
        addAndMakeVisible (c->slider);
        addAndMakeVisible (c->label);
        controls.push_back (std::move (c));
    }
    setSize (juce::jmax (360, 60 + 110 * (int) controls.size()), 220);
}

void {{ProductId}}AudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (theme.bg);
}

void {{ProductId}}AudioProcessorEditor::resized()
{
    auto area = getLocalBounds().reduced (20);
    auto header = area.removeFromTop (32);
    title.setBounds (header.removeFromLeft (header.getWidth() / 2));
    version.setBounds (header);
    area.removeFromTop (12);
    int x = area.getX();
    for (auto& c : controls)
    {
        auto box = juce::Rectangle<int> (x, area.getY(), 100, area.getHeight());
        c->label.setBounds (box.removeFromTop (20));
        c->slider.setBounds (box);
        x += 110;
    }
}
