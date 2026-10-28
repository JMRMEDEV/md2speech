"""High-level orchestration tying the layers together.

Keeps the CLI thin: given Markdown text and a resolved :class:`Config`, this
module produces narration chunks, synthesizes them (with caching), and either
assembles an output file or streams playback. Streaming interleaves synthesis
and playback so long documents start playing before full synthesis completes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .audio import SilenceCache, assemble, pause_seconds
from .chunking import Pronunciation, SpeechChunk, chunk_blocks
from .config import CACHE_DIR, Config
from .parser import MarkdownNarrator
from .playback import PlaybackBackend
from .tts import KokoroBackend


@dataclass
class Pipeline:
    config: Config
    backend: KokoroBackend

    @classmethod
    def create(cls, config: Config) -> "Pipeline":
        return cls(config=config, backend=KokoroBackend(config))

    # -- text stages ------------------------------------------------------- #
    def narration_chunks(self, md_text: str) -> list[SpeechChunk]:
        blocks = MarkdownNarrator(self.config).to_blocks(md_text)
        blocks = self._normalize_blocks(blocks)
        blocks = Pronunciation.load(self.config).apply_to_blocks(blocks)
        blocks = self._normalize_plurals(blocks)
        return chunk_blocks(blocks, self.config)

    @staticmethod
    def _normalize_blocks(blocks):
        """Technical normalization that must run BEFORE the acronym table
        (file extensions, operators, version suffixes). Headings additionally
        get their leading section number expanded (1.1 -> 'one dot one')."""
        from .normalize import (
            normalize_heading_section_number,
            normalize_tech_text,
        )
        from .parser import NarrationBlock

        out = []
        for b in blocks:
            text = b.text
            if b.is_heading:
                text = normalize_heading_section_number(text)
            text = normalize_tech_text(text)
            out.append(
                NarrationBlock(
                    text=text,
                    pause_before=b.pause_before,
                    is_heading=b.is_heading,
                    heading_level=b.heading_level,
                )
            )
        return out

    @staticmethod
    def _normalize_plurals(blocks):
        """Plural initialisms run AFTER the acronym table so singular forms
        (API) are handled by the dictionary and plurals (APIs) here."""
        from .normalize import normalize_plural_initialisms
        from .parser import NarrationBlock

        out = []
        for b in blocks:
            out.append(
                NarrationBlock(
                    text=normalize_plural_initialisms(b.text),
                    pause_before=b.pause_before,
                    is_heading=b.is_heading,
                    heading_level=b.heading_level,
                )
            )
        return out

    def preview_text(self, md_text: str) -> str:
        return "\n".join(c.text for c in self.narration_chunks(md_text))

    # -- synthesis to a file ---------------------------------------------- #
    def synthesize_to_file(
        self,
        md_text: str,
        out_path: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        self.backend.preflight()
        chunks = self.narration_chunks(md_text)
        if not chunks:
            raise ValueError("No narratable content found in the Markdown input.")
        pairs: list[tuple[SpeechChunk, Path]] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            wav = self.backend.synthesize_chunk(chunk.text)
            pairs.append((chunk, wav))
            if progress:
                progress(idx, total)
        silence = SilenceCache(CACHE_DIR / "silence")
        return assemble(pairs, out_path, self.config, silence)

    # -- streaming synthesis + playback ----------------------------------- #
    def stream_play(
        self,
        md_text: str,
        player: PlaybackBackend,
        progress: Callable[[int, int], None] | None = None,
        start_index: int = 0,
        on_chunk_done: Callable[[int, int, SpeechChunk], None] | None = None,
    ) -> None:
        """Synthesize chunk-by-chunk and play as each becomes ready.

        A one-chunk look-ahead keeps the next chunk synthesizing while the
        current one would otherwise block; here we keep it simple and safe by
        synthesizing then playing sequentially, relying on the chunk cache for
        responsiveness. Pauses are played as short silence WAVs between chunks.

        Keyboard controls (p/c/q) are active for the whole session when stdin
        is an interactive terminal.

        ``start_index`` resumes from a saved position (0-based chunk index).
        ``on_chunk_done(next_index, total, chunk)`` is called after each chunk
        finishes playing, so the caller can persist a resume bookmark. On
        interruption it is NOT called for the unfinished chunk, so the saved
        pointer stays at the last fully-heard chunk.
        """
        from .playback import KeyboardControls

        self.backend.preflight()
        chunks = self.narration_chunks(md_text)
        if not chunks:
            raise ValueError("No narratable content found in the Markdown input.")
        total = len(chunks)
        start_index = max(0, min(start_index, total))
        silence = SilenceCache(CACHE_DIR / "silence")

        with KeyboardControls() as controls:
            # Attach controls so pause/resume/quit work during each chunk.
            if hasattr(player, "controls"):
                player.controls = controls
            for idx in range(start_index, total):
                chunk = chunks[idx]
                wav = self.backend.synthesize_chunk(chunk.text)
                # Play the inter-chunk pause (skip before the very first played
                # chunk of the whole document, but keep it when resuming).
                if idx > 0:
                    sil = silence.get(
                        pause_seconds(chunk.pause_before, self.config)
                    )
                    if sil is not None:
                        player.play_file(sil)
                if progress:
                    progress(idx + 1, total)
                player.play_file(wav)
                # Chunk fully heard -> report so caller can bookmark next index.
                if on_chunk_done:
                    on_chunk_done(idx + 1, total, chunk)

    def chunk_count(self, md_text: str) -> int:
        return len(self.narration_chunks(md_text))


def iter_markdown_files(path: Path, recursive: bool) -> Iterator[Path]:
    """Yield Markdown files for a file or directory input, in sorted order."""
    path = Path(path)
    if path.is_file():
        yield path
        return
    if path.is_dir():
        pattern = "**/*" if recursive else "*"
        exts = {".md", ".markdown", ".mdown", ".mkd"}
        for p in sorted(path.glob(pattern)):
            if p.is_file() and p.suffix.lower() in exts:
                yield p
        return
    raise FileNotFoundError(f"Input path does not exist: {path}")
