"""Tests for the resume-pointer (bookmark) persistence."""

from pathlib import Path

from md2speech.config import Config
from md2speech.pipeline import Pipeline
from md2speech.progress import Bookmark, save_path_for, source_hash


def test_save_path_layout(tmp_path):
    md = tmp_path / "topics" / "01-javascript.md"
    md.parent.mkdir(parents=True)
    md.write_text("# x", encoding="utf-8")
    p = save_path_for(md)
    assert p == md.parent / ".md2speech" / "01-javascript.sav"


def test_write_read_roundtrip(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("# Title\n\nbody", encoding="utf-8")
    bm = Bookmark(
        source="notes.md",
        source_sha256=source_hash("# Title\n\nbody"),
        chunk_index=5,
        total_chunks=20,
        heading="1.4 Ordering puzzle",
        voice="af_heart",
        speed=1.0,
    )
    path = bm.write(md)
    assert path.exists()

    loaded = Bookmark.read(md)
    assert loaded is not None
    assert loaded.chunk_index == 5
    assert loaded.total_chunks == 20
    assert loaded.heading == "1.4 Ordering puzzle"
    assert loaded.updated_at  # stamped on write


def test_source_hash_mismatch_detected(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("original", encoding="utf-8")
    bm = Bookmark("notes.md", source_hash("original"), 3, 10, "", "af_heart", 1.0)
    bm.write(md)
    assert Bookmark.read(md).matches_source("original") is True
    assert Bookmark.read(md).matches_source("edited content") is False


def test_clear(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("x", encoding="utf-8")
    Bookmark("notes.md", source_hash("x"), 1, 2, "", "v", 1.0).write(md)
    assert Bookmark.clear(md) is True   # removed
    assert Bookmark.read(md) is None
    assert Bookmark.clear(md) is False  # already gone


def test_is_complete():
    bm = Bookmark("n", "h", chunk_index=10, total_chunks=10, heading="",
                  voice="v", speed=1.0)
    assert bm.is_complete() is True
    bm2 = Bookmark("n", "h", chunk_index=4, total_chunks=10, heading="",
                   voice="v", speed=1.0)
    assert bm2.is_complete() is False


def test_chunk_carries_heading(tmp_path):
    # The chunk a bookmark records should expose the section heading.
    md = "## 1.1 First\n\nAlpha paragraph.\n\n## 1.2 Second\n\nBeta paragraph.\n"
    chunks = Pipeline.create(Config()).narration_chunks(md)
    headings = {c.heading for c in chunks}
    assert any("First" in h for h in headings)
    assert any("Second" in h for h in headings)
    # The paragraph chunk after the second heading carries that heading.
    beta = [c for c in chunks if "Beta" in c.text][0]
    assert "Second" in beta.heading
