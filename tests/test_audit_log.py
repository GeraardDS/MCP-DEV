"""Unit tests for core.autonomous.audit_log."""

import json
import os

from core.autonomous.audit_log import AuditLog


def test_append_writes_jsonl(tmp_path):
    log = AuditLog("sess-1", log_path=str(tmp_path))
    log.append(op="save", args={"x": 1}, result={"success": True}, duration_ms=12.3)
    log.append(op="close", args={"save_first": True}, result={"success": False, "error": "boom"})

    assert os.path.exists(log.jsonl_path)
    lines = [l for l in open(log.jsonl_path, encoding="utf-8").read().splitlines() if l]
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["op"] == "save"
    assert first["args"]["x"] == 1
    assert first["result"]["success"] is True
    assert first["duration_ms"] == 12.3


def test_read_entries_newest_first(tmp_path):
    log = AuditLog("sess-2", log_path=str(tmp_path))
    log.append(op="a")
    log.append(op="b")
    log.append(op="c")
    entries = log.read_entries()
    assert [e["op"] for e in entries] == ["c", "b", "a"]


def test_read_entries_limit(tmp_path):
    log = AuditLog("sess-3", log_path=str(tmp_path))
    for i in range(5):
        log.append(op=f"op{i}")
    entries = log.read_entries(limit=2)
    assert len(entries) == 2


def test_sanitize_truncates_long_strings(tmp_path):
    log = AuditLog("sess-4", log_path=str(tmp_path))
    log.append(op="x", args={"big": "A" * 2000})
    entry = log.read_entries()[0]
    assert "truncated" in entry["args"]["big"]
    assert len(entry["args"]["big"]) < 2000


def test_summarize_result_keeps_only_status_fields(tmp_path):
    log = AuditLog("sess-5", log_path=str(tmp_path))
    log.append(
        op="refresh",
        result={"success": False, "error": "X", "huge_payload": ["y"] * 9999},
    )
    entry = log.read_entries()[0]
    assert entry["result"] == {"success": False, "error": "X"}


def test_summary_includes_ops_table_and_failures(tmp_path):
    log = AuditLog("sess-6", log_path=str(tmp_path))
    log.append(op="save", result={"success": True})
    log.append(op="save", result={"success": True})
    log.append(op="close", result={"success": False, "error": "kaboom"})

    path = log.emit_summary(exit_reason="manual")
    assert path is not None
    text = open(path, encoding="utf-8").read()
    assert "sess-6" in text
    assert "| `save` | 2 | 2 | 0 |" in text
    assert "| `close` | 1 | 0 | 1 |" in text
    assert "kaboom" in text
    assert "Exit reason: `manual`" in text


def test_summary_on_empty_log_still_renders(tmp_path):
    log = AuditLog("sess-7", log_path=str(tmp_path))
    path = log.emit_summary(exit_reason="empty")
    assert path is not None
    text = open(path, encoding="utf-8").read()
    assert "Total entries: 0" in text
