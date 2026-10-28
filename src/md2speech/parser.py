"""Markdown -> narration-ready text.

Parses Markdown structurally with ``markdown-it-py`` and emits an ordered list
of :class:`NarrationBlock` objects. Each block carries the spoken text plus a
*pause-before* hint so downstream audio assembly can insert natural gaps
without the TTS engine ever seeing Markdown punctuation.

Design goals:
  * Never speak formatting syntax (``*``, ``_``, ``~~``, ``>``, ``#`` ...).
  * Links -> visible label only; raw URLs dropped by default.
  * Images (paths/URLs) skipped entirely.
  * Ordered lists (incl. nonstandard ``1.-`` / ``1)`` markers) read naturally.
  * Tables -> one sentence per row, or skipped.
  * Fenced code skipped by default.
  * Preserve document / chapter order.
  * No paraphrasing: text content is passed through verbatim (minus syntax).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from markdown_it import MarkdownIt
from markdown_it.token import Token

from .config import Config


class PauseKind(str, Enum):
    """Semantic category of the gap *before* a narration block."""

    NONE = "none"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TITLE = "title"
    SECTION = "section"
    TABLE_ROW = "table_row"


@dataclass
class NarrationBlock:
    """A single spoken unit with a pause hint describing the gap before it."""

    text: str
    pause_before: PauseKind = PauseKind.NONE
    is_heading: bool = False
    heading_level: int = 0


# --------------------------------------------------------------------------- #
# Pre-normalization: fix nonstandard list markers before structural parsing.
# --------------------------------------------------------------------------- #

# Matches lines like "1.- Foo", "2.) Foo", "3 - Foo", "4) Foo" at line start.
_NONSTD_ORDERED = re.compile(
    r"^(?P<indent>\s*)(?P<num>\d+)\s*(?:\.\-|\.\)|\.|\)|\-)\s+(?P<body>\S.*)$"
)
# Standard ordered markers markdown-it already understands: "1. " / "1) ".
_STD_ORDERED_OK = re.compile(r"^\s*\d+[.)]\s+\S")


def _normalize_nonstandard_markers(md_text: str) -> str:
    """Rewrite nonstandard ordered-list markers into clean ``N. body`` form.

    markdown-it only recognizes ``1.`` and ``1)``. Study notes frequently use
    ``1.-`` which otherwise ends up as a literal paragraph where the engine
    would speak the punctuation. We rewrite such lines to a canonical marker
    so they parse as real ordered lists (and so item numbers are available).
    """
    out: list[str] = []
    for line in md_text.splitlines():
        if _STD_ORDERED_OK.match(line):
            out.append(line)
            continue
        m = _NONSTD_ORDERED.match(line)
        if m:
            out.append(f"{m.group('indent')}{m.group('num')}. {m.group('body')}")
        else:
            out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Ordinal words for natural ordered-list narration.
# --------------------------------------------------------------------------- #
_ORDINAL_WORDS = {
    1: "First", 2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth",
    6: "Sixth", 7: "Seventh", 8: "Eighth", 9: "Ninth", 10: "Tenth",
}


def _ordinal_prefix(n: int, speak_transitions: bool) -> str:
    """Spoken lead-in for ordered-list item ``n`` (no punctuation spoken)."""
    if not speak_transitions:
        return ""
    word = _ORDINAL_WORDS.get(n)
    if word:
        return f"{word}, "
    return f"Number {n}, "


class MarkdownNarrator:
    """Converts Markdown source into ordered :class:`NarrationBlock` objects."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._md = (
            MarkdownIt("commonmark")
            .enable("table")
            .enable("strikethrough")
        )

    # -- public API -------------------------------------------------------- #
    def to_blocks(self, md_text: str) -> list[NarrationBlock]:
        normalized = _normalize_nonstandard_markers(md_text)
        tokens = self._md.parse(normalized)
        blocks: list[NarrationBlock] = []
        self._walk(tokens, blocks)
        return [b for b in blocks if b.text.strip()]

    def to_text(self, md_text: str) -> str:
        """Flatten blocks into a single preview string (one block per line)."""
        lines: list[str] = []
        for b in self.to_blocks(md_text):
            lines.append(b.text)
        return "\n".join(lines)

    # -- token walking ----------------------------------------------------- #
    def _walk(self, tokens: list[Token], blocks: list[NarrationBlock]) -> None:
        i = 0
        n = len(tokens)
        # Stack of ("ol"/"ul", counter) to track ordered-list numbering & depth.
        list_stack: list[list] = []

        while i < n:
            tok = tokens[i]
            ttype = tok.type

            if ttype == "heading_open":
                level = int(tok.tag[1])
                inline = tokens[i + 1]
                text = self._render_inline(inline)
                pause = PauseKind.SECTION if level <= 2 else PauseKind.TITLE
                if text.strip():
                    blocks.append(
                        NarrationBlock(
                            text=self._finalize_sentence(text),
                            pause_before=pause,
                            is_heading=True,
                            heading_level=level,
                        )
                    )
                i += 3  # heading_open, inline, heading_close
                continue

            if ttype == "paragraph_open":
                inline = tokens[i + 1]
                text = self._render_inline(inline)
                # Determine context: inside a list item vs. standalone paragraph.
                if list_stack:
                    kind = list_stack[-1][0]
                    if kind == "ol":
                        list_stack[-1][1] += 1
                        prefix = _ordinal_prefix(
                            list_stack[-1][1],
                            self.config.speak_list_transitions,
                        )
                        text = prefix + text
                    pause = PauseKind.LIST_ITEM
                else:
                    pause = PauseKind.PARAGRAPH
                if text.strip():
                    blocks.append(
                        NarrationBlock(
                            text=self._finalize_sentence(text),
                            pause_before=pause,
                        )
                    )
                i += 3  # paragraph_open, inline, paragraph_close
                continue

            if ttype == "ordered_list_open":
                list_stack.append(["ol", 0])
                i += 1
                continue
            if ttype == "bullet_list_open":
                list_stack.append(["ul", 0])
                i += 1
                continue
            if ttype in ("ordered_list_close", "bullet_list_close"):
                if list_stack:
                    list_stack.pop()
                i += 1
                continue

            if ttype == "fence" or ttype == "code_block":
                if self.config.include_code_blocks:
                    if self._is_diagram(tok.content):
                        # Never read box-drawing / ASCII-art characters aloud.
                        blocks.append(
                            NarrationBlock(
                                text="Diagram omitted.",
                                pause_before=PauseKind.PARAGRAPH,
                            )
                        )
                    else:
                        code_text = self._spoken_code(tok)
                        if code_text.strip():
                            blocks.append(
                                NarrationBlock(
                                    text=code_text, pause_before=PauseKind.PARAGRAPH
                                )
                            )
                i += 1
                continue

            if ttype == "table_open":
                consumed = self._handle_table(tokens, i, blocks)
                i = consumed
                continue

            # blockquote: markers are already stripped; just recurse into body.
            if ttype in ("blockquote_open", "blockquote_close"):
                i += 1
                continue

            # list_item_open/close carry no spoken content themselves.
            i += 1

    # -- tables ------------------------------------------------------------ #
    def _handle_table(
        self, tokens: list[Token], start: int, blocks: list[NarrationBlock]
    ) -> int:
        """Convert a table into one spoken sentence per body row.

        Returns the index just past ``table_close``. If tables are disabled in
        the config, the table is skipped but still consumed.
        """
        headers: list[str] = []
        rows: list[list[str]] = []
        i = start + 1
        n = len(tokens)
        in_header = False
        current: list[str] = []

        while i < n and tokens[i].type != "table_close":
            t = tokens[i]
            if t.type == "thead_open":
                in_header = True
            elif t.type == "thead_close":
                in_header = False
            elif t.type == "tr_open":
                current = []
            elif t.type == "tr_close":
                if in_header:
                    headers = current
                else:
                    rows.append(current)
            elif t.type in ("th_open", "td_open"):
                # The cell's inline content is the next token.
                if i + 1 < n and tokens[i + 1].type == "inline":
                    current.append(self._render_inline(tokens[i + 1]))
                    i += 1  # skip the inline we just consumed
            i += 1

        end = i + 1  # past table_close

        if not self.config.include_tables:
            return end

        for row in rows:
            sentence = self._row_to_sentence(headers, row)
            if sentence.strip():
                blocks.append(
                    NarrationBlock(
                        text=self._finalize_sentence(sentence),
                        pause_before=PauseKind.TABLE_ROW,
                    )
                )
        return end

    @staticmethod
    def _row_to_sentence(headers: list[str], row: list[str]) -> str:
        """Render a table row as ``Header is value, Header is value``."""
        parts: list[str] = []
        for idx, cell in enumerate(row):
            cell = cell.strip()
            if not cell:
                continue
            if idx < len(headers) and headers[idx].strip():
                parts.append(f"{headers[idx].strip()} is {cell}")
            else:
                parts.append(cell)
        return ", ".join(parts)

    # -- inline rendering -------------------------------------------------- #
    def _render_inline(self, inline: Token) -> str:
        """Flatten inline children to plain spoken text (syntax removed)."""
        if inline is None or not inline.children:
            # Fallback: strip any obvious markers from raw content.
            return self._strip_inline_markers(inline.content if inline else "")

        parts: list[str] = []
        for child in inline.children:
            ctype = child.type
            if ctype == "text":
                parts.append(child.content)
            elif ctype == "code_inline":
                parts.append(self._spoken_inline_code(child.content))
            elif ctype == "softbreak":
                parts.append(" ")
            elif ctype == "hardbreak":
                parts.append(" ")
            elif ctype == "image":
                # Skip image paths/URLs entirely (no alt narration by default).
                continue
            elif ctype in (
                "strong_open", "strong_close",
                "em_open", "em_close",
                "s_open", "s_close",
                "link_close",
            ):
                continue
            elif ctype == "link_open":
                # Visible label is emitted by the following text token(s);
                # raw href is dropped.
                continue
            else:
                # Unknown inline: fall back to its text content if any.
                if child.content:
                    parts.append(child.content)

        text = "".join(parts)
        return self._collapse_ws(self._strip_inline_markers(text))

    # -- code handling ----------------------------------------------------- #
    @staticmethod
    def _spoken_inline_code(content: str) -> str:
        """Inline code: keep the literal token, it is usually a term/name."""
        return content.strip()

    # Box-drawing and common ASCII-art glyphs that signal a diagram.
    _ART_CHARS = set("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬▲▼◀▶▲►◄↑↓←→▪▶•┃━┏┓┗┛┣┫┳┻╋")

    @classmethod
    def _is_diagram(cls, content: str) -> bool:
        """Heuristic: a fenced block that is mostly box-art / punctuation is a
        diagram, not narratable code."""
        stripped = content.strip()
        if not stripped:
            return False
        if any(ch in cls._ART_CHARS for ch in stripped):
            return True
        # Fallback: very low ratio of alphanumeric characters over many lines
        # (e.g. ASCII tables made from -, |, +).
        non_ws = [c for c in stripped if not c.isspace()]
        if not non_ws:
            return False
        alnum_ratio = sum(c.isalnum() for c in non_ws) / len(non_ws)
        line_count = stripped.count("\n") + 1
        return line_count >= 3 and alnum_ratio < 0.35

    @staticmethod
    def _spoken_code(tok: Token) -> str:
        """Render a fenced code block for narration when inclusion is enabled."""
        lang = (tok.info or "").strip().split()[0] if tok.info else ""
        body = tok.content.strip()
        lines = [ln for ln in body.splitlines() if ln.strip()]
        spoken = ". ".join(ln.strip() for ln in lines)
        lead = f"Code block{(' in ' + lang) if lang else ''}. "
        return f"{lead}{spoken}."

    # -- text helpers ------------------------------------------------------ #
    @staticmethod
    def _collapse_ws(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _strip_inline_markers(text: str) -> str:
        """Defensive removal of any residual Markdown emphasis/marker chars.

        Structural parsing handles the common cases; this catches leftovers
        (e.g. stray ``**`` inside otherwise-plain text, or nonstandard markers
        that survived as inline soft-break lines).
        """
        if not text:
            return ""
        # Strip emphasis/strike markers.
        text = re.sub(r"(\*\*|\*|__|_|~~)", "", text)
        # Strip leading blockquote markers.
        text = re.sub(r"(?m)^\s*>+\s?", "", text)
        # Strip residual NONSTANDARD ordered markers at line starts
        # (e.g. "1.-", "1.)", "1)", "1-"). A plain "1." is intentionally NOT
        # stripped so heading section numbers like "1. Overview" survive and
        # are later spoken as words ("One.").
        text = re.sub(r"(?m)^\s*\d+\s*(?:\.\-|\.\)|\)|\-)\s+", "", text)
        # Strip residual bullet markers at line starts.
        text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
        return text

    @staticmethod
    def _finalize_sentence(text: str) -> str:
        """Ensure a block ends with sentence punctuation for natural prosody."""
        text = MarkdownNarrator._collapse_ws(text)
        if not text:
            return text
        if text[-1] not in ".!?:;,":
            text = text + "."
        return text


def iter_blocks(md_text: str, config: Config) -> Iterable[NarrationBlock]:
    """Convenience wrapper returning narration blocks for ``md_text``."""
    return MarkdownNarrator(config).to_blocks(md_text)
