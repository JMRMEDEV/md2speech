"""Pronunciation replacement + narration chunking.

Two concerns live here because they are the last text-only transforms before
synthesis:

* :class:`Pronunciation` applies user-supplied replacements (from a YAML file)
  so acronyms / abbreviations / domain terms are spoken sensibly.
* :func:`chunk_blocks` groups :class:`NarrationBlock` objects into speech
  chunks bounded by a soft character cap, splitting only at sentence or block
  boundaries (never mid-sentence) and preserving pause metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .config import Config
from .parser import NarrationBlock, PauseKind


# --------------------------------------------------------------------------- #
# Pronunciation
# --------------------------------------------------------------------------- #
@dataclass
class Pronunciation:
    """Whole-word, case-insensitive replacement table for spoken text.

    YAML schema (both forms accepted)::

        replacements:
          API: "A P I"
          HTTP: "H T T P"
          e.g.: "for example"

        # or a bare top-level mapping:
        API: "A P I"
    """

    replacements: dict[str, str]

    @classmethod
    def empty(cls) -> "Pronunciation":
        return cls(replacements={})

    @classmethod
    def from_file(cls, path: Path) -> "Pronunciation":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict) and "replacements" in data:
            data = data["replacements"] or {}
        if not isinstance(data, dict):
            raise ValueError(
                f"Pronunciation file {path} must be a mapping of term -> spoken form."
            )
        # Normalize keys/values to strings.
        table = {str(k): str(v) for k, v in data.items()}
        return cls(replacements=table)

    @classmethod
    def load(cls, config: Config) -> "Pronunciation":
        """Build the active replacement table.

        Precedence (lowest to highest):
          1. built-in tech-friendly defaults (unless disabled in config),
          2. a pronunciation YAML (explicit path, or first default location),
        so user entries override and extend the built-ins.
        """
        from .config import default_pronunciation_candidates
        from .pronunciations import DEFAULT_PRONUNCIATIONS

        table: dict[str, str] = {}
        if getattr(config, "use_default_pronunciation", True):
            table.update(DEFAULT_PRONUNCIATIONS)

        user: dict[str, str] | None = None
        if config.pronunciation_path is not None:
            p = Path(config.pronunciation_path)
            if not p.exists():
                raise FileNotFoundError(f"Pronunciation file not found: {p}")
            user = cls.from_file(p).replacements
        else:
            for candidate in default_pronunciation_candidates():
                if candidate.exists():
                    user = cls.from_file(candidate).replacements
                    break

        if user:
            table.update(user)  # user wins over built-ins
        return cls(replacements=table)

    def _compiled(self) -> list[tuple[re.Pattern[str], str]]:
        compiled: list[tuple[re.Pattern[str], str]] = []
        # Longer keys first so multi-word terms win over sub-terms.
        for term in sorted(self.replacements, key=len, reverse=True):
            repl = self.replacements[term]
            escaped = re.escape(term)
            # Use word boundaries when the term is alphanumeric; otherwise match
            # literally (handles tokens like "e.g." that contain punctuation).
            if re.fullmatch(r"[\w\s]+", term):
                pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
            else:
                pattern = re.compile(escaped, re.IGNORECASE)
            compiled.append((pattern, repl))
        return compiled

    def apply(self, text: str) -> str:
        if not self.replacements:
            return text
        for pattern, repl in self._compiled():
            text = pattern.sub(repl.replace("\\", r"\\"), text)
        return text

    def apply_to_blocks(
        self, blocks: Iterable[NarrationBlock]
    ) -> list[NarrationBlock]:
        if not self.replacements:
            return list(blocks)
        out: list[NarrationBlock] = []
        for b in blocks:
            out.append(
                NarrationBlock(
                    text=self.apply(b.text),
                    pause_before=b.pause_before,
                    is_heading=b.is_heading,
                    heading_level=b.heading_level,
                )
            )
        return out


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
@dataclass
class SpeechChunk:
    """A unit of text sent to the TTS engine, plus the pause that precedes it."""

    text: str
    pause_before: PauseKind
    #: The most recent heading text in effect for this chunk (for progress
    #: save files / "you are here" reporting). Empty before the first heading.
    heading: str = ""
    #: Stable cache key input is derived from (text, voice, speed, lang) later.


# Sentence boundary: terminator followed by whitespace. Keeps the terminator.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_blocks(
    blocks: Iterable[NarrationBlock], config: Config
) -> list[SpeechChunk]:
    """Group narration blocks into bounded speech chunks.

    Rules:
      * A heading always starts its own chunk (so its section pause is honored).
      * Consecutive paragraph/list text is packed up to ``max_chunk_chars``.
      * When a single block exceeds the cap, it is split on sentence
        boundaries only - never mid-sentence.
      * The pause category recorded on a chunk is that of the first block that
        began it, preserving the intended gap before the spoken unit.
    """
    cap = max(80, config.max_chunk_chars)
    chunks: list[SpeechChunk] = []

    buf_text: list[str] = []
    buf_pause: PauseKind | None = None
    current_heading = ""

    def flush() -> None:
        nonlocal buf_text, buf_pause
        if buf_text:
            chunks.append(
                SpeechChunk(
                    text=" ".join(buf_text).strip(),
                    pause_before=buf_pause or PauseKind.NONE,
                    heading=current_heading,
                )
            )
        buf_text = []
        buf_pause = None

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        # Headings are isolated for clean section pacing.
        if block.is_heading:
            flush()
            current_heading = text
            chunks.append(
                SpeechChunk(
                    text=text,
                    pause_before=block.pause_before,
                    heading=current_heading,
                )
            )
            continue

        # Oversized block: split into sentences, each respecting the cap.
        if len(text) > cap:
            flush()
            sentences = _split_sentences(text)
            cur: list[str] = []
            cur_len = 0
            first = True
            for sent in sentences:
                add_len = len(sent) + (1 if cur else 0)
                if cur and cur_len + add_len > cap:
                    chunks.append(
                        SpeechChunk(
                            text=" ".join(cur),
                            pause_before=block.pause_before
                            if first
                            else PauseKind.NONE,
                            heading=current_heading,
                        )
                    )
                    first = False
                    cur, cur_len = [], 0
                cur.append(sent)
                cur_len += add_len
            if cur:
                chunks.append(
                    SpeechChunk(
                        text=" ".join(cur),
                        pause_before=block.pause_before if first else PauseKind.NONE,
                        heading=current_heading,
                    )
                )
            continue

        # Normal block: try to pack into the current buffer.
        prospective = (sum(len(t) for t in buf_text) + len(buf_text)) + len(text)
        if buf_text and prospective > cap:
            flush()
        if not buf_text:
            buf_pause = block.pause_before
        buf_text.append(text)

    flush()
    return chunks
