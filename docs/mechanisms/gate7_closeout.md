# GATE 7 (Part VI) — Mechanism studies close-out

**Verdict: HONEST STOP. No mechanism cleared the seven-point kill-gate within the pre-committed
cycle cap.** This is a successful Inviolable-Rule-7 outcome — *"no tradeable mechanical edge at
retail scale in this slate"* is a real, honestly-earned answer, reached on budget, $0 of capital
risked.

## The slate, judged in sequence

| Cycle | Mechanism | Outcome | Why |
|---|---|---|---|
| 1 | **Index-rebalance flow** (P7.1) | **DATA-GATED** | The NSE reconstitution change-log (announcement/effective dates) is not in the repo; only a current membership snapshot exists. Machinery built + tested; cannot judge without the event feed (Rule 9: not fabricated). 0 trials. |
| 2 | **Cointegration pairs** (P7.2) | **KILL** | Run on **real data** (survivorship-free panel, 20 large-caps, 2016–2024, 5 trials). Best **+0.425 net annualised Sharpe** — the *strongest mechanical edge found* and the first to clear the +0.3 continue band — but below the +1.0 kill-gate bar by ~2.4× and **not statistically significant** (de-dup t = 1.20, p ≈ 0.12). |
| 3 | **PEAD** (P7.3) | **DATA-GATED** | Needs an external earnings-surprise feed (not in the repo). The P9.2 recorder + the `PeadSpec` are built + tested; cannot judge without the feed. 0 trials. |

**Cumulative trials: 5 / 40.** Cycle cap (3) reached. Per `budget.md`, no mechanism clearing the
kill-gate within the cycle cap → **the mechanical-edge program STOPS.**

## What this means for the downstream gates

- **GATE 7: honest stop.** No mechanism passes → **Phase 8 (CNC execution layer) is NOT built.**
  The blueprint gates Phase 8 on a Phase-7 winner (GATE 7); there is none, so building it would be
  premature — exactly the "Stage 2 correctly not undertaken" discipline of the original program
  (`FINDINGS.md` §6). The Phase-8 plan remains on the shelf, ready if a future mechanism clears.
- **Phase 9 (proprietary data accrual) stands.** The depth recorder (P9.1) and event-reaction
  recorder (P9.2) are built and tested. They are the structural unblockers for the two data-gated
  mechanisms: **forward-accruing** live depth and earnings-reaction data over months is exactly how
  P7.1/P7.3 (and a richer microstructure feature family) become judgeable. Accrual is ongoing by
  design — GATE 9 has no terminal gate.

## The honest finding

The mechanical-edge thesis (Part VI) was pursued with the same discipline that produced the
original program's honest negative. The one mechanism judgeable on data we have — cointegration
pairs — is the **strongest edge this whole project has found** (+0.42 net Sharpe, market-neutral,
real NSE large-caps), yet it is **still real-but-too-weak**: below the economic bar and not
statistically significant on 95 months. The other two mechanisms are **gated on external data the
program does not have** (index-reconstitution dates; an earnings-surprise feed) — and the Phase-9
recorders are the built, tested answer to accruing that data going forward rather than buying it.

The kill-gate did its job; the budget held; nothing fooled itself; no capital was risked. **Part VI
closes its mechanism-study arc at an honest stop, with the apparatus intact and re-pointable the
moment the gated data exists or a new mechanism is defined.**

## Re-opening criteria (for a future session / operator)

- A **reconstitution change-log** → P7.1 runs unchanged (`load_reconstitution_events`).
- An **earnings-surprise feed** populating the P9.2 store → P7.3 runs unchanged (`PeadSpec`).
- **Accrued live depth** (P9.1, over months) → a microstructure mechanism becomes possible.
- A **new mechanism** → pre-register it (P6.3) under a fresh budget and plug a new `StrategySpec`
  into the unchanged kill-gate (P6.1).
