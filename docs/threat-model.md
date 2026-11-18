# Threat model

Short trust-boundary map for the local workstation and engine. Operational
detail and procedures live in [SECURITY.md](../SECURITY.md); this file names
what is trusted, what is not, and what must never cross a boundary.

## Assets

| Asset | Where it lives | Must not leave |
| --- | --- | --- |
| Exchange API key / secret | Native OS **keychain** (wizard / `keys add`); optional env or legacy keyfile for load precedence only | Plaintext product storage; issue trackers; **krellbot.dev** |
| Live / paper journals, paper ledger | `$KRELLBOT_HOME` on the operator machine | Remote control plane; telemetry as balances or raw qty |
| License / pack purchase token | Operator machine; sent only when buying packs | Exchange credential channels |
| Bootstrap session token | Served HTML meta + session cookie on loopback | Printed URL; non-loopback hosts |
| Operator intent to go live | Typed `LIVE` grant in the workstation | Silent CLI promotion; env-only “enable live” without grant |

## Trust boundaries

```
[browser on same machine]
        |  loopback HTTP only (127.0.0.1 + Host/Origin/CSRF/session)
        v
[workstation API + local engine] ---- OS keychain ---- [exchange venue]
        |                              ^
        |                              | trade-only key; withdraw off
        | never exchange keys ---------+
        v
[krellbot.dev]  license / optional packs / opt-in telemetry only
```

1. **Loopback UI.** The workstation binds `127.0.0.1` only and refuses
   non-loopback `Host` headers. Status reads are local nonsecret metadata
   under `$KRELLBOT_HOME`; they do not probe a venue or read the exchange
   key. Auth is bootstrap token + session cookie + CSRF/Origin checks.
   Anything that reaches a non-loopback client is outside the intended
   trust perimeter.

2. **OS keychain.** New credential stores go to the native keychain, not a
   plaintext file. Presence of a key is not readiness: trade/withdraw
   permissions are fail-closed until a real probe runs. No workstation path
   sends exchange credentials to **krellbot.dev**.

3. **krellbot.dev.** May receive a license key for packs and, only when the
   operator opts in, telemetry payloads. It is not in the trading loop and
   must never receive exchange keys, secrets, or withdraw-capable material.

4. **Paper vs live.** Paper fills stay on this machine
   (`$KRELLBOT_HOME/run/paper-<venue>.json`); no exchange sees a paper fill.
   Live order send additionally requires an operator live grant (typed
   `LIVE` in the workstation), a trade-only key, and
   `PAPER_ONLY_RELEASE = False`. While `PAPER_ONLY_RELEASE` is `True` (current
   release policy), every live send refuses closed regardless of keys or
   grants. Agents do not flip that flag.

5. **Opt-in telemetry.** Telemetry is off until the operator types `y`.
   Until then nothing leaves the machine. Enabled payloads are a fixed,
   documented shape (install id, pack/venue/pair metadata, bucketed
   notional — never balances, API keys, license values, or raw quantity).
   See [telemetry.md](telemetry.md).

## Adversaries and assumptions

| Actor / failure | Assumption / mitigation |
| --- | --- |
| Remote network attacker | Loopback bind + Host refusal; no CDN/external scripts in the wizard shell |
| Malicious or compromised krellbot.dev | No exchange keys ever sent; license/telemetry are separate channels |
| Malicious pack / journal string | Embedded JSON escapes so content cannot break out of inline script |
| Operator mistake (withdraw key, live arm) | Trade-only requirement; typed live grant; paper-only release rail |
| Local malware with keychain access | Outside product control; same class as other desktop wallets |

## Explicit non-goals

- Hosting operator exchange keys or funds.
- Making the CLI a user live-arm surface (CLI stays plumbing).
- Claiming Gatekeeper/SmartScreen silence until owner-held signing is live
  (`docs/signing.md`).
- Treating research, fixtures, or paper P&L as market performance.

## Related docs

- [SECURITY.md](../SECURITY.md) — operational security notes
- [telemetry.md](telemetry.md) — opt-in egress shape
- [live.md](live.md) — live arm gate and paper-only release
- [paper.md](paper.md) — local paper simulator
- [signing.md](signing.md) — artifact integrity and signing posture
