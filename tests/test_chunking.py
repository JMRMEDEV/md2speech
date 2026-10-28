"""Tests for pronunciation replacement and chunking."""

from md2speech.config import Config
from md2speech.chunking import Pronunciation, chunk_blocks
from md2speech.parser import MarkdownNarrator, NarrationBlock, PauseKind


# --- pronunciation --------------------------------------------------------- #
def test_whole_word_case_insensitive_replacement():
    p = Pronunciation({"API": "A P I"})
    assert p.apply("The api and API are APIs.") == "The A P I and A P I are APIs."


def test_longer_terms_take_precedence():
    p = Pronunciation({"HTTP": "H T T P", "HTTPS": "H T T P S"})
    assert p.apply("Use HTTPS not HTTP.") == "Use H T T P S not H T T P."


def test_replacement_with_punctuation_key():
    p = Pronunciation({"e.g.": "for example"})
    assert p.apply("Fruits, e.g. apples.") == "Fruits, for example apples."


def test_from_file_yaml(tmp_path):
    f = tmp_path / "pron.yaml"
    f.write_text("replacements:\n  GPU: G P U\n  CPU: C P U\n", encoding="utf-8")
    p = Pronunciation.from_file(f)
    assert p.apply("GPU and CPU") == "G P U and C P U"


def test_from_file_bare_mapping(tmp_path):
    f = tmp_path / "pron.yaml"
    f.write_text("RAM: R A M\n", encoding="utf-8")
    assert Pronunciation.from_file(f).apply("RAM") == "R A M"


def test_apply_to_blocks_preserves_metadata():
    p = Pronunciation({"DNA": "D N A"})
    blk = NarrationBlock("DNA matters.", PauseKind.PARAGRAPH, False, 0)
    out = p.apply_to_blocks([blk])
    assert out[0].text == "D N A matters."
    assert out[0].pause_before == PauseKind.PARAGRAPH


# --- built-in default pronunciations --------------------------------------- #
def test_defaults_applied_automatically():
    # No pronunciation file provided; built-in tech dictionary should apply.
    p = Pronunciation.load(Config())
    assert p.apply("The UX and QA teams.") == "The you ex and cue eigh teams."
    assert p.apply("Use the API via REST.") == "Use the eigh pee eye via rest."
    assert p.apply("We ship with CI/CD.") == "We ship with see eye see dee."


def test_defaults_can_be_disabled():
    p = Pronunciation.load(Config(use_default_pronunciation=False))
    assert p.apply("The UX team.") == "The UX team."


def test_user_yaml_overrides_defaults(tmp_path):
    f = tmp_path / "pron.yaml"
    # Override the built-in UX mapping and add a new term.
    f.write_text("replacements:\n  UX: user experience\n  ACME: eigh pee eye\n",
                 encoding="utf-8")
    p = Pronunciation.load(Config(pronunciation_path=f))
    out = p.apply("ACME cares about UX and QA.")
    assert "user experience" in out      # user override wins
    assert "you ex" not in out           # default replaced
    assert "eigh pee eye" in out              # user addition (kept as given)
    assert "cue eigh" in out             # default QA still present (phonetic)


# --- chunking -------------------------------------------------------------- #
def _blocks(md, **cfg):
    return MarkdownNarrator(Config(**cfg)).to_blocks(md)


def test_heading_is_isolated_chunk():
    cfg = Config()
    chunks = chunk_blocks(_blocks("# Title\n\nbody text here."), cfg)
    assert chunks[0].text == "Title."
    assert chunks[0].pause_before == PauseKind.SECTION


def test_never_splits_mid_sentence():
    long_sentence = (
        "This is a single very long sentence that must not be broken in the "
        "middle regardless of the character cap because splitting mid sentence "
        "would sound unnatural to a listener."
    )
    cfg = Config(max_chunk_chars=50)
    chunks = chunk_blocks([NarrationBlock(long_sentence, PauseKind.PARAGRAPH)], cfg)
    # The whole oversized single sentence stays in one chunk.
    assert len(chunks) == 1
    assert chunks[0].text == long_sentence


def test_splits_on_sentence_boundary_when_oversized():
    # Each sentence is well under the cap; combined they exceed it, so the
    # block is split on sentence boundaries (never mid-sentence).
    text = (
        "Sentence one describes the first idea clearly. "
        "Sentence two describes the second idea clearly. "
        "Sentence three describes the third idea clearly. "
        "Sentence four describes the fourth idea clearly."
    )
    cfg = Config(max_chunk_chars=100)
    chunks = chunk_blocks([NarrationBlock(text, PauseKind.PARAGRAPH)], cfg)
    assert len(chunks) >= 2
    # Each chunk must end on a sentence terminator (no mid-sentence cut).
    for c in chunks:
        assert c.text.rstrip()[-1] in ".!?"


def test_small_blocks_are_packed():
    cfg = Config(max_chunk_chars=500)
    chunks = chunk_blocks(
        [
            NarrationBlock("One.", PauseKind.PARAGRAPH),
            NarrationBlock("Two.", PauseKind.PARAGRAPH),
        ],
        cfg,
    )
    assert len(chunks) == 1
    assert "One." in chunks[0].text and "Two." in chunks[0].text
