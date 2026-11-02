#pragma once

#include <juce_core/juce_core.h>

/*  Align - LinearFade, the one crossfade position every switch on the path uses (polarity, bypass,
    Listen, Rotate's bypass), mirroring "sound design"/fade.py.

    A change of target starts a straight line from wherever the fade is to the new target, over the
    full length, and the last sample lands on the target exactly. The position is the closed form
    `start + step * done`, so it does not depend on how the host cuts the stream into blocks, and
    several fades started together stay amplitude-complementary at every sample (their steps sum to
    zero). docs/failures.md 2026-11-03: a step re-derived from the *remaining distance* at every block
    made each fade geometric, so it depended on the block size and, in float, stalled about 2e-5 short
    of its target for good.
*/
namespace align::dsp
{
struct LinearFade
{
    void prepare (int lengthSamples, float initial) noexcept
    {
        length = juce::jmax (1, lengthSamples);
        snap (initial);
    }

    /** Jump to `v` with no fade (prepare, reset). */
    void snap (float v) noexcept
    {
        value = target = start = v;
        step = 0.0f;
        done = length;
    }

    void setTarget (float t) noexcept
    {
        if (juce::exactlyEqual (t, target))
            return;
        start = value;
        target = t;
        step = (t - value) / (float) length;
        done = 0;
    }

    bool idle() const noexcept { return done >= length; }

    /** The position for the next sample. */
    float next() noexcept
    {
        if (done < length)
        {
            ++done;
            value = done >= length ? target : start + step * (float) done;
        }
        return value;
    }

    float value = 0.0f, target = 0.0f;

private:
    float start = 0.0f, step = 0.0f;
    int length = 1, done = 1;
};
} // namespace align::dsp
