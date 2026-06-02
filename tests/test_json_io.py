"""Tests for the write-if-changed helper (fresh-03 / latency-07).

The site export rewrites ~2,200 detail JSON files every run regardless of change, bloating
git churn and forcing full GitHub Pages rebuilds. write_text_if_changed skips byte-identical
writes so unchanged files keep their bytes (and mtime), turning O(everything) into O(delta).
"""

from esbvaktin.utils.json_io import write_text_if_changed


def test_writes_new_file(tmp_path):
    p = tmp_path / "a.json"
    assert write_text_if_changed(p, '{"x": 1}') is True
    assert p.read_text(encoding="utf-8") == '{"x": 1}'


def test_skips_identical_content(tmp_path):
    p = tmp_path / "a.json"
    write_text_if_changed(p, '{"x": 1}')
    mtime_before = p.stat().st_mtime_ns
    assert write_text_if_changed(p, '{"x": 1}') is False
    assert p.stat().st_mtime_ns == mtime_before  # not rewritten


def test_rewrites_on_change(tmp_path):
    p = tmp_path / "a.json"
    write_text_if_changed(p, '{"x": 1}')
    assert write_text_if_changed(p, '{"x": 2}') is True
    assert p.read_text(encoding="utf-8") == '{"x": 2}'


def test_creates_parent_dirs(tmp_path):
    p = tmp_path / "sub" / "dir" / "a.json"
    assert write_text_if_changed(p, "hi") is True
    assert p.read_text(encoding="utf-8") == "hi"
