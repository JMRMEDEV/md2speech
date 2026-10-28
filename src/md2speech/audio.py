"""Audio assembly and format conversion via ffmpeg.

Takes synthesized chunk WAVs plus pause metadata and assembles a single audio
file (WAV or MP3). Silence is generated as real 24 kHz mono PCM matching the
Kokoro output so concatenation is gapless and clicks-free.

ffmpeg is used for three operations only:
  * generate silence of a given duration,
  * concatenate WAVs losslessly (``-f concat -c copy``),
  * convert the final WAV to MP3 when requested.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from .config import CHANNELS, Config, SAMPLE_RATE
from .chunking import SpeechChunk
from .parser import PauseKind


class AudioError(RuntimeError):
    """Raised for ffmpeg / assembly failures."""


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioError(
            "ffmpeg not found. Install it with:  sudo apt install ffmpeg"
        )
    return exe


def pause_seconds(kind: PauseKind, config: Config) -> float:
    p = config.pauses
    return {
        PauseKind.NONE: 0.0,
        PauseKind.PARAGRAPH: p.between_paragraphs,
        PauseKind.LIST_ITEM: p.between_list_items,
        PauseKind.TITLE: p.after_title,
        PauseKind.SECTION: p.between_sections,
        PauseKind.TABLE_ROW: p.after_table_row,
    }.get(kind, 0.0)


class SilenceCache:
    """Caches generated silence WAVs by duration to avoid re-invoking ffmpeg."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[int, Path] = {}

    def get(self, seconds: float) -> Path | None:
        if seconds <= 0:
            return None
        ms = int(round(seconds * 1000))
        if ms in self._mem:
            return self._mem[ms]
        path = self._dir / f"silence_{ms}ms_{SAMPLE_RATE}.wav"
        if not (path.exists() and path.stat().st_size > 0):
            _generate_silence(path, seconds)
        self._mem[ms] = path
        return path


def _generate_silence(path: Path, seconds: float) -> None:
    cmd = [
        _ffmpeg(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={SAMPLE_RATE}:cl={'mono' if CHANNELS == 1 else 'stereo'}",
        "-t",
        f"{seconds:.3f}",
        "-c:a",
        "pcm_s16le",
        str(path),
    ]
    _run(cmd, "generate silence")


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.SubprocessError, OSError) as exc:
        raise AudioError(f"ffmpeg failed to {what}: {exc}") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-4:])
        raise AudioError(f"ffmpeg failed to {what} (exit {proc.returncode}).\n{tail}")
    return proc


def concat_wavs(wavs: list[Path], out_wav: Path) -> None:
    """Losslessly concatenate same-format WAVs into ``out_wav``."""
    if not wavs:
        raise AudioError("No audio to concatenate.")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as lf:
        for w in wavs:
            # Escape single quotes for the ffmpeg concat demuxer syntax.
            safe = str(w).replace("'", r"'\''")
            lf.write(f"file '{safe}'\n")
        list_path = Path(lf.name)
    try:
        cmd = [
            _ffmpeg(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(out_wav),
        ]
        _run(cmd, "concatenate audio")
    finally:
        list_path.unlink(missing_ok=True)


def wav_to_mp3(in_wav: Path, out_mp3: Path, quality: int = 4) -> None:
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(in_wav),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        str(quality),
        str(out_mp3),
    ]
    _run(cmd, "convert to mp3")


def build_sequence(
    chunk_wavs: list[tuple[SpeechChunk, Path]],
    config: Config,
    silence_cache: SilenceCache,
) -> list[Path]:
    """Interleave chunk WAVs with silence WAVs according to pause metadata.

    Returns the ordered list of WAV paths to concatenate. The pause recorded on
    a chunk is inserted *before* that chunk (skipped for the very first one).
    """
    sequence: list[Path] = []
    for idx, (chunk, wav) in enumerate(chunk_wavs):
        if idx > 0:
            sil = silence_cache.get(pause_seconds(chunk.pause_before, config))
            if sil is not None:
                sequence.append(sil)
        sequence.append(wav)
    return sequence


def assemble(
    chunk_wavs: list[tuple[SpeechChunk, Path]],
    out_path: Path,
    config: Config,
    silence_cache: SilenceCache,
) -> Path:
    """Assemble chunk WAVs + pauses into ``out_path`` (``.wav`` or ``.mp3``)."""
    if not chunk_wavs:
        raise AudioError("Nothing to assemble: no synthesized chunks.")

    sequence = build_sequence(chunk_wavs, config, silence_cache)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = out_path.suffix.lower().lstrip(".") or config.audio_format

    if fmt == "wav":
        concat_wavs(sequence, out_path)
        return out_path

    if fmt == "mp3":
        with tempfile.TemporaryDirectory(prefix="md2speech_") as td:
            tmp_wav = Path(td) / "combined.wav"
            concat_wavs(sequence, tmp_wav)
            wav_to_mp3(tmp_wav, out_path)
        return out_path

    raise AudioError(f"Unsupported output format: {fmt!r} (use wav or mp3).")
