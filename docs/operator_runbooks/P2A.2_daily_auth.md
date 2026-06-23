# P2A.2 — Daily-auth flow: the manual TOTP seed (operator walkthrough)

**Subtask:** P2A.2 (Phase 2A — Operator Actions). See the master blueprint, Part IV.
**Depends on:** P2A.1 (Kite Connect app + `api_key`/`api_secret` in the secrets interface).
**Audience:** the operator (you). The once-per-day login is an action only you can take — the
exchange mandates a manual login, and the AI must never hold your Zerodha password or TOTP.
**What the AI does:** authored this runbook, provides the morning helper script, and verifies
the result. It never sees your password, TOTP, `request_token`, or the resulting token value.

---

## 0. Goal and scope

**Goal:** a repeatable morning routine that turns one manual login into a fresh **`access_token`**,
persisted to the secrets interface so the engine and research code can read it for the rest of
the trading day.

**Why this is a *daily* ritual.** Kite's `access_token` is flushed every morning (~05:00–07:30
IST) and the exchange **mandates a manual login once per day** (Project-specific Inviolable
Rule 6). So this is not a one-time setup — you run it each trading morning before the engine
trades. We do **not** automate the TOTP; manual entry is the compliant path.

**This is also where the `api_secret` is finally proven.** P2A.1 verified the `api_key` and
connectivity with a public read-only call. Here, the `request_token → access_token` exchange
computes `SHA-256(api_key + request_token + api_secret)` — so if the `api_secret` were wrong,
this step fails. A green run end-to-end validates the secret.

**Out of scope (later):** automatically *scheduling* the morning seed and a durable
cross-restart token store are **P5.2**; the live-host secret store (AWS Secrets Manager) is
**Phase 8**. This subtask is the manual dev-box routine only — no speculative plumbing for those
(Ground Rule 4).

---

## 1. Security ground rules (Ground Rule 2)

- The `request_token` and the `access_token` are **secrets**. **Never** paste either into the
  chat, a commit, a config file, or a shared screenshot. The AI never needs them.
- Your **Zerodha password and TOTP** are entered only on Zerodha's own login page — never into
  this project, never into the AI.
- The fresh `access_token` is written **only** to the secrets interface — to the file-backed
  store at `~/.quant-intraday/secrets.json` (logical name `kite_access_token`), never to git,
  never printed. An env var `QUANT_SECRET_KITE_ACCESS_TOKEN` still *overrides* the file if set
  (env always wins — that's how prod/CI inject), but on the dev box the file is the source. The
  helper logs only its **last 4 characters** so you can confirm a token was issued. On Windows
  the file uses the default ACL (no POSIX `0600`), so keep your home directory off shared/synced
  drives.
- One active session per API key: avoid logging into Kite web in another tab while the engine
  runs, or you may invalidate the session.

---

## 2. The morning helper (what it does)

On your go, the AI creates a small CLI helper — `scripts/kite_morning_auth.py` (a thin shim;
logic lives in `src/quant/data/brokers/morning_auth.py`, Ground Rule 3). When you run it, it:

1. reads `api_key`/`api_secret` from the secrets interface (never printed),
2. prints the **Kite login URL** for you to open,
3. waits for you to paste the **`request_token`** from the post-login redirect,
4. exchanges it via the SDK — which computes the `SHA-256(api_key + request_token + api_secret)`
   checksum **for you** (you never compute or paste a checksum) — yielding the `access_token`,
5. **persists** the token via `secrets.set(...)` to the file-backed store
   (`~/.quant-intraday/secrets.json`) — read back through the same secrets interface that serves
   the api_key/secret; the live host swaps this backend for AWS Secrets Manager in Phase 8,
6. logs **only the last 4 characters** of the new token, plus success.

It reuses the already-built, tested `KiteAuthenticator.seed_session` (P1.1) — this subtask adds
the operator-facing morning wrapper around it.

---

## 3. Step-by-step (each trading morning)

### Step 1 — Run the helper
In a fresh PowerShell window (your persisted `QUANT_SECRET_KITE_*` creds from P2A.1 are already
present there):
```powershell
cd C:\Users\vinay\Documents\quant-intraday
uv run python scripts/kite_morning_auth.py
```
It prints a **login URL** like `https://kite.zerodha.com/connect/login?api_key=<key>&v=3` and
then waits, prompting you to paste the `request_token`.

### Step 2 — Log in to Kite (manual TOTP)
1. Open that URL in your browser.
2. Log in with your **Zerodha client ID + password + TOTP** (your authenticator app or the
   external TOTP). This is on Zerodha's page — not the AI, not this project.

### Step 3 — Copy the `request_token` from the redirect
1. After a successful login, Kite redirects your browser to the redirect URL you set in P2A.1,
   with parameters appended, e.g.:
   ```
   http://127.0.0.1:5000/kite/redirect?request_token=ABC123XYZ&action=login&status=success
   ```
2. Your browser will likely show **"site can't be reached"** — that is **expected** (nothing is
   listening on `127.0.0.1:5000`; we only need the URL). The value you want is in the address
   bar: the **`request_token`** parameter (here, `ABC123XYZ`).
3. Copy just that `request_token` value.

> The `request_token` is **single-use and short-lived** (a few minutes). Don't dawdle between
> logging in and pasting it; if it expires, just log in again for a fresh one.

### Step 4 — Paste it into the helper
Back in the terminal, paste the `request_token` at the prompt and press Enter. The helper
exchanges it and, on success, prints something like:
```
... kite morning auth PASSED — access_token ending <last 4>; persisted to the secrets interface (kite_access_token)
```
If it errors (`TokenException` / invalid token), see [§4](#4-if-something-goes-wrong).

### Step 5 — Confirm the token is readable (no new-shell dance)
The token is in the file-backed store, so **any** process — including this same window — can
read it immediately via the secrets interface (length only, never the value):
```powershell
uv run python -c "from quant.core.secrets import default_secrets; t = default_secrets().get_optional('kite_access_token'); print('access_token chars:', len(t) if t else 0)"
```
A non-zero number means the engine/research will read the same token via
`default_secrets().get('kite_access_token')`. That's the P2A.2 success condition. (Unlike the
P2A.1 `setx` step, no fresh window is needed — the file store is visible to every process at
once.)

---

## 4. If something goes wrong

- **`TokenException` / "Invalid `request_token`".** Most often it expired or was already used —
  log in again (Step 2) for a fresh one and re-paste promptly. If it persists, the `api_secret`
  may be wrong: re-check `QUANT_SECRET_KITE_API_SECRET` (this is exactly the secret-validation
  this step performs).
- **"Required secret 'kite_api_…' is not set".** The `QUANT_SECRET_KITE_*` creds aren't in this
  window — open a fresh window (so the P2A.1 `setx` values load) and retry.
- **Token expired mid-day / next morning.** Expected — the token is a one-day credential. Re-run
  the helper (Steps 1–4) each trading morning before the engine trades.
- **You suspect the token leaked.** It self-expires within the day, but you can invalidate the
  session by logging out of Kite and re-seeding.

---

## 5. Acceptance checklist (subtask "Done when")

- [ ] Running the helper completes a full manual login → `request_token` → `access_token`
      exchange (the SDK checksum step succeeds, proving the `api_secret`).
- [ ] The fresh `access_token` is persisted to the secrets interface (the file-backed store,
      logical name `kite_access_token`) — never committed, never printed (only last-4 logged).
- [ ] Any process reads it back via the secrets interface
      (`default_secrets().get("kite_access_token")`).
- [ ] You complete one successful daily login end-to-end; recorded in `docs/PROGRESS.md` with
      the date (no token value).

---

## 6. Design notes (auditable, Ground Rules 3 / 4)

- **Token persistence = the secrets interface, dev-box backend = a file-backed store**
  (`~/.quant-intraday/secrets.json`, `0600` on POSIX), written via `Secrets.set` and read back
  with **env-then-file** precedence — so env vars (prod / AWS Secrets Manager / CI) still win.
  This is the repository pattern: the Phase-5.2 / Phase-8 swap to AWS Secrets Manager is a
  *backend* change behind the same interface (cf. the P1.3 storage `Repository` → QuestDB swap),
  not a caller change. Cross-platform from day one — same code path on Windows/Linux/macOS, no
  Windows-only `setx` branch (Ground Rule 2). A richer cross-restart token store is **P5.2**; the
  live-host backend is **Phase 8**. You can `cat`/`del` the file to inspect or wipe the token.
- **Helper logs the last-4 chars of the `access_token`** on success — the same safe visibility
  pattern as the P2A.1 verifier (you can confirm a fresh token issued without exposing it). The
  separate *engine-startup* last-4 log line is **not** added now (no engine-startup path yet to
  add it to — Ground Rule 4); it's a tracked follow-up in `docs/PROGRESS.md`.
- **No TOTP automation** — manual entry is the SEBI-compliant path (Inviolable Rule 6).

---

## 7. References (Ground Rule 9)

- Master blueprint, Part IV — **P2A.2**; Part III **Layer 5 §8.1** (morning auth/token routine);
  Project-specific **Inviolable Rule 6** (daily manual auth; static-IP order placement).
- Code: [`data/brokers/auth.py`](../../src/quant/data/brokers/auth.py) (`KiteAuthenticator`,
  `seed_session`, the SHA-256 exchange), [`core/secrets.py`](../../src/quant/core/secrets.py)
  (`EnvSecrets`).
- Prior: **P2A.1** (`docs/operator_runbooks/P2A.1_kite_signup.md`). Next: **P2A.3** (first real
  backfill), which consumes the seeded token.
