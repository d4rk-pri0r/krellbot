# Brand asset provenance — Signal / Krell Asset Pack v2

Design contract: `KRELL-SIGNAL-20261010` (owner-approved). These files are
selected supplied vector assets copied byte-identical from the approved
reference kit. Do not regenerate, repaint, mirror, or substitute them.

Copied from the reference kit's `signal-krell-pack-v2/assets/04-brand/`
directory (reference staging location outside this repository):

| File | Role | SHA256 |
| --- | --- | --- |
| `krellbot-wordmark-light.svg` | Outlined wordmark used in the app shell header | `e0362c677e59d3d0bcb1d67dcd43129dba5b3114472cacc3c0628c8ea9091703` |
| `krellbot-mark-mint.svg` | Compact outlined mark | `7e8a498e60c7c133e2d3cfcaccabe16e9ec103572c000232beeb13a881c16df1` |
| `krellbot-emblem.svg` | Mark + wordmark emblem (not mounted in the cockpit) | `6f584093db421b56d1854be655563901447a8574fbfa6fbdcf74c12366e7d73f` |

The runtime consumer is `frontend/src/components/brand/Wordmark.tsx`, which
renders the wordmark's exact vector paths inline so the artwork is unchanged
and no extra network request is needed. The `.svg` files above are the
authoritative copies of record.

Only these selected assets were staged; the full reference library is not
shipped in the product bundle.
