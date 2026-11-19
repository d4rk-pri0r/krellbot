# Character asset provenance — Signal / Krell first-run wizard (M26)

Design contract: `KRELL-SIGNAL-20261010` (owner-approved). These files are
selected supplied character assets copied **byte-identical** from the live
marketing site (and the same bytes served from `krellbot-cloud` `site/assets/`
for legacy PNGs). Do not regenerate, recolor, repaint, mirror, or invent
poses. Wizard UI wiring is a later milestone; this directory only stages art.

Staged 2026-11-19 from https://www.krellbot.dev (content-type verified).

## Signal character (primary)

Source paths under `/assets/signal/…` on krellbot.dev:

| File | Source URL | Role | SHA256 |
| --- | --- | --- | --- |
| `krell-hero.webp` | `/assets/signal/character/krell-hero.webp` | Full hero pose | `2b1f2c9b1538c4fb94af4d6b1e2c023e5c63cf827a2e36b643e99f8bf624a69c` |
| `krell-hero-768.webp` | `/assets/signal/character/krell-hero-768.webp` | Hero at ~768px | `bba678ffa7ba8f3a0ef890117a653d9f380ed621fea68ec063b4430b57c46c91` |
| `krell-guide.webp` | `/assets/signal/character/krell-guide.webp` | Guide / walking-through pose | `29a083dce2009d9743ca72be5cff527f0d32848d7997ad2d0d2c2275373aec90` |
| `krell-guide-768.webp` | `/assets/signal/character/krell-guide-768.webp` | Guide at ~768px | `aea48ace3571346c5cc1a0180a245c002d5373ea210e7c971f501927764645b7` |
| `emote-thinking-112.png` | `/assets/signal/emotes/emote-thinking-112.png` | Thinking emote (micro-accent) | `49afbe8e2a09021f1ac0447e5289a11630b31f29a317996bba1b230f97750459` |

## Legacy Krell PNGs (step variety)

Source paths under `/assets/…` on krellbot.dev (also committed under
`d4rk-pri0r/krellbot-cloud` `site/assets/`):

| File | Source URL | Approx. use | SHA256 |
| --- | --- | --- | --- |
| `krell_chibi.png` | `/assets/krell_chibi.png` | Friendly small full-body | `d4688ba56f185a83aae5dfcdef2130c40cb4ae3293e152180903d8846d99ae61` |
| `krell_portrait.png` | `/assets/krell_portrait.png` | Close portrait | `d4bc48383e64d864f1c8ebc962b217a43102e91c16aece146347d1145fafed9a` |
| `krell_waistup.png` | `/assets/krell_waistup.png` | Waist-up | `b2dd34a07b01914f0adda86ba189f50c265d029f574c3a0d3c75fc60531eef08` |
| `krell_security.png` | `/assets/krell_security.png` | Security / trust pose | `c7fe548ba2047fd6c719817446267991a78af07dbe3d573dc5509e0743a78922` |

## Proposed wizard step mapping (M26.3+)

Reuse only; agents do not invent new art. Prefer Signal webp when the mood
fits; legacy PNGs fill missing step moods until the owner supplies more
Signal poses.

| Step | Screen | Visual |
| --- | --- | --- |
| 1 | Welcome | `krell-hero.webp` (or `krell_portrait.png`) |
| 2 | Choose | `krell-guide.webp` |
| 3 | Start paper | `krell_waistup.png` or `krell-guide.webp` |
| 4 | Status | `krell_chibi.png` or `emote-thinking-112.png` as micro-accent |
| 5 | Win | `krell-hero.webp` celebrate framing / `krell_security.png` calm confidence |

`-768` variants are optional smaller bundles for denser viewports; full-size
webp remain the authoritative hero/guide copies of record.

## Gap (owner art, not agent invention)

Public Signal character poses today are essentially **hero + guide + one
thinking emote**. Five polished steps want five distinct moods. Mapped reuse
of hero / guide / legacy PNGs ships M26; additional Signal poses are an
owner follow-up into the reference kit / `krellbot-cloud`.

Only these selected assets were staged; the full marketing library is not
shipped in the product bundle. No runtime CDN fetch.
