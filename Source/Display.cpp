#include "Params.h"

/*  Align - the value strings parameters.csv marks `format_kind=custom` (paramgen's hook; the
    declaration is in the generated Params.h). One translation unit, as paramgen asks.

    rotate   degrees with the degree sign ("90°"): the table's unit list has no degree, and the
             CSV's note says the editor shows it. Parses "90", "90°", "90 deg".
*/
namespace Params::Display
{
juce::String custom (const char* id, float raw)
{
    if (juce::String (id) == "rotate")
        return juce::String (juce::roundToInt (raw)) + juce::String::fromUTF8 ("\xc2\xb0");
    return juce::String (raw, 2);
}

float parse (const char* id, const juce::String& text)
{
    juce::ignoreUnused (id);
    return text.trim().replace (",", ".").retainCharacters ("0123456789.-+").getFloatValue();
}
} // namespace Params::Display
