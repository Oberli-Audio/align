"""dspkit - measurement functions for Oberli Audio plugin verification.

Reusable across products: every function takes numpy arrays (samples x channels, or
1-D mono) and a sample rate, and returns plain numbers or dicts, so a project's test
file stays a few lines around its offline renderer (see harness-contract.md).

Every function here is checked by test_dspkit.py against an analytic result or a
published standard test case (ITU-R BS.1770 coefficients, EBU Tech 3341/3342).
Run `python3 test_dspkit.py` after any change.

Requires numpy and scipy. Python 3.9+.
"""
import json
import os
import math
import subprocess
import sys

import numpy as np
from scipy import signal
from scipy.io import wavfile

__all__ = [
    "read_wav", "write_wav", "db", "undb", "as_2d",
    "peak_dbfs", "true_peak_dbtp", "rms_dbfs", "dc_offset_dbfs", "crest_factor_db",
    "k_weighting_sos", "loudness_blocks", "integrated_lufs", "momentary_max_lufs",
    "short_term_lufs", "loudness_range_lu",
    "null_residual", "latency_samples", "harmonic_profile", "thd_db",
    "schroeder_t60", "spectral_centroid_hz", "click_score", "repeat_variation",
    "stats", "block_time_report", "render", "assert_echo",
]

# ---------------------------------------------------------------- basics

def read_wav(path):
    """Return (x, fs) with x as float64 in [-1, 1], shape (n, channels)."""
    fs, x = wavfile.read(path)
    if x.dtype.kind == "i":
        x = x.astype(np.float64) / float(np.iinfo(x.dtype).max + 1)
    elif x.dtype.kind == "u":
        x = (x.astype(np.float64) - 128.0) / 128.0
    else:
        x = x.astype(np.float64)
    return as_2d(x), fs


def write_wav(path, x, fs):
    """Write float32 WAV (no clipping, no dither - this is for analysis, not delivery)."""
    wavfile.write(path, int(fs), as_2d(x).astype(np.float32))


def as_2d(x):
    x = np.asarray(x, dtype=np.float64)
    return x[:, None] if x.ndim == 1 else x


def db(x, floor=-400.0):
    x = np.asarray(x, dtype=np.float64)
    with np.errstate(divide="ignore"):
        out = 20.0 * np.log10(np.abs(x))
    return np.maximum(out, floor)


def undb(d):
    return 10.0 ** (np.asarray(d, dtype=np.float64) / 20.0)

# ---------------------------------------------------------------- levels

def peak_dbfs(x):
    return float(db(np.max(np.abs(as_2d(x)))))


def true_peak_dbtp(x, fs=None, oversample=4):
    """Inter-sample peak by polyphase interpolation (Kaiser-windowed FIR).

    BS.1770 specifies 4x with its own filter, which under-reads by up to 0.688 dB near
    Nyquist. Use oversample=4 to mimic a meter, oversample=16 to *verify* a ceiling.
    `fs` is accepted for symmetry and unused.
    """
    x = as_2d(x)
    pad = np.zeros((64, x.shape[1]))
    y = signal.resample_poly(np.vstack([pad, x, pad]), oversample, 1, axis=0,
                             window=("kaiser", 10.0))
    return float(db(np.max(np.abs(y))))


def rms_dbfs(x):
    """RMS of all channels together, in dBFS (a full-scale sine reads -3.01)."""
    x = as_2d(x)
    return float(db(math.sqrt(float(np.mean(x ** 2)))))


def dc_offset_dbfs(x):
    return float(np.max(db(np.mean(as_2d(x), axis=0))))


def crest_factor_db(x):
    return peak_dbfs(x) - rms_dbfs(x)

# ---------------------------------------------------------------- loudness (ITU-R BS.1770 / EBU R128)

def k_weighting_sos(fs):
    """K-weighting designed for any sample rate from the BS.1770 prototype.

    Same derivation as libebur128: at 48 kHz it reproduces the coefficients printed in
    BS.1770 (checked in test_dspkit.py); at other rates it is the matched redesign that
    rule 17 requires instead of reusing the 48 kHz numbers.
    """
    # Stage 1: high shelf
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / fs)
    Vh = 10.0 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    b = [(Vh + Vb * K / Q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    # Stage 2: RLB high-pass
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / fs)
    a0 = 1.0 + K / Q + K * K
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    return np.array([b + a, b2 + a2])


def loudness_blocks(x, fs, block_s=0.4, hop_s=0.1, weights=None):
    """Loudness of each gating block in LUFS. Channel weights default to 1.0 (L, R, C)."""
    x = as_2d(x)
    y = signal.sosfilt(k_weighting_sos(fs), x, axis=0)
    n_block, n_hop = int(round(block_s * fs)), int(round(hop_s * fs))
    if len(y) < n_block:
        return np.array([])
    w = np.ones(x.shape[1]) if weights is None else np.asarray(weights, dtype=np.float64)
    sq = np.cumsum(np.vstack([np.zeros((1, y.shape[1])), y ** 2]), axis=0)
    starts = np.arange(0, len(y) - n_block + 1, n_hop)
    z = (sq[starts + n_block] - sq[starts]) / n_block              # mean square per channel
    power = z @ w
    with np.errstate(divide="ignore"):
        return -0.691 + 10.0 * np.log10(power)


def integrated_lufs(x, fs, weights=None):
    """BS.1770-5 integrated loudness: 400 ms blocks, 75 % overlap, -70 LUFS absolute
    gate, -10 LU relative gate."""
    lk = loudness_blocks(x, fs, 0.4, 0.1, weights)
    lk = lk[lk > -70.0]
    if lk.size == 0:
        return float("-inf")
    rel = 10.0 * np.log10(np.mean(10.0 ** (lk / 10.0))) - 10.0
    gated = lk[lk > rel]
    return float(10.0 * np.log10(np.mean(10.0 ** (gated / 10.0))))


def momentary_max_lufs(x, fs, weights=None):
    lk = loudness_blocks(x, fs, 0.4, 0.1, weights)
    return float(np.max(lk)) if lk.size else float("-inf")


def short_term_lufs(x, fs, hop_s=0.1, weights=None):
    """Short-term loudness series (3 s window) at the given hop."""
    return loudness_blocks(x, fs, 3.0, hop_s, weights)


def loudness_range_lu(x, fs, weights=None):
    """EBU Tech 3342 loudness range: short-term values gated at -70 LUFS absolute and
    -20 LU relative; LRA = 95th minus 10th percentile."""
    st = short_term_lufs(x, fs, 0.1, weights)
    st = st[st > -70.0]
    if st.size == 0:
        return 0.0
    rel = 10.0 * np.log10(np.mean(10.0 ** (st / 10.0))) - 20.0
    st = st[st > rel]
    return float(np.percentile(st, 95) - np.percentile(st, 10))

# ---------------------------------------------------------------- comparison

def null_residual(a, b, align=True, max_lag=48000):
    """Residual of b against a. Returns dict: residual_dbfs (RMS of a-b), peak_dbfs (peak of
    a-b; the F.8 golden tolerances are stated on this), relative_db (residual RMS relative to
    a's RMS), lag (samples b was shifted by). Goldens compare with align=False, so a latency
    change fails."""
    a, b = as_2d(a), as_2d(b)
    lag = 0
    if align:
        lag = latency_samples(a[:, 0], b[:, 0], max_lag=max_lag)
        if lag > 0:
            b = b[lag:]
        elif lag < 0:
            a = a[-lag:]
    n = min(len(a), len(b))
    d = a[:n] - b[:n]
    res = math.sqrt(float(np.mean(d ** 2))) if n else 0.0
    ref = math.sqrt(float(np.mean(a[:n] ** 2))) if n else 0.0
    pk = float(np.max(np.abs(d))) if n else 0.0
    return {"residual_dbfs": float(db(res)), "peak_dbfs": float(db(pk)),
            "relative_db": float(db(res) - db(ref)) if ref > 0 else float("nan"),
            "lag": int(lag)}


def latency_samples(reference, delayed, max_lag=48000):
    """Integer delay of `delayed` relative to `reference`, by cross-correlation."""
    r = np.asarray(reference, dtype=np.float64).ravel()
    d = np.asarray(delayed, dtype=np.float64).ravel()
    n = len(r) + len(d) - 1
    nfft = 1 << (n - 1).bit_length()
    xc = np.fft.irfft(np.fft.rfft(d, nfft) * np.conj(np.fft.rfft(r, nfft)), nfft)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    vals = np.concatenate([xc[:max_lag + 1], xc[nfft - max_lag:]])
    return int(lags[int(np.argmax(np.abs(vals)))])

# ---------------------------------------------------------------- distortion

def harmonic_profile(x, fs, f0, n_harmonics=10):
    """Level of harmonics 2..n relative to the fundamental, in dB, from a
    Blackman-Harris-windowed FFT of a steady tone (use >= 0.5 s of signal)."""
    x = as_2d(x)[:, 0]
    w = signal.windows.blackmanharris(len(x))
    spec = np.abs(np.fft.rfft(x * w))
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)

    def level(f):
        if f >= fs / 2:
            return 0.0
        k = int(round(f * len(x) / fs))
        lo, hi = max(k - 4, 0), min(k + 5, len(spec))
        return float(np.sqrt(np.sum(spec[lo:hi] ** 2)))     # energy over the main lobe

    fund = level(f0)
    out = {}
    for h in range(2, n_harmonics + 1):
        if h * f0 < fs / 2:
            out["H%d" % h] = float(db(level(h * f0) / fund)) if fund > 0 else float("nan")
    return out


def thd_db(x, fs, f0, n_harmonics=10):
    """THD (harmonics only, not noise) in dB relative to the fundamental."""
    prof = harmonic_profile(x, fs, f0, n_harmonics)
    total = sum(10.0 ** (v / 10.0) for v in prof.values())
    return float(10.0 * math.log10(total)) if total > 0 else float("-inf")

# ---------------------------------------------------------------- time and spectrum

def schroeder_t60(ir, fs, fit_db=(-5.0, -25.0)):
    """t60 from the Schroeder energy decay curve, by a line fit between fit_db levels
    (T20 by default; use (-5, -35) for T30). Band-filter the IR first for per-band t60."""
    h = as_2d(ir)[:, 0]
    edc = np.cumsum(h[::-1] ** 2)[::-1]
    edc_db = 10.0 * np.log10(edc / edc[0] + 1e-300)
    hi, lo = fit_db
    idx = np.where((edc_db <= hi) & (edc_db >= lo))[0]
    if idx.size < 2:
        return float("nan")
    t = idx / fs
    slope, _ = np.polyfit(t, edc_db[idx], 1)
    return float(-60.0 / slope) if slope < 0 else float("inf")


def spectral_centroid_hz(x, fs):
    x = as_2d(x).mean(axis=1)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    return float(np.sum(freqs * spec) / np.sum(spec)) if np.sum(spec) > 0 else 0.0


def click_score(x, fs, hp_hz=8000.0):
    """Largest high-passed sample relative to the full-band RMS, in dB.

    A smooth tonal signal with little content above hp_hz reads very low (a 220 Hz sine:
    below -80 dB); a discontinuity reads near or above -30 dB. Material with real
    high-frequency content reads higher, so compare against a known-clean render of the
    same material rather than using an absolute threshold.
    """
    x = as_2d(x).mean(axis=1)
    sos = signal.butter(4, hp_hz, "highpass", fs=fs, output="sos")
    y = signal.sosfilt(sos, x)
    rms = math.sqrt(float(np.mean(x ** 2)))
    return float(db(np.max(np.abs(y)) / rms)) if rms > 0 else float("-inf")

def repeat_variation(segments, fs, env_window_s=0.1):
    """How much repeated renders of the same event differ - the "sterile" descriptor
    (playbook I.1, A.6). `segments`: equal-length arrays, one per repeat, aligned at
    the event's onset.

    Returns, over all pairs:
      min_residual_db   the most similar pair's residual (a - b) relative to a, in dB:
                        about +3 dB for uncorrelated waveforms, very low for repeats
                        that are (nearly) identical
      max_level_diff_db the largest difference in mean level between repeats
      max_env_diff_db   the largest short-term (env_window_s) envelope difference
    """
    segs = [as_2d(s) for s in segments]
    n = min(len(s) for s in segs)
    segs = [s[:n] for s in segs]
    w = max(1, int(env_window_s * fs))

    def env(s):
        m = s.mean(axis=1)[: (n // w) * w].reshape(-1, w)
        return 20.0 * np.log10(np.sqrt(np.mean(m ** 2, axis=1)) + 1e-12)

    envs = [env(s) for s in segs]
    res, lvl, envd = [], [], []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            res.append(null_residual(segs[i], segs[j], align=False)["relative_db"])
            lvl.append(abs(rms_dbfs(segs[i]) - rms_dbfs(segs[j])))
            envd.append(float(np.max(np.abs(envs[i] - envs[j]))))
    return {"pairs": len(res), "min_residual_db": float(min(res)),
            "max_level_diff_db": float(max(lvl)), "max_env_diff_db": float(max(envd))}

# ---------------------------------------------------------------- statistics and CPU

def stats(values):
    """Median, worst (max), best (min) and spread of repeated measurements (F.13.9)."""
    v = np.asarray(list(values), dtype=np.float64)
    return {"n": int(v.size), "median": float(np.median(v)), "max": float(np.max(v)),
            "min": float(np.min(v)), "spread": float(np.max(v) - np.min(v))}


def block_time_report(block_times_s, block_size, fs, warmup=0):
    """Rule 20: block time against the deadline N / fs, as the harness contract's `profile`.

    warmup blocks are excluded from the distribution; the very first block is reported
    separately as first_block_pct (cold start, D.2.1). over_deadline counts blocks above
    100 % after warm-up; worst_block_at_s is where the maximum fell, so a recurring
    maximum (DSP) can be told from a moving one (scheduling)."""
    t = np.asarray(block_times_s, dtype=np.float64)
    deadline = block_size / float(fs)
    pct_all = 100.0 * t / deadline
    first = float(pct_all[0]) if t.size else 0.0
    w = int(min(max(warmup, 0), max(t.size - 1, 0)))
    pct = pct_all[w:]
    worst = int(np.argmax(pct)) + w if pct.size else 0
    return {"deadline_ms": 1000.0 * deadline, "p50_pct": float(np.percentile(pct, 50)),
            "p99_pct": float(np.percentile(pct, 99)), "p999_pct": float(np.percentile(pct, 99.9)),
            "max_pct": float(np.max(pct)), "worst_block_at_s": float(worst * block_size / float(fs)),
            "over_deadline": int(np.sum(pct > 100.0)), "blocks": int(pct.size),
            "first_block_pct": first, "warmup_blocks": w}


def max_click_db(x, fs=None):
    """Largest sample-to-sample step relative to the signal's peak, in dB (contract `max_click_db`).

    Method: 20 log10 (max |x[n] - x[n-1]| / max |x|), over all channels. Smooth material at
    48 kHz reads well below -20 dB (a 220 Hz sine: about -31 dB); a discontinuity or polarity
    flip reads between -6 and +6 dB. Absolute, so it compares across presets; `click_score`
    stays the relative, high-passed measure for A/B against a clean render."""
    x = as_2d(x)
    pk = float(np.max(np.abs(x))) if x.size else 0.0
    if pk <= 0.0:
        return float("-inf")
    step = float(np.max(np.abs(np.diff(x, axis=0)))) if x.shape[0] > 1 else 0.0
    return float(db(step / pk))

def dropout_db(ref, x, fs, win_s=0.005, floor_dbfs=-60.0):
    """Largest level drop of x against ref over short windows, in dB (positive = x quieter).

    Both signals framed into win_s windows; windows where ref is below floor_dbfs are ignored
    (silence is allowed to differ). A block-size bug that renders part of a block silent shows
    as a drop of 20 dB or more in one window while the whole-file RMS barely moves; that is why
    this is windowed. Returns 0.0 when x is never quieter than ref."""
    ref, x = as_2d(ref), as_2d(x)
    n = min(ref.shape[0], x.shape[0])
    w = max(int(win_s * fs), 8)
    worst = 0.0
    for i in range(0, n - w + 1, w):
        r = float(np.sqrt(np.mean(ref[i:i + w] ** 2)))
        if r <= 0 or db(r) < floor_dbfs:
            continue
        s = float(np.sqrt(np.mean(x[i:i + w] ** 2)))
        worst = max(worst, float(db(r) - db(max(s, 1e-12))))
    return worst


# ---------------------------------------------------------------- harness contract

ARCH = None   # set to "x86_64" (perf.py --arch, presetlint --arch, DSPKIT_ARCH) to run a native harness under Rosetta


def harness_cmd(harness):
    """The command that starts the harness. On macOS, when ARCH names a slice other than the one
    Python runs on, the harness is started through `arch -<slice>`; Python itself stays native
    (numpy is arm64-only on an Apple Silicon machine, so `arch -x86_64 python3` cannot work)."""
    cmd = [sys.executable, str(harness)] if str(harness).endswith(".py") else [str(harness)]
    import platform
    want = ARCH or os.environ.get("DSPKIT_ARCH")
    if want and sys.platform == "darwin" and want != platform.machine():
        cmd = ["arch", "-" + want] + cmd
    return cmd


def render(harness, params=None, **flags):
    """Run an offline renderer that follows harness-contract.md; return its JSON.

    params: {"id": value} -> repeated --param=id=value flags.
    flags:  seed=1, sample_rate=48000, block=64, preset="...", notes="60,64", out="x.wav";
            a flag whose value is a list is repeated (preset_at=["30:warm", "40:edge"]).
    Exit 3 (NaN/Inf, contract) returns the JSON with res["_exit"] = 3 so a test can assert
    on health; any other failure raises.
    """
    cmd = harness_cmd(harness)
    for k, v in flags.items():
        for one in (v if isinstance(v, (list, tuple)) else [v]):
            cmd.append("--%s=%s" % (k.replace("_", "-"), one))
    for k, v in (params or {}).items():
        cmd.append("--param=%s=%s" % (k, v))
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode == 3 and out.stdout.strip().startswith("{"):
        res = json.loads(out.stdout)
        res["_exit"] = 3
        return res
    if out.returncode != 0:
        raise RuntimeError("harness failed (%d): %s\n%s" % (out.returncode, " ".join(cmd), out.stderr))
    return json.loads(out.stdout)


def list_presets(harness):
    """`--list-presets` as the contract defines it: [{"slug", "name", "category"}, ...]."""
    cmd = harness_cmd(harness) + ["--list-presets"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def assert_echo(result, params=None, arch=None, **flags):
    """Rule 13: the harness echoes what it rendered; fail if it differs from the request.
    arch: the slice this render must come from (applied.build.arch), e.g. "x86_64" (D.2.1)."""
    echo = result.get("applied", {})
    if arch is not None and echo.get("build", {}).get("arch") != arch:
        raise AssertionError("render came from arch %r, expected %r" % (echo.get("build", {}).get("arch"), arch))
    for k, v in (params or {}).items():
        got = echo.get("params", {}).get(k)
        if got is None or abs(float(got) - float(v)) > 1e-6:
            raise AssertionError("harness applied %s=%r, asked for %r" % (k, got, v))
    for k, v in flags.items():
        got = echo.get(k)
        if got is not None and str(got) != str(v):
            raise AssertionError("harness applied %s=%r, asked for %r" % (k, got, v))
    return True


# ---------------------------------------------------------------- command line

def smoke(harness, arch=None):
    """`dspkit.py smoke <harness> [--arch x86_64]`: the contract's minimum, in one go. Lists the presets,
    renders one second of the first preset at 48 k/64 with a profile, checks the echo (rule 13), the
    arch, and that the output is finite and not silent. The real harness passes this before
    presetlint and perf are worth running."""
    global ARCH
    if arch:
        ARCH = arch
    presets = list_presets(harness)
    assert presets and all(k in presets[0] for k in ("slug", "name", "category")), "--list-presets must return [{slug,name,category}]"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "s.wav")
        flags = dict(seed=1, sample_rate=48000, block=64, seconds=1.0, profile=1, out=out, preset=presets[0]["slug"], notes="60,64")
        res = render(harness, **flags)       # --notes is a contract flag; an effect harness renders its own test input and echoes it
        assert_echo(res, arch=arch, seed=1, sample_rate=48000, block=64)
        x, fs = read_wav(out)
        assert fs == 48000, "wrote %d Hz, asked 48000" % fs
        assert np.isfinite(x).all(), "NaN/Inf in the render"
        assert float(np.max(np.abs(x))) > 1e-6, "silent render of the first preset"
        for k in ("p999_pct", "max_pct", "over_deadline", "worst_block_at_s", "first_block_pct"):
            assert k in res.get("profile", {}), "profile lacks %s (contract v3)" % k
        assert res.get("applied", {}).get("build", {}).get("arch"), "applied.build.arch missing"
    print("dspkit smoke OK: %d presets, %s rendered on %s, profile p99.9 %.1f %%" % (
        len(presets), presets[0]["slug"], res["applied"]["build"]["arch"], res["profile"]["p999_pct"]))
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="dspkit: a library; `smoke <harness>` checks a harness against the contract")
    ap.add_argument("cmd", choices=("smoke",))
    ap.add_argument("harness")
    ap.add_argument("--arch", help="the slice the host runs (x86_64 under Rosetta); the harness is started under arch -<slice>")
    a = ap.parse_args()
    sys.exit(smoke(a.harness, a.arch))
