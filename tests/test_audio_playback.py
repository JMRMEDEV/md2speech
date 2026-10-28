"""Tests for audio pause mapping and playback (no real audio device)."""

import subprocess
from pathlib import Path

import pytest

from md2speech.audio import build_sequence, pause_seconds
from md2speech.chunking import SpeechChunk
from md2speech.config import Config
from md2speech.parser import PauseKind
from md2speech.playback import PaplayBackend, PlaybackError, play_sequence


# --- pause mapping --------------------------------------------------------- #
def test_pause_seconds_mapping():
    cfg = Config()
    assert pause_seconds(PauseKind.SECTION, cfg) == cfg.pauses.between_sections
    assert pause_seconds(PauseKind.TITLE, cfg) == cfg.pauses.after_title
    assert pause_seconds(PauseKind.PARAGRAPH, cfg) == cfg.pauses.between_paragraphs
    assert pause_seconds(PauseKind.LIST_ITEM, cfg) == cfg.pauses.between_list_items
    assert pause_seconds(PauseKind.NONE, cfg) == 0.0


# --- sequence building ----------------------------------------------------- #
class _FakeSilence:
    """Stand-in SilenceCache that returns a sentinel path for any pause."""

    def __init__(self, path):
        self.path = path
        self.requested = []

    def get(self, seconds):
        self.requested.append(seconds)
        return self.path if seconds > 0 else None


def test_build_sequence_interleaves_silence(tmp_path):
    cfg = Config()
    sil = tmp_path / "sil.wav"
    sil.write_bytes(b"x")
    w1, w2 = tmp_path / "a.wav", tmp_path / "b.wav"
    w1.write_bytes(b"x")
    w2.write_bytes(b"x")
    pairs = [
        (SpeechChunk("one", PauseKind.SECTION), w1),
        (SpeechChunk("two", PauseKind.PARAGRAPH), w2),
    ]
    seq = build_sequence(pairs, cfg, _FakeSilence(sil))
    # First chunk has no leading silence; second is preceded by silence.
    assert seq == [w1, sil, w2]


# --- playback -------------------------------------------------------------- #
def test_paplay_unavailable(monkeypatch):
    monkeypatch.setattr("md2speech.playback.shutil.which", lambda _: None)
    b = PaplayBackend()
    assert b.is_available() is False
    with pytest.raises(PlaybackError):
        b.play_file(Path("/nonexistent.wav"))


def test_paplay_plays_file(monkeypatch, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr("md2speech.playback.shutil.which", lambda _: "/usr/bin/paplay")
    monkeypatch.setattr("md2speech.playback.time.sleep", lambda s: None)

    played = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd):
            played["cmd"] = cmd

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0  # finished immediately

    monkeypatch.setattr(subprocess, "Popen", lambda cmd: FakeProc(cmd))
    PaplayBackend().play_file(wav)
    assert played["cmd"][0] == "/usr/bin/paplay"
    assert played["cmd"][1] == str(wav)


def test_ctrl_c_terminates_subprocess(monkeypatch, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr("md2speech.playback.shutil.which", lambda _: "/usr/bin/paplay")
    monkeypatch.setattr("md2speech.playback.time.sleep", lambda s: None)

    events = []

    class FakeProc:
        returncode = None

        def __init__(self, cmd):
            self._alive = True
            self._interrupted = False

        def wait(self, timeout=None):
            return 0

        def poll(self):
            # Simulate the user pressing Ctrl+C once while the process is alive.
            if self._alive and not self._interrupted:
                self._interrupted = True
                raise KeyboardInterrupt
            return None if self._alive else 0

        def terminate(self):
            events.append("terminate")
            self._alive = False

        def send_signal(self, sig):
            pass

        def kill(self):
            events.append("kill")
            self._alive = False

    monkeypatch.setattr(subprocess, "Popen", lambda cmd: FakeProc(cmd))
    b = PaplayBackend()
    with pytest.raises(KeyboardInterrupt):
        b.play_file(wav)
    assert "terminate" in events  # cleaned up, no orphan


def test_play_sequence_stops_on_interrupt(monkeypatch):
    class FakeBackend:
        def __init__(self):
            self.stopped = False
            self.count = 0

        def play_file(self, wav):
            self.count += 1
            if self.count == 2:
                raise KeyboardInterrupt

        def stop(self):
            self.stopped = True

    be = FakeBackend()
    with pytest.raises(KeyboardInterrupt):
        play_sequence(be, [Path("a"), Path("b"), Path("c")])
    assert be.stopped is True
    assert be.count == 2  # third never played


# --- pause / resume / quit controls --------------------------------------- #
class _FakeProc:
    """Fake Popen tracking signals; "finishes" after a set number of polls."""

    def __init__(self, cmd, finish_after=3):
        self.cmd = cmd
        self.signals = []
        self.returncode = None
        self._polls = 0
        self._finish_after = finish_after
        self.terminated = False

    def poll(self):
        self._polls += 1
        if self._polls >= self._finish_after:
            self.returncode = 0
            return 0
        return None

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_pause_and_resume_send_signals(monkeypatch, tmp_path):
    import signal as _signal

    from md2speech.playback import PaplayBackend

    wav = tmp_path / "x.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr("md2speech.playback.shutil.which", lambda _: "/usr/bin/paplay")

    proc = _FakeProc(["paplay", str(wav)], finish_after=5)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd: proc)
    monkeypatch.setattr("md2speech.playback.time.sleep", lambda s: None)

    # Controls emit: pause, then continue, then nothing.
    class Keys:
        def __init__(self):
            self.seq = ["p", "c", None, None, None, None]

        def poll(self):
            return self.seq.pop(0) if self.seq else None

    be = PaplayBackend()
    be.controls = Keys()
    be.play_file(wav)

    assert _signal.SIGSTOP in proc.signals  # paused
    assert _signal.SIGCONT in proc.signals  # resumed


def test_quit_key_stops_playback(monkeypatch, tmp_path):
    from md2speech.playback import PaplayBackend

    wav = tmp_path / "x.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr("md2speech.playback.shutil.which", lambda _: "/usr/bin/paplay")

    proc = _FakeProc(["paplay", str(wav)], finish_after=100)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd: proc)
    monkeypatch.setattr("md2speech.playback.time.sleep", lambda s: None)

    class Keys:
        def poll(self):
            return "q"

    be = PaplayBackend()
    be.controls = Keys()
    with pytest.raises(KeyboardInterrupt):
        be.play_file(wav)
    assert proc.terminated is True  # quit -> terminated, no orphan


def test_keyboard_controls_noop_without_tty(monkeypatch):
    from md2speech.playback import KeyboardControls

    class FakeStdin:
        def isatty(self):
            return False

    monkeypatch.setattr("md2speech.playback.sys.stdin", FakeStdin())
    with KeyboardControls() as kc:
        assert kc.poll() is None  # disabled, never blocks
