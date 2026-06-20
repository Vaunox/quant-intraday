# Progress Log

The living build log for the quant-intraday system. This is the authoritative
tracker referenced by Part V of `MASTER_BLUEPRINT_Claude_Build_Handoff.md`.
Updated at the end of every session.

**Status:** ◐ in-progress / ☑ done / ☐ todo

**Gates:** Gate 0 ☑ · Gate 1 ☐ · Gate 2 ☐ · Gate 3 ☐ · Gate 4 ☐ · Gate 5 ☐ · Gate 6 ☐ · Gate 7 ☐ · Gate 8 ☐

---

## Phase 0 — Foundation & Scaffolding

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| 2026-06-17 | P0.1 Repository & tooling | ☑ done | `feat/p0.1-repo-tooling` (pushed to origin) | 2 passing (`tests/unit/test_smoke.py`) | uv toolchain; all gates verified green. See session notes below. |
| 2026-06-17 | P0.2 Configuration & secrets | ☑ done | `feat/p0.2-config-secrets` | 34 passing (config + secrets) | Layered typed config (pydantic) + `QUANT__*` overrides + secrets interface; 99% cov. See notes. |
| 2026-06-17 | P0.3 Logging & audit foundation | ☑ done | `feat/p0.3-logging-audit` (merged) | 58 passing (incl. logging + audit) | Structured JSON/text logging (IST, correlation IDs, redaction) + hash-chained append-only audit log; 100% cov both. See notes. |
| 2026-06-17 | P0.4 NSE calendar utility | ☑ done | `feat/p0.4-nse-calendar` (merged) | 87 passing (incl. calendar) | IST trading-calendar/session utility (trading days, holidays, session phases); 100% cov. See notes. |
| 2026-06-17 | P0.5 Domain types & interfaces | ☑ done | `feat/p0.5-types-interfaces` | 98 passing (incl. types + interfaces) | Frozen domain types + 6 runtime-checkable Protocols; fakes type-check; 100% cov both. See notes. |
| 2026-06-17 | **GATE 0** | ☑ **passed** | tag `gate-0-foundation` | whole-package 99% cov | Scaffolding, config/secrets, logging/audit, calendar, contracts — typed, tested, CI green. |

## Phase 1 — Data & Feature Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| 2026-06-19 | P1.1 Broker adapter + auth/session | ☑ done | `feat/p1.1-broker-adapter` | 54 new (158 total) | `KiteAdapter` behind `BrokerAdapter` (historical market data + daily session seam); `kiteconnect` SDK confined to `data/brokers/`; token-bucket rate limiter; 100% cov on the package. See notes. |
| 2026-06-19 | P1.2 Live stream consumer | ☑ done | `feat/p1.2-live-stream` | 27 new (185 total) | `TickStreamConsumer` (full-mode ticks + 5-depth → `MarketUpdate` queue; resubscribe-on-reconnect; staleness heartbeat) behind a `TickerTransport` Protocol; `KiteTickerTransport` (SDK) confined to `data/brokers/`; 100% cov on new modules. See notes. |
| 2026-06-20 | P1.3 Storage layer | ☑ done | `feat/p1.3-storage-layer` | 82 new (267 total) | Three tiers behind `Repository`: `ParquetArchive` (immutable raw, symbol/date partitions; real+tested), `ArcticRepository` (versioned research; time-travel reads), `RedisLiveStore` (bounded recent-bars hot store). Optional clients (`arcticdb`/`redis`) confined to `data/store/` + lazy; arcticdb pins pandas<3 → not a declared dep. 100% cov on new modules. See notes. |
| 2026-06-20 | P1.4 Historical backfill job | ☑ done | `feat/p1.4-historical-backfill` | 40 new (307 total) | `BackfillJob` (paginated, resumable) + `run_backfill.py` CLI, writing through `Repository`. Per-symbol accumulate-then-write-once (the only tier-agnostic, idempotent write — Arctic `write_bars` snapshots, not appends); resume skips completed symbols via a `JsonBackfillCheckpoint`; one Arctic version per symbol. 100% cov on new modules. See notes. |
| | P1.5 Data hygiene jobs | ☐ todo | | | |
| | P1.6 Feature library: core + dual-path harness | ☐ todo | | | |
| | P1.7 Feature library: microstructure/technical/x-sec/regime | ☐ todo | | | |
| | P1.8 Leakage & skew test suite (CI) | ☐ todo | | | |
| | P1.9 Data-quality dashboard | ☐ todo | | | |
| | **GATE 1** | ☐ | | | Tag `gate-1-data`. |

## Phase 2 — Research Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P2.1 Validation harness core (purged CV + cost backtester) | ☐ todo | | | |
| | P2.2 CPCV + DSR + PBO | ☐ todo | | | |
| | P2.3 Labeling: CUSUM + triple-barrier | ☐ todo | | | |
| | P2.4 Sample weighting | ☐ todo | | | |
| | P2.5 Meta-labeling + fractional differentiation | ☐ todo | | | |
| | P2.6 Model: baseline + tracking + calibration | ☐ todo | | | |
| | P2.7 Ensemble + regime gate + registry | ☐ todo | | | |
| | P2.8 Robustness battery + two-engine reconciliation | ☐ todo | | | |
| | P2.9 Validation report + kill-gate emitter | ☐ todo | | | |
| | **GATE 2 — THE KILL-GATE** | ☐ | | | Tag `gate-2-research`. |

## Phase 3 — Capital Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P3.1 Risk-limit engine (first) | ☐ todo | | | |
| | P3.2 Signal combination + selection | ☐ todo | | | |
| | P3.3 Portfolio construction + constraints | ☐ todo | | | |
| | P3.4 Position sizing | ☐ todo | | | |
| | P3.5 Capital pipeline integration | ☐ todo | | | |
| | **GATE 3** | ☐ | | | Tag `gate-3-capital`. |

## Phase 4 — Execution Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P4.1 OMS state machine + durable store | ☐ todo | | | |
| | P4.2 Order-update ingestion | ☐ todo | | | |
| | P4.3 Order router + ≤10-OPS throttle | ☐ todo | | | |
| | P4.4 Slicer | ☐ todo | | | |
| | P4.5 Reconciliation loop + stop-existence guarantee | ☐ todo | | | |
| | P4.6 Execution safety | ☐ todo | | | |
| | P4.7 Implementation-shortfall measurement | ☐ todo | | | |
| | P4.8 Adversarial execution tests | ☐ todo | | | |
| | **GATE 4** | ☐ | | | Tag `gate-4-execution`. |

## Phase 5 — Operations Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P5.1 Daily lifecycle scheduler | ☐ todo | | | |
| | P5.2 Morning auth/token routine | ☐ todo | | | |
| | P5.3 Monitoring metrics + dashboard | ☐ todo | | | |
| | P5.4 P&L attribution | ☐ todo | | | |
| | P5.5 Drift detection (observe-only first) | ☐ todo | | | |
| | P5.6 MLOps: retraining + champion/challenger | ☐ todo | | | |
| | P5.7 Platform: audit, alerting, secrets, config | ☐ todo | | | |
| | P5.8 Infra & disaster recovery | ☐ todo | | | |
| | **GATE 5** | ☐ | | | Tag `gate-5-operations`. |

## Phase 6 — Paper Trading

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P6.1 End-to-end paper trading | ☐ todo | | | |
| | P6.2 Live-vs-backtest validation | ☐ todo | | | |
| | **GATE 6** | ☐ | | | Tag `gate-6-paper`. |

## Phase 7 — Control Layer (Mobile Master Control)

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P7.1 Control API gateway (auth + scopes) | ☐ todo | | | |
| | P7.2 Bounded command handlers + clamping + 2FA | ☐ todo | | | |
| | P7.3 Telemetry stream | ☐ todo | | | |
| | P7.4 Private-network setup | ☐ todo | | | |
| | P7.5 PWA dashboard | ☐ todo | | | |
| | P7.6 APK wrapping (operator-signed) | ☐ todo | | | |
| | P7.7 Security validation | ☐ todo | | | |
| | **GATE 7** | ☐ | | | Tag `gate-7-control`. |

## Phase 8 — Live, Micro Size

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P8.1 Go live, trivially small | ☐ todo | | | Operator-driven; Claude never places real orders. |
| | P8.2 Sustained live validation | ☐ todo | | | |
| | **GATE 8** | ☐ | | | Tag `gate-8-live`. |

---

## Session notes

### 2026-06-17 — P0.1 Repository & tooling ☑

**Goal:** stand up the project skeleton and quality gates.

**Delivered**
- Full Part-I folder structure under `src/quant/` (six layers, all subpackages),
  `tests/{unit,integration,adversarial}`, `config/{,env}`, `app/`, `scripts/`,
  `notebooks/`, `data/`. Every Python package has a one-line module docstring.
- `pyproject.toml` — `hatchling` build (src layout, package `quant`); dev tools in a
  PEP 735 `dependency-groups.dev`; configs for ruff (lint + isort + pydocstyle),
  black, mypy (`strict`), and pytest. Runtime deps intentionally empty (added per layer).
- `.pre-commit-config.yaml` — generic file-hygiene hooks + **local** ruff/black/mypy
  hooks run via `uv run`, so hook versions equal the project's pinned versions (one
  source of truth, no drift between local/CI).
- `.gitignore` — secrets/data/models/.env/caches.
- `.gitattributes` — repo-wide LF normalization (`* text=auto eol=lf`).
- `.github/workflows/ci.yml` — lint + type-check + test on every push/PR via uv, using
  the committed `uv.lock` for reproducible installs.
- `.python-version` (3.12) + committed `uv.lock`.
- `README.md` rewritten with setup/run instructions.
- `tests/unit/test_smoke.py` — 2 tests (package imports; all layer subpackages import).

**Verification (all green, Python 3.12.12 via uv):**
- `uv run ruff check .` → All checks passed
- `uv run black --check .` → 38 files unchanged
- `uv run mypy` → no issues in 38 source files
- `uv run pytest` → 2 passed
- `uv run pre-commit run --all-files` → all 12 hooks Passed

**Decisions**
- **Toolchain = uv** (operator-approved). Single binary, reproducible lockfile; CI uses
  the same. Python pinned to **3.12** to match CI exactly.
- **black formats, ruff lints** (Ground Rule 7 names both). Same line length (100); ruff's
  formatter is left off so the two never conflict. Typing is enforced by mypy `strict`, so
  ruff's `ANN` rules are intentionally **not** enabled (avoids double-reporting); docstrings
  (`D`, google convention) **are** enabled per Ground Rule 5.
- **Local pre-commit hooks via `uv run`** rather than mirror repos, so versions track
  `uv.lock` exactly.

**Bug caught & fixed (root cause, not band-aid — Ground Rule 4)**
- Initial `.gitignore` used unanchored `data/` and `models/`, which also matched the
  **source** packages `src/quant/data/` (6 files) and `src/quant/research/models/` (1 file),
  plus `env/` matched `config/env/`. Because ruff/black/git honor `.gitignore`, those source
  packages would have been silently un-linted **and excluded from commits** — a serious
  defect for a data-centric system. Fixed by anchoring the root-only dirs (`/data/`,
  `/models/`, `/secrets/`, …) and dropping the colliding `env/` pattern. Verified that the
  source packages are now tracked while the root `data/` cache stays ignored.

**Follow-ups / notes for next sessions**
- `config/*.yaml` are intentionally absent (only `config/env/.gitkeep`); their contents are
  **P0.2**'s deliverable.
- Repo is git-initialised on `main`; P0.1 is **committed** on branch `feat/p0.1-repo-tooling`.
  No remote exists yet and nothing has been pushed.
- `gate-0-foundation` tag is **not** applied yet; it comes after P0.5.
- **Next subtask: P0.2 — Configuration & secrets system.**

### 2026-06-17 — P0.2 Configuration & secrets ☑

**Goal:** layered config loader + secrets interface; zero hard-coding.

**Delivered**
- `core/config.py` — layered loader: `default.yaml` ← `config/env/<env>.yaml` ←
  `QUANT__<section>__<key>` env-var overrides; deep-merged and validated into an
  **immutable, typed pydantic `Config`** (`extra="forbid"` → unknown keys fail loud).
  Section models seed the blueprint's locked decisions (15-min clock, broker limits,
  Indian cost model, risk limits, ¼-Kelly, inverse-vol, storage URIs, logging). Plus
  `load_universe()` → typed `Universe`. Loader is fully DI (`config_dir`, `environ`).
- `core/secrets.py` — `Secrets` Protocol + `EnvSecrets` (env-backed, `QUANT_SECRET_`
  prefix). Missing/empty secret raises `MissingSecretError` naming the env var (never
  the value); `environ` excluded from `repr` so values can't leak.
- `config/default.yaml`, `config/env/{dev,paper,live}.yaml`, `config/universe.yaml`.
- Deps: `pydantic`, `pyyaml` (+ `types-PyYAML` dev).

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 42 files), pre-commit;
**34 tests pass**; coverage 99% config (only an unreachable defensive raise) / 100% secrets.

**Decisions**
- **pydantic v2** for the schema: typed access, fail-loud validation, immutability.
- Safety/compliance invariants encoded as schema constraints: OPS ≤ 10 (SEBI),
  `max_slices` ≤ 10, `kelly_fraction` ∈ (0,1], `max_gross_exposure` ≤ 5 (default 1.0 =
  no leverage), slippage `min_bps ≤ max_bps`.
- Override convention: `QUANT__section__key` (double-underscore nesting, highest
  precedence); `QUANT_ENV` selects env; `QUANT_CONFIG_DIR` overrides config location.
- A test asserts **no secret-like keys** in any committed config file (keys parsed,
  comments ignored) — enforcing "secrets never in config files".

**Follow-ups / notes**
- Execution/risk/sizing/portfolio config is seeded now (anti-hard-coding) and will be
  *consumed* by its layer (P3/P4); fields extend per subtask.
- The logger that reads `logging.*` is **P0.3**.
- **Next subtask: P0.3 — Logging & audit foundation.**

### 2026-06-17 — P0.3 Logging & audit foundation ☑

**Goal:** structured logging configured once; append-only audit log interface.

**Delivered**
- `core/logging.py` — `configure_logging(config)` sets up the root logger once
  (idempotent) from `config.logging` (level/format/timezone). JSON or text output;
  **IST timestamps** (zoneinfo + tzdata); **correlation IDs** via a `ContextVar` +
  `correlation_id_context()` + `CorrelationIdFilter`; **secret redaction** (`Redactor`
  masks sensitive-named fields and inline token patterns) applied in both formatters.
  `get_logger(__name__)` everywhere else.
- `core/audit.py` — `AuditLog` Protocol + `FileAuditLog`: append-only JSONL with a
  **SHA-256 hash chain** (each entry links to the prior), per-entry seq + IST timestamp
  + correlation id; secrets redacted on write; `verify()` detects tampering/reordering;
  chain continues across restarts; thread-safe.
- Dep: `tzdata` (zoneinfo resolves Asia/Kolkata on any OS).

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 46 files), pre-commit;
**58 tests pass**; **100% coverage** on both new modules.

**Decisions**
- Root logger configured (all modules' logs become structured); idempotent so
  "configure once" is safe to call again.
- Redaction is key-name + inline-pattern based (no need to hold secret literals);
  reused by the audit log.
- Audit log is hash-chained for tamper-evidence (immutable / SEBI traceability),
  beyond a plain append-only file; `verify()` tested against data-tamper and seq-break.
- IST via `zoneinfo` (config-driven), not a hard-coded offset.

**Follow-ups / notes**
- Alerting on CRITICAL events + secrets-manager wiring are **P5.7** (platform); this is
  the logging/audit substrate they build on.
- **Next subtask: P0.4 — NSE calendar utility.**

### 2026-06-17 — P0.4 NSE calendar utility ☑

**Goal:** authoritative trading-calendar/session utility used everywhere.

**Delivered**
- `core/calendar.py` — `NSECalendar` (frozen): `is_trading_day` / `is_holiday` /
  `is_weekend`, `session_open` / `session_close` / `session_bounds`, `phase_at`
  (CLOSED / PRE_OPEN / REGULAR via the `SessionPhase` enum), `is_open`,
  `next_` / `previous_trading_day` — all in IST. `phase_at` fails loud on naive
  datetimes and converts aware ones to IST. Exchange session times (09:00 pre-open,
  09:15 open, 15:30 close) are named constants (Ground Rule 2). `load_nse_calendar()`
  loads holidays from `config/nse_holidays.yaml` (DI-friendly).
- `config/nse_holidays.yaml` — **partial seed** (fixed-date national holidays, 2025–26)
  with a prominent warning that movable festival holidays MUST be added from the
  official NSE list before trading.
- Small refactor: exposed `config.discover_config_dir` (was private) so the calendar
  reuses config-dir discovery (DRY).

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 48 files), pre-commit;
**87 tests pass**; **100% coverage** on calendar.

**Decisions**
- Calendar is **data-driven** (holidays injected/loaded), keeping `core/` light — no heavy
  market-calendar library in the foundation; the holiday list is reference data like the
  universe.
- **Honesty:** only fixed-date holidays are seeded (no fabricated movable festival dates);
  the engine is fully tested with injected holidays regardless of seed completeness.
- Self-square-off (~15:15) stays in config (`execution.self_square_off_time`); this module
  models exchange session phases only.

**Follow-ups / notes**
- ⚠️ Before paper/live: complete `config/nse_holidays.yaml` with the official NSE holiday
  list (festival holidays move yearly); the live universe/hygiene (P1.5) or operator owns this.
- **Next subtask: P0.5 — Domain types & interfaces (contracts).** Last one before Gate 0.

### 2026-06-17 — P0.5 Domain types & interfaces ☑ (completes Gate 0)

**Goal:** the shared data models and the Protocols every layer implements.

**Delivered**
- `core/types.py` — immutable, slotted value objects: `Bar`, `Tick`, `DepthLevel`,
  `DepthSnapshot` (+ `best_bid`/`best_ask`), `OrderRequest`, `Order`
  (+ `is_complete`/`remaining_quantity`), `Position` (+ `side`/`is_flat`), `Signal`,
  `RiskDecision`; enums `Side`, `OrderType`, `Product`, `OrderStatus`. Pure carriers
  (business invariants enforced by the constructing layer; documented).
- `core/interfaces.py` — `runtime_checkable` Protocols: `BrokerAdapter`, `Repository`,
  `Model`, `PortfolioConstructor`, `Sizer`, `RiskEngine`.
- Coverage config: exclude Protocol/type-only stubs (`...`) from reports.

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 52 files), pre-commit;
**98 tests pass**; types/interfaces 100% cov; whole-package **99%** (only the one
unreachable defensive `raise` in config). A trivial fake of each Protocol is statically
checked (typed assignment → mypy) and runtime-checked (`isinstance`).

**Decisions**
- Domain types are **frozen + slotted dataclasses** (immutable, hot-path-cheap), not
  pydantic — market data streams fast and these are pure carriers.
- All six core Protocols are `runtime_checkable` for fakes; mypy is the authoritative
  conformance check.

---

## GATE 0 — Foundation: ✅ PASSED (2026-06-17)

Project scaffolding, layered config + secrets, structured logging + append-only audit,
the NSE calendar, and the core domain types/Protocols all exist — typed, tested, and
green in CI. Tagged **`gate-0-foundation`**.

**Next: Phase 1 — Data & Feature Layer** (P1.1 — broker adapter + auth/session).

---

### 2026-06-17 — Post-Gate-0 audit + hybrid data contracts (amends P0.5)

**Why:** before starting P1.1, audited all of Phase 0 against deep dives 01–05 and
amended the P0.5 data contracts to the deep-dive "hybrid" shape.

**Audit result (P0.1–P0.5 vs deep dives):** verified correct — cost-model rates
([02 §4b.6]), risk/sizing limits + Kelly ([03 §6]), the order state machine and order
types/product, which correctly exclude the discontinued CO/BO ([04 §7.1–7.2]), session
times/IST ([01 §1.3]), and the secrets/audit/logging discipline ([05]). Two contract
gaps found (below).

**Amendment delivered (`refactor/p0.5-hybrid-data-contracts`):**
- **Hybrid bar representation:** bulk time-series cross boundaries as a pandas
  `DataFrame`; single events stay typed. `BrokerAdapter.fetch_historical` and
  `Repository.read_bars`/`write_bars` now return/accept `pd.DataFrame`; `core/frames.py`
  is the single bridge (`bars_to_frame`/`frame_to_bars` + `BAR_COLUMNS` derived from
  `Bar` so the schema can't drift). Keeps the money/event path typed; gives research the
  pandas it wants.
- Added typed **`Margins`** + `BrokerAdapter.margins()` (pre-open gate + sizing; matches
  the deep-dive `BrokerAdapter`).
- `pandas` is now a `core` dependency (deliberate — foundational for a quant system).

**Verification:** ruff, black, mypy strict (54 files), pre-commit; **103 tests**;
frames/types/interfaces 100% cov.

**Still open (flagged):**
- **Signal direction:** ✓ resolved — `SignalDirection` (LONG/SHORT/FLAT) added, distinct
  from order `Side` (see entry below).
- Deferred to their own layer (not P0 errors): `OrderRequest` `validity`/`variety`/
  `market_protection` → P4.3; `stream()` on the adapter vs a separate port → P1.1/P1.2;
  `Model` primary/meta split → P2.

---

### 2026-06-17 — SignalDirection (long/short/flat), distinct from order Side

`core/types.py`: added **`SignalDirection`** (LONG / SHORT / FLAT) with `to_target_sign()`
(+1 / 0 / -1) as the *only* pure mapping off direction. `Signal` now carries
`direction: SignalDirection` — a `FLAT` signal is a first-class "model ran, no edge"
prediction, kept distinct from the *absence* of a signal. Order `Side` (BUY/SELL) is
unchanged and stays on `OrderRequest`; the **position-aware** direction → (Side, quantity)
translation (target − current position; a future `Side.from_delta`) is deferred to the
capital/execution layer (**P3/P4**) — no `Signal`→`Side` mapping exists in core.

**Verification:** ruff, black, mypy strict (54 files), pre-commit; **104 tests**; types 100% cov.

**Next:** **P1.1** (broker adapter + auth/session) — awaiting operator go.

---

## Phase 1 — Data & Feature Layer

### 2026-06-19 — P1.1 Broker adapter (market data) + auth/session ☑

**Goal:** a `KiteAdapter` for historical market data behind the `BrokerAdapter`
Protocol, with the daily session/token seam — nothing outside `data/brokers/`
importing the SDK.

**Reference (Ground Rule 9):** Deep Dive #1 §0.2 (Kite mechanics: ~3 req/s data
limit, static-IP-for-orders, daily session reset), §0.3 ("never let the rest of the
system import `kiteconnect`"); Deep Dive #5 (morning auth/token routine: login URL →
`request_token` → `SHA-256(api_key+request_token+api_secret)` → `access_token`,
manual-seed-then-automate). Transport decision (official SDK vs custom httpx)
**confirmed by the operator at session start: official `kiteconnect` SDK.**

**Delivered (`src/quant/data/brokers/`):**
- `client.py` — `KiteClient` Protocol (the narrow SDK surface we use) + interval
  normalization (`normalize_interval` / `KITE_INTERVALS`) + `create_kite_client`,
  the **single, lazy** `kiteconnect` import site (keeps the SDK — and its heavy
  twisted/autobahn deps — out of every import path until a live client is built).
- `kite.py` — `KiteAdapter` (implements `BrokerAdapter`): `fetch_historical`
  resolves symbol→token, ensures the session is seeded, throttles, calls the SDK,
  and maps candles to the canonical bars schema **via `core.frames.bars_to_frame`**
  (one schema source of truth). Trading/account methods raise `NotImplementedError`
  naming their subtask (orders → P4.3, order reads → P4.2, positions → P4.5,
  margins → P5.1) — tracked deferral, not a buried TODO (Ground Rule 4).
- `auth.py` — `TokenStore` Protocol + `InMemoryTokenStore` (P1.1 default) +
  `KiteAuthenticator` (`login_url` / `seed_session` / `access_token`); the
  `api_secret` is read only via `core.secrets` and never logged.
- `instruments.py` — `InstrumentRegistry` (`(exchange, tradingsymbol)`→token, from
  the instruments dump; `from_client` builder).
- `rate_limit.py` — `RateLimiter` Protocol + thread-safe `TokenBucketRateLimiter`
  (config-driven, injectable clock/sleep).
- `errors.py` — `BrokerError` + `SessionNotSeededError` / `InstrumentNotFoundError`
  / `UnsupportedIntervalError`.
- `docs/runbooks/kite_session.md` — the daily auth flow, secrets, wiring, caveats.
- `pyproject.toml` — `kiteconnect>=4.2,<6` runtime dep (resolved 5.2.0; v5 signatures
  verified) + a mypy override marking the untyped SDK `ignore_missing_imports`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (67 files),
pre-commit (12 hooks); **158 tests pass** (54 new); **100% coverage** on every
`data/brokers/` module. A `test_brokers_confinement.py` scans the whole `quant`
tree and fails CI on any `kiteconnect` reference outside `data/brokers/`.

**Decisions**
- **Official SDK, confined + wrapped.** Operator-confirmed. The SDK is fronted by our
  own `KiteClient` Protocol and `TokenBucketRateLimiter`, and imported lazily in one
  place, so tests run with fakes (no SDK, no network, no credentials).
- **Symbol-based interface, token resolution inside the adapter.** Our
  `BrokerAdapter.fetch_historical` is symbol-based (P0.5); Kite is token-based, so
  the adapter resolves via `InstrumentRegistry` — the rest of the system never sees
  instrument tokens.
- **Candle → DataFrame via the existing `core.frames` bridge** (not a hand-rolled
  frame) so the bars schema can't drift.
- **`stream()` stays off `BrokerAdapter`.** The live WebSocket consumer is its own
  ingest module (P1.2), matching the existing interface; not added here.

**Bug caught & fixed (root cause, not the test — Ground Rule 4)**
- The token-bucket's refill loop could spin forever: FP rounding left `tokens` a few
  ULPs below 1.0, making the computed wait so small it fell below the clock's ULP, so
  time stopped advancing (a unit test surfaced it as a `MemoryError`). Fixed with a
  `1e-9` epsilon on the token comparison (grant ≈ sub-nanosecond early; loop now
  provably terminates).

**Follow-ups / notes (deferred, tracked)**
- Token **persistence + automated morning seed → P5.2** (`InMemoryTokenStore` is
  behind the `TokenStore` Protocol; a persistent store drops in with no other change).
- **Orders/positions/margins → P4.2/P4.3/P4.5/P5.1** (currently `NotImplementedError`).
- **Live tick/depth stream → P1.2**; **multi-year paginated/resumable backfill → P1.4.**
- **Static IP** matters only for order placement (Phase 4); data endpoints are exempt.
- ⚠️ Operator live-run prerequisites (none needed to build/test): paid Kite Connect
  plan, `QUANT_SECRET_KITE_API_KEY` / `QUANT_SECRET_KITE_API_SECRET`, daily TOTP seed.

**Next subtask: P1.2 — Live stream consumer.**

### 2026-06-19 — P1.2 Live stream consumer ☑

**Goal:** a robust live WebSocket consumer for ticks + 5-level depth, behind a
swappable transport so nothing in `data/ingest` imports the broker SDK.

**Reference (Ground Rule 9):** Deep Dive #1 §0.2 (WebSocket modes — `full` = 5-depth
+ timestamp; 3000 instruments/conn, 3 conns/key) and the `brokers/` module note
("WebSocket lifecycle: reconnect, heartbeat, resubscribe"). KiteTicker v5 API + full-
mode tick shape verified via context7 and SDK introspection.

**Delivered:**
- `core/interfaces.py` — `TickerTransport` (the live-socket port) + `StreamListener`
  (the callback sink) Protocols; `core/types.py` — `MarketUpdate` (a `Tick` + optional
  `DepthSnapshot`).
- `data/ingest/stream.py` — `TickStreamConsumer` (implements `StreamListener`):
  resubscribes its full token set on **every (re)connect** (the testable
  auto-recovery), parses each raw tick to a `MarketUpdate` (tz-aware IST), pushes to a
  `queue.Queue` off the socket thread (a full queue **drops with a WARNING**, never
  blocks the feed), and tracks a **staleness heartbeat**. Pure `parse_market_update`
  for the tick/5-depth mapping. SDK-free.
- `data/brokers/ticker.py` — `KiteTickerTransport` wrapping `kiteconnect.KiteTicker`
  (the **only** ticker import site, lazy via `create_kite_ticker_transport`);
  translates the SDK's `(ws, …)` callbacks to `StreamListener`. Confinement test still
  green.
- `config` — `broker.websocket` gains `reconnect_max_tries` / `reconnect_max_delay_seconds`
  / `connect_timeout_seconds` / `stale_timeout_seconds` (schema + `default.yaml`),
  so reconnect/backoff is config-driven (handed to the SDK's exponential backoff).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (72 files),
pre-commit (12 hooks); **185 tests pass** (27 new); **100% coverage** on
`stream.py`, `ticker.py`, and `MarketUpdate`.

**Decisions**
- **Reconnect/backoff = the SDK's** (KiteTicker's exponential backoff, configured by
  us); duplicating it would fight the library (Ground Rule 4). Our consumer owns the
  **resubscribe-on-connect** and **staleness** logic — the parts worth testing — and
  those are driven by a `FakeTickerTransport` (the "fake socket").
- **Backpressure drops loudly, never blocks.** `on_ticks` runs on the SDK's reactor
  thread; blocking it would stall the feed, so a full queue increments a counter and
  WARNs. Escalation of persistent staleness/feed-loss to the kill-switch is Layer 4/5.
- **SDK confinement holds for streaming too:** the WebSocket lives behind
  `TickerTransport`; `data/ingest` imports no SDK.

**Follow-ups / notes (deferred, tracked)**
- Consumer pushes to a `queue.Queue`; wiring it to the **Redis live store → P1.3**.
- Multi-connection sharding (≤3000 tokens/conn, ≤3 conns) is config-aware but a
  single-connection consumer suffices for a Nifty-100 universe; shard in a later pass
  if the universe grows.
- Feed-staleness → kill-switch escalation lands with execution safety (**P4.6**) /
  monitoring (**P5.3**); P1.2 detects + warns only.

**Next subtask: P1.3 — Storage layer.**

### 2026-06-20 — P1.3 Storage layer ☑

**Goal:** the `Repository` interface + the three tiered implementations, all swappable
behind the one interface so the rest of the system never sees a concrete store.

**Reference (Ground Rule 9):** Deep Dive #1 §1.2 (the three-tier design — Redis hot →
ArcticDB warm/versioned → Parquet cold/immutable; "partition raw archives by
`symbol/date` and keep them immutable and versioned … corrections become new versions";
"storage is behind a repository interface", swappable to QuestDB later) and the §"What
I'd build" `store/` spec (`Repository` + `ParquetArchive` + `ArcticRepository` +
`RedisLiveStore`). ArcticDB `Library` API (`Arctic(uri)` → `get_library(create_if_missing)`
→ `write(prune_previous_versions=False)` / `read(as_of=…)` → `VersionedItem.data/.version`
/ `list_versions` / `has_symbol`) verified via context7.

**Delivered (`src/quant/data/store/`):**
- `serde.py` — the one place that validates the canonical bars schema
  (`ensure_bars_schema`), orders/sorts/range-filters (`sort_bars`,
  `restrict_to_range`, inclusive), (de)serializes via Parquet bytes
  (`to_parquet_bytes`/`from_parquet_bytes` — verified dtype-exact round-trip, reused by
  both the Parquet and Redis tiers), and compares content order-insensitively
  (`frames_equal`). Schema source of truth stays `core.frames.BAR_COLUMNS`.
- `parquet.py` — `ParquetArchive` (a `Repository`): immutable raw archive,
  Hive-partitioned `symbol=<S>/date=<YYYY-MM-DD>/bars.parquet` by **IST** trading day;
  atomic temp-then-replace writes; **idempotent** identical re-write, **immutable**
  conflicting overwrite → `ImmutableArchiveError`; range reads prune partitions then
  filter precisely. Real (pyarrow), fully round-trip tested. `create_parquet_archive`.
- `arctic.py` — `ArcticRepository` (a `Repository`) over a narrow `ArcticLibrary`
  Protocol: every changed write is a new version; identical re-write is a no-op (no
  version bloat); `read_bars_version` + `list_versions` + `latest_version` give
  point-in-time time travel. `open_arctic_library`/`create_arctic_repository` are the
  single, lazy `arcticdb` import site.
- `redis_store.py` — `RedisLiveStore` (a `Repository`) over a narrow `RedisClient`
  Protocol: a bounded rolling window (newest `live_max_bars_per_symbol`) per symbol,
  de-duped by timestamp (incoming wins), optional Redis TTL; `create_redis_client`/
  `create_redis_live_store` are the single, lazy `redis` import site.
- `errors.py` — `StorageError` + `SchemaError` / `ImmutableArchiveError` /
  `VersionNotFoundError` / `OptionalDependencyError` (Ground Rule 7).
- `core/config.py` + `config/default.yaml` — `StorageConfig` gains `arctic_library`,
  `redis_key_prefix`, `live_max_bars_per_symbol` (>0), `live_ttl_seconds` (≥0), all
  config-driven (Ground Rule 2).
- `pyproject.toml` — `pyarrow` runtime dep (Parquet engine); `redis` optional extra;
  `arcticdb`/`redis` added to mypy `ignore_missing_imports` (absent in CI).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (84 files),
pre-commit (12 hooks); **267 tests pass (82 new)**; **100% coverage** on all five
`data/store/` modules. `uv lock --check` + `uv sync --frozen` clean (pandas stays 3.0.3).
A `test_store_confinement.py` (AST-based) fails CI on any `arcticdb`/`redis` import
outside `data/store/`; a parametrized `test_store_repository_contract.py` runs the same
`Repository` contract across all three tiers (the swappability proof).

**Decisions**
- **All three tiers implement the existing `Repository`** (bars). The hot tier keeps a
  bounded recent-bars window (the "live" flavor); tick-level buffering / wiring the P1.2
  consumer→store is deferred (needs tick→bar aggregation, a later pass).
- **`arcticdb` is NOT a declared dependency.** It pins `pandas<3` and would drag the
  whole project's locked pandas down from 3.x (verified: `uv pip install --dry-run
  arcticdb` ⇒ pandas 3.0.3 → 2.3.3). It is operator-installed in a pandas<3 environment
  (or swap the warm tier for QuestDB — the `Repository` interface makes that clean).
  `redis` is a safe optional extra (no pandas constraint). Parquet (pyarrow) is the
  always-installed baseline — Deep Dive #1: "Parquet … perfectly adequate to start."
- **Optional clients confined + lazy + faked**, exactly like the P1.1 `kiteconnect`
  pattern: narrow Protocols (`ArcticLibrary`, `RedisClient`), one lazy `create_*` import
  site each, repository logic fully tested against fakes (no install, no server). Only
  the post-import construction lines are `# pragma: no cover`; the missing-dependency
  path (→ `OptionalDependencyError`) **is** tested (it is reachable in CI, where the
  clients are absent), skipping only where a client happens to be installed.
- **One serializer for Parquet files and Redis values** (Parquet bytes via pyarrow),
  so dtypes round-trip identically across tiers and the archive immutability check
  compares apples to apples.

**Bug caught & fixed (root cause, not a workaround — Ground Rule 4)**
- A method named `set` (to match `redis.Redis.set`) shadowed the builtin `set` inside
  the class body, so a sibling annotation `set[bytes]` evaluated the *method* and raised
  `TypeError: 'function' object is not subscriptable` at import. Fixed by typing those
  returns as the abstract `collections.abc.Set[bytes]` (the codebase's idiom for abc
  types), which resolves to the module global, not the shadowing method.

**Follow-ups / notes (deferred, tracked)**
- **Multi-year paginated/resumable backfill → P1.4** writes through these tiers.
- **Wiring the live consumer → `RedisLiveStore`** (tick→bar aggregation) lands with the
  feature/ingest path (P1.6-ish); P1.3 provides the store, not the aggregation.
- ⚠️ Operator, to use the optional tiers: `uv sync --extra redis` for the hot store;
  `pip install "arcticdb>=5,<7"` in a **pandas<3** env for the versioned research store.
- Parquet range reads prune by IST date then filter precisely; if a single symbol grows
  to many years of partitions, a future optimization is a DatetimeIndex + arcticdb-native
  `date_range` (perf only, with evidence — Ground Rule 7).

**Next subtask: P1.4 — Historical backfill job.**

### 2026-06-20 — P1.4 Historical backfill job ☑

**Goal:** a paginated, resumable multi-year historical backfill that writes through the
`Repository` interface — `data/ingest/backfill.py` + `scripts/run_backfill.py`.

**Reference (Ground Rule 9):** Deep Dive #1 §1.1/§1.2 + the "What I'd build" `ingest/`
spec ("historical backfill jobs (paginated, resumable) … writing through a `Repository`
interface"); §0.2 (Kite caps a single historical request — ~60 days for minute candles —
which is *why* pagination exists). Build order (§"What I'd build"): adapter → **historical
backfill** → storage → hygiene.

**Delivered:**
- `data/ingest/backfill.py` — `BackfillJob` (programs against `BrokerAdapter` + `Repository`
  + a `BackfillCheckpoint`, all injected): paginates `[start, end]` into day-aligned,
  non-overlapping `chunk_days` windows (`iter_chunks`), accumulates a symbol's chunks, and
  writes **once per symbol**. Per-symbol failures are isolated (logged ERROR + recorded in
  the `BackfillReport`, run continues); naive bounds / `start>end` / `chunk_days<=0` fail
  loud. `JsonBackfillCheckpoint` (atomic temp-then-replace JSON, keyed `symbol:interval`)
  is the durable resume state; `BackfillCheckpoint` Protocol + in-memory fake for tests.
- `data/ingest/backfill_cli.py` — importable CLI wiring (arg/date parsing, universe
  fallback, tier selection `parquet|arctic|redis`, `build_adapter`, `main`); `main` takes
  an injected `environ` + `adapter_factory` so the whole orchestration is unit-tested with
  a fake adapter. `scripts/run_backfill.py` is a thin shim (Ground Rule 3).
- `core/config.py` + `config/default.yaml` — new `IngestConfig` (`backfill_chunk_days` (>0),
  `backfill_interval`, `backfill_checkpoint_file`); the chunk window is config, not a magic
  number (Ground Rule 2), since the cap is a per-interval broker constraint.
- `data/ingest/errors.py` — `IngestError` + `BackfillCheckpointError`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (90 files), pre-commit
(12 hooks); **307 tests pass (40 new)**; **100% coverage** on all new `data/ingest`
modules (`backfill`, `backfill_cli`, `errors`, `__init__`). Coverage on this Windows env
needs path-based `--cov=src/quant/data/ingest` (the module-name form trips a numpy-2.x
"load module more than once" import guard under pytest-cov).

**Decisions**
- **Accumulate-then-write-once per symbol** (the key design call). `Repository.write_bars`
  is *not* a guaranteed append across tiers: Parquet appends day-partitions, but **Arctic
  `write_bars` writes the frame as a whole new version (snapshot, replacing prior data)**
  and Redis merges a bounded window (P1.3). The only behaviour the interface guarantees
  everywhere is "persist this frame as the symbol's data, idempotently, readable by range".
  So the job concatenates a symbol's paginated chunks and writes the full series in one
  call — correct on *every* tier, and it yields exactly one Arctic version per symbol per
  run (= "writes versioned data"). Writing per-chunk would silently corrupt the Arctic tier
  (each chunk would overwrite the last) — a latent bug Ground Rule 4 forbids.
- **Resume granularity is one symbol.** The checkpoint records "completed through date D"
  per `(symbol, interval)`; a re-run skips any symbol already complete through the requested
  `end` and re-fetches the rest in full. No duplication: completed symbols aren't re-fetched,
  and the single re-write of an unfinished symbol is idempotent (and even with the checkpoint
  deleted, idempotent writes prevent dups). Finer **per-chunk durable** resume would need an
  explicit `append`-style method on `Repository` — deferred, tracked (it would also let a
  multi-year symbol resume mid-stream instead of re-fetching from `start`).
- **Broker- and store-agnostic.** The job imports no SDK and no concrete store; the CLI's
  live `build_adapter` is the only operator/network path (`# pragma: no cover`). The
  `kiteconnect`-confinement scanner still passes (the CLI only *imports from* `data/brokers`).

**Follow-ups / notes (deferred, tracked)**
- **Per-chunk durable resume** ⇒ a `Repository.append_bars` (or an ingest-side staging
  area); only matters once single-symbol histories are large enough that re-fetching a
  whole symbol on resume is costly.
- **Hygiene (corp-actions/survivorship/bad-tick/gaps/liquidity) → P1.5** runs over what
  this backfill lands in the raw archive.
- ⚠️ Operator live-run prerequisites (none needed to build/test): paid Kite plan,
  `QUANT_SECRET_KITE_API_KEY`/`_SECRET`, today's `--request-token` (daily manual seed),
  static IP not required for data endpoints. Tune `backfill_chunk_days` down if a coarser
  interval hits its own Kite cap.

**Next subtask: P1.5 — Data hygiene jobs.**
