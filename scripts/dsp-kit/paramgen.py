#!/usr/bin/env python3
"""paramgen - the parameter table as a mechanism, not a convention (joint workflow, D.5.2).

Reads a product's `parameters.csv` (columns defined in `joint-plugin-workflow.md`) and:

    paramgen.py juce     parameters.csv [-o Parameters.h]   JUCE parameter layout + value strings
    paramgen.py manual   parameters.csv [-o parameters.md]  manual section and tooltip table
    paramgen.py check    parameters.csv [--list-params p.json] [--frozen last_release.csv]
                                                            table lint, value-string round trip in the
                                                            C and de_CH locales, harness diff, ID freeze
    paramgen.py selftest                                    runs the built-in checks on the sample table

Exit codes: 0 ok, 1 check failed, 2 bad arguments or an invalid table.
Pure Python 3.8+, no dependencies. The C++ it writes needs JUCE 8.0.11 or newer (the pinned minimum, ship-bob notices.md).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import locale
import math
import re
import sys
from pathlib import Path

CONTRACT = 1
TYPES = {"float", "int", "choice", "bool"}
KINDS = {"plain", "macro", "modtarget", "bypass"}
FORMAT_KINDS = {"time", "hz", "db", "percent", "cents", "semitones", "note", "ratio",
                "choice", "bool", "plain", "custom"}   # custom: the project supplies Display::custom (id, v) and parse
SMOOTHING_DOMAINS = {"linear", "log", "db", "crossfade", ""}
CONTROL_RATES = {"sample", "block", "event", ""}
REQUIRED = ["id", "name", "type", "min", "max", "default"]          # Tier S minimum
OPTIONAL_DEFAULTS = {
    "version_added": "1", "kind": "plain", "short": "", "group": "", "core": "N", "unit": "",
    "centre": "", "bipolar": "N", "choices": "", "steps": "", "format_kind": "", "precision": "",
    "parse_aliases": "", "automatable": "Y", "smoothing": "", "smoothing_domain": "",
    "control_rate": "block", "meaning": "", "tooltip": "", "notes": "",
    "display_scale": "",   # shown value = raw * display_scale (raw 0..1 shown as 0..100 %: 100); default 1
}
ID_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class TableError(Exception):
    pass


# ----------------------------------------------------------------------------- reading

def read_table(path: Path | str | io.TextIOBase) -> list[dict]:
    """Read parameters.csv, fill Tier S defaults, validate. Raises TableError."""
    if isinstance(path, io.TextIOBase):
        rows = list(csv.DictReader(path))
    else:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    if not rows:
        raise TableError("empty table")
    header = list(rows[0].keys())
    dup = {c for c in header if header.count(c) > 1}
    if dup:
        raise TableError(f"duplicate column(s): {sorted(dup)}")
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise TableError(f"missing required column(s): {missing}")
    params, ids, errors = [], set(), []
    for n, raw in enumerate(rows, start=2):
        p = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        for k, d in OPTIONAL_DEFAULTS.items():
            p.setdefault(k, d)
            if p[k] == "":
                p[k] = d
        where = f"row {n} ({p.get('id') or '?'})"
        if not ID_RE.match(p["id"]):
            errors.append(f"{where}: id must be lowerCamel ASCII, got {p['id']!r}")
        if p["id"] in ids:
            errors.append(f"{where}: duplicate id")
        ids.add(p["id"])
        if p["type"] not in TYPES:
            errors.append(f"{where}: type must be one of {sorted(TYPES)}")
            continue
        if p["kind"] not in KINDS:
            errors.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if p["type"] == "choice":
            p["choice_list"] = [c.strip() for c in p["choices"].split("|") if c.strip()]
            if len(p["choice_list"]) < 2:
                errors.append(f"{where}: choice needs at least two names in `choices`")
            p["min"], p["max"] = "0", str(max(len(p["choice_list"]) - 1, 1))
            p["steps"] = str(len(p["choice_list"]))
            p["format_kind"] = p["format_kind"] or "choice"
        elif p["type"] == "bool":
            p["min"], p["max"] = "0", "1"
            p["steps"] = "2"
            p["format_kind"] = p["format_kind"] or "bool"
        try:
            p["fmin"], p["fmax"], p["fdefault"] = float(p["min"]), float(p["max"]), float(p["default"])
        except ValueError:
            errors.append(f"{where}: min/max/default must be numbers")
            continue
        if not p["fmin"] < p["fmax"]:
            errors.append(f"{where}: min must be below max")
        if not p["fmin"] <= p["fdefault"] <= p["fmax"]:
            errors.append(f"{where}: default outside range")
        if p["centre"]:
            try:
                p["fcentre"] = float(p["centre"])
            except ValueError:
                errors.append(f"{where}: centre must be a number")
                p["fcentre"] = None
            else:
                if not p["fmin"] < p["fcentre"] < p["fmax"]:
                    errors.append(f"{where}: centre must lie strictly inside the range")
        else:
            p["fcentre"] = None
        p["nsteps"] = int(p["steps"] or 0)
        if p["type"] == "int" and p["nsteps"] == 0:
            p["nsteps"] = int(round(p["fmax"] - p["fmin"])) + 1
        if p["format_kind"] == "":
            p["format_kind"] = _guess_format(p)
        if p["format_kind"] not in FORMAT_KINDS:
            errors.append(f"{where}: format_kind must be one of {sorted(FORMAT_KINDS)}")
        try:
            p["fscale"] = float(p["display_scale"]) if str(p["display_scale"]).strip() else 1.0
            if p["fscale"] <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"{where}: display_scale must be a positive number")
            p["fscale"] = 1.0
        if p["smoothing_domain"] not in SMOOTHING_DOMAINS:
            errors.append(f"{where}: smoothing_domain must be one of {sorted(SMOOTHING_DOMAINS - {''})}")
        if p["control_rate"] not in CONTROL_RATES:
            errors.append(f"{where}: control_rate must be one of {sorted(CONTROL_RATES - {''})}")
        if p["smoothing"] == "":
            p["smoothing"] = "0" if p["type"] != "float" else "20"
        try:
            p["fsmoothing"] = float(p["smoothing"])
        except ValueError:
            errors.append(f"{where}: smoothing must be a number of ms (0 = none)")
            p["fsmoothing"] = 0.0
        if p["type"] != "float" and p["fsmoothing"] != 0:
            errors.append(f"{where}: {p['type']} parameters are never smoothed (rule 2, Law 5); set smoothing to 0")
        if p["type"] != "float" and p["smoothing_domain"] not in ("", "crossfade"):
            errors.append(f"{where}: {p['type']} parameters switch by crossfade, not {p['smoothing_domain']}")
        try:
            p["iversion"] = int(p["version_added"])
            if p["iversion"] < 1:
                raise ValueError
        except ValueError:
            errors.append(f"{where}: version_added must be an integer >= 1")
            p["iversion"] = 1
        p["precision_n"] = int(p["precision"]) if p["precision"] else _default_precision(p)
        p["aliases"] = [a.strip() for a in p["parse_aliases"].split("|") if a.strip()]
        for yn in ("core", "bipolar", "automatable"):
            if p[yn] not in ("Y", "N"):
                errors.append(f"{where}: {yn} must be Y or N")
        params.append(p)
    bypass = [p for p in params if p["kind"] == "bypass"]
    if len(bypass) > 1:
        errors.append("more than one bypass row")
    for b in bypass:
        if b["id"] != "bypass" or b["type"] != "bool":
            errors.append("the bypass row must have id `bypass` and type bool")
    if any(p["id"] in ("bypass",) and p["kind"] != "bypass" for p in params):
        errors.append("a row with id `bypass` must have kind `bypass`")
    # VST3 ParamID hash collision check (JUCE's hash of the string id, top bit cleared)
    hashes = {}
    for p in params:
        h = juce_vst3_param_id(p["id"])
        if h in hashes:
            errors.append(f"VST3 ParamID hash collision: {p['id']} and {hashes[h]} (rename one before the first release)")
        hashes[h] = p["id"]
    if errors:
        raise TableError("\n".join(errors))
    return params


def _guess_format(p):
    u = p["unit"].lower()
    return {"s": "time", "ms": "time", "hz": "hz", "khz": "hz", "db": "db", "%": "percent",
            "ct": "cents", "st": "semitones", "note": "note"}.get(u, "plain")


def _default_precision(p):
    return {"time": 2, "hz": 1, "db": 1, "percent": 0, "cents": 0, "semitones": 0,
            "note": 0, "ratio": 2, "plain": 2, "choice": 0, "bool": 0, "custom": 2}[p["format_kind"]]


def juce_vst3_param_id(sid: str) -> int:
    """JUCE's string hash for VST3 ParamIDs (juce::String::hashCode, top bit cleared)."""
    h = 0
    for ch in sid:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h & 0x7FFFFFFF


# ----------------------------------------------------------------------------- mapping

def skew_from_centre(p) -> float:
    """JUCE NormalisableRange skew such that `centre` sits at 0.5 of travel."""
    if p["fcentre"] is None:
        return 1.0
    return math.log(0.5) / math.log((p["fcentre"] - p["fmin"]) / (p["fmax"] - p["fmin"]))


def to_normalised(p, v: float) -> float:
    x = (v - p["fmin"]) / (p["fmax"] - p["fmin"])
    s = skew_from_centre(p)
    return x ** s if s != 1.0 else x


def from_normalised(p, n: float) -> float:
    s = skew_from_centre(p)
    x = n ** (1.0 / s) if s != 1.0 else n
    v = p["fmin"] + x * (p["fmax"] - p["fmin"])
    return snap(p, v)


def snap(p, v: float) -> float:
    v = min(max(v, p["fmin"]), p["fmax"])
    if p["nsteps"] > 1:
        step = (p["fmax"] - p["fmin"]) / (p["nsteps"] - 1)
        v = p["fmin"] + round((v - p["fmin"]) / step) * step
    return v


# ----------------------------------------------------------------------------- value strings
# One function and its inverse per parameter, used by GUI, host, tests and the generated C++
# (rule: one stringFromValue and one valueFromString; audio-plugins.md 4).

def _fmt(x: float, n: int) -> str:
    s = f"{x:.{n}f}"
    return s


def string_from_value(p, v: float) -> str:
    k, n = p["format_kind"], p["precision_n"]
    v = snap(p, v)
    sign = "+" if (p["bipolar"] == "Y" and v > 0) else ""
    if k == "choice":
        return p["choice_list"][int(round(v))]
    if k == "bool":
        return "On" if v >= 0.5 else "Off"
    if k == "custom":        # the project's hook owns the text; the table only knows the raw value
        return f"{sign}{_fmt(v * p['fscale'], n)}{(' ' + p['unit']) if p['unit'] else ''}"
    v = v * p["fscale"]      # display scale: raw 0..1 shown as 0..100 %
    if k == "time":          # table values in seconds (unit s) or ms (unit ms); display switches
        secs = v / 1000.0 if p["unit"].lower() == "ms" else v
        if abs(secs) < 1.0:
            return f"{sign}{_fmt(secs * 1000.0, max(n - 2, 0))} ms"
        return f"{sign}{_fmt(secs, n)} s"
    if k == "hz":
        if abs(v) >= 1000.0:
            return f"{sign}{_fmt(v / 1000.0, n + 1)} kHz"
        return f"{sign}{_fmt(v, n)} Hz"
    if k == "db":
        if v <= p["fmin"] and p["fmin"] <= -96.0:
            return "-inf dB"
        return f"{sign}{_fmt(v, n)} dB"
    if k == "percent":
        return f"{sign}{_fmt(v, n)} %"
    if k == "cents":
        return f"{sign}{_fmt(v, n)} ct"
    if k == "semitones":
        return f"{sign}{_fmt(v, n)} st"
    if k == "note":
        m = int(round(v))
        return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"
    if k == "ratio":
        return f"{_fmt(v, n)}:1"
    unit = f" {p['unit']}" if p["unit"] else ""
    return f"{sign}{_fmt(v, n)}{unit}"


_NUM = re.compile(r"^\s*([+-]?)(\d+(?:[.,]\d*)?|[.,]\d+)\s*([a-zA-Z%:/]*)\s*$")


def value_from_string(p, text: str) -> float | None:
    """Inverse of string_from_value: accepts the display text, bare numbers, unit aliases and
    the table's parse_aliases ('2k', '-6', 'off'); decimal comma as well as point; returns the
    snapped value, or None when the text is not understood."""
    k = p["format_kind"]
    t = text.strip()
    if k == "choice":
        for i, name in enumerate(p["choice_list"]):
            if t.lower() == name.lower() or t == str(i):
                return float(i)
        return None
    if k == "bool":
        if t.lower() in ("on", "1", "true", "yes", "ja"):
            return 1.0
        if t.lower() in ("off", "0", "false", "no", "nein"):
            return 0.0
        return None
    if k == "note":
        m = re.match(r"^([A-Ga-g])([#b]?)(-?\d+)$", t)
        if m:
            base = NOTE_NAMES.index(m.group(1).upper() + ("#" if m.group(2) == "#" else ""))
            if m.group(2) == "b":
                base -= 1
            return snap(p, float((int(m.group(3)) + 1) * 12 + base))
    if t.lower() in ("-inf", "-inf db", "off") and k == "db":
        return p["fmin"]
    m = _NUM.match(t)
    if not m:
        return None
    sign, num, unit = m.group(1), m.group(2).replace(",", "."), m.group(3).lower()
    try:
        x = float(sign + num)
    except ValueError:
        return None
    if k == "time":
        table_ms = p["unit"].lower() == "ms"
        if unit == "":
            v = x                                   # a bare number is in the table's unit
        else:
            if unit in ("ms", "msec"):
                secs = x / 1000.0
            elif unit in ("s", "sec"):
                secs = x
            elif unit in ("m", "min"):
                secs = x * 60.0
            else:
                return None
            v = secs * 1000.0 if table_ms else secs
    elif k == "hz":
        if unit in ("k", "khz"):
            v = x * 1000.0
        elif unit in ("", "hz"):
            v = x
        else:
            return None
    elif k == "ratio":
        v = x
    elif k in ("db", "percent", "cents", "semitones", "plain", "custom"):
        v = x
    else:
        return None
    v = v / p["fscale"]
    return snap(p, v)


# ----------------------------------------------------------------------------- emitters

TOOLTIP_BUDGET = 90


def tooltip_suffix(p) -> str:
    """The generated range-and-default suffix (joint workflow `tooltip` column)."""
    if p["type"] == "bool":
        return f"Default {string_from_value(p, p['fdefault'])}."
    if p["type"] == "choice":
        return f"Options {', '.join(p['choice_list'])}; default {string_from_value(p, p['fdefault'])}."
    return (f"Range {string_from_value(p, p['fmin'])} to {string_from_value(p, p['fmax'])}, "
            f"default {string_from_value(p, p['fdefault'])}.")


def tooltip_full(p) -> str:
    t = p["tooltip"].strip()
    if t and not t.endswith((".", "!", "?")):
        t += "."
    return (t + " " + tooltip_suffix(p)).strip()


def _cstr(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit_juce(params, namespace="Params") -> str:
    out = []
    w = out.append
    w("// Generated by paramgen.py from parameters.csv - do not edit; edit the CSV (joint workflow).")
    w("// One stringFromValue and one valueFromString per parameter, shared by GUI, host and tests.")
    w("#pragma once")
    w("#include <juce_audio_processors/juce_audio_processors.h>")
    w("#include <cstring>")
    w("")
    w(f"namespace {namespace}")
    w("{")
    w("// IDs are frozen at the first shared build (rule 19). Never rename, never reuse.")
    for p in params:
        w(f'inline constexpr const char* {p["id"]} = "{p["id"]}";')
    w("")
    if any(p["format_kind"] == "custom" for p in params):
        w("// format_kind custom: the project defines these two (one translation unit), e.g. a root-time readout for ATTACK")
        w("namespace Display { juce::String custom (const char* id, float raw); float parse (const char* id, const juce::String& text); }")
    w("inline juce::String fmt (double v, int decimals) { return decimals <= 0 ? juce::String (juce::roundToInt (v)) : juce::String (v, decimals); }   // decimals 0 = rounded integer, as paramgen's Python prints it")
    w("")
    w("inline juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout()")
    w("{")
    w("    using namespace juce;")
    w("    AudioProcessorValueTreeState::ParameterLayout layout;")
    for p in params:
        pid = f'ParameterID {{ {p["id"]}, {p["iversion"]} }}'
        name = p["name"].replace('"', '\\"')
        attrs = []
        if p["short"]:
            attrs.append(f'.withLabel ("{p["unit"]}")' if p["unit"] else "")
        if p["automatable"] == "N":
            attrs.append(".withAutomatable (false)")
        if p["kind"] == "macro":
            attrs.append(".withMeta (true)")
        attr = "".join(a for a in attrs if a)
        if p["type"] == "bool":
            w(f'    layout.add (std::make_unique<AudioParameterBool> ({pid}, "{name}", {"true" if p["fdefault"] >= 0.5 else "false"},')
            w(f"        AudioParameterBoolAttributes(){attr}.withStringFromValueFunction ([] (bool b, int) {{ return juce::String (b ? \"On\" : \"Off\"); }})));")
        elif p["type"] == "choice":
            names = ", ".join(f'"{c}"' for c in p["choice_list"])
            w(f'    layout.add (std::make_unique<AudioParameterChoice> ({pid}, "{name}", StringArray {{ {names} }}, {int(p["fdefault"])},')
            w(f"        AudioParameterChoiceAttributes(){attr}));")
        elif p["type"] == "int":   # the same text as a float of its format_kind (a note shows C4, not 60)
            w(f'    layout.add (std::make_unique<AudioParameterInt> ({pid}, "{name}", {int(p["fmin"])}, {int(p["fmax"])}, {int(p["fdefault"])},')
            w(f"        AudioParameterIntAttributes(){attr}")
            w(f"            .withStringFromValueFunction ({_cpp_string_lambda(p).replace('[] (float v, int) {', '[] (int i, int) { const float v = (float) i;', 1)})")
            w(f"            .withValueFromStringFunction ([] (const juce::String& text) {{ return juce::roundToInt (({_cpp_parse_lambda(p)}) (text)); }})));")
        else:
            skew = skew_from_centre(p)
            step = 0.0 if p["nsteps"] <= 1 else (p["fmax"] - p["fmin"]) / (p["nsteps"] - 1)
            w(f'    layout.add (std::make_unique<AudioParameterFloat> ({pid}, "{name}",')
            w(f"        NormalisableRange<float> ({cppf(p['fmin'])}, {cppf(p['fmax'])}, {cppf(step)}, {skew:.6f}f), {cppf(p['fdefault'])},")
            w(f"        AudioParameterFloatAttributes(){attr}")
            w(f"            .withStringFromValueFunction ({_cpp_string_lambda(p)})")
            w(f"            .withValueFromStringFunction ({_cpp_parse_lambda(p)})));")
    w("    return layout;")
    w("}")
    w("")
    w("// Smoothing per parameter: tau in ms (0 = none) and domain (D.1, Law 5). Read once in prepareToPlay.")
    w("struct Smoothing { const char* id; float tauMs; const char* domain; const char* controlRate; };")
    w("inline constexpr Smoothing smoothing[] = {")
    for p in params:
        w(f'    {{ {p["id"]}, {cppf(p["fsmoothing"])}, "{p["smoothing_domain"] or ("linear" if p["type"]=="float" else "crossfade")}", "{p["control_rate"]}" }},')
    w("};")
    w("")
    w("// Help text per parameter, from the table's tooltip and meaning columns (D.9.0). The editor")
    w("// calls slider.setTooltip (tooltipFor (id)) and setHelpText (tooltipFor (id)); never types text.")
    w("struct Help { const char* id; const char* tooltip; const char* meaning; };")
    w("inline constexpr Help help[] = {")
    for p in params:
        w(f'    {{ {p["id"]}, "{_cstr(tooltip_full(p))}", "{_cstr(p["meaning"])}" }},')
    w("};")
    w("inline const char* tooltipFor (const char* id) noexcept")
    w("{")
    w("    for (const auto& h : help) if (std::strcmp (h.id, id) == 0) return h.tooltip;")
    w('    return "";')
    w("}")
    w("inline const char* meaningFor (const char* id) noexcept")
    w("{")
    w("    for (const auto& h : help) if (std::strcmp (h.id, id) == 0) return h.meaning;")
    w('    return "";')
    w("}")
    bypass = [p for p in params if p["kind"] == "bypass"]
    if bypass:
        w("")
        w("// Return this from AudioProcessor::getBypassParameter() (D.5.1).")
        w(f'inline constexpr const char* bypassParameterId = "{bypass[0]["id"]}";')
    w(f"}} // namespace {namespace}")
    return "\n".join(out) + "\n"


def cppf(x: float) -> str:
    """A valid C++ float literal: 20 -> 20.0f, 0.3 -> 0.3f, 1e-05 -> 1e-05f."""
    s = f"{x:g}"
    if "." not in s and "e" not in s and "inf" not in s:
        s += ".0"
    return s + "f"


def _cpp_string_lambda(p) -> str:
    k, n = p["format_kind"], p["precision_n"]
    sign = 'juce::String (v > 0 ? "+" : "") + ' if p["bipolar"] == "Y" else ""
    if k == "custom":
        return f'[] (float v, int) {{ return Display::custom ("{p["id"]}", v); }}'
    scale = f" * {cppf(p['fscale'])}" if p["fscale"] != 1.0 else ""
    if k not in ("time", "hz", "db", "note", "choice", "bool") and scale:
        unit = {"percent": " %", "cents": " ct", "semitones": " st", "ratio": ":1"}.get(k, f" {p['unit']}" if p["unit"] else "")
        return f"[] (float v, int) {{ return {sign}fmt (v{scale}, {n}) + \"{unit}\"; }}"
    if k == "time":
        to_s = "v / 1000.0" if p["unit"].lower() == "ms" else "v"
        return (f"[] (float v, int) {{ double s = {to_s}; return std::abs (s) < 1.0 ? "
                f"{sign}fmt (s * 1000.0, {max(n-2,0)}) + \" ms\" : {sign}fmt (s, {n}) + \" s\"; }}")
    if k == "hz":
        return (f"[] (float v, int) {{ return std::abs (v) >= 1000.0f ? {sign}fmt (v / 1000.0, {n+1}) + \" kHz\" "
                f": {sign}fmt (v, {n}) + \" Hz\"; }}")
    if k == "db":
        inf = f'if (v <= {cppf(p["fmin"])}) return juce::String ("-inf dB"); ' if p["fmin"] <= -96 else ""
        return f"[] (float v, int) {{ {inf}return {sign}fmt (v, {n}) + \" dB\"; }}"
    unit = {"percent": " %", "cents": " ct", "semitones": " st", "ratio": ":1"}.get(k, f" {p['unit']}" if p["unit"] else "")
    if k == "note":
        return ('[] (float v, int) { static const char* n[] = { "C","C#","D","D#","E","F","F#","G","G#","A","A#","B" }; '
                'int m = juce::roundToInt (v); return juce::String (n[((m % 12) + 12) % 12]) + juce::String (m / 12 - 1); }')
    return f"[] (float v, int) {{ return {sign}fmt (v, {n}) + \"{unit}\"; }}"


def _cpp_parse_lambda(p) -> str:
    k = p["format_kind"]
    if k == "custom":
        return f'[] (const juce::String& s) {{ return Display::parse ("{p["id"]}", s); }}'
    body = ['juce::String t = s.trim().replace (",", ".").toLowerCase();']
    if k == "db":
        body.append(f'if (t == "-inf" || t == "-inf db" || t == "off") return {cppf(p["fmin"])};')
    body.append('double x = t.retainCharacters ("0123456789.+-").getDoubleValue();')
    if k == "time":
        conv = "x" if p["unit"].lower() == "ms" else "x / 1000.0"
        conv_s = "x * 1000.0" if p["unit"].lower() == "ms" else "x"
        body.append(f'if (t.endsWith ("ms")) return (float) ({conv}); if (t.endsWith ("min") || t.endsWith ("m")) return (float) ({conv_s} * 60.0); return (float) ({conv_s});')
    elif k == "hz":
        body.append('if (t.endsWith ("k") || t.endsWith ("khz")) return (float) (x * 1000.0); return (float) x;')
    elif k == "note":
        # sharps before naturals ("c#4" also starts with "c"), a flat after the letter, as value_from_string
        body = ['auto t = s.trim().toLowerCase(); static const char* n[] = { "c#","d#","f#","g#","a#","c","d","e","f","g","a","b" }; '
                'static const int pc[] = { 1, 3, 6, 8, 10, 0, 2, 4, 5, 7, 9, 11 }; '
                'for (int i = 0; i < 12; ++i) if (t.startsWith (n[i])) { auto rest = t.substring ((int) std::strlen (n[i])); int base = pc[i]; '
                'if (rest.startsWith ("b")) { base -= 1; rest = rest.substring (1); } return (float) ((rest.getIntValue() + 1) * 12 + base); } '
                'return (float) t.getFloatValue();']
    else:
        body.append("return (float) x;" if p["fscale"] == 1.0 else f"return (float) (x / {cppf(p['fscale'])});")
    return "[] (const juce::String& s) { " + " ".join(body) + " }"


def emit_manual(params, product="") -> str:
    out = [f"## Parameters{(' - ' + product) if product else ''}", "",
           "Generated by paramgen.py from parameters.csv - do not edit. Core controls are marked.", ""]
    groups: dict[str, list] = {}
    for p in params:
        groups.setdefault(p["group"] or "General", []).append(p)
    for g, ps in groups.items():
        out.append(f"### {g}")
        out.append("")
        out.append("| Control | Range | Default | Across the travel | What it does | Automation | Notes |")
        out.append("|---|---|---|---|---|---|---|")
        for p in ps:
            if p["kind"] == "bypass":
                continue
            core = " (core)" if p["core"] == "Y" else ""
            if p["type"] == "choice":
                rng = ", ".join(p["choice_list"])
            elif p["type"] == "bool":
                rng = "Off, On"
            else:
                rng = f"{string_from_value(p, p['fmin'])} to {string_from_value(p, p['fmax'])}"
            meaning = p["meaning"] or "-"
            if p["type"] == "float" and p["meaning"] and p["bipolar"] == "Y":
                meaning = f"{p['meaning']} (left / centre / right)"
            elif p["type"] == "float" and p["meaning"]:
                meaning = f"{p['meaning']} (low / mid / high)"
            auto = "yes" if p["automatable"] == "Y" else "no"
            if p["kind"] == "macro":
                auto += " (macro)"
            out.append(f"| **{p['name']}**{core} | {rng} | {string_from_value(p, p['fdefault'])} | {meaning} | {p['tooltip']} | {auto} | {p['notes'] or ''} |")
        out.append("")
    return "\n".join(out)


def check_manual(params, text: str, product="") -> list[str]:
    """The committed docs/parameters.md must equal a fresh render (heading line aside)."""
    fresh = emit_manual(params, product).strip().splitlines()[1:]
    have = text.strip().splitlines()[1:]
    if fresh != have:
        return ["docs/parameters.md is stale: regenerate with `paramgen.py manual parameters.csv -o docs/parameters.md`"]
    return []


# ----------------------------------------------------------------------------- checks

def check_roundtrip(params, points=101) -> list[str]:
    """valueFromString(stringFromValue(v)) == v within one display step, at `points` values per
    parameter, in the C locale and (when installed) de_CH, which uses a decimal comma."""
    errors = []
    locales = ["C"]
    for cand in ("de_CH.UTF-8", "de_CH", "de_DE.UTF-8", "de_DE"):
        try:
            locale.setlocale(locale.LC_NUMERIC, cand)
            locales.append(cand)
            break
        except locale.Error:
            continue
    try:
        for loc in locales:
            locale.setlocale(locale.LC_NUMERIC, loc)
            for p in params:
                n = max(p["nsteps"], points) if p["nsteps"] > 1 else points
                for i in range(n):
                    v = snap(p, p["fmin"] + (p["fmax"] - p["fmin"]) * i / (n - 1))
                    s = string_from_value(p, v)
                    back = value_from_string(p, s)
                    if back is None:
                        errors.append(f"{p['id']}: {s!r} does not parse ({loc})")
                        break
                    tol = _display_step(p, v)
                    if abs(back - v) > tol + 1e-9:
                        errors.append(f"{p['id']}: {v:g} -> {s!r} -> {back:g}, off by more than one display step {tol:g} ({loc})")
                        break
                for alias in p["aliases"]:
                    probe = alias if p["format_kind"] in ("choice", "bool") or not re.match(r"^[a-z%/]+$", alias) else "1" + alias
                    if value_from_string(p, probe) is None:
                        errors.append(f"{p['id']}: parse alias {alias!r} is not accepted ({probe!r})")
    finally:
        locale.setlocale(locale.LC_NUMERIC, "C")
    return errors


def _display_step(p, v):
    k, n = p["format_kind"], p["precision_n"]
    if p["nsteps"] > 1:
        return 0.0
    if k == "time":
        secs = v / 1000.0 if p["unit"].lower() == "ms" else v
        step_s = 10 ** -max(n - 2, 0) / 1000.0 if abs(secs) < 1.0 else 10 ** -n
        return step_s * (1000.0 if p["unit"].lower() == "ms" else 1.0)
    if k == "hz":
        return 10 ** -(n + 1) * 1000.0 if abs(v) >= 1000.0 else 10 ** -n
    return 10 ** -n


def check_harness(params, listing) -> list[str]:
    """Diff the harness's --list-params output against the table (rule 13 for parameters)."""
    errors = []
    if isinstance(listing, dict) and "params" in listing:
        listing = listing["params"]
    by_id = {}
    for item in listing:
        if isinstance(item, str):
            by_id[item] = {}
        else:
            by_id[item.get("id")] = item
    table_ids = [p["id"] for p in params]
    for pid in table_ids:
        if pid not in by_id:
            errors.append(f"{pid}: in the table, not in the harness")
    for pid in by_id:
        if pid not in table_ids:
            errors.append(f"{pid}: in the harness, not in the table")
    for p in params:
        h = by_id.get(p["id"])
        if not h:
            continue
        if "default" in h and abs(float(h["default"]) - to_normalised(p, p["fdefault"])) > 1e-4 \
                and abs(float(h["default"]) - p["fdefault"]) > 1e-6:
            errors.append(f"{p['id']}: harness default {h['default']} != table {p['fdefault']:g} (normalised {to_normalised(p, p['fdefault']):.4f})")
        if "steps" in h and int(h["steps"]) != p["nsteps"]:
            errors.append(f"{p['id']}: harness steps {h['steps']} != table {p['nsteps']}")
        if "automatable" in h and bool(h["automatable"]) != (p["automatable"] == "Y"):
            errors.append(f"{p['id']}: automatable differs")
    order = [i for i in (x if isinstance(x, str) else x.get("id") for x in listing) if i in table_ids]
    if order != [i for i in table_ids if i in order]:
        errors.append("parameter order differs from the table (Ableton Live shows the first 32 in host order)")
    return errors


def check_frozen(params, frozen_params) -> list[str]:
    """Against the table of the last shared build: IDs, types, automatable, choices never change;
    rows are only ever appended (D.5.2, rule 19)."""
    errors = []
    old = {p["id"]: p for p in frozen_params}
    new = {p["id"]: p for p in params}
    for pid, o in old.items():
        if pid not in new:
            errors.append(f"{pid}: removed - keep it (hidden, non-automatable) or every project loses its lane")
            continue
        q = new[pid]
        for col in ("type", "automatable"):
            if o[col] != q[col]:
                errors.append(f"{pid}: {col} changed {o[col]!r} -> {q[col]!r}")
        if o["type"] == "choice" and o["choice_list"] != q["choice_list"][:len(o["choice_list"])]:
            errors.append(f"{pid}: choice names changed or reordered; only append")
        if (o["fmin"], o["fmax"]) != (q["fmin"], q["fmax"]) and o["type"] != "choice":
            errors.append(f"{pid}: range changed {o['fmin']:g}-{o['fmax']:g} -> {q['fmin']:g}-{q['fmax']:g}: saved normalised values now mean something else")
        if q["iversion"] != o["iversion"]:
            errors.append(f"{pid}: version_added changed")
    old_order = [p["id"] for p in frozen_params]
    new_order = [p["id"] for p in params if p["id"] in old]
    if old_order != new_order:
        errors.append("order of existing parameters changed; append new ones at the end of their group")
    latest = max((p["iversion"] for p in frozen_params), default=1)
    for pid, q in new.items():
        if pid not in old and q["iversion"] <= latest:
            errors.append(f"{pid}: new parameter needs version_added > {latest}")
    return errors


def check_table(params, kind="effect") -> list[str]:
    """Lints that are policy, not validity. kind: effect (default) or instrument (no bypass expected)."""
    warnings = []
    if kind != "instrument" and not any(p["kind"] == "bypass" for p in params):
        warnings.append("no bypass row: JUCE will add its own with an ID you do not control (D.5.1); an instrument passes --kind instrument")
    for p in params:
        if p["format_kind"] == "percent" and p["fmax"] <= 1.0 and p["fscale"] == 1.0:
            warnings.append(f"{p['id']}: percent with range {p['min']}..{p['max']} shows '0.5 %'; set display_scale 100 (raw stays 0..1) or make the range 0..100")
    core = [p for p in params if p["core"] == "Y"]
    if not 3 <= len(core) <= 5:
        warnings.append(f"{len(core)} core controls; the brief asks for 3-5")
    first32 = params[:32]
    for p in core:
        if p not in first32:
            warnings.append(f"core control {p['id']} is beyond the first 32 rows; Ableton Live auto-shows only the first 32")
    for p in params:
        if p["kind"] == "macro" and p["automatable"] == "Y":
            pass
        if p["kind"] == "modtarget" and "mod" not in (p["notes"] + p["meaning"]).lower():
            warnings.append(f"{p['id']} is a modtarget but notes do not name the source")
        if p["type"] == "float" and p["fcentre"] is not None:
            # default should sit at 40-60% of travel
            t = to_normalised(p, p["fdefault"])
            if not 0.3 <= t <= 0.7:
                warnings.append(f"{p['id']}: default sits at {t*100:.0f}% of knob travel; F.14.2 asks for 40-60% (move centre or default)")
        if p["type"] == "float" and p["fcentre"] is None and p["format_kind"] in ("hz", "time"):
            warnings.append(f"{p['id']}: {p['format_kind']} parameter with a linear taper (no centre); F.14.2 default tapers say log")
        if not p["tooltip"]:
            warnings.append(f"{p['id']}: no tooltip")
        elif len(p["tooltip"]) > TOOLTIP_BUDGET:
            warnings.append(f"{p['id']}: tooltip is {len(p['tooltip'])} characters; budget {TOOLTIP_BUDGET} before the generated range suffix")
        low = p["tooltip"].lower()
        if p["tooltip"] and (re.search(r"\d+\s*(?:to|-)\s*\d+", low) or "default" in low):
            warnings.append(f"{p['id']}: tooltip states a range or default; the generator appends those (joint workflow `tooltip`)")
    return warnings


# ----------------------------------------------------------------------------- sample

SAMPLE_CSV = """id,version_added,type,kind,name,short,group,core,unit,min,max,default,centre,bipolar,choices,steps,format_kind,precision,parse_aliases,automatable,smoothing,smoothing_domain,control_rate,meaning,tooltip,notes
size,1,float,plain,Size,Size,Space,Y,s,0.3,20,2.4,2.0,N,,0,time,2,ms,Y,50,log,block,small room / hall / cathedral,Length of the reverb tail,
preDelay,1,float,plain,Pre-delay,PreDly,Space,N,ms,0,120,15,20,N,,0,time,1,s,Y,20,log,block,none / a short gap / the voice stays in front,Gap before the reverb starts,
tone,1,float,plain,Tone,Tone,Colour,Y,Hz,1500,12000,4000,4000,N,,0,hz,0,k,Y,20,log,block,dark / warm / open,Loop lowpass: the warmth of the tail,
mix,1,float,plain,Mix,Mix,Output,Y,%,0,100,35,,N,,0,percent,0,,Y,20,linear,block,dry / balanced / wet,Dry to wet balance (equal power),
outGain,1,float,plain,Output,Out,Output,N,dB,-24,12,0,,Y,,0,db,1,,Y,20,db,block,quiet / unity / loud,Output level after the mix,
fine,1,float,modtarget,Fine tune,Fine,Pitch,N,ct,-50,50,0,,Y,,0,cents,0,,Y,10,linear,sample,down / centre / up,Fine tuning of the shifter,Mod target of LFO 1
mode,1,choice,plain,Mode,Mode,Space,Y,,0,2,0,,N,Hall|Plate|Room,3,choice,0,,Y,0,crossfade,event,,Reverb character,
freeze,1,bool,plain,Freeze,Freeze,Space,N,,0,1,0,,N,,2,bool,0,,Y,0,crossfade,event,,Holds the tail forever,
shimmer,1,float,macro,Shimmer,Shimmer,Colour,Y,%,0,100,40,,N,,0,percent,0,,Y,30,linear,block,plain reverb / a halo / octaves everywhere,Feedback and shift amount together,Drives hidden targets feedback and shiftMix
bypass,1,bool,bypass,Bypass,Bypass,Output,N,,0,1,0,,N,,2,bool,0,,Y,0,crossfade,event,,Bypass the plugin (latency compensated),
"""


def selftest() -> int:
    params = read_table(io.StringIO(SAMPLE_CSV))
    errs = check_roundtrip(params)
    warn = check_table(params)
    # display_scale: raw 0..1 shown as percent, round trip through the text, C++ carries the scale
    scaled = SAMPLE_CSV.replace("tooltip,notes", "tooltip,notes,display_scale").replace(
        "mix,1,float,plain,Mix,Mix,Output,Y,%,0,100,35,,N,,0,percent,0,,Y,20,linear,block,dry / balanced / wet,Dry to wet balance (equal power),",
        "mix,1,float,plain,Mix,Mix,Output,Y,%,0,1,0.35,,N,,0,percent,0,,Y,20,linear,block,dry / balanced / wet,Dry to wet balance (equal power),,100")
    sp = {q["id"]: q for q in read_table(io.StringIO(scaled))}
    assert string_from_value(sp["mix"], 0.477) == "48 %", string_from_value(sp["mix"], 0.477)
    assert abs(value_from_string(sp["mix"], "48 %") - 0.48) < 1e-9
    assert "Range 0 % to 100 %, default 35 %." in tooltip_suffix(sp["mix"])
    cpp_scaled = emit_juce(list(sp.values()))
    assert "v * 100.0f" in cpp_scaled and "x / 100.0f" in cpp_scaled and "roundToInt" in cpp_scaled
    plain = read_table(io.StringIO(SAMPLE_CSV.replace("mix,1,float,plain,Mix,Mix,Output,Y,%,0,100,35", "mix,1,float,plain,Mix,Mix,Output,Y,%,0,1,0.35")))
    assert any("display_scale 100" in w for w in check_table(plain)), "0..1 percent without a scale must warn"
    assert not any("bypass" in w for w in check_table([q for q in params if q["kind"] != "bypass"], "instrument"))
    # custom: the hook is declared, the lambdas call it
    custom = SAMPLE_CSV.replace("preDelay,1,float,plain,Pre-delay,PreDly,Space,N,ms,0,120,15,20,N,,0,time,1,s,",
                                "preDelay,1,float,plain,Pre-delay,PreDly,Space,N,ms,0,120,15,20,N,,0,custom,1,s,")
    cpp_custom = emit_juce(read_table(io.StringIO(custom)))
    assert 'Display::custom ("preDelay", v)' in cpp_custom and "namespace Display" in cpp_custom
    # int: the host gets the format_kind's text too (a note shows C4, not 60), and the C++ note parser
    # tries the sharps before the naturals ("c#4" starts with "c")
    note = SAMPLE_CSV.rstrip("\n") + "\nsplit,1,int,plain,Split,Split,Keys,N,note,36,96,60,,N,,61,note,0,,Y,0,crossfade,block,low / C4 / high,Keys below this note play the lower part,\n"
    np_ = {q["id"]: q for q in read_table(io.StringIO(note))}
    assert string_from_value(np_["split"], 61) == "C#4" and value_from_string(np_["split"], "C#4") == 61.0
    cpp_note = emit_juce(list(np_.values()))
    row = cpp_note[cpp_note.index("AudioParameterInt> (ParameterID { split"):]
    row = row[:row.index("layout.add", 10) if "layout.add" in row[10:] else len(row)]
    if ".withStringFromValueFunction ([] (int i, int)" not in row or "juce::roundToInt ((" not in row:
        errs.append("an int parameter got no value strings in the C++ (its format_kind is lost in the host)")
    if '{ "c#","d#","f#","g#","a#","c",' not in row:
        errs.append("the C++ note parser must try the sharps first")
    # a broken table must be refused
    broken = SAMPLE_CSV.replace("size,1,float", "Size,1,float")
    try:
        read_table(io.StringIO(broken))
        errs.append("lint did not reject a non-lowerCamel id")
    except TableError:
        pass
    broken = SAMPLE_CSV.replace("mode,1,choice,plain,Mode,Mode,Space,Y,,0,2,0,,N,Hall|Plate|Room,3,choice,0,,Y,0,",
                                "mode,1,choice,plain,Mode,Mode,Space,Y,,0,2,0,,N,Hall|Plate|Room,3,choice,0,,Y,20,")
    try:
        read_table(io.StringIO(broken))
        errs.append("lint did not reject a smoothed choice")
    except TableError:
        pass
    # frozen: a renamed id and a dropped row are caught
    frozen = read_table(io.StringIO(SAMPLE_CSV))
    changed = read_table(io.StringIO(SAMPLE_CSV.replace("preDelay,1", "predelay,1")))
    f = check_frozen(changed, frozen)
    if not any("removed" in e for e in f):
        errs.append("frozen check missed a renamed id")
    # harness diff: a missing param and a wrong default are caught
    listing = [{"id": p["id"], "default": to_normalised(p, p["fdefault"]), "steps": p["nsteps"]} for p in params]
    listing[0]["default"] = 0.99
    listing.pop()
    h = check_harness(params, listing)
    if not any("default" in e for e in h) or not any("not in the harness" in e for e in h):
        errs.append("harness diff missed a defect")
    # generated C++ is well-formed enough to count braces
    cpp = emit_juce(params)
    if cpp.count("{") != cpp.count("}") or "createParameterLayout" not in cpp:
        errs.append("generated C++ is unbalanced")
    if re.search(r"(?<![\d.])\d+f\b", cpp):
        errs.append("generated C++ has an integer-looking float literal (e.g. 20f)")
    if "tooltipFor" not in cpp or "Range 300 ms to 20.00 s, default 2.40 s." not in cpp:
        errs.append("generated C++ lacks the help table or the range suffix")
    # manual: a fresh render passes, an edited one is stale
    man = emit_manual(params)
    if check_manual(params, man):
        errs.append("check_manual flags a fresh render")
    if not check_manual(params, man.replace("Length of the reverb tail", "Length of the tail")):
        errs.append("check_manual missed a stale manual")
    if "| Automation |" not in man or "### Tooltips" in man:
        errs.append("manual columns not as specified")
    # a tooltip with a range is a policy warning
    rp = read_table(io.StringIO(SAMPLE_CSV.replace("Length of the reverb tail", "Length of the reverb tail 0.3 to 20 s")))
    if not any("states a range" in w for w in check_table(rp)):
        errs.append("tooltip range check missed")
    # spot checks on strings
    size = params[0]
    checks = [(size, 2.4, "2.40 s"), (size, 0.3, "300 ms"), (params[2], 4000, "4.0 kHz"),
              (params[4], 0, "0.0 dB"), (params[5], 12, "+12 ct"), (params[6], 1, "Plate"), (params[7], 1, "On")]
    for p, v, want in checks:
        got = string_from_value(p, v)
        if got != want:
            errs.append(f"string_from_value({p['id']}, {v}) = {got!r}, want {want!r}")
    parse_checks = [(params[2], "2k", 2000.0), (size, "350 ms", 0.35), (params[4], "-6", -6.0),
                    (params[5], "+12", 12.0), (params[6], "room", 2.0), (params[7], "off", 0.0), (size, "2,4", 2.4),
                    (params[1], "15", 15.0), (params[1], "0.1 s", 100.0), (size, "90", 20.0)]
    for p, s, want in parse_checks:
        got = value_from_string(p, s)
        if got is None or abs(got - want) > 1e-6:
            errs.append(f"value_from_string({p['id']}, {s!r}) = {got!r}, want {want}")
    if errs:
        print("paramgen selftest FAILED:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    print(f"paramgen selftest OK: {len(params)} sample parameters, round trip at 101 points, "
          f"lint rejects bad tables, frozen and harness diffs catch defects, display_scale and custom formats round-trip, {len(warn)} policy warning(s) on the sample")
    return 0


# ----------------------------------------------------------------------------- cli

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("juce", "manual", "check"):
        s = sub.add_parser(name)
        s.add_argument("csv")
        s.add_argument("-o", "--out")
        if name == "juce":
            s.add_argument("--namespace", default="Params")
        if name == "manual":
            s.add_argument("--product", default="")
        if name == "check":
            s.add_argument("--list-params", help="JSON from the harness's --list-params")
            s.add_argument("--frozen", help="parameters.csv of the last shared build")
            s.add_argument("--strict", action="store_true", help="policy warnings fail too")
            s.add_argument("--manual", help="committed docs/parameters.md; fails when stale")
            s.add_argument("--kind", choices=("effect", "instrument"), default="effect", help="instrument: no bypass row expected")
    sub.add_parser("selftest")
    sub.add_parser("sample").add_argument("-o", "--out")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "sample":
        (Path(a.out).write_text(SAMPLE_CSV) if a.out else sys.stdout.write(SAMPLE_CSV))
        return 0
    try:
        params = read_table(a.csv)
    except (TableError, OSError) as e:
        print(f"paramgen: {a.csv}: {e}", file=sys.stderr)
        return 2
    if a.cmd == "juce":
        text = emit_juce(params, a.namespace)
    elif a.cmd == "manual":
        text = emit_manual(params, a.product)
    else:
        errors = check_roundtrip(params)
        warnings = check_table(params, getattr(a, 'kind', 'effect'))
        if a.list_params:
            with open(a.list_params, encoding="utf-8") as f:
                errors += check_harness(params, json.load(f))
        if a.frozen:
            try:
                errors += check_frozen(params, read_table(a.frozen))
            except TableError as e:
                errors.append(f"frozen table invalid: {e}")
        if a.manual:
            errors += check_manual(params, Path(a.manual).read_text(encoding="utf-8"))
        for w in warnings:
            print(f"warning: {w}")
        for e in errors:
            print(f"ERROR: {e}")
        n = len(params)
        if errors or (a.strict and warnings):
            print(f"paramgen check: {n} parameters, {len(errors)} error(s), {len(warnings)} warning(s)")
            return 1
        print(f"paramgen check OK: {n} parameters, round trip at 101 points, {len(warnings)} warning(s)")
        return 0
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
