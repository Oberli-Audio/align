#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include "PluginProcessor.h"

/*  {{Product}} - the editor.

    The template's editor is a placeholder: the {{theme}} background, the product name, one
    slider per parameter with the table's tooltips, the version. plugin-ui-bob builds the real
    editor from the Oberli Audio brand sheet at G2 (Strip layout, the knob of the logo, Rubik, the
    preset drawer, About on the back) and replaces this file; the processor interface stays. */
class {{ProductId}}AudioProcessorEditor final : public juce::AudioProcessorEditor
{
public:
    explicit {{ProductId}}AudioProcessorEditor ({{ProductId}}AudioProcessor&);
    ~{{ProductId}}AudioProcessorEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    {{ProductId}}AudioProcessor& processor;
    juce::TooltipWindow tooltips { this, 500 };
    struct Control
    {
        juce::Slider slider;
        juce::Label label;
        std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> attachment;
    };
    std::vector<std::unique_ptr<Control>> controls;
    juce::Label title, version;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR ({{ProductId}}AudioProcessorEditor)
};
