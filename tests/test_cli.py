"""CLI-level tests using click's test runner (no real synthesis/playback)."""

from pathlib import Path

from click.testing import CliRunner

from md2speech.cli import main
from md2speech.pipeline import iter_markdown_files


def test_preview_outputs_clean_text(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text(
        "# Title\n\n**Bold** text with a [link](http://x).\n\n1.- Step one\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, [str(md), "--preview"])
    assert result.exit_code == 0
    assert "Title." in result.output
    assert "Bold text" in result.output
    assert "Step one." in result.output
    assert "http://x" not in result.output
    assert "**" not in result.output


def test_no_input_errors_with_exit_2():
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code == 2


def test_missing_file_errors_with_exit_2(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, [str(tmp_path / "ghost.md"), "--preview"])
    assert result.exit_code == 2


def test_iter_markdown_files_recursive(tmp_path):
    (tmp_path / "a.md").write_text("# a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.markdown").write_text("# b", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")

    flat = list(iter_markdown_files(tmp_path, recursive=False))
    assert [p.name for p in flat] == ["a.md"]

    deep = list(iter_markdown_files(tmp_path, recursive=True))
    names = sorted(p.name for p in deep)
    assert names == ["a.md", "b.markdown"]


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "md2speech" in result.output
