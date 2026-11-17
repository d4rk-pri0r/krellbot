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

Navigation destinations (`?view=`) stay stable. Capabilities relocated only via progressive disclosure within a view.

| Capability | Destination | Disclosure |
| --- | --- | --- |
| Workspace orientation / next step | `home` | Essential hero + primary path |
| Paper arm / pause entries / resume / disarm / raise stop | `workstation` | Essential status + primary arm/controls |
| Synthetic paper rehearsal | `workstation` (inside Paper status) | Primary (paper/test-run controls) |
| Armed fleet list + unresolved orders | `workstation` and `operations` | Essential |
| Last paper runs + fills detail | `workstation` | Primary list; row expands detail |
| Portfolio / equity history | `workstation` | Advanced |
| Armed paper run records | `workstation` | Advanced (detail list; fleet is primary) |
| Paper alerts (compact) | `workstation` | Essential |
| Selection inspector | `workstation` aside | Contextual |
| Strategy author / validate / library | `strategies` | Primary editor; Library toggle |
| Pack library (installed) | `strategies` Packs toggle | Contextual toggle |
| Catalogue browse / install | `packs` | Primary |
| Research / backtest / evidence | `research` | Primary |
| Strategy graph / authoring | `studio` | Primary canvas; authoring when pack loaded |
| Kill switch / live status / deployments pause-resume | `operations` | Essential |
| Alerts acknowledge | `operations` | Essential |
| Scheduler install/enable | `operations` | Advanced (open by default; collapsible) |
| Opt-in notifications | `operations` | Advanced |
| Live authorization grant/revoke | `operations` | Advanced (open by default; honest paper-only refusal) |
| Journal browse | `operations` | Advanced |
| Deployment history | `operations` | Advanced |
| Live preflight | `deployments` | Primary (paper-only honesty) |
| Exchange keys onboarding | `home` aside | Advanced (session setup) |
| Reconnect QR / token | `home` aside | Advanced |
| About / version / signing channel | `home` aside | Advanced |
| Jobs drawer / command palette | Shell chrome | Always reachable |

## Verification expectations

Frontend typecheck, unit tests, build, and journey/e2e paths that touch disclosure persistence or primary workflows must stay green. Prefer behavior-named regression tests for mount-while-collapsed and force-open validation.
