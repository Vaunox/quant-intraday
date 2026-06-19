# Runbook — Kite daily session (auth/token seed)

How the daily Zerodha Kite access token is obtained and served to the system.
Grounded in Deep Dive #5 ("morning auth/token routine") and Deep Dive #1 §0.2.
Delivered by subtask **P1.1** (`src/quant/data/brokers/`).

> **Why this is manual (and why that's correct).** Kite's access token is flushed
> every morning (~05:00–07:30 IST) and SEBI mandates a manual login once per day.
> The compliant, robust pattern is a ~30-second **manual morning seed** (login +
> TOTP) to obtain the token, then **full automation** for the rest of the session.
> Headless TOTP automation is deliberately *not* used — it is fragile and in tension
> with the manual-login mandate.

## One-time setup (operator)

1. Create a Kite Connect app in the Zerodha developer console; note the **API key**
   and **API secret**, and set the app's **redirect URL**.
2. Subscribe to the paid Connect plan (the free Personal API has **no market data**).
3. Provide the credentials to the process **only** via environment variables (never
   in code or config, never logged):

   | Logical secret name | Environment variable            |
   | ------------------- | ------------------------------- |
   | `kite_api_key`      | `QUANT_SECRET_KITE_API_KEY`     |
   | `kite_api_secret`   | `QUANT_SECRET_KITE_API_SECRET`  |

   These are read through `quant.core.secrets` (`EnvSecrets`); a missing one fails
   loudly naming the variable, never the value.

4. For **order placement** (Phase 4, not P1.1) the engine must run from a
   **static IP** registered in the console. Market-data endpoints are exempt.

## The daily flow

```
login_url()  ──▶  operator logs in (ID + password + TOTP)  ──▶  redirect with
?request_token=…  ──▶  seed_session(request_token)  ──▶  access_token stored & served
```

1. **Get the login URL** — `KiteAuthenticator.login_url()` (delegates to the SDK).
2. **Log in** at that URL with ID + password + **TOTP**. Kite redirects to your
   registered URL with a one-time `request_token` query parameter.
3. **Seed the session** — call `KiteAuthenticator.seed_session(request_token)`. The
   SDK exchanges the request token, signing the call with
   `SHA-256(api_key + request_token + api_secret)` internally, and returns an
   `access_token`. The authenticator sets it on the client and stores it in the
   `TokenStore`.
4. **Use it** — every component reads the current token from the `TokenStore`; the
   `KiteAdapter` applies it before each data call. If nothing is seeded, calls raise
   `SessionNotSeededError` (we never call the API unauthenticated).

### Wiring (illustrative)

```python
from quant.core.config import load_config
from quant.core.secrets import EnvSecrets
from quant.data.brokers import (
    InMemoryTokenStore, InstrumentRegistry, KiteAdapter,
    KiteAuthenticator, TokenBucketRateLimiter, create_kite_client,
)

config, secrets = load_config(), EnvSecrets()
client = create_kite_client(
    secrets.get("kite_api_key"), root=config.broker.api_base_url
)
store = InMemoryTokenStore()

# --- morning seed (manual request_token from the redirect) ---
auth = KiteAuthenticator(client, secrets, store)
print(auth.login_url())                 # operator opens this, logs in
auth.seed_session("<request_token>")    # ~30 seconds, once per day

# --- data path, throttled to the data-endpoint limit ---
adapter = KiteAdapter(
    client, store,
    InstrumentRegistry.from_client(client, exchange=config.market.exchange),
    TokenBucketRateLimiter(config.broker.rate_limits.data_requests_per_second),
    exchange=config.market.exchange,
)
bars = adapter.fetch_historical("RELIANCE", start, end, "minute")
```

## Caveats (design around these)

- **One active session per API key.** Generating a new token invalidates the old;
  logging into Kite web can invalidate the API session — don't log into Kite web
  while the bot runs.
- **Rate limits.** ~3 req/s data, ~10/s orders. The `TokenBucketRateLimiter` keeps
  us under the data limit; exceeding returns HTTP 429.
- **Token lifetime.** The token is valid for the trading day and flushed next
  morning; re-seed daily.

## Deferred to later subtasks

- **Token persistence across restarts + the automated morning routine → P5.2.** P1.1
  ships `InMemoryTokenStore` (process-lifetime) behind the `TokenStore` Protocol; a
  persistent store implements the same Protocol with no other code change.
- **Order placement, positions, margins → P4.x / P5.1.** These methods on
  `KiteAdapter` currently raise `NotImplementedError` naming their subtask.
- **Live WebSocket tick/depth stream → P1.2.**
