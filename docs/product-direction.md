# Krellbot product direction

## Goal

Krellbot is **self-custody crypto automation with guardrails and receipts**.
The open-source Python engine and local React workstation run on the
operator’s machine. Krellbot **never receives exchange keys**. Execution is
deterministic under declared inputs; every material decision leaves a
receipt in the local journal.

The website distributes the engine and sells optional premium capabilities.
It is not in the trading loop and never holds operator funds or venue
credentials.

## Who it is for

1. **Primary (co-equal for the V1 front door):** the self-directed trader
   who wants automation they can inspect, reproduce, and operate under
   explicit controls — and **newcomers** who should feel a paper-first
   default path (free starter → paper arm → Run status) without inventing
   live performance or needing a paid account. Power tools stay in the
   same binary behind More / Advanced (see M24); there is no Beginner /
   Power mode toggle.
2. **Still secondary for monetization stories:** operators who later
   deepen into Studio, Research, Deploy, paid packs, or live readiness
   after the paper path feels clear.

## Earn (disclosed)

Monetization is optional and separate from the free engine:

1. **Exchange fee share / referral** — disclosed attribution when an
   operator creates or links an exchange account through a Krellbot
   referral path.
2. **Pro packs + key-blind remote alerts** — paid strategy packs and
   alerts that never require sending exchange keys off-machine.
3. **Creator signed packs** — revenue share on signed packs sold through
   the catalogue; pack format stays open so operators can author their
   own without paying.

## Non-negotiable rules

- Exchange credentials live in the **OS keychain only** (see
  `SECURITY.md`); never plaintext product storage for new stores.
- Never present backtests, fixtures, or rehearsals as **market
  performance**.
- No returns promises. Packs are tools, **not personalized advice**.
- **Live arm only by a human in the web workstation** (typed confirmation).
  The CLI stays plumbing — launcher, scheduler entry, diagnostics — not a
  user feature surface (`AGENTS.md`).
- Telemetry stays **opt-in** and egress is disclosed accurately
  (`docs/telemetry.md`).
- Unknown order outcome means **reconcile, never blindly resubmit**.
- Preserve strategy-owned versus external inventory separation and
  Decimal accounting.
- Billing/store failure must not prevent risk reduction, exits,
  historical export, or diagnostics.
- `PAPER_ONLY_RELEASE` stays `True` until an explicit owner flip after the
  live phase gate (see `docs/milestones/M20.md` / Phase P1).

## Delivery sequence (phases)

Phases are milestone files `M19`–`M23` (P0–P4). In-flight `M14`–`M18` are
not rewritten by this roadmap; finish or park them on their own terms.
Do not start phase engineering until the owner merges the roadmap PR.
**M24** (Beginner-default front door) is a V1 UX milestone that rebalances
workstation disclosure and copy without rewriting P0–P4 gates.

| Phase | Milestone | Theme | Gate (summary) |
| --- | --- | --- | --- |
| P0 | M19 | Evidence / trust | Outsider installs with no platform warning and can reproduce a pack |
| P1 | M20 | Live from web (Kraken) | Outsider places a live order using only the web workstation |
| P2 | M21 | Paid 1.0 | 10 paying customers + day-30 retention evidence |
| P3 | M22 | Agent-ready | Agent completes paper path; policy refuse is journaled |
| P4 | M23 | Distribution | 100 paying + a second revenue line > $1k/mo |
| V1 UX | M24 | Beginner-default front door | Newcomer completes starter → paper arm → Run without Studio; power via More/Advanced |

Explicitly out of scope for these phases: hosting operator keys; more
than two qualified live venues (P4 ships Kraken + Coinbase; Binance stays
paper); paid ads for signals; personalized advice; CLI user features.

## Preserved engineering requirements

- One shared application/domain implementation for GUI and CLI plumbing;
  no separate GUI trading semantics.
- Free and user-authored strategies work without a paid account.
- Deterministic execution; generative AI does not choose orders or
  override risk in the execution path.
- User actions have typed results, state transitions, audit records, and
  truthful error presentation.
- Preserve v1 JSON strategy semantics while extending the versioned
  representation.
- Extend the frozen distribution incrementally; no mandatory
  desktop-shell rewrite.
- UI work follows `docs/design-system.md` (contract
  `KRELL-SIGNAL-20261010`).

## Market context

See `docs/market-position.md` (one page). Ambiguity resolves toward
**custody, correctness, and honesty**.

## Design reference (KRELL-SIGNAL-20261010)

All product UI work follows the owner-approved Signal + Krell Asset Pack
v2 design, contract `KRELL-SIGNAL-20261010`. The portable design contract
lives in `docs/design-system.md`; its tokens, fonts, shell composition
and asset rules are binding for every new or newly scoped frontend task.
Reference compositions are consulted from the approved reference kit
(staged outside this repository); this document does not duplicate
reference paths or private host locations.
