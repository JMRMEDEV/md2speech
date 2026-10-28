"""Playback backends with pause/resume keyboard controls.

Default backend is ``paplay`` (PulseAudio), which under WSL2/WSLg routes audio
to the Windows host. The abstraction keeps playback decoupled from the parser
and TTS layers so an alternative backend can be added without touching them.

Features:
  * Play a single WAV file; stream an ordered sequence of WAV paths.
  * Clean Ctrl+C handling: the active subprocess is terminated promptly and no
    orphaned player processes are left behind.
  * Interactive keyboard controls during playback (when stdin is a TTY):
      - ``p`` pause      (suspends the player process with SIGSTOP)
      - ``c`` continue   (resumes it with SIGCONT)
      - ``q`` quit       (stops playback, like Ctrl+C)
"""

from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Protocol


class PlaybackError(RuntimeError):
    """Raised when playback cannot start or fails."""


class StopPlayback(Exception):
    """Raised internally when the user presses the quit key."""


class PlaybackBackend(Protocol):
    """Interface for a playback backend."""

    name: str

    def is_available(self) -> bool: ...

    def play_file(self, wav_path: Path) -> None: ...


# --------------------------------------------------------------------------- #
# Keyboard controls (raw-mode single-key reader; no-op without a TTY)
# --------------------------------------------------------------------------- #
class KeyboardControls:
    """Reads single keypresses without Enter, in a `with` block.

    Falls back to a no-op (``poll`` always returns ``None``) when stdin is not
    an interactive terminal, so piped/non-interactive runs and tests are safe.
    """

    def __init__(self) -> None:
        self._enabled = False
        self._fd: int | None = None
        self._saved = None

    def __enter__(self) -> "KeyboardControls":
        try:
            import termios  # noqa: F401
            import tty  # noqa: F401

            if sys.stdin is None or not sys.stdin.isatty():
                return self
            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self._enabled = True
        except Exception:
            # Any failure (no termios on platform, redirected stdin) -> no-op.
            self._enabled = False
        return self

    def __exit__(self, *exc) -> None:
        if self._enabled and self._fd is not None and self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        self._enabled = False

    def poll(self) -> str | None:
        """Return a pending keypress (single char) or ``None`` if none ready."""
        if not self._enabled or self._fd is None:
            return None
        r, _, _ = select.select([self._fd], [], [], 0)
        if r:
            ch = os.read(self._fd, 1)
            if ch:
                return ch.decode("utf-8", errors="ignore")
        return None


class PaplayBackend:
    """Playback via the ``paplay`` command (WSLg PulseAudio by default)."""

    name = "paplay"

    def __init__(self, executable: str = "paplay") -> None:
        self._executable = executable
        self._current: subprocess.Popen | None = None
        self._paused = False
        #: Optional controls object (injected for testing / shared sequence).
        self.controls: KeyboardControls | None = None

    def is_available(self) -> bool:
        return shutil.which(self._executable) is not None

    def _resolve(self) -> str:
        exe = shutil.which(self._executable)
        if not exe:
            raise PlaybackError(
                "paplay not found. On WSL2 install it with:\n"
                "  sudo apt install pulseaudio-utils\n"
                "Verify playback works:  paplay /usr/share/sounds/alsa/Front_Center.wav"
            )
        return exe

    # -- pause / resume --------------------------------------------------- #
    def pause(self) -> None:
        proc = self._current
        if proc and proc.poll() is None and not self._paused:
            proc.send_signal(signal.SIGSTOP)
            self._paused = True

    def resume(self) -> None:
        proc = self._current
        if proc and proc.poll() is None and self._paused:
            proc.send_signal(signal.SIGCONT)
            self._paused = False

    def _handle_key(self, key: str) -> None:
        """Act on a control key. Raises StopPlayback on quit."""
        k = key.lower()
        if k == "p":
            self.pause()
        elif k == "c":
            self.resume()
        elif k in ("q", "\x03"):  # q or Ctrl+C
            raise StopPlayback

    # -- playback --------------------------------------------------------- #
    def play_file(self, wav_path: Path) -> None:
        """Play one WAV, blocking until done.

        While waiting, poll keyboard controls (if attached) so the user can
        pause/resume/quit. Ctrl+C always stops cleanly.
        """
        exe = self._resolve()
        wav_path = Path(wav_path)
        if not wav_path.exists():
            raise PlaybackError(f"Audio file not found: {wav_path}")

        try:
            self._current = subprocess.Popen([exe, str(wav_path)])
            self._paused = False
            while True:
                rc = self._current.poll()
                if rc is not None:
                    break
                key = self.controls.poll() if self.controls else None
                if key:
                    self._handle_key(key)
                time.sleep(0.05)
            if rc not in (0, None):
                raise PlaybackError(
                    f"paplay exited with code {rc}. "
                    "Check that WSLg audio is working: "
                    "paplay /usr/share/sounds/alsa/Front_Center.wav"
                )
        except (KeyboardInterrupt, StopPlayback):
            self.stop()
            raise KeyboardInterrupt
        finally:
            self._current = None
            self._paused = False

    def stop(self) -> None:
        """Terminate the active player subprocess promptly, if any."""
        proc = self._current
        if proc is None:
            return
        # If paused (SIGSTOP), resume first so terminate is delivered.
        if self._paused and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGCONT)
            except Exception:
                pass
            self._paused = False
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


def get_backend(name: str = "paplay") -> PlaybackBackend:
    if name == "paplay":
        return PaplayBackend()
    raise PlaybackError(f"Unknown playback backend: {name!r}")


def play_sequence(backend: PlaybackBackend, wavs: Iterable[Path]) -> None:
    """Play an ordered sequence of WAV paths one after another.

    Ctrl+C aborts the whole sequence cleanly. Intended for streaming playback
    where chunk and silence WAVs are produced progressively.
    """
    try:
        for wav in wavs:
            backend.play_file(Path(wav))
    except KeyboardInterrupt:
        stop = getattr(backend, "stop", None)
        if callable(stop):
            stop()
        raise
