# Pack format

A pack is a JSON file. One file, one pack. Put it in `~/.krellbot/packs/`.

The client reads the file. It does not execute code from it. A pack is not an order.

There are two formats. Legacy packs (`id` + `public_label` only) still list but
do not run. New packs include `schema_version: 1` and follow the DSL below.

## DSL packs

Required keys: `schema_version`, `id`, `version`, `label`, `author`, `timeframe`,
`indicators`, `entry`, `exit`, `risk`, `markets`. Optional: `origin`.

- `schema_version` is `1`.
- `id` is lowercase letters, digits, and dashes; 1 to 32 characters.
- `version` is `MAJOR.MINOR.PATCH`.
- `timeframe` is `1h`, `4h`, or `1d`.
- `label`, `author`, `origin` are at most 120 characters each.
- `indicators` is a map of names to whitelist functions: `sma`, `ema`, `wma`,
  `vwma`, `stdev`, `roc`, `efficiency_ratio`, `hma`, `power_mean`, `atr`,
  `highest`, `lowest`, `roofing_filter`. Each has its own `len` (2 to 600).
- `entry` and `exit` are conditions. A leaf is `[left, op, right]` where `op`
  is one of `>`, `<`, `>=`, `<=`, `crosses_above`, `crosses_below`. Conditions
  nest with `{all: [...]}` or `{any: [...]}` up to depth 3.
- `risk.max_account_pct` is an integer 1 to 100. `risk.stop` is either
  `{type: pct, pct: number}` or `{type: atr, len: int, mult: number}`.
- `markets` is 1 to 4 items of `{venue: kraken|coinbase, pair: ...}`.

The engine never reads a pack file as code. Indicators and stops are computed
locally. The engine evaluates the last bar only and returns a single decision:
long or flat, plus a stop price.

```json
{
  "schema_version": 1,
  "id": "trend-follow",
  "version": "1.0.0",
  "label": "Trend follow",
  "author": "krellbot",
  "origin": "Written on this machine.",
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
}
```

Save that as `~/.krellbot/packs/trend-follow.json`, then run `krellbot lint
~/.krellbot/packs/trend-follow.json`.

## Legacy packs

A file with `id` + `public_label` and no `schema_version` is a legacy pack.
`krellbot list` prints it with the marker `legacy: not runnable`. The engine
does not evaluate it.

Required:

- `id` — short name, no spaces
- `public_label` — the name `krellbot list` prints

Optional:

- `rule` — one sentence, your words
- `timeframe` — such as `1h`
- `venue_of_history` — the venue the history came from

Do not invent a return. A number without dates is not a result.

```json
{
  "id": "mine",
  "public_label": "Mine",
  "rule": "Replace this sentence with your own rule.",
  "origin": "Written on this machine.",
  "timeframe": "1h"
}
```

The packs we maintain are not in this repository.
