"""Pre-registration protocol for mechanism studies (Part VI / P6.3).

*"Set thresholds before running"* (Inviolable Rule 1). The original program's honesty came
partly from bands written down **before** any result existed (the P2R.4 budget). Part VI makes
that a hard precondition: a mechanism cannot enter Phase 7 until its hypothesis, economic
rationale, pre-committed success / kill thresholds, and planned trial budget are written to
``docs/mechanisms/<mechanism>_prereg.md`` **and committed to git before the first test run** —
so both the reasoning and the trial count are honest from the start, and auditable in history.

This module is the machine-checkable half of that protocol:

* :func:`parse_preregistration` / :func:`load_preregistration` — read the YAML front-matter of a
  ``<mechanism>_prereg.md`` file into a validated :class:`Preregistration` (fails loudly on a
  missing field — Ground Rule 7).
* :func:`require_preregistration` — the **gate**: it loads + validates the document, then verifies
  via git that the file is **tracked, committed, and clean** (the committed version is what will be
  tested), returning a :class:`CommittedPreregistration` carrying the commit hash + time.
* :meth:`CommittedPreregistration.verify_precedes` — asserts the prereg commit **precedes** a
  test-run start time, the concrete "commit before first test run" check (P6.3 done-when).

The human-readable template + workflow live in ``docs/mechanisms/PREREGISTRATION_TEMPLATE.md`` and
``docs/mechanisms/README.md``.
"""

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from quant.core.logging import get_logger
from quant.research.mechanisms.errors import PreregistrationError

_logger = get_logger(__name__)

#: A git runner: given argument tokens (no leading ``git``), return the command's stdout.
GitRunner = Callable[[Sequence[str]], str]

#: Front-matter keys every pre-registration must define (P6.3 deliverable contract).
_REQUIRED_FIELDS: tuple[str, ...] = (
    "mechanism",
    "hypothesis",
    "economic_rationale",
    "success_thresholds",
    "kill_thresholds",
    "trial_budget",
)


@dataclass(frozen=True, slots=True)
class Preregistration:
    """A parsed, validated mechanism pre-registration (the committed-before-testing contract)."""

    mechanism: str
    hypothesis: str
    economic_rationale: str
    success_thresholds: Mapping[str, float]
    kill_thresholds: Mapping[str, float]
    trial_budget: int


@dataclass(frozen=True, slots=True)
class CommittedPreregistration:
    """A pre-registration confirmed committed to git, with its commit hash + time (the audit)."""

    preregistration: Preregistration
    commit_hash: str
    commit_time: datetime

    def verify_precedes(self, run_started_at: datetime) -> None:
        """Assert the pre-registration was committed **before** ``run_started_at`` (P6.3).

        Raises:
            PreregistrationError: If the commit is at or after the test-run start — i.e. the
                hypothesis was not pre-committed, defeating the honest trial count.
        """
        if self.commit_time >= run_started_at:
            raise PreregistrationError(
                f"pre-registration for {self.preregistration.mechanism!r} was committed at "
                f"{self.commit_time.isoformat()}, not before the test run at "
                f"{run_started_at.isoformat()} — the hypothesis must be committed first (P6.3)"
            )


def parse_preregistration(text: str, *, expected_mechanism: str | None = None) -> Preregistration:
    """Parse a ``<mechanism>_prereg.md`` document's front-matter into a :class:`Preregistration`.

    The document begins with a ``---``-fenced YAML front-matter block holding the structured,
    pre-committed fields; the markdown body below it is free-form rationale.

    Args:
        text: the full document text.
        expected_mechanism: if given, the front-matter ``mechanism`` must equal it (guards a
            mismatched filename vs declared id).

    Raises:
        PreregistrationError: If the front-matter is missing, unparseable, missing a required
            field, or declares a mechanism other than ``expected_mechanism``.
    """
    front_matter = _extract_front_matter(text)
    missing = [field for field in _REQUIRED_FIELDS if front_matter.get(field) in (None, "")]
    if missing:
        raise PreregistrationError(
            f"pre-registration is missing required field(s): {', '.join(sorted(missing))}"
        )
    mechanism = str(front_matter["mechanism"])
    if expected_mechanism is not None and mechanism != expected_mechanism:
        raise PreregistrationError(
            f"pre-registration declares mechanism {mechanism!r} but {expected_mechanism!r} "
            "was expected (filename / id mismatch)"
        )
    trial_budget = _coerce_positive_int(front_matter["trial_budget"], field="trial_budget")
    return Preregistration(
        mechanism=mechanism,
        hypothesis=str(front_matter["hypothesis"]).strip(),
        economic_rationale=str(front_matter["economic_rationale"]).strip(),
        success_thresholds=_coerce_threshold_map(front_matter["success_thresholds"], "success"),
        kill_thresholds=_coerce_threshold_map(front_matter["kill_thresholds"], "kill"),
        trial_budget=trial_budget,
    )


def load_preregistration(path: Path, *, expected_mechanism: str | None = None) -> Preregistration:
    """Read and validate the pre-registration at ``path`` (see :func:`parse_preregistration`)."""
    if not path.is_file():
        raise PreregistrationError(f"pre-registration not found: {path}")
    return parse_preregistration(
        path.read_text(encoding="utf-8"), expected_mechanism=expected_mechanism
    )


def require_preregistration(
    mechanism_id: str,
    *,
    repo_root: Path,
    prereg_dir: str = "docs/mechanisms",
    git_runner: GitRunner | None = None,
) -> CommittedPreregistration:
    """Gate entry into a Phase-7 study on a committed, clean pre-registration (P6.3).

    Loads ``<repo_root>/<prereg_dir>/<mechanism_id>_prereg.md``, validates it, then verifies via
    git that the file is **tracked, committed, and not dirty** (the committed version is exactly
    what will be tested). Returns the commit hash + time so an auditor — or
    :meth:`CommittedPreregistration.verify_precedes` — can confirm the commit precedes the first
    test run.

    Args:
        mechanism_id: the mechanism's stable id (the file is ``<id>_prereg.md``).
        repo_root: the repository root (git operations run here).
        prereg_dir: repo-relative directory holding pre-registrations
            (``config.mechanisms.prereg_dir``).
        git_runner: injectable git command runner (defaults to running ``git`` in ``repo_root``).

    Raises:
        PreregistrationError: If the document is missing/malformed, untracked, uncommitted, or
            has uncommitted local modifications.
    """
    runner = git_runner if git_runner is not None else _default_git_runner(repo_root)
    relative = f"{prereg_dir}/{mechanism_id}_prereg.md"
    path = repo_root / relative
    preregistration = load_preregistration(path, expected_mechanism=mechanism_id)

    if _is_dirty(runner, relative):
        raise PreregistrationError(
            f"pre-registration {relative} has uncommitted changes — commit it before testing "
            "the mechanism, so the committed version is what is judged (P6.3)"
        )
    commit_hash, commit_time = _last_commit(runner, relative)
    _logger.info(
        "pre-registration verified committed",
        extra={
            "mechanism": mechanism_id,
            "commit": commit_hash,
            "committed_at": commit_time.isoformat(),
        },
    )
    return CommittedPreregistration(
        preregistration=preregistration, commit_hash=commit_hash, commit_time=commit_time
    )


def _extract_front_matter(text: str) -> Mapping[str, Any]:
    """Return the parsed YAML front-matter mapping from a ``---``-fenced document."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        raise PreregistrationError(
            "pre-registration must begin with a '---'-fenced YAML front-matter block"
        )
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        raise PreregistrationError("pre-registration front-matter block is not closed by '---'")
    try:
        loaded = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise PreregistrationError(
            f"pre-registration front-matter is not valid YAML: {exc}"
        ) from exc
    if not isinstance(loaded, Mapping):
        raise PreregistrationError("pre-registration front-matter must be a YAML mapping")
    return loaded


def _coerce_threshold_map(value: Any, label: str) -> dict[str, float]:
    """Coerce a thresholds block into a ``{name: float}`` map (non-empty, numeric values)."""
    if not isinstance(value, Mapping) or not value:
        raise PreregistrationError(
            f"{label}_thresholds must be a non-empty mapping of name -> number"
        )
    coerced: dict[str, float] = {}
    for name, raw in value.items():
        try:
            coerced[str(name)] = float(raw)
        except (TypeError, ValueError) as exc:
            raise PreregistrationError(
                f"{label}_thresholds[{name!r}] must be numeric, got {raw!r}"
            ) from exc
    return coerced


def _coerce_positive_int(value: Any, *, field: str) -> int:
    """Coerce ``value`` into a positive int, or fail loudly."""
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PreregistrationError(f"{field} must be a positive integer, got {value!r}") from exc
    if result <= 0:
        raise PreregistrationError(f"{field} must be a positive integer, got {result}")
    return result


def _default_git_runner(repo_root: Path) -> GitRunner:
    """A :data:`GitRunner` running ``git`` in ``repo_root`` (OS-portable; no shell)."""

    def run(args: Sequence[str]) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise PreregistrationError(
                f"git {' '.join(args)} failed in {repo_root}: {completed.stderr.strip()}"
            )
        return completed.stdout

    return run


def _is_dirty(runner: GitRunner, relative: str) -> bool:
    """Whether ``relative`` has uncommitted modifications (``git status --porcelain``)."""
    return bool(runner(["status", "--porcelain", "--", relative]).strip())


def _last_commit(runner: GitRunner, relative: str) -> tuple[str, datetime]:
    """Return ``(commit_hash, commit_time)`` of the last commit touching ``relative``.

    Raises:
        PreregistrationError: If the file has no commit (untracked / never committed).
    """
    # %H = full hash, %cI = committer date, strict ISO-8601 (tz-aware) — fromisoformat parses it.
    output = runner(["log", "-1", "--format=%H%x09%cI", "--", relative]).strip()
    if not output:
        raise PreregistrationError(
            f"pre-registration {relative} is not committed to git — commit it before testing "
            "the mechanism (P6.3: the commit must precede the first test run)"
        )
    commit_hash, _, iso_time = output.partition("\t")
    try:
        commit_time = datetime.fromisoformat(iso_time)
    except ValueError as exc:
        raise PreregistrationError(f"could not parse commit time {iso_time!r}") from exc
    return commit_hash, commit_time
