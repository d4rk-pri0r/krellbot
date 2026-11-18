# Telemetry

Telemetry is **default off** until the operator opts in. `krellbot telemetry enable` prints one example payload and waits for `y`. Anything other than `y` leaves it off.

The workstation Packs checkout UI also exposes an explicit opt-in control
that writes the same `$KRELLBOT_HOME/telemetry.json` flag via
`PUT /api/v1/telemetry`. Until that flag is true, nothing leaves the
machine.

```
krellbot telemetry enable
krellbot telemetry disable
```

`enable` and `disable` write the flag and print the new state. Neither
command sends a payload by itself. The Packs consent toggle behaves the
same way: consent is recorded; no event is posted by the toggle alone.

## What the fill payload carries

A fill telemetry record carries only these keys:

| Key | Meaning |
| --- | --- |
| `install_id` | A random per-install UUID. Not a key, not a license. |
| `pack_id` | The slug of the armed pack. |
| `pack_version` | The version recorded at arm time. |
| `venue` | The exchange the pack is armed on. |
| `pair` | The market the pack trades. |
| `side` | `buy` or `sell`. |
| `bar_ts` | The candle close time the engine acted on. |
| `modeled_px` | The price the pack's signal produced. |
| `fill_px` | The fill price the simulator or venue reported. |
| `qty_bucket` | The floor of log2 of the USD notional. Not the raw quantity. |
| `fee_bps` | The venue's fee in basis points. |

## Checkout funnel events (opt-in)

When telemetry is enabled, the workstation may also post closed funnel
events for the paid catalogue path:

| `event` | When |
| --- | --- |
| `view` | Signed catalogue successfully loaded |
| `checkout_start` | Checkout started for a catalogue SKU |
| `checkout_success` | Checkout paid / entitlement granted |
| `checkout_fail` | Checkout refused, failed, or unreachable |
| `install` | Catalogue pack installed into the local library |
| `arm` | Pack armed (paper or live) |

A funnel record carries only:

| Key | Meaning |
| --- | --- |
| `install_id` | Same per-install UUID as fill telemetry |
| `kind` | Always `funnel` |
| `event` | One of the events above |
| `sku` | Catalogue SKU / pack id stem (never a path or source blob) |

## What payloads do NOT carry

Neither fill nor funnel records send:

- a balance,
- an API key or secret,
- a license value,
- a session id or claim-cache token,
- an IP address,
- the raw quantity,
- strategy source or pack bytes.

The payload travels over HTTPS to `https://krellbot.dev/api/telemetry`.
The operator can inspect the recorded shape any time with
`krellbot telemetry show`.
