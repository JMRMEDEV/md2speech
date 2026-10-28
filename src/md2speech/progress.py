"""Resume-pointer (bookmark) persistence for playback sessions.

When a user plays a Markdown file and stops partway (quit key / Ctrl+C), we
save a small ``.sav`` file recording the last fully-heard chunk so a later run
can resume from there. The save lives in a ``.md2speech/`` directory next to
the source file and never touches the original Markdown.

Save file example (``topics/.md2speech/01-javascript.sav``)::

    {
      "version": 1,
      "source": "01-javascript.md",
      "source_sha256": "…",          # guards against resuming a stale index
      "chunk_index": 42,              # next chunk to play (0-based)
      "total_chunks": 130,
      "heading": "1.4 Ordering puzzle #2 — await is a microtask continuation",
      "voice": "af_heart",
      "speed": 1.0,
      "updated_at": "2026-10-27T18:50:00"
    }
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

SAVE_DIR_NAME = ".md2speech"
SAVE_SUFFIX = ".sav"
SAVE_VERSION = 1


def source_hash(md_text: str) -> str:
    return hashlib.sha256(md_text.encode("utf-8")).hexdigest()


def save_path_for(md_file: Path) -> Path:
    """Return the ``.sav`` path for a given Markdown source file."""
    md_file = Path(md_file)
    return md_file.parent / SAVE_DIR_NAME / (md_file.stem + SAVE_SUFFIX)


@dataclass
class Bookmark:
    source: str
    source_sha256: str
    chunk_index: int          # 0-based index of the NEXT chunk to play
    total_chunks: int
    heading: str
    voice: str
    speed: float
    updated_at: str = ""
    version: int = SAVE_VERSION

    # -- persistence ------------------------------------------------------ #
    def write(self, md_file: Path) -> Path:
        path = save_path_for(md_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic
        return path

    @classmethod
    def read(cls, md_file: Path) -> "Bookmark | None":
        path = save_path_for(md_file)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                source=data["source"],
                source_sha256=data["source_sha256"],
                chunk_index=int(data["chunk_index"]),
                total_chunks=int(data.get("total_chunks", 0)),
                heading=data.get("heading", ""),
                voice=data.get("voice", ""),
                speed=float(data.get("speed", 1.0)),
                updated_at=data.get("updated_at", ""),
                version=int(data.get("version", SAVE_VERSION)),
            )
        except (ValueError, KeyError, OSError):
            return None

    @staticmethod
    def clear(md_file: Path) -> bool:
        path = save_path_for(md_file)
        if path.exists():
            path.unlink()
            return True
        return False

    # -- validation ------------------------------------------------------- #
    def matches_source(self, md_text: str) -> bool:
        return self.source_sha256 == source_hash(md_text)

    def is_complete(self) -> bool:
        return self.total_chunks > 0 and self.chunk_index >= self.total_chunks
