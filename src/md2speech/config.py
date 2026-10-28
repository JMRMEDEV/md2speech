"""Configuration defaults and data directories for md2speech.

Centralizes tunable defaults (voice, speed, pause durations) and the
filesystem locations used for the Kokoro model files and the audio-chunk
cache. Nothing here performs I/O at import time beyond resolving paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path


# --------------------------------------------------------------------------- #
# Filesystem locations (XDG-friendly)
# --------------------------------------------------------------------------- #
def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


#: Directory where the Kokoro model + voices files are expected to live.
DATA_DIR: Path = _xdg_data_home() / "md2speech"
MODELS_DIR: Path = DATA_DIR / "models"

#: Default model/voices filenames shipped by the kokoro-tts project.
MODEL_FILENAME = "kokoro-v1.0.onnx"
VOICES_FILENAME = "voices-v1.0.bin"

MODEL_URL = (
    "https://github.com/nazdridoy/kokoro-tts/releases/download/"
    "v1.0.0/kokoro-v1.0.onnx"
)
VOICES_URL = (
    "https://github.com/nazdridoy/kokoro-tts/releases/download/"
    "v1.0.0/voices-v1.0.bin"
)

#: Audio chunk cache root.
CACHE_DIR: Path = _xdg_cache_home() / "md2speech"

#: Kokoro always emits 24 kHz mono PCM; silence must match for clean concat.
SAMPLE_RATE = 24000
CHANNELS = 1


@dataclass(frozen=True)
class PauseConfig:
    """Pause lengths (seconds) inserted between narration elements."""

    after_title: float = 0.9        # after a heading, before its content
    between_sections: float = 1.2   # before a new top-level/section heading
    between_paragraphs: float = 0.6
    between_list_items: float = 0.35
    after_table_row: float = 0.4
    trailing: float = 0.3           # tail padding on the final chunk


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    voice: str = "af_heart"
    speed: float = 1.0
    lang: str = "en-us"
    audio_format: str = "wav"       # "wav" | "mp3"
    include_code_blocks: bool = False
    include_tables: bool = True     # False => skip tables entirely
    speak_list_transitions: bool = False
    max_chunk_chars: int = 500      # soft cap; never splits mid-sentence

    model_path: Path = field(default_factory=lambda: MODELS_DIR / MODEL_FILENAME)
    voices_path: Path = field(default_factory=lambda: MODELS_DIR / VOICES_FILENAME)

    pauses: PauseConfig = field(default_factory=PauseConfig)

    #: Optional path to a YAML pronunciation-replacement file.
    pronunciation_path: Path | None = None

    #: Apply the built-in tech-friendly default pronunciations (acronyms etc.).
    use_default_pronunciation: bool = True

    def with_overrides(self, **kwargs: object) -> "Config":
        """Return a copy with the given non-None fields overridden."""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean)


def default_pronunciation_candidates() -> list[Path]:
    """Standard locations searched for a pronunciation YAML when unspecified."""
    return [
        Path.cwd() / "md2speech.pronunciation.yaml",
        DATA_DIR / "pronunciation.yaml",
    ]
