"""
Post-process recovered PDF/image text to populate component values and
footprints.

The PDF parser already extracts reference designators (R1, C12, U3, ...) by
regex. What was missing is the **value/footprint** column: schematic PDFs
exported from EDA tools place those strings spatially next to the refdes,
which translates into textual adjacency in the recovered raw text. We
exploit that adjacency here.

Heuristic:
  1. Tokenize raw text into typed tokens: ``ref``, ``footprint``,
     ``bare_value``, ``part_number``, ``other``.
  2. For each ``ref`` token, scan a small window of surrounding tokens for
     the closest **type-compatible** ``footprint`` / ``bare_value`` /
     ``part_number``. Type-compatibility prevents pairing e.g. ``R1`` with
     ``C0402_100nF`` even when they appear in the same line.
  3. Write the result back into the existing ``Component`` objects.

This module is intentionally pure-functional and side-effect-free except
for mutating ``Component`` instances passed in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from ..ir import Component


# ---------------------------------------------------------------------------
# Token patterns
# ---------------------------------------------------------------------------

# Reference designator (matches what the PDF parser already extracts).
_REF_RE = re.compile(
    r"^("
    r"R|C|L|D|Q|U|IC|J|JP|K|F|FB|TP|SW|S|BT|Y|X|RV|RN|LED|MOV|CN|P"
    r")(\d{1,4})$"
)

# Full footprint string used on schematics (e.g. ``C0402_100nF_16V_X7R``,
# ``R0402_10k_5%``, ``L0603_68nH``, ``FB0805_220ohm@100MHz_0.050Ohm@2.0A``).
# The first letter is the component class prefix.
_FOOTPRINT_RE = re.compile(
    r"^(?P<klass>[CRLDF]B?|FB)"
    r"(?P<pkg>\d{3,4})"
    r"_(?P<rest>[A-Za-z0-9._%@+\-]+)$"
)

# Bare engineering value not anchored to a package (e.g. ``4.7uF``, ``10nH``,
# ``39MHz``, ``5.1Kohms``).
_BARE_VALUE_RE = re.compile(
    r"^\d+(?:\.\d+)?"
    r"(?:uF|nF|pF|mF|nH|uH|mH|Hz|MHz|kHz|GHz|Kohms|kohms|kohm|kOhm|Kohm|ohms|Ohms|ohm|Ohm|mA|A|kV|V)$"
)

# All-caps part-number-ish identifier (SY8120B, W25Q80DVUX, AT25QF641,
# LP1102-3NL, BLM03PG330SN1, SLVU2.8-4, LAN8720A, ...).
#
# Must contain at least one digit AND at least 4 alphanumeric characters
# (excluding separators), to avoid catching short refdes-like tokens
# ("ANT1", "GND", "VCC", "U9").
_PART_NUMBER_RE = re.compile(
    r"^[A-Z][A-Z0-9](?:[A-Z0-9._/+\-]*\d[A-Z0-9._/+\-]*)$"
)

# Tokens that look like part numbers but are actually nets / refs / labels.
# Anything matching these is dropped from part-number classification.
_PART_NUMBER_BLOCKLIST = {
    "ANT1", "ANT2", "GND", "VCC", "VDD", "VSS", "VBUS", "VREF",
    "DGND", "AGND", "PGND", "SGND",
    "NC", "DNI", "DNP", "DNF", "NA",
    "USB", "USB2", "USB3", "USBC",
    "RX", "TX", "RXD", "TXD", "SCL", "SDA", "MOSI", "MISO", "SCK",
}

# Prefixes that mark a token as a *symbol descriptor*, not a part number.
# These look part-number-ish (all caps + digits) but represent a class of
# component on the schematic (e.g. ``LED_0603_GREEN``, ``RJ45-TM58S811EXX11``).
_PART_NUMBER_PREFIX_BLOCKLIST = (
    "LED_", "RJ45-", "RJ45_", "SMA-", "SMA_",
)

# Anything we can split a word stream on.
_WORD_SPLIT_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


@dataclass
class _Tok:
    text: str
    kind: str          # "ref" | "footprint" | "bare_value" | "part_number" | "other"
    klass: str = ""    # for footprint/ref: the leading letter(s); empty otherwise


def _classify(word: str) -> _Tok:
    if not word:
        return _Tok(text=word, kind="other")
    m = _REF_RE.match(word)
    if m:
        return _Tok(text=word, kind="ref", klass=m.group(1))
    m = _FOOTPRINT_RE.match(word)
    if m:
        return _Tok(text=word, kind="footprint", klass=m.group("klass"))
    if _BARE_VALUE_RE.match(word):
        return _Tok(text=word, kind="bare_value")
    if (
        _PART_NUMBER_RE.match(word)
        and len(word) >= 5
        and word not in _PART_NUMBER_BLOCKLIST
        and not any(word.startswith(p) for p in _PART_NUMBER_PREFIX_BLOCKLIST)
        # Composite tokens with '/' are usually concatenated net / pin labels
        # (e.g. ``U1TXD/HS1_DATA3/SPIWP/GPIO10/SD_DATA_3``), not part numbers.
        and "/" not in word
    ):
        return _Tok(text=word, kind="part_number")
    return _Tok(text=word, kind="other")


def _tokenize(text: str) -> list[_Tok]:
    out: list[_Tok] = []
    for raw in _WORD_SPLIT_RE.split(text or ""):
        # Strip surrounding punctuation that is purely decorative.
        word = raw.strip(",;:()[]{}")
        if not word:
            continue
        out.append(_classify(word))
    return out


# ---------------------------------------------------------------------------
# Class-compatibility check (R* refs pair with R-class footprints, etc.)
# ---------------------------------------------------------------------------

# Map refdes prefix -> set of footprint prefixes considered compatible.
_REF_TO_FP_KLASS: dict[str, set[str]] = {
    "R":   {"R"},
    "RN":  {"R"},
    "RV":  {"R"},
    "C":   {"C"},
    "L":   {"L"},
    "D":   {"D", "LED"},
    "LED": {"LED", "D"},
    "FB":  {"FB"},
}


def _footprint_compatible(ref_klass: str, fp_klass: str) -> bool:
    allowed = _REF_TO_FP_KLASS.get(ref_klass)
    if not allowed:
        return False
    return fp_klass in allowed


# ICs / FETs / regulators / relays / switches that expect a part_number.
_IC_REF_KLASSES = {"U", "IC", "Q", "K", "SW", "S"}

# Crystals / oscillators: typical "value" is a frequency (bare_value) — but
# beware that diodes / LEDs near crystals can capture the frequency. We
# require the bare_value to actually be a frequency, not e.g. a capacitance.
_CRYSTAL_REF_KLASSES = {"Y", "X"}
_FREQ_RE = re.compile(r"^\d+(?:\.\d+)?(?:Hz|MHz|kHz|GHz)$")

# Connectors / test points / fuses / batteries / diodes / LEDs: we don't
# currently extract a useful value for these from raw text — leave them
# blank rather than misattribute a neighboring passive's value.
_NOVALUE_REF_KLASSES = {"J", "JP", "CN", "P", "TP", "BT", "F", "FB", "LED", "D"}


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def _best_neighbor(
    tokens: list[_Tok],
    idx: int,
    window: int,
    accept,  # callable(_Tok) -> bool
) -> Optional[_Tok]:
    """Return the closest token to *idx* (within ``window``) that ``accept`` likes."""
    n = len(tokens)
    for offset in range(1, window + 1):
        for j in (idx - offset, idx + offset):
            if 0 <= j < n and accept(tokens[j]):
                return tokens[j]
    return None


def _extract_pairs(
    text: str,
    window: int = 4,
) -> dict[str, dict[str, str]]:
    """
    Return ``{reference: {"value": ..., "footprint": ...}}`` extracted from *text*.

    *window* controls how many tokens around a refdes we consider when
    looking for a compatible value/footprint/part-number. Empirically 4
    works well for EDA-exported PDFs of complex boards (up to ~3 unrelated
    tokens can appear between a ref and its value).
    """
    tokens = _tokenize(text)
    out: dict[str, dict[str, str]] = {}

    for i, tok in enumerate(tokens):
        if tok.kind != "ref":
            continue
        ref = tok.text
        # First refdes occurrence wins; later mentions tend to be net names.
        if ref in out:
            continue

        fp: Optional[_Tok] = None
        val: Optional[_Tok] = None

        if tok.klass in _IC_REF_KLASSES:
            # ICs / FETs / regulators / switches: pair with a part_number.
            val = _best_neighbor(
                tokens, i, window, lambda t: t.kind == "part_number"
            )
        elif tok.klass in _CRYSTAL_REF_KLASSES:
            # Crystals / oscillators: only accept a frequency bare_value.
            val = _best_neighbor(
                tokens, i, window,
                lambda t: t.kind == "bare_value" and _FREQ_RE.match(t.text) is not None,
            )
            # Crystal package part number (e.g. X40M-3.2x2.5) → footprint.
            fp = _best_neighbor(
                tokens, i, window, lambda t: t.kind == "part_number"
            )
        elif tok.klass in _NOVALUE_REF_KLASSES:
            # Connectors / test points / fuses / batteries / diodes / LEDs:
            # don't guess — misattribution is worse than empty.
            continue
        else:
            # Passives (R/C/L/RV/RN/...): prefer a class-compatible footprint,
            # fall back to a bare value.
            fp = _best_neighbor(
                tokens, i, window,
                lambda t: t.kind == "footprint"
                and _footprint_compatible(tok.klass, t.klass),
            )
            val = _best_neighbor(
                tokens, i, window, lambda t: t.kind == "bare_value"
            )

        entry: dict[str, str] = {}
        if fp is not None:
            entry["footprint"] = fp.text
            # Derive a "value" string from the footprint suffix when possible
            # (e.g. ``C0402_100nF_16V_X7R`` → ``100nF``).
            m = _FOOTPRINT_RE.match(fp.text)
            if m:
                rest = m.group("rest")
                first = rest.split("_", 1)[0]
                if _BARE_VALUE_RE.match(first) or re.match(r"^\d", first):
                    entry["value"] = first
        if "value" not in entry and val is not None:
            entry["value"] = val.text
        if entry:
            out[ref] = entry
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_components_from_text(
    components: Iterable[Component],
    raw_text: str,
    window: int = 4,
) -> int:
    """
    Mutate *components* in place, filling in ``value`` / ``footprint``
    fields heuristically from *raw_text*.

    Returns the number of components that received at least one new field.
    Existing non-empty fields are never overwritten.
    """
    if not raw_text:
        return 0
    pairs = _extract_pairs(raw_text, window=window)
    enriched = 0
    for c in components:
        e = pairs.get(c.reference)
        if not e:
            continue
        changed = False
        if not c.value and "value" in e:
            c.value = e["value"]
            changed = True
        if not c.footprint and "footprint" in e:
            c.footprint = e["footprint"]
            changed = True
        if changed:
            enriched += 1
    return enriched


__all__ = ["enrich_components_from_text"]
