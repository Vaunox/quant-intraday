# Mechanism studies — pre-registration workflow (Part VI / Phase 6–7)

This directory holds the **pre-registrations** and **verdicts** for the mechanical-edge research
program (Part VI of the master blueprint). Each mechanism study is judged by the **existing**
seven-point kill-gate; this folder enforces the two disciplines the original program learned the
hard way — an **honest, cumulative DSR trial count** (P6.2) and a **pre-registered hypothesis**
committed before any test code (P6.3).

## The harness (what's reused, what's new)

The validation engine — purged CV + embargo, CPCV, DSR, PBO, the robustness battery, the Indian
cost model, and the seven-point kill-gate — is **reused unchanged** (`src/quant/research/validation/`,
`src/quant/research/reports/killgate.py`). Part VI only adds the thin adapter that lets a mechanism
plug into it:

- **`StrategySpec`** (`quant.research.mechanisms.spec`) — express a mechanism as its event timeline
  + per-event **net** returns; `evaluate_spec_under_cpcv` runs it through the existing CPCV engine
  and `mechanism_kill_gate_evidence` assembles the seven-point evidence the kill-gate judges.
- **`TrialCountSource`** (`quant.research.mechanisms.trials`) — the DSR trial count `N` is pulled
  **automatically** from the live cumulative MLflow run count (`config.mechanisms.experiment_names`);
  `deflated_sharpe_auto` is the only DSR entry point, and no caller may pass a literal `N`.
- **pre-registration** (`quant.research.mechanisms.preregistration`) — this folder's protocol.

## The pre-registration workflow

1. **Copy the template.** `cp docs/mechanisms/PREREGISTRATION_TEMPLATE.md docs/mechanisms/<mechanism>_prereg.md`.
   The `mechanism:` front-matter field must equal `<mechanism>` in the filename.
2. **Fill it in** — hypothesis, economic rationale, pre-committed success / kill thresholds, and the
   planned trial budget. Set the thresholds **before** you have any result (Inviolable Rule 1).
3. **Commit it first.** `git add` + `git commit` the pre-registration **before** writing or running
   any code that tests the mechanism. The commit timestamp is the audit record that the hypothesis
   preceded the evidence.
4. **Gate entry into the study.** The study's entry point calls
   `require_preregistration(<mechanism>, repo_root=..., prereg_dir=config.mechanisms.prereg_dir)`,
   which loads + validates the document and verifies via git that it is **tracked, committed, and
   clean**. It returns the commit hash + time; `CommittedPreregistration.verify_precedes(run_start)`
   asserts the commit precedes the first test run.
5. **Run the study, record the verdict.** Every variant (including discarded ones) is one MLflow run
   under a `config.mechanisms.experiment_names` experiment, so it counts toward the cumulative DSR
   `N`. Record the kill-gate PASS / KILL outcome in `docs/mechanisms/<mechanism>_verdict.md`.

## Budget & stop discipline (operator-only)

Before the first Phase-7 study (P7.1) begins, the operator commits a budget to
`docs/mechanisms/budget.md` (mirrors P2R.4): a cycle cap, a cumulative trial cap, and pre-committed
stop / pivot criteria. The agent surfaces the trial / cycle count; **the operator decides continue
or stop** — an honest negative across the slate is a successful Inviolable-Rule-7 outcome.

## Files

- `PREREGISTRATION_TEMPLATE.md` — copy this per mechanism.
- `<mechanism>_prereg.md` — a committed pre-registration (created per study, before testing).
- `<mechanism>_verdict.md` — the kill-gate verdict for a completed study.
- `budget.md` — the operator's Phase-7 budget (committed before P7.1).
