# Deep Dive #4 — The Execution Layer

*Module 7 of the pipeline: the Order Management System (OMS) and everything between "the system decided to trade" and "the position is actually on with a stop protecting it." This is where intended P&L quietly leaks and where operational bugs — not bad signals — end live systems. Grounded against Kite Connect mechanics and the SEBI/exchange algo rules, June 2026.*

**Context carried forward:** liquid cash equities, intraday MIS, 15-min decision clock. From Deep Dive #3 we receive **final risk-checked orders** (symbol, side, quantity), each already inside every hard limit, with the kill-switch and daily/drawdown guards live. The execution layer's job is to get those orders filled faithfully, cheaply, and safely — and to never leave a position unprotected.

---

## The mental model for this layer

One sentence governs everything here, straight from the broker's own documentation:

> **Successful placement of an order via the API does NOT imply successful execution.**

The placement HTTP response gives you an `order_id`, not a fill. The order then moves through a lifecycle and may be rejected, partially filled, or stuck. A naive system that assumes "I got an order_id, therefore I'm in the trade, therefore I'll place my stop now" will — eventually, on a bad day — hold an unprotected position because the entry confirmation never arrived. The execution layer is built around **confirm, then act; reconcile, never assume.**

Three truths shape the design:
1. **The intended order and the realized fill differ** (slippage, partial fills, rejects). Measuring and minimizing that gap is core, not cosmetic.
2. **The network is unreliable.** A timeout doesn't mean the order failed — it might have succeeded. Acting on that uncertainty wrongly causes double-fills or naked positions.
3. **Compliance is enforced at the order endpoint.** The 10-OPS limit, market protection, and static IP are hard gates that *reject* non-compliant orders with errors you must handle.

---

## Module 7 — OMS & Execution

### 7.1 The order lifecycle (a state machine, not a fire-and-forget call)

A Kite order transitions through states roughly like:

```
 PUT ORDER REQ RECEIVED → VALIDATION PENDING → OPEN PENDING → OPEN ──► COMPLETE
                                                     │                    ▲
       (SL/SL-M orders) ──► TRIGGER PENDING ─────────┘            (partial fills
                                                                   accumulate here)
                          REJECTED        CANCELLED
```

Model orders as an explicit **state machine** in your OMS. The placement call returns an `order_id` and nothing more; you learn the real outcome through **two channels** that you must use together:

- **Postbacks (webhooks):** the broker pushes asynchronous order-update events as they happen (the preferred, low-latency path). Also available as order updates on the WebSocket connection.
- **Order-history polling:** retrieve the order's current status by `order_id`. Your reliability backstop, because postbacks can be missed.

**Real, documented failure mode:** order status can get **stuck at "PUT ORDER REQUEST RECEIVED"** even though the order actually executed at the exchange. A system that waits for a "COMPLETE" callback before placing its stop-loss will, in that case, never place the stop — leaving the position naked. The fix is in §7.8/§7.9: never make safety depend solely on a single expected callback.

### 7.2 Order types and when to use each

Kite's relevant primitives for our cash-equity intraday system:

- **Product:** `MIS` (intraday, auto-square-off, leverage-eligible). (Others: `CNC` delivery, `NRML` overnight derivatives, `CO` cover order.)
- **Order types:** `MARKET`, `LIMIT`, `SL` (stop-loss limit), `SL-M` (stop-loss market).
- **Varieties:** `regular`, `iceberg`, `amo` (after-market), `co`, `auction`.
- **Validity:** `DAY`, `IOC` (immediate-or-cancel), `TTL`.
- **`tag`:** a client-side label attached to the order — use it to attribute every order to its strategy (your own audit/attribution; see compliance below).

**How to use them for a 15-min system:**
- **Entry:** prefer a **LIMIT order near the touch** (e.g. at/just inside the best bid for a buy) over a raw MARKET order. A limit order controls slippage; a market order guarantees fill but pays the spread and risks adverse fills. On a 15-min clock you usually have time to work a limit and cancel-replace if unfilled. Use MARKET (with protection) only when immediacy matters more than price.
- **Protective stop:** place an **SL-M** (stop-loss market) for the triple-barrier lower barrier — SL-M is more likely to execute than SL when the trigger is breached (SL can fail to fill in a fast move). Note SL-M is **blocked for index options** (freak-trade protection) — not an issue for cash equities, but relevant if you ever extend.
- **Target:** a **LIMIT** order at the upper barrier, or manage the exit on the decision clock.

**Market protection is mandatory for MARKET and SL-M orders.** You cannot send `market_protection = 0` — such orders are rejected (exchange-mandated for algo orders). Use `-1` (automatic) or a sane percentage. Market protection converts a market order into a limit within a threshold and is subject to the exchange's Limit Price Protection (LPP) ranges; orders outside LPP may be rejected. Handle that rejection path.

### 7.3 Compliance enforced at the order layer (hard gates)

These are not advisory — non-compliant orders are **rejected with errors** you must catch and handle:

- **Static IP:** order requests from a non-whitelisted IP are **rejected**. (Data endpoints are exempt.) Your live engine runs on the registered fixed-IP VPS.
- **10 OPS hard limit:** exceeding 10 orders/second returns **HTTP 429**. This applies to *all* API users regardless of frequency. Your OMS must **rate-limit itself to ≤10 OPS** (a token-bucket throttle in front of every order call) and handle 429 with backoff/queueing. Exceeding 10 OPS *legitimately* would require registering the strategy with the exchange — which we are deliberately avoiding by staying a sub-10-OPS white-box personal user.
- **Market protection mandatory** (as above).
- **Order modification cap:** ~25 modifications per order — relevant if you cancel-replace limit orders aggressively; budget for it.
- **Strategy tagging:** tag every order with its strategy via `tag` for your own attribution and audit. For a sub-10-OPS personal/white-box user, the broker handles the exchange-side algo tagging; you do **not** register a separate exchange strategy ID unless you cross 10 OPS. Keep tags consistent — they're your P&L-attribution key (Deep Dive #5).
- **IOC caveat:** MCX doesn't support IOC in the algo segment (irrelevant for NSE cash, noted for completeness).

### 7.4 Smart execution & slicing (minimize impact, stay compliant)

For **liquid large-caps at modest retail size**, market impact is small — you are a price-taker, not a price-mover — so heroic execution algorithms are mostly unnecessary. The pragmatic toolkit:

- **Limit-near-touch with cancel-replace:** post a limit at/just inside the touch; if unfilled after a short interval, re-quote toward the market. Captures spread when possible, crosses when necessary.
- **Order slicing for larger orders:** split a large order into smaller child orders spread over time (TWAP-style) to reduce footprint and avoid walking the book. **Cap slices at ≤10** to respect the 10-OPS limit — the broker explicitly recommends a 10-slice maximum.
- **Iceberg orders** (built-in) for showing only part of a large order — but the **minimum order value is ₹1,00,000 for equity**, so only relevant above that size.
- **Auto-slicing for freeze limits:** the API auto-splits quantities exceeding exchange freeze limits into child orders (returns a parent `order_id` + a `children` list, each child either an `order_id` or an error). Your OMS must parse and track the children, not just the parent.

The size at which this matters is set by **your order size vs the available 5-level depth** (from Deep Dive #1): if your order would consume more than the top level or two, slice it. Otherwise a single limit order is fine.

### 7.5 Implementation shortfall & slippage (closing the loop with the backtest)

The honest measure of execution quality is **implementation shortfall** — the gap between the price you *assumed* when you decided (Deep Dive #2 uses next-bar-open) and the price you *actually realized*, decomposed into:

- **Spread cost** (crossing bid-ask),
- **Delay cost** (price moved between decision and order),
- **Market impact** (your own order moved the price),
- **Opportunity cost** (the part that didn't fill at all).

Why this matters: your backtest assumed a slippage model (0.05–0.20% etc.). **Live, you must measure realized slippage per trade and compare it to that assumption.** If realized slippage consistently exceeds the model, your backtested edge is partly fictional and the strategy may need to trade less aggressively, use more passive orders, or be retired. This measurement feeds the monitoring/drift layer (Deep Dive #5) and is one of the most important reality checks in the whole system.

### 7.6 Optimal execution theory (and when it's worth it for you)

The principled framework is **Almgren-Chriss optimal execution**: there is a fundamental trade-off between **market impact** (trading fast moves the price against you) and **timing/volatility risk** (trading slowly exposes you to adverse price moves while you wait). The solution is an *efficient frontier of execution trajectories* — an optimal schedule for working a large order given your risk aversion, the asset's volatility, and its impact parameters. **VWAP/TWAP** are simple points on/near this frontier.

For our system: **this is mostly overkill at v1 scale.** A retail-sized order in a liquid Nifty-100 name has negligible permanent impact; limit-near-touch or a few TWAP slices captures ~all the available execution quality. Almgren-Chriss earns its keep only when (a) order size grows large relative to depth, or (b) you move to less liquid names or larger capital. Know the framework; deploy it only when the impact term is actually non-trivial. Over-engineering execution for tiny orders is wasted effort that adds bugs.

### 7.7 Idempotency & reliability (the unreliable-network problem)

A placement call can **time out or error while the order actually succeeded** at the exchange. The dangerous reflex is to retry — and double-fill. Rules:

- **Never blind-retry a placement on timeout.** First **reconcile**: query the order book / positions to determine whether the order actually went through. Only retry if confirmed *not* placed.
- **Use a deterministic client tag / local order key** per intended order, recorded *before* the call, so you can match an uncertain order back to your intent during reconciliation.
- **Persist OMS state** (every intended order, its local key, its broker `order_id`, its state) to durable storage *before* and *after* each call, so a crash/restart can recover and reconcile rather than re-fire.
- **Treat every external call as possibly-lost-response** and design the recovery path first.

### 7.8 Reconciliation (the loop that keeps reality and intent aligned)

Continuously (and on every restart) reconcile **three views**:

```
   INTENDED book          BROKER order book          ACTUAL positions
 (what the system          (what the exchange          (what you actually
  decided to hold)          knows about)                hold + avg price)
        └──────────────── must agree ────────────────────┘
```

The reconciliation loop detects and repairs mismatches:
- Order I think is open but broker shows rejected → re-decide.
- Order broker shows filled but my OMS missed the postback → update state, **place the protective stop now** (this is the fix for the §7.1 stuck-status bug — reconciliation, not the entry callback, guarantees the stop gets placed).
- Position exists that I didn't intend (or size differs) → flatten the discrepancy.
- Stop order missing for an open position → place it immediately.

Reconciliation is what makes the system *self-healing* instead of silently drifting into an inconsistent, dangerous state.

### 7.9 Failure handling (the scenarios that actually bite)

Design explicit handlers for each — these are not edge cases, they happen weekly:

- **Partial fills:** an entry fills 60%. Decide: size the stop/target to the *filled* quantity, and either work the remainder or cancel it. Never place a stop for the full intended size when only part filled.
- **Entry filled but stop failed to place** (the nightmare): the position is naked. Mitigations: (a) reconciliation loop that guarantees a stop exists for every open position; (b) a **system-side stop monitor** that watches live price and market-exits if no exchange stop is confirmed; (c) place the protective stop as fast as possible after entry confirmation, but don't *rely* solely on the confirmation arriving.
- **Order rejected** (margin shortfall, LPP breach, market-protection=0, circuit limit, ESM/T2T name): catch the specific error, log it, and route to the right response (skip, resize, re-quote) — never silently ignore.
- **WebSocket / postback disconnect:** auto-reconnect with backoff, resubscribe, and **fall back to polling** during the gap. Treat a data-feed loss as a risk event (the kill-switch may trigger if it persists).
- **Rate-limit 429:** queue and throttle; never hammer.
- **Auto-square-off (~15:20–15:25):** the broker force-closes MIS positions. **Square off *yourself* a few minutes earlier** (e.g. by 15:15) at prices you control, rather than being force-closed at whatever the broker's square-off gets — broker auto-square-off is a worse fill and a loss of control. Build an explicit end-of-day flatten routine.
- **Margin-shortfall forced square-off:** can happen intraday under peak-margin rules; keep the buffer (Deep Dive #3) and monitor margin live.

### 7.10 Where RL / optimal execution genuinely earns its place

Bounded, well-defined execution sub-problems are a *legitimate* and historically successful use of RL — e.g. learning, given the current order-book state, whether to post a passive limit or cross with a market order, and how to schedule slices to minimize implementation shortfall. This is a much safer use of RL than alpha generation (small action space, clear reward = minimize shortfall). But:
- It is a **phase-2+ optimization**, only worth it once order size makes execution quality matter (§7.6).
- The **hard risk limits (Deep Dive #3 §6.4) sit above any execution policy** and can flatten/halt regardless.

**Output contract of Module 7:** faithful, cost-minimized, compliance-respecting execution of the risk-checked orders — with a guarantee (via reconciliation + system-side stop monitoring) that **no open position is ever left without a stop**, complete fill/slippage records emitted for attribution, and clean self-square-off before the bell.

---

## What I'd build for this layer (concrete spec)

An `execution/` package:

1. **`oms/`** — the order state machine; durable order store (local key ↔ broker `order_id` ↔ state); postback webhook receiver + WebSocket order-update consumer + order-history poller (all three feeding one source of truth).
2. **`router/`** — order-type selection (limit-near-touch default, market-with-protection when needed, SL-M stops); cancel-replace logic with modification budgeting; slicer (≤10 slices, TWAP spacing, freeze-limit child handling); self-imposed **≤10 OPS token-bucket throttle**.
3. **`reconcile/`** — the intended↔broker↔positions reconciliation loop (continuous + on-restart); the **stop-existence guarantee**; discrepancy-repair actions.
4. **`safety/`** — system-side stop monitor (backstop to exchange stops); end-of-day self-square-off routine (~15:15); disconnect/feed-loss handling that escalates to the kill-switch; 429/backoff.
5. **`shortfall/`** — per-trade implementation-shortfall and realized-slippage measurement, emitted to the monitoring layer for backtest-vs-live comparison.

**Build/validate order:** OMS state machine + durable store + reconciliation **first** (against the broker's *paper/sandbox* or tiny live size), proving the **stop-existence guarantee** and idempotent recovery under simulated timeouts/crashes — *before* any strategy runs through it. Then router/slicing, then shortfall measurement. Execution correctness is validated by deliberately injecting failures (kill the WebSocket mid-trade, time out a placement, force a partial fill) and confirming the system never ends up with a naked or doubled position.

---

## Open questions to settle for this layer

- **Passive vs aggressive default:** lean on limit-near-touch (cheaper, risks non-fill) or market-with-protection (certain fill, pays spread)? Recommend passive-first with a re-quote/cross fallback for a 15-min system.
- **Self-square-off time:** how many minutes before the 15:20 auto-square-off to flatten (trading off a longer holding window vs better-controlled exit fills)?
- **System-side stop vs exchange stop reliance:** run both (belt-and-suspenders) or trust exchange SL-M? Recommend both, at least until live behavior is well understood.
- **Sandbox availability:** confirm the broker's paper/sandbox order environment for testing the OMS without real fills (and its fidelity vs live).

---

*Next installment (Deep Dive #5 — the Operations Layer): the layer that keeps the whole thing alive and honest — live monitoring and dashboards, P&L attribution by strategy, the all-important backtest-vs-live drift detection (is the edge still real?), feature/model drift, automated walk-forward retraining (MLOps for a decaying edge), logging/alerting, secrets and config management, the morning auth/session routine, and the operational runbook including how and when to pull the plug.*

*This is an engineering/research reference, not financial advice. Trading carries substantial risk of loss.*
