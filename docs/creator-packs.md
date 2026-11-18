# Signed creator packs + rev share

Creator packs are **third-party** schema_version 1 DSL packs sold through
the signed catalogue lane with a disclosed revenue share. They extend the
M5 free/paid catalogue and sit beside unpaid community packs (M17). The
client **verifies the signature before install** and never executes pack
JSON as code.

Packs are tools, **not personalized advice**. A signed creator pack must
carry `disclosures.not_personalized_advice: true` or verify refuses it.

See also: [Pack format](pack-format.md), [Community packs](community.md),
[Product direction](product-direction.md) earn rule (3).

## Wire envelope

Same shape as the signed catalogue / license refresh:

```json
{
  "payload": "{\"envelope_version\":\"1\",\"kind\":\"creator_pack\",...}",
  "sig": "<unpadded-base64url-ed25519>"
}
```

- `payload` is **canonical JSON**: UTF-8, sorted keys, separators `,` / `:`,
  no trailing spaces.
- `sig` is the unpadded base64url encoding of a 64-byte ed25519 signature
  over the exact `payload` bytes.
- Verification uses the same public keys under `src/krellbot/keys/` as
  license / catalogue (`krellbot.license.verify_signed`). DEV keys are
  refused when `release=True` or `KRELLBOT_RELEASE=1`.

Tampered or malformed envelopes raise before any write under
`$KRELLBOT_HOME`. Prior local packs are left untouched.

## Inner document (closed contract)

| Field | Required | Meaning |
| --- | --- | --- |
| `envelope_version` | yes | `"1"` |
| `kind` | yes | `"creator_pack"` |
| `pack` | yes | Full schema_version 1 DSL object (lint-clean); see [pack-format.md](pack-format.md#dsl-packs) |
| `creator.id` | yes | Creator slug (`[a-z0-9][a-z0-9_-]{0,63}`) |
| `creator.display_name` | yes | Human label (≤ 120 chars) |
| `creator.contact` | no | Optional contact string (≤ 120 chars) |
| `rev_share.creator_bps` | yes | Integer basis points owed to the creator |
| `rev_share.platform_bps` | yes | Integer basis points owed to the platform |
| `rev_share.currency` | no | Defaults to `"USD"` (≤ 8 chars) |
| `sku.id` | yes | Paid SKU id; **must equal** `pack.id` |
| `sku.tier` | yes | Always `"paid"` for creator rev-share SKUs |
| `sku.price_cents` | yes | Non-negative integer list price in cents |
| `disclosures.not_personalized_advice` | yes | Must be JSON `true` |

`creator_bps + platform_bps` must equal **10000**. Unknown fields are
dropped after verify so a hostile payload cannot widen the contract.

Example (pretty-printed; wire form is canonical / minified):

```json
{
  "envelope_version": "1",
  "kind": "creator_pack",
  "pack": {
    "schema_version": 1,
    "id": "creator-trend",
    "version": "1.0.0",
    "label": "Creator trend",
    "author": "example-creator",
    "origin": "Signed creator pack. Not personalized advice.",
    "timeframe": "1h",
    "indicators": {
      "sma20": {"fn": "sma", "src": "close", "len": 20}
    },
    "entry": ["close", ">", "sma20"],
    "exit": ["close", "<", "sma20"],
    "risk": {
      "max_account_pct": 25,
      "stop": {"type": "pct", "pct": 5}
    },
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}]
  },
  "creator": {
    "id": "example-creator",
    "display_name": "Example Creator"
  },
  "rev_share": {
    "creator_bps": 7000,
    "platform_bps": 3000,
    "currency": "USD"
  },
  "sku": {
    "id": "creator-trend",
    "tier": "paid",
    "price_cents": 1999
  },
  "disclosures": {
    "not_personalized_advice": true
  }
}
```

## Verify-before-install

Application seam: `krellbot.packs.creator_signed`.

1. `verify_before_install(envelope)` — parse `payload`/`sig`, verify
   ed25519, normalize the closed document. **No disk write.**
2. `install_verified_creator_pack(home, envelope)` — same verify, then
   write **only** the inner DSL pack to
   `$KRELLBOT_HOME/packs/creator/<id>.json`. Rev-share metadata is
   returned to the caller for later ledger work; it is not re-serialized
   into the pack file.

Community installs remain the unsigned Labs path
(`packs/community/`). First-party paid catalogue redeem remains
`packs/catalog/` via activation. Creator signed packs do not replace
either lane.

## Rev-share ledger (fake settlements)

After a paid install or redeem of a verified creator pack, record the
owed share locally. Application seam: `krellbot.packs.rev_share_ledger`.

- Storage: `$KRELLBOT_HOME/receipts/creator-rev-share.json` (atomic
  write). No bank tokens, payout API keys, or other payout secrets.
- `record_owed_share(home, document, event_kind=...)` — append one
  `owed` row from a closed creator-pack document (`paid_install` or
  `paid_redeem`). Idempotent on `event_id`. Creator cents are
  `floor(price_cents * creator_bps / 10000)`; platform gets the
  remainder so the split sums to `price_cents`.
- `settle_pending(home, transport=...)` — POST a secret-free batch
  through an injectable settlement transport. Rows flip to `settled`
  only when the transport acks their `entry_id`. Tests use
  `FakeSettlementTransport` (no network).
- `operator_view(home)` / `creator_view(home, creator_id)` — local-honest
  summaries. Views never invent remote settlement state.

## What this is not

- Not personalized or individualized trading advice.
- Not executable pack code; indicators stay on the local DSL whitelist.
- Not a real payout rail or a place for payout secrets.
- Not a substitute for the typed `LIVE` grant when arming live.
