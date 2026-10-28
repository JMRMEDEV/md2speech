"""Command-line interface for md2speech.

Examples::

    md2speech notes.md --output notes.mp3
    md2speech notes.md --voice af_heart --speed 0.95
    md2speech notes.md --preview
    md2speech notes.md --play
    md2speech ./study-material/ --recursive --output ./audio/
    md2speech --list-voices
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .config import Config
from .pipeline import Pipeline, iter_markdown_files
from .playback import PlaybackError, get_backend
from .tts import KokoroBackend, KokoroError


def _echo_err(msg: str) -> None:
    click.echo(click.style(msg, fg="red"), err=True)


def _progress(idx: int, total: int) -> None:
    click.echo(f"  synthesizing chunk {idx}/{total}", err=True)


def _echo_controls_hint() -> None:
    if sys.stdin is not None and sys.stdin.isatty():
        click.echo(
            click.style("  controls: [p] pause  [c] continue  [q] quit",
                        fg="yellow"),
            err=True,
        )


def _default_output_name(src: Path, fmt: str) -> Path:
    return src.with_suffix(f".{fmt}")


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="md2speech")
@click.argument("input_path", required=False, type=click.Path(path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="Output audio file (or directory when processing a folder).")
@click.option("--voice", default=None,
              help="Kokoro voice (e.g. af_heart). Blends: 'af_sarah:60,am_adam:40'.")
@click.option("--speed", type=float, default=None,
              help="Speech speed multiplier (default 1.0).")
@click.option("--lang", default=None, help="Language code (default en-us).")
@click.option("-f", "--format", "audio_format",
              type=click.Choice(["wav", "mp3"]), default=None,
              help="Output audio format (default wav).")
@click.option("--preview", is_flag=True,
              help="Print narration-ready text without synthesizing audio.")
@click.option("--play", "play", is_flag=True,
              help="Play audio through paplay (WSLg). Streams long documents.")
@click.option("-r", "--recursive", is_flag=True,
              help="Recurse into subdirectories when INPUT_PATH is a folder.")
@click.option("--include-code/--skip-code", "include_code", default=None,
              help="Include fenced code blocks in narration (default: skip).")
@click.option("--skip-tables", is_flag=True,
              help="Skip tables entirely instead of reading rows as sentences.")
@click.option("--list-transitions", is_flag=True,
              help="Speak ordinal lead-ins for ordered lists (First, Second...).")
@click.option("--pronunciation", type=click.Path(path_type=Path), default=None,
              help="YAML file of term -> spoken-form replacements (overrides defaults).")
@click.option("--no-default-pronunciation", is_flag=True,
              help="Disable the built-in tech acronym pronunciations.")
@click.option("--max-chunk-chars", type=int, default=None,
              help="Soft cap on characters per synthesis chunk (default 500).")
@click.option("--resume/--restart", "resume", default=None,
              help="With --play: resume from the saved position (default if a "
                   "save exists) or restart from the beginning.")
@click.option("--clear-progress", is_flag=True,
              help="Delete the saved resume pointer for the input and exit.")
@click.option("--list-voices", is_flag=True,
              help="List available Kokoro voices and exit.")
def main(
    input_path: Path | None,
    output: Path | None,
    voice: str | None,
    speed: float | None,
    lang: str | None,
    audio_format: str | None,
    preview: bool,
    play: bool,
    recursive: bool,
    include_code: bool | None,
    skip_tables: bool,
    list_transitions: bool,
    pronunciation: Path | None,
    no_default_pronunciation: bool,
    max_chunk_chars: int | None,
    resume: bool | None,
    clear_progress: bool,
    list_voices: bool,
) -> None:
    """Convert Markdown study materials into natural-sounding audio."""

    config = Config().with_overrides(
        voice=voice,
        speed=speed,
        lang=lang,
        audio_format=audio_format,
        include_code_blocks=include_code,
        include_tables=(False if skip_tables else None),
        speak_list_transitions=(True if list_transitions else None),
        pronunciation_path=pronunciation,
        use_default_pronunciation=(False if no_default_pronunciation else None),
        max_chunk_chars=max_chunk_chars,
    )

    # --list-voices is a standalone action.
    if list_voices:
        _run_list_voices(config)
        return

    if input_path is None:
        _echo_err("No input provided. Pass a Markdown file or directory, "
                  "or use --list-voices. See --help.")
        sys.exit(2)

    try:
        files = list(iter_markdown_files(input_path, recursive))
    except FileNotFoundError as exc:
        _echo_err(str(exc))
        sys.exit(2)

    if not files:
        _echo_err(f"No Markdown files found under: {input_path}")
        sys.exit(2)

    # --clear-progress is a standalone action over the selected files.
    if clear_progress:
        from .progress import Bookmark

        cleared = 0
        for src in files:
            if Bookmark.clear(src):
                cleared += 1
                click.echo(f"Cleared resume pointer for {src}")
        if cleared == 0:
            click.echo("No saved resume pointers found.")
        return

    fmt = config.audio_format
    is_dir = input_path.is_dir()

    # Resolve output directory semantics for folder inputs.
    out_dir: Path | None = None
    if is_dir and output is not None:
        out_dir = output
        out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    for src in files:
        try:
            md_text = src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _echo_err(f"Could not read {src}: {exc}")
            exit_code = 1
            continue

        pipeline = Pipeline.create(config)

        if preview:
            click.echo(click.style(f"# {src}", fg="cyan"))
            click.echo(pipeline.preview_text(md_text))
            click.echo("")
            continue

        try:
            if play and output is None:
                # Pure playback: stream chunks, no file saved.
                _play_with_resume(
                    pipeline, md_text, src, config, resume
                )
            else:
                # Determine output path.
                if is_dir:
                    base = out_dir or src.parent
                    target = base / src.with_suffix(f".{fmt}").name
                else:
                    target = output if output is not None else _default_output_name(src, fmt)
                    # If an explicit output has an extension, honor its format.
                    if output is not None and target.suffix:
                        config_fmt = target.suffix.lower().lstrip(".")
                        if config_fmt in ("wav", "mp3"):
                            config = config.with_overrides(audio_format=config_fmt)
                            pipeline = Pipeline.create(config)

                click.echo(click.style(f"Converting {src} -> {target}", fg="green"),
                           err=True)
                result = pipeline.synthesize_to_file(
                    md_text, target, progress=_progress
                )
                click.echo(str(result))

                if play:
                    player = get_backend("paplay")
                    if not player.is_available():
                        _echo_err("Saved file but paplay is unavailable for --play.")
                    else:
                        _play_saved(result, player)

        except KokoroError as exc:
            _echo_err(str(exc))
            exit_code = 1
        except PlaybackError as exc:
            _echo_err(str(exc))
            exit_code = 1
        except KeyboardInterrupt:
            click.echo("\nStopped.", err=True)
            sys.exit(130)
        except Exception as exc:  # pragma: no cover - defensive
            _echo_err(f"Error processing {src}: {exc}")
            exit_code = 1

    sys.exit(exit_code)

def _play_with_resume(pipeline, md_text, src, config, resume):
    """Stream playback with a persistent resume bookmark.

    - Resolves the start chunk from a saved ``.sav`` (unless --restart).
    - Saves the bookmark after each chunk finishes.
    - On completion, clears the bookmark. On Ctrl+C/quit, the bookmark is left
      at the last fully-heard chunk so the next run resumes there.
    """
    from .progress import Bookmark, source_hash

    player = get_backend("paplay")
    if not player.is_available():
        raise PlaybackError(
            "paplay not available. Install pulseaudio-utils and "
            "ensure WSLg audio works."
        )

    total = pipeline.chunk_count(md_text)
    start_index = 0

    existing = Bookmark.read(src)
    if existing is not None and resume is not False:
        if not existing.matches_source(md_text):
            _echo_err(
                f"Saved position for {src.name} is for a different version of "
                "the file; starting from the beginning."
            )
            Bookmark.clear(src)
        elif existing.is_complete():
            click.echo("Previous session finished this file; starting over.",
                       err=True)
            Bookmark.clear(src)
        else:
            start_index = existing.chunk_index
            where = existing.heading or f"chunk {start_index + 1}"
            click.echo(
                click.style(f"Resuming {src.name} at: {where}", fg="cyan"),
                err=True,
            )
    elif resume is False:
        Bookmark.clear(src)

    if start_index == 0:
        click.echo(click.style(f"Playing {src} ...", fg="green"), err=True)
    _echo_controls_hint()

    sha = source_hash(md_text)

    def _save(next_index: int, total_chunks: int, chunk) -> None:
        Bookmark(
            source=src.name,
            source_sha256=sha,
            chunk_index=next_index,          # next chunk to play
            total_chunks=total_chunks,
            heading=getattr(chunk, "heading", ""),
            voice=config.voice,
            speed=config.speed,
        ).write(src)

    try:
        pipeline.stream_play(
            md_text,
            player,
            progress=_progress,
            start_index=start_index,
            on_chunk_done=_save,
        )
    except KeyboardInterrupt:
        # Bookmark already persisted up to the last completed chunk by _save.
        bm = Bookmark.read(src)
        if bm is not None:
            where = bm.heading or f"chunk {bm.chunk_index + 1}"
            click.echo(
                click.style(f"\nSaved position at: {where}", fg="yellow"),
                err=True,
            )
        raise

    # Finished the whole file -> clear the pointer so next time starts fresh.
    Bookmark.clear(src)
    click.echo(click.style(f"Finished {src.name}.", fg="green"), err=True)



def _play_saved(path: Path, player) -> None:
    """Play a saved file, converting MP3 -> temp WAV via ffmpeg if needed."""
    import tempfile

    from .playback import KeyboardControls

    path = Path(path)
    _echo_controls_hint()
    with KeyboardControls() as controls:
        if hasattr(player, "controls"):
            player.controls = controls
        if path.suffix.lower() == ".wav":
            player.play_file(path)
            return

        # MP3 (or other): decode to a temporary WAV for paplay, then clean up.
        import subprocess
        import shutil

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            _echo_err("Cannot play non-WAV output: ffmpeg not found.")
            return
        with tempfile.TemporaryDirectory(prefix="md2speech_play_") as td:
            tmp_wav = Path(td) / "play.wav"
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", str(path), str(tmp_wav)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                _echo_err("Failed to decode audio for playback.")
                return
            player.play_file(tmp_wav)


def _run_list_voices(config: Config) -> None:
    backend = KokoroBackend(config)
    try:
        backend.resolve_executable()
        backend.validate_models()
        voices = backend.available_voices()
    except KokoroError as exc:
        _echo_err(str(exc))
        sys.exit(1)
    if not voices:
        _echo_err("No voices reported by the engine.")
        sys.exit(1)
    click.echo("Available voices:")
    for v in voices:
        click.echo(f"  {v}")


if __name__ == "__main__":
    main()
