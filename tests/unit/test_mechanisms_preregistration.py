"""Tests for the mechanism pre-registration protocol (Part VI / P6.3).

Covers front-matter parsing/validation, the committed-and-clean git gate (with an injected git
runner — no real repo touched), and the commit-precedes-first-test-run audit check.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant.research.mechanisms.errors import PreregistrationError
from quant.research.mechanisms.preregistration import (
    parse_preregistration,
    require_preregistration,
)

_IST = timezone(timedelta(hours=5, minutes=30))

_VALID = """---
mechanism: index_rebalance
date: 2026-06-27
hypothesis: >
  Index additions are bid up and deletions sold off by passive funds on a known schedule.
economic_rationale: >
  Index-tracking funds must trade the reconstitution price-insensitively on the effective date.
success_thresholds:
  cpcv_median_sharpe_min: 1.0
  dsr_min: 0.95
kill_thresholds:
  cpcv_median_sharpe_stop: 0.3
trial_budget: 10
---

# Pre-registration: Index-rebalance flow

Body text.
"""


def test_parse_valid_preregistration() -> None:
    prereg = parse_preregistration(_VALID, expected_mechanism="index_rebalance")
    assert prereg.mechanism == "index_rebalance"
    assert prereg.trial_budget == 10
    assert prereg.success_thresholds["cpcv_median_sharpe_min"] == pytest.approx(1.0)
    assert prereg.kill_thresholds["cpcv_median_sharpe_stop"] == pytest.approx(0.3)
    assert "passive funds" in prereg.hypothesis


def test_parse_rejects_missing_field() -> None:
    text = _VALID.replace("trial_budget: 10\n", "")
    with pytest.raises(PreregistrationError, match="missing required field.*trial_budget"):
        parse_preregistration(text)


def test_parse_rejects_mechanism_mismatch() -> None:
    with pytest.raises(PreregistrationError, match="declares mechanism"):
        parse_preregistration(_VALID, expected_mechanism="pairs")


def test_parse_rejects_non_positive_trial_budget() -> None:
    text = _VALID.replace("trial_budget: 10", "trial_budget: 0")
    with pytest.raises(PreregistrationError, match="trial_budget must be a positive integer"):
        parse_preregistration(text)


def test_parse_rejects_missing_front_matter() -> None:
    with pytest.raises(PreregistrationError, match="must begin with a '---'"):
        parse_preregistration("# no front matter\n")


def _write_prereg(repo_root: Path, mechanism: str, text: str = _VALID) -> None:
    prereg_dir = repo_root / "docs" / "mechanisms"
    prereg_dir.mkdir(parents=True, exist_ok=True)
    (prereg_dir / f"{mechanism}_prereg.md").write_text(text, encoding="utf-8")


def _git_runner(*, dirty: bool, commit: str | None) -> object:
    """A fake git runner: ``status`` reports clean/dirty; ``log`` reports the last commit."""

    def run(args: Sequence[str]) -> str:
        if args[0] == "status":
            return " M docs/mechanisms/index_rebalance_prereg.md\n" if dirty else ""
        if args[0] == "log":
            return commit or ""
        raise AssertionError(f"unexpected git call: {args}")

    return run


def test_require_preregistration_returns_committed_record(tmp_path: Path) -> None:
    _write_prereg(tmp_path, "index_rebalance")
    runner = _git_runner(dirty=False, commit="abc123\t2026-06-27T10:00:00+05:30")
    committed = require_preregistration(
        "index_rebalance", repo_root=tmp_path, git_runner=runner  # type: ignore[arg-type]
    )
    assert committed.commit_hash == "abc123"
    assert committed.commit_time == datetime(2026, 6, 27, 10, 0, tzinfo=_IST)
    assert committed.preregistration.mechanism == "index_rebalance"


def test_require_preregistration_fails_when_missing(tmp_path: Path) -> None:
    runner = _git_runner(dirty=False, commit="abc\t2026-06-27T10:00:00+05:30")
    with pytest.raises(PreregistrationError, match="not found"):
        require_preregistration(
            "index_rebalance", repo_root=tmp_path, git_runner=runner  # type: ignore[arg-type]
        )


def test_require_preregistration_fails_when_uncommitted(tmp_path: Path) -> None:
    _write_prereg(tmp_path, "index_rebalance")
    runner = _git_runner(dirty=False, commit=None)  # log returns nothing => never committed
    with pytest.raises(PreregistrationError, match="not committed to git"):
        require_preregistration(
            "index_rebalance", repo_root=tmp_path, git_runner=runner  # type: ignore[arg-type]
        )


def test_require_preregistration_fails_when_dirty(tmp_path: Path) -> None:
    _write_prereg(tmp_path, "index_rebalance")
    runner = _git_runner(dirty=True, commit="abc\t2026-06-27T10:00:00+05:30")
    with pytest.raises(PreregistrationError, match="uncommitted changes"):
        require_preregistration(
            "index_rebalance", repo_root=tmp_path, git_runner=runner  # type: ignore[arg-type]
        )


def test_verify_precedes_enforces_commit_before_run(tmp_path: Path) -> None:
    _write_prereg(tmp_path, "index_rebalance")
    runner = _git_runner(dirty=False, commit="abc\t2026-06-27T10:00:00+05:30")
    committed = require_preregistration(
        "index_rebalance", repo_root=tmp_path, git_runner=runner  # type: ignore[arg-type]
    )
    # A run started after the commit is fine ...
    committed.verify_precedes(datetime(2026, 6, 27, 11, 0, tzinfo=_IST))
    # ... but a run at/before the commit defeats the pre-registration.
    with pytest.raises(PreregistrationError, match="must be committed first"):
        committed.verify_precedes(datetime(2026, 6, 27, 9, 0, tzinfo=_IST))


def test_template_is_parseable() -> None:
    """The shipped template parses (with placeholder ids), so it is a valid starting point."""
    template = Path("docs/mechanisms/PREREGISTRATION_TEMPLATE.md").read_text(encoding="utf-8")
    prereg = parse_preregistration(template)
    assert prereg.trial_budget == 10
    assert prereg.success_thresholds["cpcv_median_sharpe_min"] == pytest.approx(1.0)
