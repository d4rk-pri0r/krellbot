# Character asset provenance — Signal / Krell first-run wizard (M26)

Design contract: `KRELL-SIGNAL-20261010` (owner-approved). Wizard step
art is a transparent cutout of the Astra Signal Krell so it blends on
the navy canvas (`#0e1c29`). No white sticker outline and no opaque
backdrop rectangle.

## Wizard step illustrations

The five files the first-run wizard displays are step-matched scenes.
They were generated from the Astra Signal hero and guide likeness
(navy-to-cyan bob, black glasses, hoodie, KRELLBOT shirt, circuit
tattoo, cybernetic arm), then chroma-keyed to a true transparent
background. `-768` files are width-768 downscales of the welcome and
choose illustrations. `krell_chibi.png` and `emote-thinking-112.png`
are unchanged original staged bytes.

| Step | Screen | File | What the picture shows | SHA256 |
| --- | --- | --- | --- | --- |
| 1 | Welcome | `krell-hero.webp` | Krell waving beside a local laptop whose screen shows a toy bot and play-coins (pretend money, not cash) | `efcbd3730c7d5ad6a4407c7cd11b3b6cdba7aa624eb21ad664a63c9a5d95266b` |
| 1 | Welcome, 768 | `krell-hero-768.webp` | Same welcome scene at width 768 | `b3b6cbb7230b501d62b7a43db1815b636a6938f8989ce478b621cda034f2deed` |
| 2 | Choose | `krell-guide.webp` | Krell presenting three chart cards: a moving-average cross, a mean-reversion band, and a range breakout | `1234024f6b9c83c125ccfa3d8785744c69a3808b835d4bc864aa16ff22302a40` |
| 2 | Choose, 768 | `krell-guide-768.webp` | Same choose scene at width 768 | `c2cfef6ff01df9410ed38e009035639bd93aff9a492dcf855cbe484e397374f8` |
| 3 | Start paper | `krell_waistup.png` | Krell pressing a play switch beside a simulation gauge and play-token coins | `36b2f043bb06e78d2058b3b7ea22e32757f01492f3b8ce596c35137fdcaba7d6` |
| 4 | Status | `krell_portrait.png` | Krell watching a local desktop whose screen shows a seafoam pulse, with a paper shield on the bezel | `1adc6463cbab7ee54f09601f1888cfa042327b06344839d6c833ff67f82e015f` |
| 5 | Win | `krell_security.png` | Krell unveiling a workspace window with a seafoam check and sparkles | `655492353a5c3824755cad567d46e8151b36a0e065d00f858adf787e90ab8998` |

Filename mapping stays stable for `data-wizard-visual` assertions.
Full-size webp are the authoritative welcome and choose copies.

## Unchanged staged originals

These two files were not regenerated. Hashes match the earlier staged
copies.

| File | Role | SHA256 |
| --- | --- | --- |
| `emote-thinking-112.png` | Thinking emote (micro-accent) | `49afbe8e2a09021f1ac0447e5289a11630b31f29a317996bba1b230f97750459` |
| `krell_chibi.png` | Friendly small full-body, not used by the wizard | `d4688ba56f185a83aae5dfcdef2130c40cb4ae3293e152180903d8846d99ae61` |

Only these selected assets ship in the product bundle. No runtime CDN fetch.
