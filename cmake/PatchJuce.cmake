# Local fixes on the pinned JUCE, kept until upstream carries them; drop one when a JUCE
# bump does. CMakeLists.txt applies them to the FetchContent tree at configure time
# and only checks a FETCHCONTENT_SOURCE_DIR_JUCE checkout. Running again on a patched
# tree changes nothing; a JUCE that no longer has the original line stops the configure,
# so a bump cannot drop a fix silently. By hand, on any JUCE checkout:
#   cmake -DJUCE_DIR=/path/to/JUCE -P cmake/PatchJuce.cmake
# Every Oberli Audio repo carries this file; the template (Oberli-Audio/plugin-template) is its source.

function(oberli_patch_juce juce_dir mode)
    # 1. VST3 getMidiControllerAssignment indexes [channel][cc] unchecked. The Steinberg
    #    validator asks for cc 130 (kCountCtrlNumber) and JUCE read past the row: UBSan,
    #    2026-10-25 (EX-006). Unfixed in JUCE 8.0.16, develop and master on that date.
    set(file "${juce_dir}/modules/juce_audio_plugin_client/juce_audio_plugin_client_VST3.cpp")
    set(original "        resultID = midiControllerToParameter[channel][midiControllerNumber];")
    set(marker "Oberli Audio patch (cmake/PatchJuce.cmake)")
    set(fixed "        if (! isPositiveAndBelow (channel, (int) numMIDIChannels)\n            || ! isPositiveAndBelow (midiControllerNumber, (int) Vst::kCountCtrlNumber))\n            return kResultFalse; // ${marker}\n\n${original}")

    file(READ "${file}" content)
    string(FIND "${content}" "patch (cmake/PatchJuce.cmake)" at)   # ours, or the same fix applied by another family repo
    if (NOT at EQUAL -1)
        return()
    endif()

    string(REPLACE "${original}" "" without "${content}")
    string(LENGTH "${content}" len_with)
    string(LENGTH "${without}" len_without)
    string(LENGTH "${original}" len_line)
    math(EXPR count "(${len_with} - ${len_without}) / ${len_line}")
    if (NOT count EQUAL 1)
        message(FATAL_ERROR "cmake/PatchJuce.cmake: expected the getMidiControllerAssignment line once in ${file}, found ${count}. "
                            "If this JUCE fixed it upstream, drop the patch; otherwise update it.")
    endif()

    if (mode STREQUAL "CHECK_ONLY")
        message(FATAL_ERROR "JUCE at ${juce_dir} lacks the getMidiControllerAssignment bounds check. Apply it with:\n"
                            "  cmake -DJUCE_DIR=\"${juce_dir}\" -P \"${CMAKE_CURRENT_FUNCTION_LIST_DIR}/PatchJuce.cmake\"")
    endif()

    string(REPLACE "${original}" "${fixed}" content "${content}")
    file(WRITE "${file}" "${content}")
    message(STATUS "Patched JUCE: VST3 getMidiControllerAssignment bounds check")
endfunction()

if (CMAKE_SCRIPT_MODE_FILE STREQUAL CMAKE_CURRENT_LIST_FILE)
    if (NOT JUCE_DIR)
        message(FATAL_ERROR "usage: cmake -DJUCE_DIR=/path/to/JUCE -P cmake/PatchJuce.cmake")
    endif()
    oberli_patch_juce("${JUCE_DIR}" APPLY)
endif()
