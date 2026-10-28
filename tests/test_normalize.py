"""Tests for technical text normalization."""

from md2speech.normalize import (
    normalize_file_extensions,
    normalize_plural_initialisms,
    normalize_symbols,
    normalize_tech_text,
    normalize_version_suffixes,
)


# --- file extensions ------------------------------------------------------- #
def test_bare_extension_spoken():
    assert normalize_file_extensions("drop it in a .js file") == (
        "drop it in a dot jay ess file"
    )


def test_file_with_extension_spoken():
    assert normalize_file_extensions("run node file.js now") == (
        "run node file dot jay ess now"
    )


def test_html_and_ts_extensions():
    out = normalize_file_extensions("a .html and a .ts")
    assert "dot aitch tee em el" in out
    assert "dot tee ess" in out
    assert ".html" not in out and ".ts" not in out


def test_extension_not_confused_with_sentence_end():
    # A period ending a sentence followed by a word that isn't a known ext
    # must not be treated as an extension.
    assert normalize_file_extensions("end of line.Next sentence") == (
        "end of line.Next sentence"
    )


# --- plural initialisms ---------------------------------------------------- #
def test_plural_initialism_voiced():
    # Phonetic body + an English-word plural ending on the final letter.
    assert normalize_plural_initialisms("many APIs here") == "many eigh pee eyes here"
    assert normalize_plural_initialisms("SDKs and IDEs") == "ess dee kays and eye dee ees"


def test_singular_initialism_untouched_by_plural_rule():
    # The plural rule only fires on a trailing lowercase s.
    assert normalize_plural_initialisms("one API only") == "one API only"


# --- symbols --------------------------------------------------------------- #
def test_symbols_spoken():
    out = normalize_symbols("use === not == and ?? over ||")
    assert "triple equals" in out
    assert "double equals" in out
    assert "nullish coalescing" in out
    assert "logical or" in out


def test_arrow_symbol():
    assert "arrow" in normalize_symbols("const f = () => 1")


# --- version suffixes ------------------------------------------------------ #
def test_trailing_plus():
    assert normalize_version_suffixes("ES6+ features") == "ES6 plus features"
    # (ES->E S happens in the acronym table later; here only the + is handled)


# --- full chain ------------------------------------------------------------ #
def test_full_chain_order_and_spacing():
    out = normalize_tech_text("prefer === over ==, and ?? vs ||")
    assert out == "prefer triple equals over double equals, and nullish coalescing vs logical or"
    # No stray space before the comma.
    assert " ," not in out


# --- section numbers ------------------------------------------------------- #
def test_multilevel_section_number_expanded_anywhere():
    from md2speech.normalize import normalize_multilevel_section_numbers

    assert normalize_multilevel_section_numbers("see 1.1.1 now") == (
        "see one dot one dot one now"
    )
    # Two-segment numbers are NOT touched here (ambiguous with decimals).
    assert normalize_multilevel_section_numbers("pi is 3.14") == "pi is 3.14"


def test_heading_section_number_expanded():
    from md2speech.normalize import normalize_heading_section_number

    assert normalize_heading_section_number("1.1 What X") == "one dot one. What X"
    assert normalize_heading_section_number("1.1.1 Deep") == (
        "one dot one dot one. Deep"
    )
    assert normalize_heading_section_number("1. Overview") == "One. Overview"
    # A heading with no leading number is unchanged.
    assert normalize_heading_section_number("Overview") == "Overview"


def test_decimals_preserved_in_heading_fn():
    from md2speech.normalize import normalize_heading_section_number

    # No leading section number -> untouched (decimal stays).
    assert normalize_heading_section_number("The value 3.14") == "The value 3.14"
