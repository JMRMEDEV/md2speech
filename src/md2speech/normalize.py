"""Technical text normalization for narration.

This stage runs on each narration block's text *before* the acronym
pronunciation dictionary, and handles the things a plain term->term table
cannot do correctly:

  * File extensions:  ``.js`` -> "dot jay ess", ``file.js`` -> "file dot jay ess".
    (Must run before the acronym table, so ``.js`` is not turned into ".JavaScript".)
  * Plural initialisms: ``APIs`` -> "A P Iz", ``SDKs`` -> "S D Kz", so the
    trailing ``s`` is voiced as a plural, not glued to the last letter.
  * Common operators / symbols: ``===`` -> "triple equals", ``=>`` -> "arrow",
    ``??`` -> "nullish coalescing", so code-ish prose is readable.
  * Version/suffix tidy-ups: ``ES6+`` -> "E S six plus".

Order matters and is encoded in :func:`normalize_tech_text`. Everything is
pure text-in/text-out and never paraphrases content words.
"""

from __future__ import annotations

import re


# Letter-by-letter spelling for file extensions (spoken, not expanded).
_EXT_SPOKEN = {
    "js": "jay ess",
    "ts": "tee ess",
    "jsx": "jay ess ex",
    "tsx": "tee ess ex",
    "html": "aitch tee em el",
    "htm": "aitch tee em",
    "css": "see ess ess",
    "scss": "ess see ess ess",
    "json": "jason",
    "yaml": "yamel",
    "yml": "yamel",
    "md": "em dee",
    "py": "pie",
    "sh": "ess aitch",
    "xml": "ex em el",
    "sql": "sequel",
    "env": "dot e n v",  # handled specially below
}

# Operators / symbol tokens commonly found in technical prose.
# Ordered longest-first in application to avoid partial clobbering.
_SYMBOLS: list[tuple[str, str]] = [
    ("===", " triple equals "),
    ("!==", " strict not equals "),
    ("==", " double equals "),
    ("!=", " not equals "),
    ("=>", " arrow "),
    ("??=", " nullish assign "),
    ("??", " nullish coalescing "),
    ("||", " logical or "),
    ("&&", " logical and "),
    ("...", " spread "),
    ("[[Prototype]]", " prototype "),
    ("->", " to "),
]


# file.ext or .ext  (extension limited to known spoken set)
_EXTS = "|".join(sorted(_EXT_SPOKEN, key=len, reverse=True))
_FILE_WITH_EXT = re.compile(rf"\b([\w-]+)\.({_EXTS})\b", re.IGNORECASE)
_BARE_DOT_EXT = re.compile(rf"(?<![\w.])\.({_EXTS})\b", re.IGNORECASE)

# Plural initialism: 2-5 uppercase letters directly followed by a lowercase s.
_PLURAL_INITIALISM = re.compile(r"\b([A-Z]{2,5})s\b")

# ES6+ / ES2020+ style trailing plus.
_TRAILING_PLUS = re.compile(r"\b([A-Za-z]+\d+)\+")


def _spell_extension(ext: str) -> str:
    return _EXT_SPOKEN.get(ext.lower(), " ".join(ext.lower()))


#: Phonetic spelling of each letter NAME, tuned by ear against Kokoro so bare
#: capitals never fall back to Spanish-style vowels in sentence context.
#: Vowel spellings (A/E/I/O/U) were chosen from listening tests:
#:   A -> "eigh", E -> "ee", I -> "eye", O -> "oh", U -> "you".
_LETTER_SPOKEN = {
    "A": "eigh",
    "B": "bee",
    "C": "see",
    "D": "dee",
    "E": "ee",
    "F": "eff",
    "G": "gee",
    "H": "aitch",
    "I": "eye",
    "J": "jay",
    "K": "kay",
    "L": "el",
    "M": "em",
    "N": "en",
    "O": "oh",
    "P": "pee",
    "Q": "cue",
    "R": "ar",
    "S": "ess",
    "T": "tee",
    "U": "you",
    "V": "vee",
    "W": "double-you",
    "X": "ex",
    "Y": "why",
    "Z": "zee",
}

#: Spoken English PLURAL of each letter name, for the final letter of a plural
#: initialism (e.g. APIs -> "eigh pee eyes", SDKs -> "ess dee kays").
_LETTER_PLURAL = {
    "A": "eyes",
    "B": "bees",
    "C": "sees",
    "D": "dees",
    "E": "ees",
    "F": "effs",
    "G": "gees",
    "H": "aitches",
    "I": "eyes",
    "J": "jays",
    "K": "kays",
    "L": "els",
    "M": "ems",
    "N": "ens",
    "O": "ohs",
    "P": "pees",
    "Q": "cues",
    "R": "ars",
    "S": "esses",
    "T": "tees",
    "U": "yous",
    "V": "vees",
    "W": "double-yous",
    "X": "exes",
    "Y": "whys",
    "Z": "zees",
}


def spell_letters(letters: str) -> str:
    """Spell an initialism phonetically, letter by letter.

    ``API`` -> "eigh pee eye". Non-letters are passed through spaced.
    """
    parts = []
    for ch in letters:
        up = ch.upper()
        parts.append(_LETTER_SPOKEN.get(up, ch) if up.isalpha() else ch)
    return " ".join(p for p in parts if p).strip()


def _spell_initialism(letters: str) -> str:
    """Plural initialism -> phonetic body + an English-word plural ending.

    Every letter is spelled phonetically (so a leading A reads as the English
    letter name, not a Spanish vowel), and the final letter becomes its spoken
    English plural word. ``APIs`` -> "eigh pee eyes", ``SDKs`` -> "ess dee kays".
    """
    letters = letters.upper()
    body = letters[:-1]
    last = letters[-1]
    last_plural = _LETTER_PLURAL.get(last, _LETTER_SPOKEN.get(last, last) + "s")
    spoken_body = spell_letters(body)
    return f"{spoken_body} {last_plural}".strip()


# --------------------------------------------------------------------------- #
# Section numbers:  1.1.1 -> "one dot one dot one",  1. -> "One"
# --------------------------------------------------------------------------- #
_NUMBER_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}


def _number_word(n: int) -> str:
    """Small integers -> words; larger ones fall back to the digits as-is."""
    return _NUMBER_WORDS.get(n, str(n))


def _spell_dotted_number(seq: str) -> str:
    """'1.1.1' -> 'one dot one dot one'. Trailing dot dropped ('1.' -> 'one')."""
    parts = [p for p in seq.split(".") if p != ""]
    words = [_number_word(int(p)) for p in parts]
    return " dot ".join(words)


# 3+ segment dotted integers are unambiguously section numbers (never decimals).
_MULTI_SECTION = re.compile(r"\b\d+(?:\.\d+){2,}\b")


def normalize_multilevel_section_numbers(text: str) -> str:
    """Expand 3+ level dotted numbers anywhere: 1.1.1 -> 'one dot one dot one'.

    Two-segment numbers (1.1, 3.14, 2.0) are left untouched here because they
    are ambiguous with decimals/versions; heading-leading section numbers are
    handled separately where heading context is known.
    """
    return _MULTI_SECTION.sub(lambda m: _spell_dotted_number(m.group(0)), text)


# Leading section number at the START of a heading string:
#   "1.1 Title" / "1.1.1 Title" / "1. Title" / "1 Title"
_HEADING_SECTION = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(?=\S)")


def normalize_heading_section_number(text: str) -> str:
    """Expand a leading section number in a heading to spoken words.

    '1.1 What X' -> 'one dot one. What X'   (a short pause after the number)
    '1. Overview' -> 'One. Overview'
    Non-numeric headings are returned unchanged.
    """
    m = _HEADING_SECTION.match(text)
    if not m:
        return text
    spoken = _spell_dotted_number(m.group(1))
    rest = text[m.end():]
    # Capitalize a lone leading number for a clean "One." when single-level.
    if "." not in m.group(1):
        spoken = spoken[:1].upper() + spoken[1:]
    return f"{spoken}. {rest}".strip()





def normalize_file_extensions(text: str) -> str:
    def file_repl(m: re.Match[str]) -> str:
        stem, ext = m.group(1), m.group(2)
        return f"{stem} dot {_spell_extension(ext)}"

    def bare_repl(m: re.Match[str]) -> str:
        return f"dot {_spell_extension(m.group(1))}"

    text = _FILE_WITH_EXT.sub(file_repl, text)
    text = _BARE_DOT_EXT.sub(bare_repl, text)
    return text


def normalize_plural_initialisms(text: str) -> str:
    return _PLURAL_INITIALISM.sub(lambda m: _spell_initialism(m.group(1)), text)


def normalize_symbols(text: str) -> str:
    for sym, spoken in _SYMBOLS:
        text = text.replace(sym, spoken)
    return text


def normalize_version_suffixes(text: str) -> str:
    return _TRAILING_PLUS.sub(lambda m: f"{m.group(1)} plus", text)


def collapse_ws(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Remove spaces that symbol substitution may have left before punctuation.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def normalize_tech_text(text: str) -> str:
    """Apply all technical normalizations in the correct order.

    Order rationale:
      1. multilevel section numbers (1.1.1) before file-ext so the dots there
         are not mistaken for extensions,
      2. file extensions (protect ``.js`` from the acronym ``JS`` rule),
      3. symbols/operators,
      4. version suffixes (``ES6+``).
    (Plural initialisms run separately, after the acronym table.)
    """
    text = normalize_multilevel_section_numbers(text)
    text = normalize_file_extensions(text)
    text = normalize_symbols(text)
    text = normalize_version_suffixes(text)
    return collapse_ws(text)
