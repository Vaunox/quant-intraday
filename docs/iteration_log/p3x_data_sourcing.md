# Phase 3X — Data track (parallel workstream)

**Status: OPEN — operator-driven, runs parallel to the factor build from day one.**

This is the validity-critical path for Phase 3X. The factor library (P3X.2), labeling (P3X.3),
combiner (P3X.4), and gate config can all be built and unit-tested on synthetic panels with no
market data — but **no backtest number is trustworthy until the data decision below is settled.**
It gates P3X.1 and therefore the P3X.8 gate run.

---

## 1. The validity-critical blocker: survivorship on Nifty 500

A momentum / low-vol backtest is *especially* sensitive to survivorship bias — its whole premise
is sorting on past returns, and a universe that quietly drops the names that crashed will inflate
the measured edge.

Two facts, established empirically in the Cycle-5 work (see [`../FINDINGS.md`](../FINDINGS.md) §5):

1. **Kite cannot serve delisted symbols.** Confirmed: `HDFC`, `TATAMOTORS`, `LTIM` all returned
   `InstrumentNotFoundError` — once a symbol is restructured/delisted it leaves the instruments
   dump and its history is unreachable via the Kite historical API.
2. **Nifty-50 was the easy case; Nifty-500 is the hard one.** For Nifty-50/2021–2026 the dropouts
   were orderly demotions and one value-neutral merger — no collapses — so the survivorship gap
   was nearly harmless. FINDINGS §5 flagged that this leniency is *index/window-specific*. **Nifty
   500 over a multi-year window is the opposite:** it contains genuine small/mid-cap delistings and
   blow-ups, and **those crashed names are exactly what the backtest must include and exactly what
   Kite drops.**

**Consequence:** P3X.1's acceptance criterion — *"delisted/removed names are present with history
up to their exit"* — is **largely unmeetable through the Kite pipeline alone.** This is not a
caveat to note at the end; it determines whether the eventual IR is real.

### The decision (operator's call — pick one before P3X.8)

- **(a) Proper survivorship-bias-free vendor (recommended for a trustworthy number).** Source
  point-in-time Nifty-500 membership **and** delisted-name OHLCV from a paid India dataset that
  retains delisted history. Cost + procurement is the operator's; this is the only path to an
  unasterisked IR.
- **(b) Accept and quantify the residual bias.** Build on Kite for surviving names only, measure
  the IR, and treat it explicitly as an **upper bound** — then estimate the survivorship haircut
  (e.g., proportion of the universe unreachable per year × typical dropped-name underperformance)
  and report the bias-adjusted range. Cheaper; honest if the haircut is stated, not hidden.
- **(c) Restricted survivorship-tractable sub-universe.** Restrict to names with continuous
  listing over the sample (e.g., historically-liquid F&O names) and state plainly it is **not the
  full Nifty 500** — narrower breadth, but no hidden bias. This also aligns with the §6 long-short
  extension's universe.

The momentum literature's strong India results assume survivorship-corrected data; on a
Kite-only surviving-names panel, expect the *measured* IR to be optimistic.

---

## 2. Operator-provided inputs required for P3X.1

| Input | Form | Notes |
|---|---|---|
| Nifty-500 point-in-time membership | table: `symbol, sector, join_date, leave_date` (leave blank = current) | The survivorship-correct union over the sample, including names that left. ~10× the Nifty-50 union; sourced from NSE index reconstitution history or the vendor in (a). |
| Delisted-name OHLCV | per the chosen option above | (a) vendor; (b) accept gap; (c) exclude by construction. |
| Fresh Kite access token | interactive daily login → `request_token` | The Cycle-5 token expired end-of-day. Needed only when an actual backfill runs. |
| Liquidity-screen parameters | confirm `min_median_adv_inr` (default ₹25 cr) + `min_history_sessions` (252) | In `config/factor_default.yaml`; tune in P3X.1. |
| Sector taxonomy for Nifty 500 | `symbol → sector` map | Drives sector-neutral z-score + the ≤25% sector cap. The vendor/NSE classification. |

## 3. What proceeds without it (the parallel build)

- **P3X.2** price-only factor library — built and **leakage-tested on synthetic panels** now.
- **P3X.3** cross-sectional labeling — built and tested on synthetic panels.
- **P3X.4** the combiner interface + zero-parameter baseline.
- **gate config** — locked (`config/factor_default.yaml`).
- **P3X.6 / P3X.7** — CNC cost mode + the (to-be-built) capital layer can be developed against
  synthetic books.

Everything plugs into real data the moment the §1 decision is made and the §2 inputs arrive. The
factor code is written data-source-agnostic (operates on a canonical panel) precisely so the data
track and the build track converge cleanly.
