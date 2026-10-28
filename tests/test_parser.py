"""Tests for Markdown -> narration normalization."""

from md2speech.config import Config
from md2speech.parser import MarkdownNarrator, PauseKind


def blocks(md: str, **cfg):
    return MarkdownNarrator(Config(**cfg)).to_blocks(md)


def texts(md: str, **cfg):
    return [b.text for b in blocks(md, **cfg)]


# --- headings -------------------------------------------------------------- #
def test_heading_becomes_spoken_title_with_section_pause():
    bs = blocks("# Introduction to Cells")
    assert len(bs) == 1
    assert bs[0].is_heading is True
    assert bs[0].heading_level == 1
    assert bs[0].text == "Introduction to Cells."
    assert bs[0].pause_before == PauseKind.SECTION


def test_deep_heading_uses_title_pause():
    bs = blocks("### Subsection")
    assert bs[0].pause_before == PauseKind.TITLE
    assert "#" not in bs[0].text


# --- emphasis / blockquote stripping -------------------------------------- #
def test_bold_italic_strike_blockquote_removed():
    md = "**bold** and *italic* and ~~gone~~ text\n\n> quoted line"
    joined = " ".join(texts(md))
    for marker in ("*", "_", "~", ">", "#"):
        assert marker not in joined
    assert "bold" in joined and "italic" in joined and "gone" in joined
    assert "quoted line" in joined


# --- links ----------------------------------------------------------------- #
def test_link_keeps_label_drops_url():
    bs = texts("See [the manual](https://example.com/manual) now.")
    text = " ".join(bs)
    assert "the manual" in text
    assert "https://example.com/manual" not in text
    assert "http" not in text


# --- images ---------------------------------------------------------------- #
def test_image_paths_are_skipped():
    text = " ".join(texts("Here ![alt text](diagram.png) end."))
    assert "diagram.png" not in text
    assert "alt text" not in text  # alt not narrated by default


# --- ordered lists incl. nonstandard markers ------------------------------ #
def test_nonstandard_ordered_markers_no_spoken_punctuation():
    md = "1.- Alpha\n2.- Beta\n3.- Gamma\n"
    bs = texts(md)
    assert bs == ["Alpha.", "Beta.", "Gamma."]
    for line in bs:
        assert ".-" not in line
        assert not line.startswith(("1", "2", "3"))


def test_standard_ordered_markers_clean():
    bs = texts("1. First\n2. Second\n")
    assert bs == ["First.", "Second."]


def test_heading_leading_number_not_stripped():
    # A heading like "## 1. Overview" must keep its section number (which the
    # pipeline later speaks as "One."); only the Markdown '##' is removed.
    bs = blocks("## 1. Overview")
    assert bs[0].is_heading is True
    assert bs[0].text == "1. Overview."  # number preserved at parser stage


def test_heading_dotted_number_preserved_at_parser_stage():
    bs = blocks("## 1.1 Mechanism")
    assert bs[0].text == "1.1 Mechanism."


def test_ordered_list_transitions_optional():
    bs = texts("1. Mix\n2. Heat\n", speak_list_transitions=True)
    assert bs[0].startswith("First,")
    assert bs[1].startswith("Second,")


# --- nested lists ---------------------------------------------------------- #
def test_nested_list_items_preserved_in_order():
    md = "- Outer one\n- Outer two\n  - Inner a\n  - Inner b\n"
    bs = texts(md)
    assert bs == ["Outer one.", "Outer two.", "Inner a.", "Inner b."]
    for line in bs:
        assert not line.lstrip().startswith(("-", "*", "+"))


# --- tables ---------------------------------------------------------------- #
def test_table_rows_become_sentences():
    md = (
        "| Organelle | Role |\n"
        "|-----------|------|\n"
        "| Nucleus | Stores DNA |\n"
        "| Ribosome | Makes protein |\n"
    )
    bs = texts(md)
    assert "Organelle is Nucleus, Role is Stores DNA." in bs
    assert "Organelle is Ribosome, Role is Makes protein." in bs
    assert all("|" not in b for b in bs)


def test_table_can_be_skipped():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    bs = texts(md, include_tables=False)
    assert bs == []


# --- code blocks ----------------------------------------------------------- #
def test_fenced_code_skipped_by_default():
    md = "Intro.\n\n```python\nprint('secret')\n```\n"
    text = " ".join(texts(md))
    assert "secret" not in text
    assert "print" not in text
    assert "Intro." in text


def test_fenced_code_included_when_enabled():
    md = "```python\nx = 1\n```\n"
    text = " ".join(texts(md, include_code_blocks=True))
    assert "x = 1" in text
    assert "python" in text


def test_inline_code_is_kept():
    text = " ".join(texts("Use the `numpy` package today."))
    assert "numpy" in text
    assert "`" not in text


# --- diagrams -------------------------------------------------------------- #
def test_ascii_diagram_is_announced_not_read():
    md = (
        "Intro.\n\n"
        "```\n"
        "┌──────────┐\n"
        "│ CALL STACK │\n"
        "└──────────┘\n"
        "```\n"
    )
    bs = texts(md, include_code_blocks=True)
    assert "Diagram omitted." in bs
    # None of the box-drawing characters leak into narration.
    joined = " ".join(bs)
    for ch in "┌┐└┘│─":
        assert ch not in joined


def test_real_code_block_still_narrated_when_included():
    md = "```js\nconst x = 1;\n```\n"
    bs = texts(md, include_code_blocks=True)
    joined = " ".join(bs)
    assert "Diagram omitted." not in joined
    assert "const x = 1" in joined


# --- ordering -------------------------------------------------------------- #
def test_document_order_preserved():
    md = "# A\n\npara\n\n## B\n\n- item\n"
    bs = texts(md)
    assert bs == ["A.", "para.", "B.", "item."]
