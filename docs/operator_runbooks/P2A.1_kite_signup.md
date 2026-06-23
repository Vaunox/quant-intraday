# P2A.1 — Kite Connect: subscription + developer app creation (operator walkthrough)

**Subtask:** P2A.1 (Phase 2A — Operator Actions). See the master blueprint, Part IV.
**Audience:** the operator (you). Every step here is an action only you can take — it touches
your Zerodha account, your payment method, and credentials that must never reach the AI, git,
or any config file.
**What the AI does:** authored this document before you began, sits with you while you execute
it, verifies the result with a single read-only call, and records the *fact* of completion in
`docs/PROGRESS.md` (never the credential values).

---

## 0. Goal and scope

**Goal:** an active Kite Connect subscription with a registered developer app, yielding an
**API key** and **API secret** for this project, recorded so the engine and research code can
read them through the secrets interface.

**In scope (this subtask):** subscribe, create the app, set the redirect URL, capture the two
credentials, store them via the secrets interface, and verify connectivity with one read-only
call.

**Out of scope (later subtasks):**
- The daily login → `request_token` → `access_token` flow is **P2A.2** (the morning auth seed).
  P2A.1 only obtains the static `api_key`/`api_secret`; it does **not** produce a session token.
- The first real historical backfill is **P2A.3**.

**Prerequisite:** you have an active Zerodha trading account (you can log in to kite.zerodha.com).

---

## 1. Security ground rules (read first — Ground Rule 2)

These are non-negotiable. The credentials you are about to create are how orders get placed on
your money.

- **Never paste the API secret (or API key) into the chat, a commit, a config file, a
  screenshot you share, or any file under the repo.** The AI will never ask you to.
- **Where they go:** both are read through the project's secrets interface
  (`src/quant/core/secrets.py`, `EnvSecrets`), which reads **process environment variables**:
  - `QUANT_SECRET_KITE_API_KEY`  → the API key   (logical name `kite_api_key`)
  - `QUANT_SECRET_KITE_API_SECRET` → the API secret (logical name `kite_api_secret`)
  These names are defined in [`auth.py`](../../src/quant/data/brokers/auth.py) and resolved by
  the `QUANT_SECRET_` prefix in [`secrets.py`](../../src/quant/core/secrets.py).
- **The API key is a public-ish identifier** (it appears in the Kite login URL and ships inside
  client apps), so it is low-sensitivity — but in this project we still keep it in the secrets
  mechanism (an env var), **not** in any committed file, for uniformity and so nothing has to
  change later. The structured logger already redacts `api_key` from log output.
- **The API secret is the real secret.** Treat it like a password. Kite shows it **once**.
- `.gitignore` already excludes `/secrets/`, `.env`, and `.env.*`, but the app does **not**
  auto-load a `.env` file — it reads real environment variables (see Step 5). Do not rely on a
  committed file for either value.

- **Identifying which key is loaded, safely.** Because the API key now lives in an env var
  rather than a glanceable config file, the verification script (Step 6) — and the engine at
  startup — log only the **last 4 characters** of the active API key (e.g. `…ab12`). That lets
  you confirm *which* key is in use without ever exposing the value: the at-a-glance convenience
  config would have given, with no leak surface.

> **Design note (auditable, Ground Rule 4 / 9).** Both the API key and the API secret are
> recorded only via the secrets interface (never config, never git). The API key is a public-ish
> identifier, but treating it as a secret costs nothing, keeps one uniform mechanism, and favours
> the conservative side on leak risk. The blueprint's P2A.1 wording was corrected to match the
> canonical merged P1.1 code (PR #30); blueprint and code now agree — the working code is
> canonical and was not refactored to chase a drifted doc.

---

## 2. The console may differ slightly from this script

This walkthrough is written against the Kite Connect developer console
(`developers.kite.trade`) as documented. Zerodha changes the console UI and pricing from time
to time, so **field names, button labels, and the exact rupee figure may differ from what you
see**. When we execute this together, tell me (or screenshot) what's actually on screen and
I'll map it to the steps below. Where a number might be stale, this doc says so rather than
asserting it.

---

## 3. Step-by-step

### Step 1 — Sign in to the developer console
1. In a browser, go to **`https://developers.kite.trade`**.
2. Click **Sign up / Login** and authenticate with your **Zerodha (Kite) credentials**
   (client ID + password + TOTP). This is your normal Zerodha login — the developer console is
   tied to your trading account.
3. You land on the **My apps** dashboard (empty if you've never created an app).

### Step 2 — Create a new Kite Connect app
1. Click **Create new app** (or **+ Create app**).
2. Choose the app type **Kite Connect** (the paid type that grants API access for data and
   order placement — *not* the free "Publisher" type).
3. Fill the form. Expect roughly these fields:
   | Field | What to enter |
   |---|---|
   | **App name** | A name you'll recognize, e.g. `quant-intraday-dev`. |
   | **Zerodha Client ID** | Your own Zerodha user/client ID. |
   | **Redirect URL** | `http://127.0.0.1:5000/kite/redirect` — see the note below. |
   | **Postback URL** (optional) | Leave blank for now (postback wiring is a later execution-layer subtask). |
   | **Description** | One line, e.g. "Personal intraday research/trading system (dev)." |
   | **Logo** (optional) | Skip. |
4. Submit / **Create**.

**About the Redirect URL (local-development setup).** After you log in each morning (P2A.2),
Kite redirects your browser to this URL with a one-time `request_token` appended, e.g.
`http://127.0.0.1:5000/kite/redirect?request_token=XXXX&action=login&status=success`. For local
development you do **not** need a server listening there — you'll simply copy the
`request_token` out of the browser's address bar by hand in P2A.2. So any local URL you control
works; `http://127.0.0.1:5000/kite/redirect` is our convention (the `127.0.0.1:5000` mirrors the
local MLflow convention elsewhere in the project). It only *matters* in P2A.2; it is harmless in
P2A.1. If Kite rejects a plain-IP URL, try `http://localhost:5000/kite/redirect`.

### Step 3 — Subscribe / billing (the ₹500/month part)
1. Creating a Kite Connect app puts it on a **monthly subscription** — currently
   **₹500/month per app** (verified 2026-06-23; Zerodha repriced it down from the ₹2000 the
   blueprint originally assumed), charged by Zerodha to your account/wallet. Complete whatever
   the console requires to activate the subscription (you may be prompted to add funds or
   confirm billing). **You pay this; the AI cannot and will not.**
2. **Historical data is included** in the ₹500 plan (confirmed on the official site and at
   signup, 2026-06-23) — so the P2A.3 backfill's historical candles are covered with no extra
   add-on. Pricing changes, so re-confirm the *current* monthly figure on the billing screen if
   revisiting this much later.
3. Confirm the app shows as **active / subscribed** on the dashboard.

### Step 4 — Copy the API key and API secret (the once-only step)
1. Open the app's detail page. It displays the **API key** and the **API secret**.
2. **Copy both immediately**, into a temporary secure place (a password manager, *not* a repo
   file, *not* chat).
3. ⚠️ **The API secret is shown once.** If you navigate away or close the page without copying
   it, it is **irrecoverable** — see [§4 Recovery](#4-if-something-goes-wrong). The API key can
   be re-read from the console any time; the secret cannot.

### Step 5 — Record the credentials via the secrets interface
The app reads these from **environment variables**. Set them on your machine. Do **not** put
them in any file inside the repo.

Pick **session-only** (good for the verification right now) or **persistent** (so they survive
new terminals). For a shared/locked-down or production host you'd use a real secret store / AWS
Secrets Manager (Phase 8 / P5A) instead of the steps below — these are the local-dev path.

**Windows (PowerShell) — current session only:**
```powershell
$env:QUANT_SECRET_KITE_API_KEY    = "paste-api-key-here"
$env:QUANT_SECRET_KITE_API_SECRET = "paste-api-secret-here"
```

**Windows (PowerShell) — persistent for your user (survives new terminals):**
```powershell
setx QUANT_SECRET_KITE_API_KEY    "paste-api-key-here"
setx QUANT_SECRET_KITE_API_SECRET "paste-api-secret-here"
# Note: setx affects only NEW terminals, not the current one. Open a fresh terminal afterwards,
# or also run the session-only commands above so you can verify immediately.
# setx stores the value in your Windows user environment (registry); fine for a personal dev
# box, but it is not encrypted at rest — use AWS Secrets Manager on the live host (Phase 8).
```

**Linux / macOS — current session:**
```bash
export QUANT_SECRET_KITE_API_KEY="paste-api-key-here"
export QUANT_SECRET_KITE_API_SECRET="paste-api-secret-here"
# Persistent: add the two export lines to ~/.bashrc or ~/.zshrc (a file OUTSIDE the repo).
```

**Confirm they're set without printing the values** (length-only check):
```powershell
# PowerShell
"$($env:QUANT_SECRET_KITE_API_KEY.Length) / $($env:QUANT_SECRET_KITE_API_SECRET.Length) chars set"
```
```bash
# bash
echo "key:${#QUANT_SECRET_KITE_API_KEY} secret:${#QUANT_SECRET_KITE_API_SECRET} chars set"
```
Both numbers should be non-zero. (Never echo the values themselves.)

### Step 6 — Verify with one read-only call
With the env vars set in the **current** terminal, the AI will run a small verification script
(`scripts/verify_kite_credentials.py`, created on your go) that:
1. loads the `dev` config via `load_config(env="dev")`,
2. reads the API key through the secrets interface (and confirms the API secret is present) —
   without printing either value, and prints only the **last 4 characters** of the API key
   (e.g. `key …ab12 loaded`) so you can confirm which key is active,
3. builds the Kite client (`create_kite_client(api_key, root=config.broker.api_base_url)`),
4. makes **one read-only call** — `client.instruments("NSE")` — and prints only the instrument
   **count** plus a success line.

(The engine logs the same last-4 fingerprint at startup, so "which key is loaded" stays
verifiable in normal operation, not just here.)

**What this proves, honestly:** the credentials are recorded and readable through the secrets
interface, the SDK client builds with your API key, and the machine can reach the Kite API. The
instruments dump is a broad read-only endpoint, so a green result here means "wiring + reachability
are good." The **API secret is fully end-to-end validated in P2A.2**, where the
`request_token → access_token` exchange computes `SHA-256(api_key + request_token + api_secret)`
and *fails* if the secret is wrong. So: P2A.1 verifies the key and the plumbing; P2A.2 proves the
secret.

### Step 7 — Record completion (no credentials)
The AI appends a line to `docs/PROGRESS.md` recording that P2A.1 credentials were obtained, with
**the date only** — never the key or secret, not even partially. Example wording:
> P2A.1 ☑ — Kite Connect app created & subscribed; api_key/api_secret stored via the secrets
> interface (`QUANT_SECRET_KITE_*`); read-only `instruments` verification passed. <date>.

---

## 4. If something goes wrong

- **API secret closed without copying it.** It is **irrecoverable**. On the app's page use
  **Regenerate API secret** (or delete the app and create a new one). Regenerating issues a
  **new secret** (the API key usually stays the same); update `QUANT_SECRET_KITE_API_SECRET`
  with the new value and re-run Step 6. Any place already using the old secret must be updated.
- **Verification call fails with an auth/permission error.** Check that the env vars are set in
  the *same* terminal the script runs in (a `setx`-only value won't be in the current session),
  and that there are no stray quotes/spaces in the pasted values. Re-run the length check in
  Step 5.
- **Verification call fails with a network/TLS error.** Confirm plain internet reachability to
  `https://api.kite.trade`; corporate VPNs/proxies can block it.
- **App shows "not subscribed" / data calls rejected for billing.** Re-check Step 3; the app
  must be on an active paid subscription. Historical-data calls may need the separate add-on
  (confirm before P2A.3).
- **You suspect the secret leaked** (pasted somewhere shared). Regenerate it immediately
  (as above) and update the env var.

---

## 5. Acceptance checklist (subtask "Done when")

- [ ] Kite Connect app created and on an **active subscription**.
- [ ] **API key** stored as `QUANT_SECRET_KITE_API_KEY` (secrets interface; not in any committed
      file).
- [ ] **API secret** stored as `QUANT_SECRET_KITE_API_SECRET` (secrets interface; never
      committed, never logged).
- [ ] The verification script makes **one read-only call** (`instruments`) successfully.
- [ ] `docs/PROGRESS.md` records the **date** P2A.1 was completed (no credential values).

---

## 6. References (Ground Rule 9)

- Master blueprint, Part IV — **P2A.1** (this subtask's spec) and Part III **Layer 1 §0.2**
  (Kite connectivity: paid Connect plan, API key/secret, static-IP-for-orders).
- Master blueprint, Part I — **Ground Rule 2** (no hard-coded secrets; secrets only from the
  environment via one interface).
- Code: [`core/secrets.py`](../../src/quant/core/secrets.py) (`EnvSecrets`, `QUANT_SECRET_`
  prefix), [`data/brokers/auth.py`](../../src/quant/data/brokers/auth.py) (logical secret names),
  [`data/brokers/client.py`](../../src/quant/data/brokers/client.py) (`create_kite_client`,
  `instruments`).
- Next: **P2A.2** (`docs/operator_runbooks/P2A.2_daily_auth.md`) — the daily login / token seed,
  authored at the start of that subtask.
