# Deep Dive #6 — The Control Layer (Mobile Master Control)

*The "all in one place" Android app to monitor and control the whole system. This installment is mostly about **security**, because a phone that can touch a live trading system is a serious attack surface, and getting the trust model wrong is the one mistake here that can be catastrophic. It also operationalizes the independent "panic-flatten" path that Deep Dive #5 required. Grounded against the static-IP and session constraints from earlier installments.*

---

## The one principle everything else follows from

**The phone is a remote control, never the brain.**

- Orders **always originate from the VPS**, never the phone. This is forced by the static-IP rule (only the registered IP may place orders) *and* by security (broker secrets must not live on a device you carry around and can lose).
- The phone **issues intents**; the engine on the VPS **validates them against the hard limits and executes**. The engine remains the single source of truth and authority — exactly as in Deep Dives #3–#5. The app cannot do anything the engine wouldn't already permit.
- The app's most powerful action is **fail-safe**: FLATTEN / PAUSE / STOP can only ever *reduce* risk. That asymmetry — powerful in the safe direction, tightly constrained in the dangerous direction — is what makes a phone control surface acceptable at all.

If you remember nothing else from this document: **secrets stay on the server, orders leave from the server, and the phone's superpower is the off switch.**

---

## The security model (the heart of this layer)

A trading-control app is a high-value target. Design it assuming the phone *will* eventually be lost, stolen, or compromised, and make sure the worst case is bounded.

### What the phone must NEVER hold or do
- **Never** stores the broker `api_key` / `api_secret` / access token. Those live only on the VPS.
- **Never** places orders directly with the broker (wrong IP, and wrong trust boundary).
- **Never** holds anything that, if extracted, lets an attacker drain the account or trade arbitrarily.

### The control API is the only thing the phone talks to
All phone↔system communication goes through a **control API** you run on the VPS, in front of the engine. Its security stack:

1. **Put it behind a private network, not the open internet.** The single highest-leverage decision: expose the control API only over a **VPN / WireGuard / Tailscale** mesh so only your own devices can reach it. A trading-control endpoint should not be publicly routable. (If you must expose it, restrict by IP allowlist + everything below.)
2. **TLS everywhere** (and mutual TLS / client certificates if you can — the app presents a cert, the server verifies it).
3. **Strong authentication, device-bound.** The app authenticates with a credential that is (a) issued per device, (b) **short-lived / refreshable**, and (c) **revocable server-side**. Gate the app open with **biometrics** (fingerprint/face) on the device itself.
4. **Two-factor for dangerous actions.** Read actions (view P&L) are low-risk. **Write actions that change risk posture** — raising a limit, starting the engine, promoting a model — require a second factor (TOTP / re-auth). Flatten/stop, being fail-safe, can be quicker to invoke (you want the panic button fast).
5. **Authorization scopes — read vs control.** Two privilege tiers: a **read scope** (monitoring) and a **control scope** (commands). The app's token carries only what it needs; consider a "monitor-only" mode for day-to-day and an explicit elevation for control.
6. **Bounded commands, validated server-side.** The API exposes **high-level intents**, not arbitrary order placement. "Pause strategy," "flatten all," "set daily-loss-limit to X" — and the engine **clamps every parameter to the hard bounds** from Deep Dive #3. The app can *tighten* risk freely; it can *loosen* it only within server-enforced ceilings (or not at all). The phone can never instruct an arbitrary trade or exceed a hard limit, by construction.
7. **Audit log every action.** Every command (who/what/when, and the resulting engine action) is written to the immutable audit log from Deep Dive #5 — both for debugging and for the SEBI traceability expectation.
8. **Rate limiting** on the control API, independent of the broker's 10-OPS limit.

### Defense-in-depth outcome
If the phone is stolen: biometric lock blocks casual access; the device token is revocable from the VPS; even an unlocked phone can only issue bounded intents (it can flatten/halt — which is *safe* — but cannot extract secrets, cannot place arbitrary trades, and cannot raise limits past the server ceilings). The blast radius is contained to "an attacker can turn your bot off," which is annoying, not ruinous.

---

## Architecture

```
   ┌─────────────┐     HTTPS (commands)      ┌──────────────────┐
   │  ANDROID     │ ───────────────────────▶  │  CONTROL API      │
   │  MASTER       │     WSS (live stream)      │  (on the VPS,     │
   │  CONTROL APP  │ ◀───────────────────────  │  behind VPN)      │
   │  (read +      │     metrics, P&L,          │  • authN / authZ  │
   │   bounded      │     positions, alerts      │  • bounded intents│
   │   control)     │                            │  • clamps to      │
   └─────────────┘                            │    hard limits    │
        ▲  biometric lock                       │  • audit log      │
        │                                        └────────┬─────────┘
        │                                                 │ in-process / local
        │                                        ┌────────▼─────────┐
        │                                        │  TRADING ENGINE   │  ← single source of truth
        │                                        │  (Modules 1–8)    │     & authority
        │                                        └────────┬─────────┘
        │                                                 │ static IP
        │                                        ┌────────▼─────────┐
        │                                        │  BROKER (Kite)    │  ← only the VPS talks here
        │                                        └──────────────────┘
   (phone never reaches the broker directly)
```

Two channels:
- **Read path (high-volume, low-risk):** a WebSocket/SSE stream pushing the same metrics, P&L, positions, health, drift status, and alerts that the monitoring layer (Deep Dive #5) already produces. The app is just another subscriber to that telemetry.
- **Control path (low-volume, high-risk):** request/response commands, each authenticated, second-factored where dangerous, bounded, clamped, and audited.

The control API is a **thin, hardened gateway** — it does not contain trading logic; it translates authenticated intents into calls the engine already exposes internally, and the engine applies the same hard limits it always does.

---

## The control API contract (sketch)

Read scope (stream + GET):
- live telemetry stream: P&L, positions, exposure, margin, latency, feed health, drift status, alerts
- `GET /status`, `GET /positions`, `GET /pnl`, `GET /limits`, `GET /strategies`, `GET /alerts`

Control scope (POST, audited; ★ = requires 2FA / re-auth):
- `POST /flatten-all` — square off everything now (fail-safe; fast path)
- `POST /engine/pause`, `POST /engine/stop` — fail-safe
- `POST /engine/start` ★ — risk-increasing
- `POST /strategy/{id}/pause` , `/enable` ★
- `POST /limits` ★ — set a limit; **server clamps to hard bounds** (tighten freely, loosen only within ceilings)
- `POST /alerts/{id}/ack`
- `POST /model/rollback` (fail-safe) , `POST /model/promote` ★ (champion/challenger from Deep Dive #5)

Every control call: authenticated, scope-checked, second-factored if dangerous, parameter-clamped server-side, written to the audit log. Nothing here is arbitrary order entry.

---

## Feature / screen inventory ("all in one place")

The app surfaces what the operations layer already tracks, plus the bounded controls:

- **Dashboard / home:** engine state, today's P&L (realised/unrealised), daily-loss-budget bar, drawdown vs limit, margin used, and the prominent **flatten / kill** controls.
- **Positions:** live open positions with side, qty, entry, LTP, per-position P&L, and stop status; per-position close.
- **Risk & limits:** current hard limits and their armed status; adjust within server-enforced bounds (★).
- **Strategies:** per-strategy P&L attribution; pause/enable a strategy (★).
- **Health & drift:** feed status, latency, token validity, and the three drift detectors (performance / data / concept) with green-amber-red status.
- **Alerts:** the critical/warning feed with acknowledge.
- **Models:** champion/challenger status; promote (★) / rollback.
- **Activity log:** the audit trail of recent control actions (transparency + reassurance).

Day-to-day this runs in **monitor-only mode**; control actions require explicit elevation. The flatten/kill path stays one-tap-plus-confirm fast (the prototype shows the confirm step), because in a real incident speed matters and the action is safe.

---

## Tech stack decision (and how each becomes an APK)

| Option | Language | APK path | Verdict |
|---|---|---|---|
| **PWA → wrapped APK** | HTML/JS/TS (web) | Trusted Web Activity via **Bubblewrap**, or **Capacitor**, produces a signed APK from a responsive web app | **Recommended for v1.** Single responsive codebase works on phone + desktop, fastest to build, reuses the prototype above as a starting point, easiest to update. An installable APK is a thin wrapper around the web dashboard your VPS serves. |
| **Flutter** | Dart | `flutter build apk` | Best choice if you want a true native feel, push notifications, and offline polish. More work; new language. Strong option for v2. |
| **React Native** | JS/TS | Gradle build → APK | Native-ish, large ecosystem. Reasonable if you prefer the RN stack. |
| **Native Android** | Kotlin / Jetpack Compose | Android Studio → APK | Maximum control/UX, most effort. Overkill for a personal control app. |
| **Python mobile (Kivy/BeeWare)** | Python | buildozer/briefcase → APK | Tempting since the backend is Python, but **not recommended** — weaker UX and rougher tooling for a polished control surface. |

**My recommendation:** ship a **PWA control dashboard** served by your VPS (behind the VPN), then wrap it to an installable **APK via Bubblewrap (TWA)** or **Capacitor**. You get the app on your home screen, one codebase, and the fastest path from prototype to working tool. Move to **Flutter** later if you want native push notifications for critical alerts and a more app-like experience.

---

## What I can build vs what needs your environment

**I can write for you:**
- The **control API** (the hardened gateway): auth, scopes, second-factor, bounded/clamped command handlers, the telemetry stream, audit logging — wired to the engine's internal interfaces.
- The **app frontend** (responsive PWA dashboard in the recommended stack, or Flutter if you prefer) — the real version of the prototype above, talking to the control API.
- The **wrapper/build config** (Bubblewrap/Capacitor or Flutter project) so it produces an APK.
- Setup docs for the VPN (WireGuard/Tailscale) so the API isn't public.

**You must do (these can't and shouldn't come from me):**
- Run the build tooling on your machine (Android Studio / Flutter SDK / Bubblewrap) to compile the APK.
- **Generate and hold the signing key yourself** — never share it; whoever holds it can ship updates as you.
- Deploy the control API + engine on your VPS, and stand up the VPN.
- Provide/secure your own credentials and 2FA enrolment.
- Install the APK on your device (sideload or via your own Play Console).

This division isn't a limitation of effort — it's the security model. The signing key and the broker credentials are yours alone by design.

---

## Build-to-APK path (PWA route, summarized)

1. Build the responsive PWA dashboard (served by the VPS, behind the VPN) with a valid web manifest + service worker.
2. Verify it works as an installed PWA over HTTPS on your phone.
3. Use **Bubblewrap** (`bubblewrap init` → `bubblewrap build`) to wrap the PWA URL into a Trusted Web Activity APK (or Capacitor for more native bridging).
4. **Generate your signing keystore** (`keytool`), keep it secret and backed up, and sign the APK with it.
5. Sideload the signed APK to your device (or distribute privately via the Play Console internal track).
6. Set up the Digital Asset Links file so the TWA opens without a browser chrome.

(Flutter route: `flutter create`, build the screens against the control API, `flutter build apk --release`, sign with your keystore.)

---

## Security checklist before it touches real money

- [ ] Control API reachable **only over VPN / private network**, never public.
- [ ] TLS (ideally mutual TLS) on every connection.
- [ ] Broker secrets/tokens exist **only on the VPS**, never in the app or its storage.
- [ ] App opens behind **biometric lock**; device token is **short-lived and server-revocable**.
- [ ] **Read vs control scopes** enforced; default to monitor-only.
- [ ] **2FA / re-auth on risk-increasing actions**; flatten/stop fast-pathed.
- [ ] Every limit change is **clamped to hard bounds server-side** (cannot loosen past ceilings).
- [ ] Phone **cannot** place arbitrary orders or exceed any hard limit, by construction.
- [ ] Every control action **audit-logged**.
- [ ] Tested: stolen-phone scenario (revoke token, confirm blast radius is bounded to "turn the bot off").
- [ ] Tested: the **flatten/kill path actually works** end-to-end against the engine (this is your DR panic button from Deep Dive #5).

---

## Where this fits in the series

This is **Deep Dive #6 — the Control Layer**, sitting on top of the operations layer (#5). It doesn't add trading capability; it adds *safe remote observability and control*, and it makes the independent panic-flatten path from #5 a real, in-your-pocket button. The trust boundary is the whole point: the engine and its hard limits (#2–#5) remain the authority; the app is a constrained, fail-safe remote.

**Natural next step:** since the app is just a client of the control API, and the control API is a client of the engine, the build order is **engine first, control API second, app last**. Concretely, that means starting where the series always pointed — the **Data & Feature Layer (Deep Dive #1)** and the engine — then exposing the hardened control API, then wrapping the dashboard into an APK. If you want, I can start writing either the control-API gateway or the PWA dashboard code now (both can be built and tested against a stubbed engine before the real engine exists).

*This is an engineering/security reference, not financial advice. A trading-control app carries real operational and security risk; treat the security checklist as mandatory, not optional. Trading carries substantial risk of loss.*
