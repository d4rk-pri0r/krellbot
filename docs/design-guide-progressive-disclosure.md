# Progressive disclosure design guide

**Extends:** Signal contract `KRELL-SIGNAL-20261010` (`docs/design-system.md`).  
**Scope:** Presentation and interaction only. Does not change live gates, arming semantics, credentials, Decimal accounting, or reconcile-never-resubmit.

## Experience goal

“I understand what is happening, I know what to do next, and I can get to more detail when I need it.”

## Disclosure classes

| Class | What belongs here | Default |
| --- | --- | --- |
| **Essential context** | Mode, execution state, errors, freshness, funds/limits, stop/pause controls, selected strategy/account | Always visible |
| **Primary task** | Controls for the current goal on this view | Always visible |
| **Contextual detail** | Inspectors, per-row detail, raise-stop, selection rails | Near the thing they affect |
| **Advanced** | Rehearsal, portfolio history, scheduler, notifications, live authorization forms, journal, reconnect QR, keys setup, About | Collapsed, labeled **Advanced**, discoverable |

Rules:

- Children stay mounted when collapsed so values and validation survive hide/show.
- If a collapsed section has validation/error, force it open and show a caution badge.
- No nested accordion → dialog chains.
- One sage primary action per view; seafoam for selection/focus/nav only.
- Stop/pause labels must match actual behavior (e.g. “Pause entries” does not sell or disarm).

## Composition

- Group tightly; avoid giant empty equal-weight cards.
- Useful graphics only from real data; mascot for empty/onboarding only.
- Honest unavailable/empty/loading/stale states — never invent KPIs or balances.
- Plain copy: no profit promises or “autopilot” hype.

## Shared component

`frontend/src/components/disclosure/DisclosureSection.tsx` implements summary → detail with optional `storageKey` persistence and `forceOpen` for validation.

## Capability → destination map

Navigation destinations (`?view=`) stay stable. Capabilities relocate only via progressive disclosure within a view or via **tiered nav chrome** (primary tabs vs **More** overflow) — never via a Beginner/Power mode toggle or a second app shell. See M24 and the store plan `docs/beginner-default-ux-plan.md` (KRE-187).

First-run is a full-screen wizard gate, not a coach painted on the cockpit. After complete or skip, this guide applies to the mounted shell: Advanced stays collapsed and reachable, and the wizard win screen is the only celebration.

**Nav tiers:** Primary = Workspace (`home`), Run (`workstation` — UI label **Run**), Strategies (`strategies`), Packs (`packs`), Settings (`settings`). More = Research (`research`), Strategy studio (`studio`), Operations (`operations`), Deploy (`deployments`). Pause/disarm stay on Run; Operations kill switch remains ≤2 clicks from an armed paper state (deep link from Run when needed).

| Capability | Destination | Disclosure |
| --- | --- | --- |
| Workspace orientation / next step | `home` | Essential hero + **one** sage CTA into free paper starter (or Open paper run when armed) + quiet setup tour replay |
| Home-mounted starter chooser | `home` (Chooser A) | Primary task; free local starter default; catalogue secondary |
| Paper arm / pause entries / resume / disarm / raise stop | `workstation` (Run) | Essential status + primary arm/controls |
| Synthetic paper rehearsal | `workstation` (inside Paper status) | Primary (paper/test-run controls) |
| Armed fleet list | `workstation` and `operations` | Essential |
| Unresolved orders (ops panel) | `operations` | Advanced (open by default; collapsible); nav via More |
| Last paper runs + fills detail | `workstation` | Primary list; row expands detail |
| Portfolio / equity history | `workstation` | Advanced |
| Armed paper run records | `workstation` | Advanced (open by default; fleet is primary) |
| Forward paper ledger | `workstation` | Advanced |
| Paper alerts (compact) | `workstation` | Essential |
| Selection inspector | `workstation` aside (contextual) | Opens only when a deployment, position, or alert is selected; Run uses full width when idle |
| Strategy author / validate / library | `strategies` | Primary editor; Library toggle; deep JSON Advanced |
| Pack library (installed) | `strategies` Packs toggle | Contextual toggle |
| Catalogue browse / install | `packs` | Primary (“get a strategy”); disclosures under Settings → Trust & billing |
| Research / backtest / evidence | `research` | Full view unchanged; **nav: More** |
| Strategy graph / authoring | `studio` | Full canvas unchanged; **nav: More**; no soft tips after first arm |
| Kill switch / live status / deployments pause-resume | `operations` | Essential on Operations view; **nav: More** (reachable from Run) |
| Alerts acknowledge | `operations` | Essential |
| Scheduler install/enable | `operations` | Advanced (open by default; collapsible) |
| Opt-in notifications | `operations` | Advanced |
| Live authorization grant/revoke | `operations` | Advanced (open by default; honest paper-only refusal) |
| Journal browse | `operations` | Advanced |
| Deployment history | `operations` | Advanced |
| Live preflight | `deployments` | Primary on Deploy view (paper-only honesty); **nav: More** |
| Exchange keys onboarding | `settings` (`section=keys`) | Primary Settings section (optional trade-only keys; local OS keyring) |
| Live-ready wizard / paper-only posture | `settings` (`section=safety`) | Settings section |
| Paid disclosures & exchange referral | `settings` (`section=trust`) | Settings section |
| Opt-in telemetry consent | `settings` (`section=privacy`) | Settings section (off by default) |
| Local session, reconnect QR/token, demo fixture seed | `settings` (`section=computer`) | Settings section (demo fixture collapsed, labeled Fixture) |
| About this build | `settings` (`section=about`) | Settings section |
| Jobs drawer / command palette | Shell chrome | Always reachable; palette leads with Start free paper strategy |

## Verification expectations

Frontend typecheck, unit tests, build, and journey/e2e paths that touch disclosure persistence or primary workflows must stay green. Prefer behavior-named regression tests for mount-while-collapsed and force-open validation.
