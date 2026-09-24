# Telemetry

Telemetry is off until the operator types `y`. `krellbot telemetry enable` prints one example payload and waits. Anything other than `y` leaves it off.

Until the operator types `y`, nothing leaves the machine. The choice is
recorded in `$KRELLBOT_HOME/telemetry.json`.

```
krellbot telemetry enable
krellbot telemetry disable
```

`enable` and `disable` write the flag and print the new state. Neither
command sends a payload by itself.

## What the payload carries

A telemetry record carries only these keys:

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

## What the payload does NOT carry

The record does not send:

- a balance,
- an API key or secret,
- a license value,
- an IP address,
- the raw quantity.

The payload travels over HTTPS to `https://krellbot.dev/api/telemetry`.
The operator can inspect the recorded shape any time with
`krellbot telemetry show`.
