"""Tests for the append-only audit log (P0.3)."""

import json
from pathlib import Path

from quant.core.audit import GENESIS_HASH, AuditLog, FileAuditLog
from quant.core.logging import REDACTION_MASK, correlation_id_context


def test_append_returns_chained_entries(tmp_path: Path) -> None:
    log = FileAuditLog(tmp_path / "audit.jsonl")
    first = log.append("order_placed", {"symbol": "RELIANCE", "qty": 10})
    second = log.append("order_filled", {"symbol": "RELIANCE", "qty": 10})
    assert first.seq == 1
    assert first.prev_hash == GENESIS_HASH
    assert second.seq == 2
    assert second.prev_hash == first.entry_hash
    assert log.verify() is True


def test_log_is_append_only(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    log.append("a")
    after_one = path.read_text(encoding="utf-8")
    log.append("b")
    after_two = path.read_text(encoding="utf-8")
    assert after_two.startswith(after_one)  # first line untouched
    assert len(after_two.splitlines()) == 2


def test_entries_iterate_in_append_order(tmp_path: Path) -> None:
    log = FileAuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("evt", {"i": i})
    assert [entry.seq for entry in log] == [1, 2, 3]


def test_verify_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    log.append("evt", {"amount": 100})
    log.append("evt", {"amount": 200})
    assert log.verify() is True

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["data"]["amount"] = 999  # tamper, leave the stored hash in place
    lines[0] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert log.verify() is False


def test_chain_continues_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    first_log = FileAuditLog(path)
    first = first_log.append("evt")
    reopened = FileAuditLog(path)
    second = reopened.append("evt")
    assert second.seq == 2
    assert second.prev_hash == first.entry_hash
    assert reopened.verify() is True


def test_correlation_id_is_captured(tmp_path: Path) -> None:
    log = FileAuditLog(tmp_path / "audit.jsonl")
    with correlation_id_context("trace-9"):
        entry = log.append("evt")
    assert entry.correlation_id == "trace-9"


def test_secrets_are_redacted(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    entry = log.append("login", {"user": "u", "password": "p@ss"})
    assert entry.data["password"] == REDACTION_MASK
    assert "p@ss" not in path.read_text(encoding="utf-8")


def test_filelog_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(FileAuditLog(tmp_path / "audit.jsonl"), AuditLog)


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    log.append("a")
    log.append("b")
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # trailing blank
    assert [entry.seq for entry in log] == [1, 2]
    assert log.verify() is True


def test_verify_detects_sequence_break(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    log.append("a")
    log.append("b")
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["seq"] = 99  # wrong sequence number, hash left untouched
    lines[1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert log.verify() is False
