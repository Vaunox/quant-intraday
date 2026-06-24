# P2A.3 — Real-data backfill: first historical pull (operator walkthrough)

**Subtask:** P2A.3 (Phase 2A — Operator Actions). See the master blueprint, Part IV.
**Depends on:** P2A.1 (credentials), P2A.2 (a seeded daily token), P1.4–P1.7 + P1.9 (code already exists).
**Audience:** the operator (you). The data is pulled **under your Kite subscription** and lands in
**your** local store, so you run it; the AI provides the exact command and reads the result back to verify.

---

## 0. Goal and scope

**Goal:** the project's first **real** historical dataset in the storage layer — **~5 years of
minute bars** for the **8-name seed universe** (`config/universe.yaml`), pulled through P1.4's
resumable backfill into the P1.3 **Parquet** archive, then checked with P1.5 gap detection and
the P1.9 data-quality dashboard.

**Decisions for this run** (set with you):
| Parameter | Value | Why |
|---|---|---|
| Universe | the **8 seed large-caps** in `config/universe.yaml` | defined, liquid, proves the path; Nifty-50/100 is a later config-only expansion |
| Interval | **minute** (`config.ingest.backfill_interval`) | the research substrate; the 15-min decision clock is *derived* from minute bars, not pulled separately |
| Range | **2021-06-24 → 2026-06-23** (~5 years) | enough regimes for CPCV / DSR / kill-gate criterion 7 |
| Tier | **Parquet** (`--tier parquet`, the default) | the immutable cold/raw archive (Deep Dive #1 §1.2); base engine dep, no extra install |
| Token | **read from the secrets interface** (`kite_access_token`, seeded by P2A.2) | no `--request-token` to paste each run |

**Local, not cloud.** A few-hundred-MB Parquet dataset on your laptop is the right environment
at this stage (Part II cloud policy: cloud is for the heavy P2.7/P2.8 runs, not this).

**Survivorship note.** The 8 seed names are all continuously-listed large-caps, so the
point-in-time constituent registry (P1.5 survivorship) is trivially satisfied here — there are
no delisted/renamed names in this window. That machinery becomes load-bearing when the universe
expands to Nifty-50/100, where constituents change over time.

---

## 1. Prerequisites

- **P2A.1 done** — `QUANT_SECRET_KITE_API_KEY` / `QUANT_SECRET_KITE_API_SECRET` set (persistent).
- **A fresh token for *today*** — the Kite `access_token` expires every morning, so the backfill
  needs one seeded **today** (P2A.2). If you haven't run the morning helper today, do it first:
  ```powershell
  cd C:\Users\vinay\Documents\quant-intraday
  uv run python scripts/kite_morning_auth.py
  ```
  (Run a backfill the same day you seed; if it spans a date boundary and the token expires,
  re-seed and re-run — the backfill resumes where it left off.)

---

## 2. What the run does

1. **`scripts/run_backfill.py`** (P1.4): for each symbol in the universe, paginates history into
   ≤60-day minute-candle requests (Kite's cap), self-throttled to ≤3 data req/s, and writes each
   symbol's bars into the Parquet archive (`data/parquet/`, symbol/date partitions). It reads the
   **api_key** and **today's access_token** from the secrets interface (no `--request-token`).
   The run is **resumable**: re-running skips symbols already completed through `--end` (state in
   `data/backfill_checkpoint.json`).
2. **`scripts/check_backfill.py`** (the P2A.3 verifier): reads the Parquet back through the
   `Repository`, then runs the **P1.5 gap detection** + **P1.9 `DataQualityDashboard`** over the
   pulled bars and prints, per symbol: observed sessions vs expected, row count, first/last bar,
   intraday gaps, missing days, bad ticks — plus the report's one-line summary. No credentials, no
   network; it only reads what landed on disk.

> `data/` is gitignored — the dataset is never committed (Ground Rule 6). Only its *version /
> row-counts* get recorded in `docs/PROGRESS.md`.

---

## 3. Step-by-step

### Step 1 — (If not already today) seed the daily token
See §1. Confirm with the read-back one-liner from the P2A.2 runbook if unsure.

### Step 2 — Run the backfill
```powershell
cd C:\Users\vinay\Documents\quant-intraday
uv run python scripts/run_backfill.py --start 2021-06-24 --end 2026-06-23
```
- Universe, interval (minute), tier (parquet), and chunk size (60 days) all come from config — no
  extra flags needed.
- **Expect ~5–15 minutes** wall-clock (≈250 paginated requests across 8 symbols at ≤3 req/s, plus
  per-request latency) and **a few hundred MB** of Parquet.
- You'll see structured INFO lines per symbol as each completes. If interrupted (Ctrl-C, network
  blip, token expiry), just re-run the same command — it resumes.

### Step 3 — Verify (read-back + hygiene + quality)
```powershell
uv run python scripts/check_backfill.py --start 2021-06-24 --end 2026-06-23
```
It prints a per-symbol table (sessions observed/expected, rows, first/last bar, gaps, missing
days, bad ticks) and the `DataQualityReport` summary line. **Paste me that output** — I'll read it
with you and confirm it's within tolerance.

---

## 4. Reading the results (what "green" means here)

- **Every symbol has data** — `observed_sessions > 0` and a sensible row count (a liquid name over
  ~5y of minute bars is on the order of a few hundred thousand to ~1M rows). A symbol with **zero**
  bars is a real failure (the verifier exits non-zero).
- **Coverage close to expected** — `observed_sessions ≈ expected_sessions` (NSE trading days in
  range). A small shortfall at the **far-past end** is expected if Kite's minute history doesn't
  reach all the way to 2021 for a name — that's a Kite availability limit, not a bug (see §5).
- **Intraday gaps / bad ticks are reported, not fatal** — minute data naturally has some micro-gaps;
  the dashboard surfaces the counts for review. We judge "under tolerance" together; nothing here is
  auto-failed except a symbol with no data at all.

---

## 5. If something goes wrong

- **`SessionNotSeededError` / auth error** — today's token isn't seeded (or expired overnight).
  Re-run the morning helper (§1), then re-run the backfill (it resumes).
- **Empty / short coverage for the earliest months** — Kite's minute history may not extend the
  full 5 years for every name. The gap report will show it; if a name is badly short at the start,
  we trim `--start` to where Kite actually has minute data and re-run. (Resumable, so cheap.)
- **429 / rate-limit** — handled by the built-in token-bucket throttle (≤3 data req/s); the run
  backs off automatically. If it persists, re-run later.
- **Interrupted mid-run** — re-run the exact same command; completed symbols are skipped via the
  checkpoint (`data/backfill_checkpoint.json`).

---

## 6. Acceptance checklist (subtask "Done when")

- [ ] The Parquet store contains the **8-symbol** universe over **2021-06-24 → 2026-06-23** (minute).
- [ ] **P1.5 hygiene** (gap detection) runs on the pull; gaps reviewed and within tolerance.
- [ ] The **P1.9 data-quality dashboard** reports each symbol with data and acceptable coverage.
- [ ] The dataset version (range, interval, per-symbol row/session counts) is recorded in
      `docs/PROGRESS.md` (no credentials).

---

## 7. Design notes (auditable, Ground Rules 3 / 4 / 9)

- **Token from the secrets interface.** P2A.3 wires the backfill to read today's `access_token`
  from the secrets interface (`kite_access_token`, seeded once by the P2A.2 morning helper) instead
  of requiring `--request-token` per run — `build_adapter` seeds via OAuth only if a `request_token`
  is explicitly passed, else loads the token from the store (clear error if neither is present).
- **Minute substrate, 15-min derived.** We pull minute bars only; the 15-min decision clock and all
  features (P1.6/P1.7) are computed from them — no separate 15-min pull.
- **Parquet cold archive** is the canonical backfill destination; the versioned ArcticDB research
  tier (operator-installed, `pandas<3`) is a later, optional step in the research env (P2A.4).
- **Verifier is read-only** and composes the existing P1.5/P1.9 modules — no new hygiene logic
  (Ground Rule 4); it just drives them over the pulled data and renders the report.

---

## 8. References (Ground Rule 9)

- Master blueprint, Part IV — **P2A.3**; Part III **Layer 1** (storage tiers, hygiene, coverage).
- Subtasks **P1.4** (backfill job), **P1.3** (Parquet `Repository`), **P1.5** (gap detection /
  survivorship), **P1.9** (data-quality dashboard).
- Code: [`data/ingest/backfill_cli.py`](../../src/quant/data/ingest/backfill_cli.py),
  [`data/quality/dashboard.py`](../../src/quant/data/quality/dashboard.py),
  [`data/store/parquet.py`](../../src/quant/data/store/parquet.py).
- Prior: **P2A.2** (`docs/operator_runbooks/P2A.2_daily_auth.md`). Next: **P2A.4** (research env + MLflow).
