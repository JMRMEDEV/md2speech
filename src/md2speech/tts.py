"""Kokoro TTS backend wrapper.

Wraps the external ``kokoro-tts`` command. Responsibilities:

* Detect the ``kokoro-tts`` executable and validate model/voices files.
* Validate the requested voice against the engine's advertised voice list.
* Synthesize a single text chunk to a WAV file via a safe subprocess call
  (argument list, never a shell string).
* Cache synthesized chunks keyed by a hash of (text, voice, speed, lang,
  format, model), so unchanged content is never regenerated.

This module never implements TTS itself - it only orchestrates the CLI.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import CACHE_DIR, Config


class KokoroError(RuntimeError):
    """Raised for any backend problem with actionable messaging."""


# Lines in kokoro-tts stderr/stdout that are noise, not real errors.
_NOISE_SUBSTRINGS = (
    "onnxruntime",
    "device_discovery",
    "GPU device discovery",
    "fitz` API is deprecated",
    "Use `import pymupdf`",
)


def _filter_noise(text: str) -> str:
    lines = [
        ln
        for ln in text.splitlines()
        if ln.strip() and not any(s in ln for s in _NOISE_SUBSTRINGS)
    ]
    return "\n".join(lines)


@dataclass
class KokoroBackend:
    """Thin orchestrator around the ``kokoro-tts`` executable."""

    config: Config
    executable: str = "kokoro-tts"
    cache_dir: Path = CACHE_DIR

    # -- discovery / validation ------------------------------------------- #
    def resolve_executable(self) -> str:
        exe = shutil.which(self.executable)
        if not exe:
            raise KokoroError(
                "The 'kokoro-tts' command was not found on PATH.\n"
                "Install it with:  pip install --user kokoro-tts\n"
                "and ensure ~/.local/bin is on your PATH."
            )
        return exe

    def validate_models(self) -> None:
        missing = []
        if not self.config.model_path.exists():
            missing.append((self.config.model_path, "kokoro-v1.0.onnx"))
        if not self.config.voices_path.exists():
            missing.append((self.config.voices_path, "voices-v1.0.bin"))
        if missing:
            lines = ["Required Kokoro model files are missing:"]
            for path, name in missing:
                lines.append(f"  - {name}: expected at {path}")
            lines.append("")
            lines.append("Download them once (works offline afterwards):")
            lines.append(f"  mkdir -p {self.config.model_path.parent}")
            lines.append(
                f"  wget -O {self.config.model_path} "
                "https://github.com/nazdridoy/kokoro-tts/releases/download/"
                "v1.0.0/kokoro-v1.0.onnx"
            )
            lines.append(
                f"  wget -O {self.config.voices_path} "
                "https://github.com/nazdridoy/kokoro-tts/releases/download/"
                "v1.0.0/voices-v1.0.bin"
            )
            raise KokoroError("\n".join(lines))

    def available_voices(self) -> list[str]:
        """Return the voice identifiers advertised by the engine."""
        exe = self.resolve_executable()
        try:
            proc = subprocess.run(
                [
                    exe,
                    "--help-voices",
                    "--model",
                    str(self.config.model_path),
                    "--voices",
                    str(self.config.voices_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise KokoroError(f"Failed to query Kokoro voices: {exc}") from exc

        voices: list[str] = []
        for line in proc.stdout.splitlines():
            # Lines look like "    3. af_bella"
            parts = line.strip().split(". ", 1)
            if len(parts) == 2 and parts[0].isdigit():
                voices.append(parts[1].strip())
        return voices

    def validate_voice(self) -> None:
        """Validate the configured voice; supports blends like 'a:60,b:40'."""
        requested = self._voice_components(self.config.voice)
        try:
            available = set(self.available_voices())
        except KokoroError:
            # If voice listing fails we skip strict validation rather than
            # blocking synthesis; the engine will still error clearly later.
            return
        if not available:
            return
        unknown = [v for v in requested if v not in available]
        if unknown:
            raise KokoroError(
                "Unknown voice(s): "
                + ", ".join(unknown)
                + "\nRun 'md2speech --list-voices' to see available voices."
            )

    @staticmethod
    def _voice_components(voice: str) -> list[str]:
        """Extract bare voice names from a blend spec like 'a:60,b:40'."""
        names: list[str] = []
        for part in voice.split(","):
            name = part.split(":", 1)[0].strip()
            if name:
                names.append(name)
        return names

    def preflight(self) -> None:
        """Run all backend validations up front with actionable errors."""
        self.resolve_executable()
        self.validate_models()
        self.validate_voice()

    # -- caching ----------------------------------------------------------- #
    def _cache_key(self, text: str) -> str:
        h = hashlib.sha256()
        payload = "\x1f".join(
            [
                text,
                self.config.voice,
                f"{self.config.speed:.3f}",
                self.config.lang,
                "wav",  # chunks are always cached as wav for clean concat
                str(self.config.model_path),
            ]
        )
        h.update(payload.encode("utf-8"))
        return h.hexdigest()

    def _cache_path(self, text: str) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / f"{self._cache_key(text)}.wav"

    # -- synthesis --------------------------------------------------------- #
    def synthesize_chunk(self, text: str, *, use_cache: bool = True) -> Path:
        """Synthesize one text chunk to a cached WAV file; return its path."""
        text = text.strip()
        if not text:
            raise KokoroError("Refusing to synthesize empty text.")

        out_path = self._cache_path(text)
        if use_cache and out_path.exists() and out_path.stat().st_size > 0:
            return out_path

        exe = self.resolve_executable()

        # Write the input text to a temp .txt (kokoro-tts needs a file input).
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(text)
            tmp_in = Path(tf.name)

        # Synthesize to a temp file first; only move into cache on success so a
        # crashed run never leaves a half-written cache entry.
        tmp_out = out_path.with_suffix(".tmp.wav")
        cmd = [
            exe,
            str(tmp_in),
            str(tmp_out),
            "--voice",
            self.config.voice,
            "--speed",
            f"{self.config.speed}",
            "--lang",
            self.config.lang,
            "--format",
            "wav",
            "--model",
            str(self.config.model_path),
            "--voices",
            str(self.config.voices_path),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
        except subprocess.TimeoutExpired as exc:
            tmp_in.unlink(missing_ok=True)
            raise KokoroError("Kokoro synthesis timed out.") from exc
        except OSError as exc:
            tmp_in.unlink(missing_ok=True)
            raise KokoroError(f"Failed to invoke kokoro-tts: {exc}") from exc
        finally:
            tmp_in.unlink(missing_ok=True)

        if proc.returncode != 0 or not tmp_out.exists() or tmp_out.stat().st_size == 0:
            tmp_out.unlink(missing_ok=True)
            detail = _filter_noise(proc.stderr) or _filter_noise(proc.stdout)
            raise KokoroError(
                "Kokoro synthesis failed"
                + (f" (exit {proc.returncode}).\n{detail}" if detail else ".")
            )

        tmp_out.replace(out_path)
        return out_path
