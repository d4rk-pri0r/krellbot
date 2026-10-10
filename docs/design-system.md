# Krellbot design system — Signal

**Contract: `KRELL-SIGNAL-20261010` (owner-approved).** This is the portable
design contract for all Krellbot product UI work in this repository. It
supersedes the old neon-lime/cyan token rules. Every new or newly scoped UI
task must name `KRELL-SIGNAL-20261010` and follow this document.

## Where the tokens live

`frontend/src/styles/tokens.css` is the single source of the approved palette.

| Token | Value | Use |
| --- | --- | --- |
| `--navy` | `#0E1C29` | page canvas |
| `--surface` | `#14222E` | resting panels |
| `--panel` | `#18354A` | raised/emphasis panels, controls |
| `--line` | `#22465D` | restrained borders and dividers |
| `--text` | `#E9F0F5` | primary text |
| `--muted` | `#ABC4D8` | secondary text |
| `--seafoam` | `#A8D8D1` | selection, focus ring, links, "on" state |
| `--sage` | `#B3DDA8` | affirmative primary action only |
| `--coral` | `#CC9689` | caution/attention base — never success |

Semantic roles (`--accent`, `--focus-ring`, `--action-primary-bg`,
`--caution-*`, `--danger-*`, `--font-ui`, `--font-mono`, radii) are derived
from those nine tokens. Prefer semantic roles in component CSS.

### Compatibility aliases

`--canvas`, `--signal`, `--warn`, `--ink` still exist for older consumers:

- `--canvas` → `--navy`, `--ink` → `--text`, `--signal` → `--seafoam`.
- `--warn` means **caution** in its consumers (operations refusals, critical
  alert rows). It maps to `--caution-text`, deliberately **not** to
  `--sage`. Never recolor a caution/error consumer green.

## Typography

- **Manrope** (SIL OFL 1.1) is the primary UI/body/heading font.
- **IBM Plex Mono** (SIL OFL 1.1) is for restrained technical/numeric labels
  (ids, revisions, timestamps, the command input). The UI is not a terminal
  wall of monospace.
- Both are bundled locally from `frontend/src/assets/fonts/` via
  `frontend/src/styles/fonts.css` (license notices ship beside the binaries).
  No CDN, no runtime font fetch, no CSP change.

## Color semantics

- **Sage** is the affirmative primary action (the one "go" button per view).
- **Seafoam** supports selection, focus, links, and active navigation.
- **Caution** (coral-derived `--caution-*`) and **danger** (`--danger-*`)
  stay unmistakable and distinct from both. Live activation, refusal and
  kill-switch surfaces must never render as success-colored.

## Shell composition

The local application shell is **compact, horizontal and product-led**
(`frontend/src/shell/WorkstationShell.tsx` + `frontend/src/styles/shell.css`):

1. Brand bar: the supplied outlined wordmark, then status context
   (mode + truthful availability), Jobs, and the command palette affordance.
2. View navigation directly beneath it, with the active view underlined in
   seafoam.
3. Real content panels below: readable `--surface` panels with `--line`
   borders and a consistent radius.

Rules:

- **No big mascot marketing hero in the cockpit.** Krell character artwork is
  for onboarding, help and purposeful empty states — never covering controls
  or data.
- Panels stay operational: explicit empty/loading/unavailable/error states
  bound to real data. Never invent balances, positions, returns, latency,
  health or license status.
- Dense tables and canvases scroll internally instead of widening the page.
- Narrow layouts (≤640px) keep all controls reachable with ≥44px targets.

## Controls

- Buttons: `--panel`-tinted background, `--line` border, 7px radius, ≥34px
  height (≥44px on touch). `aria-pressed`/active states use seafoam.
- Inputs/selects/textareas: `--navy` field on `--surface` panel, `--line`
  border, same radius. Textareas (rule JSON) use the mono font.
- Focus: 2px seafoam `--focus-ring` outline with 2px offset, everywhere,
  keyboard-visible only.

## Brand assets

Selected supplied vector assets live in `frontend/src/assets/brand/` with
hashes and provenance in `PROVENANCE.md` there. The mounted consumer is
`frontend/src/components/brand/` (`Wordmark`, `BrandMark`), which renders the
supplied vector paths unchanged. Do not regenerate, repaint, mirror, or
substitute the artwork; do not ship the whole reference library.

## Fonts licensing

Manrope and IBM Plex Mono are released under the SIL Open Font License 1.1;
the notices (`manrope-OFL.txt`, `ibmplexmono-OFL.txt`) are committed next to
the font binaries in `frontend/src/assets/fonts/`.
