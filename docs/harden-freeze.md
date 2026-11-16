# HARDEN freeze (M13.1)

Owner-authorized agent freeze recorded **2026-11-16** (America/New_York).
This file is the freeze identity and the **only** named findings budget for M13.2.
Do not invent findings. Do not expand mid-pass.

## Freeze identity

| Field | Value |
| --- | --- |
| Repo | `d4rkpr10r-Labs/krellbot` |
| Branch | `main` |
| Freeze commit | `9b6310144a9d12a8ba56bedfe89a9e033aaaa4c4` |
| Short tip | `9b63101` — feat(coinbase): live gate + preflight parity with Kraken (M11.3) [risk-path] (#484) |
| Recorded | 2026-11-16 (America/New_York) |

Agents treat this SHA as the frozen functional candidate unless the owner re-freezes.

## Severity bar (in-scope HARDEN)

In scope for this HARDEN pass only if a finding:

1. Comes from **#371 section B** (owner-visible before live enablement) **or** an already-documented product-gap issue cited below, and
2. Still **fails** on the freeze tip, or remains **unverified-as-fixed** after triage, and
3. Affects **order outcomes, money-math / paper accounting, credential integrity, or live-safety gating** (not cosmetic UI polish).

Severity for M13.2 remediation: fix or explicit owner-accepted wontfix/park. Prefer non-risk paths; risk-path findings → agent draft, owner merge.

## Explicitly out of scope

- Learn top-nav / Learn view (leave parked; do not invent).
- Indefinite **#371 section C** (typed-refusal / corrupt-input / cosmetic / not-planned consolidation). Closure there is not a fix claim and is not M13.2 work.
- Owner-gated soak / validate smoke / G1 / flipping `PAPER_ONLY_RELEASE` (M1.8, M1.12, M10.3–M10.5, G1).
- Inventing new audits, scanner campaigns, or expanding beyond the named list below.
- CI flakes and PARKING items not listed here (e.g. editor seed-identity flake, macOS workstation timeout, test renames).
- Installer / site arm64 pin (M13.4), certified publication approval (M13.3), signing certs (M12.1 owner secrets).

## Named HARDEN findings (M13.2 budget)

**Count: 0.**

Triage of every #371-B item against freeze tip `9b63101` found **no** remaining fail or unverified-as-fixed findings within the severity bar. M13.2 has an empty remediation budget unless the owner re-freezes with new named ids.

| Id | Source | Scope | Target paths | Status on freeze tip |
| --- | --- | --- | --- | --- |
| — | — | — | — | *(none)* |

## Verified closed before freeze (not M13.2 work)

Pinning evidence re-run on freeze tip `9b6310144a9d12a8ba56bedfe89a9e033aaaa4c4` (2026-11-16). Already-fixed items stay here; do not reopen them as H-ids.

| #371-B | Title (short) | Evidence on freeze tip |
| --- | --- | --- |
| #156 | Kill switch refused/unknown outcomes | Merged #397; FE unit `OperationsView.killCommandFeedback.test.tsx` (pass) |
| #168 | Preflight obsolete dry-run verdict | Merged #405; FE unit `LivePreflight.inputIntent.test.tsx` (pass) |
| #173 | Paper status other-market position | M0.8 / #418; `tests/test_paper_status_market_scope.py` (pass) |
| #197 | Exclude forming/future Kraken bars (+ paper forming MEDIUM) | #388 + M13.7 / #481; `tests/test_kraken_closed_fetch_cutoff.py`, `tests/test_paper_forming_candle_pricing.py` (pass) |
| #200 | Research returns UTC calendar year | Merged #391; `tests/test_backtest_calendar_returns.py` (pass) |
| #217 | Power-mean overflow/underflow | `tests/test_power_mean_numerical_range.py` (pass) |
| #225 | Paper tick mutual exclusion | Merged #396; `tests/test_tick_lock_inode_handoff.py` (pass) |
| #240 | Research entry-candle stop breach | Merged #386; `tests/test_backtest_entry_candle_stop.py` (pass) |
| #242 | Community pack install confinement | Merged #384; `tests/test_community_pack_id_confinement.py` (pass) |
| #252 | Refuse gapped research windows | `tests/test_research_window_gap_validation.py` (pass) |
| #257 | Refuse nonfinite paper command values | `tests/test_paper_command_finite_numeric_refusal.py` (pass) |
| #258 | Preserve credentials on failed key rotation | Merged #399; `tests/test_cli_key_rotation_integrity.py` (pass) |
| #262 | Refuse out-of-order research candles | `tests/test_research_event_time_order_refusal.py` (pass) |
| #266 | Redact secrets in diagnostic mapping keys | Merged #385; `tests/test_registered_secret_mapping_keys.py` (pass) |
| #268 | Honor explicit research market selection | `tests/test_research_explicit_pair_selection.py` (pass) |
| #269 | Paper tick replay suppression scoped | Merged #402; `tests/test_tick_journal_market_identity.py` (pass) |
| #273 | Refuse unrepresentable instrument steps | Merged #400; `tests/test_instrument_adapter_step_representability.py` (pass) |
| #275 | Buy-and-hold within starting cash | `tests/test_backtest_buy_hold_affordability.py` (pass) |
| #277 | Paper stop raises across concurrent commands | Merged #398; `tests/test_paper_command_concurrent_updates.py` (pass) |
| #279 | No phantom VWMA volume residue entries | `tests/test_vwma_zero_volume_window.py` (pass) |
| #280 | Refuse unfunded paper buys (price + fees) | M0.7 / #417; `tests/test_paper_buy_funding.py` (pass). GitHub issue may still be open as tracker hygiene — not a code finding. |
| #281 | Reject nonfinite strategy rule numbers | Merged #395; `tests/test_pack_operand_execution_range.py` (pass) |
| #289 | Refuse snapshot rules for wrong instrument | Merged #401; `tests/test_instrument_snapshot_identity_refusal.py` (pass) |

### Retired roadmap safety obligations (cited by #371-B)

Re-proven on main via M1.1–M1.5; pinning suite on freeze tip:

`KRELLBOT_HOME=$(mktemp -d) uv run --no-sync pytest -q tests/test_live_obligations.py` — pass (entry pause, ownership/reservation isolation, reconcile-never-resubmit, restore fencing).

## Triage commands (acceptance evidence)

```bash
git rev-parse origin/main
# 9b6310144a9d12a8ba56bedfe89a9e033aaaa4c4

KRELLBOT_HOME=$(mktemp -d) uv run --no-sync pytest -q \
  tests/test_paper_buy_funding.py \
  tests/test_paper_status_market_scope.py \
  tests/test_paper_forming_candle_pricing.py \
  tests/test_kraken_closed_fetch_cutoff.py \
  tests/test_registered_secret_mapping_keys.py \
  tests/test_community_pack_id_confinement.py \
  tests/test_backtest_entry_candle_stop.py \
  tests/test_research_event_time_order_refusal.py \
  tests/test_power_mean_numerical_range.py \
  tests/test_research_window_gap_validation.py \
  tests/test_paper_command_finite_numeric_refusal.py \
  tests/test_research_explicit_pair_selection.py \
  tests/test_instrument_snapshot_identity_refusal.py \
  tests/test_vwma_zero_volume_window.py \
  tests/test_backtest_buy_hold_affordability.py \
  tests/test_live_obligations.py \
  tests/test_backtest_calendar_returns.py \
  tests/test_tick_lock_inode_handoff.py \
  tests/test_cli_key_rotation_integrity.py \
  tests/test_tick_journal_market_identity.py \
  tests/test_instrument_adapter_step_representability.py \
  tests/test_paper_command_concurrent_updates.py \
  tests/test_pack_operand_execution_range.py
# 500 passed (337 + 163) across the two focused batches on freeze tip

cd frontend && npm run test:unit -- --run \
  src/features/operations/OperationsView.killCommandFeedback.test.tsx \
  src/features/deployments/LivePreflight.inputIntent.test.tsx
# 38 passed
```
