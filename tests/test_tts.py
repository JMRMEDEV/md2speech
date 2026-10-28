"""Tests for the Kokoro backend wrapper (subprocess mocked, no real TTS)."""

import subprocess
from pathlib import Path

import pytest

from md2speech.config import Config, PauseConfig
from md2speech.tts import KokoroBackend, KokoroError


def _cfg(tmp_path) -> Config:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"x")
    voices.write_bytes(b"x")
    return Config(model_path=model, voices_path=voices)


def test_missing_executable_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("md2speech.tts.shutil.which", lambda _: None)
    b = KokoroBackend(_cfg(tmp_path))
    with pytest.raises(KokoroError) as e:
        b.resolve_executable()
    assert "not found" in str(e.value)


def test_missing_models_raises(tmp_path):
    cfg = Config(
        model_path=tmp_path / "nope.onnx",
        voices_path=tmp_path / "nope.bin",
    )
    with pytest.raises(KokoroError) as e:
        KokoroBackend(cfg).validate_models()
    assert "missing" in str(e.value).lower()


def test_unknown_voice_rejected(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path).with_overrides(voice="does_not_exist")
    b = KokoroBackend(cfg)
    monkeypatch.setattr(b, "available_voices", lambda: ["af_heart", "am_adam"])
    with pytest.raises(KokoroError) as e:
        b.validate_voice()
    assert "Unknown voice" in str(e.value)


def test_blend_voice_components_validated(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path).with_overrides(voice="af_heart:60,am_adam:40")
    b = KokoroBackend(cfg)
    monkeypatch.setattr(b, "available_voices", lambda: ["af_heart", "am_adam"])
    b.validate_voice()  # should not raise


def test_available_voices_parses_numbered_lines(monkeypatch, tmp_path):
    b = KokoroBackend(_cfg(tmp_path))
    monkeypatch.setattr("md2speech.tts.shutil.which", lambda _: "/usr/bin/kokoro-tts")

    class P:
        stdout = "Supported voices:\n    1. af_alloy\n    2. af_heart\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
    assert b.available_voices() == ["af_alloy", "af_heart"]


def test_synthesize_uses_cache(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    cache = tmp_path / "cache"
    b = KokoroBackend(cfg, cache_dir=cache)
    monkeypatch.setattr("md2speech.tts.shutil.which", lambda _: "/usr/bin/kokoro-tts")

    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        # Emulate kokoro writing the output WAV (the 3rd positional arg).
        out = Path(cmd[2])
        out.write_bytes(b"RIFFfakewavdata")

        class P:
            returncode = 0
            stderr = ""
            stdout = ""

        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)

    p1 = b.synthesize_chunk("hello world")
    p2 = b.synthesize_chunk("hello world")
    assert p1 == p2
    assert p1.exists()
    assert calls["n"] == 1  # second call served from cache, no subprocess


def test_synthesize_failure_raises_and_no_cache(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    b = KokoroBackend(cfg, cache_dir=tmp_path / "cache")
    monkeypatch.setattr("md2speech.tts.shutil.which", lambda _: "/usr/bin/kokoro-tts")

    def fail_run(cmd, **kwargs):
        class P:
            returncode = 1
            stderr = "boom\nonnxruntime noise"
            stdout = ""

        return P()

    monkeypatch.setattr(subprocess, "run", fail_run)
    with pytest.raises(KokoroError) as e:
        b.synthesize_chunk("hello")
    assert "failed" in str(e.value).lower()
    assert "boom" in str(e.value)
    assert "onnxruntime" not in str(e.value)  # noise filtered


def test_empty_text_refused(tmp_path):
    with pytest.raises(KokoroError):
        KokoroBackend(_cfg(tmp_path)).synthesize_chunk("   ")
