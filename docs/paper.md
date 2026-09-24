# Paper trading

Paper mode lets a pack run end-to-end against a local fill simulator — no
exchange API call, no live money, no license required. The engine and the
pack see the same prices and the same stop behavior as a real venue would,
just inside `$KRELLBOT_HOME/run/paper-<venue>.json`.

## Arm a pack in paper mode

```
krellbot arm tests/fixtures/packs/sma_cross.json \
    --venue kraken \
    --mode paper \
    --paper-balance 1000
```

The arm step records the pack path, the sha256 of its bytes, the venue,
the pair, the cap from the pack's `risk.max_account_pct`, and the starting
cash. It refuses if the cap cannot meet the pair minimum. It never places
an order.

A second pack on the same venue+pair is refused — only one armed pack
per (venue, pair).

## Run a tick

```
krellbot tick --venue kraken \
    --offline-candles tests/fixtures/candles/kraken_SUIUSD_1h_sample.csv
```

The tick engine:

1. Acquires `<home>/run/<venue>.lock`. If another tick is already running,
   prints `another tick running` and exits 0.
2. Loads the license cache and the armed-pack config.
3. Snapshots the paper venue.
4. For each armed pack on that venue: if the pack owns base on the pair
   and no stop is resting on the pair, place a stop. If placing the stop
   fails, market-exit the owned qty in the same tick.
5. Acts on the latest closed bar. Missed bars are coalesced by replaying
   every candle into `evaluate.run`, so indicator state includes them.
6. Entry when `Target.long`, owned qty is 0, entries are allowed, and the
   sized qty meets `ordermin` and `costmin`.
7. Exit only when the evaluator says `exit` and the pack owns qty. A flat or warmup bar does not sell.
8. While long and already in, calls `raise_stop` only if the new stop is
   strictly above the resting stop.
9. Journals one `kind=tick` record per pack per bar.
10. If entries are blocked by the license gate, prints
    `License lapsed or unreachable: entries off, exits on`.

## Costs

| Venue    | Taker fee | Slippage |
| -------- | --------- | -------- |
| Kraken   | 40 bps    | 5 bps    |
| Coinbase | 120 bps   | 5 bps    |

A market entry fills at `last_close * (1 + buy_slip)`. A market exit fills
at `last_close * (1 - sell_slip)`. A stop fill lands at
`min(stop, open) * (1 - sell_slip)` before any signal fill on the same
bar.

## State file

The paper venue's state lives at
`$KRELLBOT_HOME/run/paper-<venue>.json` and is written via
`paths.atomic_write`. A crash mid-write leaves the previous file intact
and never leaves a stray `.tmp` sibling.

```
{
  "venue": "kraken",
  "balances": {"USD": "...", "SUI": "..."},
  "open_orders": [
    {"coid": "...", "pair": "SUIUSD", "side": "sell",
     "qty": "...", "stop_price": "..."}
  ],
  "recent_fills": [
    {"coid": "...", "pair": "SUIUSD", "side": "buy",
     "qty": "...", "price": "...", "ts_ms": 0}
  ]
}
```

## Kraken validate-only

When a Kraken key is stored in the OS keychain AND a validate transport
is injected, the paper venue additionally POSTs `AddOrder` with
`validate=true` and the same fields as the real call. That POST never
records a fill. With no key stored, or no transport injected, zero
validate calls happen.

## Inspect

```
krellbot status [--venue kraken]
krellbot journal --tail 10
```

`status` prints one row per armed pack:
`pack_id pack_version venue pair cap stop mode requires_license`.

`journal` prints the most recent N journal records (newest last). Each
record has the canonical keys: `ts`, `kind`, `venue`, `pack`, `bar_ts`,
`detail`.

## Disarm

```
krellbot disarm --venue kraken --pair SUIUSD
```

Disarm removes the armed record. The paper state file is left on disk
until you delete it manually.

## Raise the stop

```
krellbot stop --venue kraken --pair SUIUSD --price 12.50
```

Raises the resting stop on the armed pack. The new stop must be strictly
above the current stop — the engine never lowers a stop.

## What this phase does NOT do

- Does not place a real order. Paper only.
- Does not require a license for fixture or community packs.
- Does not place a validate POST when no key is stored or no transport
  is injected.
- Does not lower a stop.
- Does not sell more base than this pack's journal says it filled.