# Slice C — local exchange-key onboarding (stacked on A/B)

Spec: the user brief attached in the parent session, §2.3 step 2 and §3. This plan is local-only; do not merge or publish the A/B drafts as a release.

## Global constraints

- Venues: Kraken and Coinbase only. No API key, secret, JWT, signed header, raw venue response, or keyfile bytes in HTML/JS bootstrap, status, log, journal, receipt, cookie, URL, or public telemetry. Never send secrets to krellbot.dev. No raw exception string from a venue in a browser response.
- The page stays at `127.0.0.1` behind the existing 32-byte token, session cookie, Origin and CSRF checks. Existing live-arm 403 remains. No writes to plaintext files, no localStorage/sessionStorage. One credential-bearing POST does probe **and** store in the same request; never trust a previous browser probe result or allow a TOCTOU gap.
- Probe unknown/error is not trade-only. Deny before any keychain write if withdraw/transfer/address-management is allowed or required trade capability is absent. Do not call `kb_secrets.store` until permission check succeeds, and refuse fake/null/fail keyring backends.
- Preserve CLI keys-check semantics and existing adapter tests. Add RED regression tests first; run focused and `uv run pytest -q`; run Ruff and dashboard security tests. Screenshots use fake credentials only. No real exchange calls in tests.
- `GetApiKeyInfo` docs (https://docs.kraken.com/api-reference/account-data/get-api-key-info) describe a read-only, no-extra-permission POST returning `permissions`. The current Kraken `WithdrawMethods`-denied check **incorrectly treats invalid keys and read-only keys as trade-only**; this is a blocker before any green UI state.

## Task 1 — truthful Kraken key-permission probe

TDD in `tests/test_venue_kraken.py`, `tests/test_keys_check.py` and fake Kraken transport. Assert invalid key, malformed/absent permissions, withdraw-funds, add/update-withdraw-address, and read-only keys cannot pass; valid required query/trade/cancel permissions can pass. Replace the `WithdrawMethods` inference with `GetApiKeyInfo` permissions; validate response shape strictly, require `modify-trades`, `close-trades`, `query-funds`, `query-open-trades`; reject withdrawal/address-management rights. A live read must not place/cancel an order. No raw returned `apiKey` enters logs or UI. Existing CLI `keys check` must still report `trade on, withdraw off` only when proven.

## Task 2 — shared ephemeral probe/store operation

A small internal module accepts a venue + key + secret, registers redaction immediately, rejects unsupported/missing/oversized inputs and non-persistent keyring, calls the validated venue probe, and stores only on affirmative trade-only result. Return a fixed safe status enum/message/backend name, not raw exceptions. A second request must re-probe; never accept a client-supplied `validated=true`. Handle keyring failures without emitting secrets and without falsely reporting success; do not write to `KRELLBOT_HOME`. Test both venues, unknown result, withdraw-on, trade-off, silent/fail backend, store exception, redaction, and no file writes. Preserve CLI behavior.

## Task 3 — gated wizard exchange page and status

GET `/<token>/keys` offers Kraken/Coinbase instructions, secret fields, and an honest backend/posture status; no prefilled values. POST `/<token>/keys/add` requires the existing token/session/CSRF/Origin guard, processes one credential-bearing request via Task 2, never echoes credentials even on error, and answers with a no-store 303 to a credential-free result/status page (PRG). No client-side persistence and clear the form on submit. A GET status must not perform a live venue probe or access credentials just to render; distinguish key present from trade-only verified (fresh probe during POST; if no durable safe verification, say 'stored; last checked at …', not 'currently connected'). Back and skip remain safe; retain free paper mode, live-arm refusal, and all dashboard controls. Test malformed body/oversize, CSRF/Origin/Host, XSS, no secrets in response/log/bootstrap/cookies, backend failures, both venues, and no-JS flow.

## Task 4 — visual/docs/security review

Wire the exchange step into Welcome → Security → Exchange → Next, update truthful app and site docs together for new behavior, use the existing cyan-based local visual system and self-hosted assets only, maintain no outbound static URL contract. Verify mobile/desktop DOM and keyboard labels without real keys. Independent scoped review plus final whole-branch security review. No merge/deploy until explicit release gates.

## Preflight interface table

| Producer → consumer | Risk | Ruling |
|---|---|---|
| Task 1 `check_key` → Task 2 probe | Current Kraken false-positive on invalid/read-only keys | Require strict API key info before Task 2; a failed venue check is denial, not a green state. |
| Task 2 probe/store → Task 3 POST | Two-step browser probe/store has a TOCTOU gap and leaves secrets in page memory | One POST re-probes immediately before storage, then PRG; never trust a prior client claim. |
| Task 3 wizard → Task 4 docs | 'Connected' may imply a live venue state from a stale check | Show verified-at time or 'not checked'; do not claim continuously connected. |
| Tasks 2/3 internal consistency | `secrets.store` writes key and secret separately | Do not claim atomic rollback. On a write failure, return a failure, never green; assess replacement-key partial-write risk in review. |

Ruling: A/B remains a separate draft PR; Slice C is stacked on A/B in its own local worktree so code review can isolate credential handling. Cost if wrong: rebasing after A/B changes.
