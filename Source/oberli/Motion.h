#pragma once

// Oberli Audio shared code (Source/oberli/): byte-copied from ~/bob-skills, never edited in a plugin repo.

#include <juce_gui_basics/juce_gui_basics.h>

#include <cmath>

namespace oberli::ui::motion
{

/** The repaint interval for motion that runs on its own while you play -
    meters, level displays, analysis curves: about 30 fps. Light that
    follows a sound does not need 60, and the editor's continuous painting
    halves. Interactive motion (a knob under the mouse, a glide after a
    recall) keeps the full frame rate. Slightly under 1/30 s, so on a 60 Hz
    display every second frame qualifies despite timing jitter. */
constexpr double kAmbientFrameSeconds = 0.03;

/**
    A critically damped spring: eases toward its target from rest, without
    overshoot - the motion behind every glide in the editor (knobs after a
    preset recall, a fade). Stepped with the exact solution of the
    spring equation, so it is stable at any frame rate and frame drops only
    skip ahead.

    `omega` (rad/s) sets the speed: a jump of any size is 95% done after
    4.7 / omega seconds (omega 12: 0.4 s, omega 5: about 1 s).
*/
struct Spring
{
    float value = 0.0f, velocity = 0.0f, target = 0.0f;

    void snapTo (float v) noexcept { value = target = v; velocity = 0.0f; }

    bool isSettled() const noexcept { return juce::exactlyEqual (value, target) && juce::exactlyEqual (velocity, 0.0f); }

    /** Advances by dt seconds. Returns true if the value moved; lands exactly
        on the target once within `epsilon` of it, so a finished glide stops
        asking for repaints. */
    bool advance (float dt, float omega, float epsilon = 1.0e-3f) noexcept
    {
        if (isSettled())
            return false;

        const auto x0 = value - target;
        const auto c = velocity + omega * x0;
        const auto e = std::exp (-omega * dt);
        const auto x = (x0 + c * dt) * e;

        velocity = (velocity - omega * c * dt) * e;
        value = target + x;

        if (std::abs (x) < epsilon && std::abs (velocity) < epsilon * omega)
        {
            value = target;
            velocity = 0.0f;
        }

        return true;
    }
};

/**
    A one-pole follower with separate rise and fall times - meter ballistics,
    and the fades for hover, highlights and the preset title.
*/
struct Follower
{
    float value = 0.0f;

    /** Moves toward `target` (time constants in seconds). Returns true if the
        value changed; lands exactly on the target once within `epsilon`. */
    bool advance (float target, float dt, float riseSeconds, float fallSeconds,
                  float epsilon = 1.0e-3f) noexcept
    {
        if (juce::exactlyEqual (value, target))
            return false;

        const auto tau = juce::jmax (1.0e-4f, target > value ? riseSeconds : fallSeconds);
        auto next = value + (target - value) * (1.0f - std::exp (-dt / tau));

        if (std::abs (target - next) < epsilon)
            next = target;

        value = next;
        return true;
    }
};

} // namespace oberli::ui::motion
