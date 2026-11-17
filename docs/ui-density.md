# First-viewport density contract

**Extends:** Signal contract `KRELL-SIGNAL-20261010` (`docs/design-system.md`) and
progressive disclosure (`docs/design-guide-progressive-disclosure.md`).  
**Scope:** Presentation density for Workspace home, Workstation, Operations, and
Packs. Does not invent a Learn view, flip `PAPER_ONLY_RELEASE`, place real orders,
or fabricate live P&L / fills / portfolio results.

Reference viewports for acceptance and visual checks:

| Name | Size | Role |
| --- | --- | --- |
| Desktop | **1440×900** | Primary composition target |
| Narrow | **~390×844** | Phone / stacked shell; ≥44px targets |

“Above the fold” means visible in the content area below the sticky brand bar
without scrolling the page at that viewport (internal panel scroll is allowed).

## Fixture and honesty rules

Demo, seed, and rehearsal data may appear in the UI **only** when clearly labeled
as fixture / demo / rehearsal (or an equivalent opt-in badge). Rules:

1. **Never** present fixture metrics as live P&L, market performance, soak PASS,
   real fills, or portfolio history.
2. A **default fresh home** stays empty/honest: no invented balances, equity
   curves, sample bots, latency, or health KPIs.
3. Empty and loading states stay short and actionable; they do not pad the
   viewport with sparse equal-weight cards.
4. Opt-in fixture seeds (when shipped) refuse to look like live proof — badges
   and copy must say fixture/demo/rehearsal.
5. Telemetry stays opt-in. Backtest or fixture results are never framed as live
   market performance.

**Opt-in helper:** `krellbot.application.demo_fixture_seed` plus
`GET/POST /api/v1/demo-fixture` (and Workspace Advanced → Demo fixture seed).
Requires explicit confirm to enable; clear restores an empty honest home.
See `tests/test_demo_fixture_seed_honesty.py`.

These honesty rules bind every M18 composition pass and any later density work.

## Per-view first-viewport goals

### Workspace home (`?view=home` — `AppHome`)

**One composition:** brand/product signal + one short path into work + status
honesty — not a tall stack of sparse cards with empty scroll.

| Viewport | Must appear without page scroll | Stays below / collapsed |
| --- | --- | --- |
| 1440×900 | Sticky brand bar; hero (title + purpose); sage CTA into paper workstation; Local preview / Live unavailable honesty; primary destination path (compact, not a card wall) | Advanced: keys onboarding, reconnect QR/token, About; secondary destination detail that does not compete with the hero |
| ~390×844 | Same essential hero + CTA + honesty, stacked; primary path reachable without inventing metrics; ≥44px controls | Same Advanced blocks; long destination lists may continue below |

Tighten progressive disclosure before adding card chrome. No fabricated equity
or sample-bot strip.

### Workstation (`?view=workstation` — paper shell)

**Armed or empty:** a dense operator summary above the fold — status, next
action, and chart **or** an honest empty — without fabricating series when no
journal / run data exists.

| Viewport | Must appear without page scroll | Stays below / collapsed |
| --- | --- | --- |
| 1440×900 | Mode/status strip context; paper status (armed/idle/unavailable); next action (arm / pause entries / resume / disarm as real); chart or honest empty; compact alerts if present | Advanced portfolio/history; long last-runs tables (internal scroll OK); armed-record detail after selection |
| ~390×844 | Status + next action + honest empty/chart stack; ≥44px stop/pause targets | Inspector/selection detail below or in contextual rail; Advanced history |

Never invent candle series, fills, or equity when the journal is empty.

### Operations (`?view=operations`)

**Useful density:** alerts and fleet/control summary show useful rows above the
fold; empty states are short and actionable. **No Learn nav.**

| Viewport | Must appear without page scroll | Stays below / collapsed |
| --- | --- | --- |
| 1440×900 | Operations title + freshness; live status honesty; kill-switch panel; alerts list head (or short empty); fleet/deployments summary head when present | Advanced: scheduler, notifications, live authorization, journal browse, deployment history detail |
| ~390×844 | Title, status, kill switch, first alert/empty; stacked panels; ≥44px controls | Same Advanced blocks; long alert lists continue below with internal scroll preferred |

### Packs (`?view=packs`)

**Browse density:** catalogue / library rows useful above the fold; empty states
short and actionable. **No Learn nav.**

| Viewport | Must appear without page scroll | Stays below / collapsed |
| --- | --- | --- |
| 1440×900 | Packs view chrome; refresh/filters; at least the list head or a short empty/install prompt; first useful row(s) when data exists | Deep pack detail after selection; long catalogue tails (internal scroll OK) |
| ~390×844 | Toolbar + first row or empty prompt, stacked; ≥44px install/refresh targets | Same detail below |

## Verification

Composition PRs name a unit/visual assertion for the view at **1440×900** (and
narrow where claimed). Prefer behavior-named tests. Journey/e2e density pins
follow M7.6 patterns without inventing live performance fixtures.

Chromium geometry smoke (M18.6): `frontend/e2e/density-first-viewport-smoke.spec.ts`
pins Workspace home + Workstation first-viewport density at **1440×900** via
`getBoundingClientRect` (same class as M7.6 starter-home layout smoke).

## Out of scope

- Inventing a Learn view (see `docs/milestones/PARKING.md`).
- Fabricating live fills, portfolio history, or soak PASS from fixtures.
- Purple/glow redesigns that violate `KRELL-SIGNAL-20261010`.
- Risk-path engine work; flipping `PAPER_ONLY_RELEASE`.
