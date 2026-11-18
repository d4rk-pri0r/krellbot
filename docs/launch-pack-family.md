# Launch pack family (Paid 1.0)

Paid 1.0 (M21) launches **one** pack family. Default: the **DCA mode pack
family** (SKU `paid-launch-dca`), the paid catalogue SKU that mirrors the
built-in DCA mode shape (`mode-dca` / `docs/trading-modes.md`).

Owner may pick another family later; agents do not invent a second launch
SKU here. See `docs/milestones/M21.md`.

## Honesty contract

Enforced by `krellbot.packs.launch_family` and pinned by
`tests/test_launch_pack_family_honesty.py`:

1. **No returns promises.** Copy must not guarantee returns, profit, or
   “risk-free” outcomes.
2. **Fixture / backtest labeled.** Research and fixture results stay labeled
   as backtest or pinned fixture — never live market performance.
3. **Not personalized advice.** Packs are tools. Catalogue description and
   pack `origin` must say so.
4. **Signed catalogue entry matches installed bytes.** The family catalogue
   entry declares `pack_sha256` over the canonical pack JSON; installing the
   family writes those exact bytes under `$KRELLBOT_HOME/packs/paid-launch-dca.json`.

## Shipped pack

Package resource: `krellbot.packs.launch/paid-launch-dca.json`

- Ordinary schema_version 1 DSL with the same DCA teaching shape as
  `mode-dca` (interval = `timeframe`; slice = `risk.max_account_pct`;
  wave `XXBTZUSD`)
- Does **not** claim the reserved built-in id / `mode` object (`mode-dca`
  stays the built-in mode pack); the launch SKU is `paid-launch-dca`
- Pack `origin` stays within schema maxLength and carries honesty phrases

## Catalogue metadata

Closed entry shape (additive honesty fields beyond the M5 free/paid wire
cache):

| Field | Meaning |
| --- | --- |
| `id` | `paid-launch-dca` |
| `tier` | `paid` |
| `description` | Honesty paragraph (not advice; fixture/backtest; no returns) |
| `pack_sha256` | Hex sha256 of canonical pack bytes |
| `disclosures.not_personalized_advice` | must be `true` |
| `disclosures.no_returns_promises` | must be `true` |
| `disclosures.fixture_backtest_labeled` | must be `true` |

Fixture used by tests: `tests/fixtures/catalogue/launch_pack_family.json`.

## Packs UI

The signed-catalogue Packs surface shows launch-family honesty copy when the
SKU is present (see `frontend/src/features/packs/launchPackFamily.ts`). This
is not a second product line and not personalized advice. Broader paid
checkout disclosures (fee share / referral, refund window pointer, telemetry
opt-in) live in [paid-disclosures.md](paid-disclosures.md).

## Out of scope

- Multiple launch families / paid ads / personalized advice
- Flipping `PAPER_ONLY_RELEASE`
- Real payment processors in CI (fake transport only; M21.1)
