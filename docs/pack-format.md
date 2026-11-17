# Pack format

A pack is a JSON file. One file, one pack. Put it in `~/.krellbot/packs/`.

The client reads the file. It does not execute code from it. A pack is not an order.

There are two formats. Legacy packs (`id` + `public_label` only) still list but
do not run. New packs include `schema_version: 1` and follow the DSL below.

## DSL packs

Required keys: `schema_version`, `id`, `version`, `label`, `author`, `timeframe`,
`indicators`, `entry`, `exit`, `risk`, `markets`. Optional: `origin`, `mode`.

- `schema_version` is `1`.
- `id` is lowercase letters, digits, and dashes; 1 to 32 characters.
- `version` is `MAJOR.MINOR.PATCH`.
- `timeframe` is `1h`, `4h`, or `1d`.
- `label`, `author`, `origin` are at most 120 characters each.
- `mode` is optional trading-mode metadata (`dca` / `grid` / `rebalance`). Packs
  without `mode` stay valid. Built-in mode ids, labels, and validation rules are
  documented in [Trading-mode packs](trading-modes.md).
- `indicators` is a map of names to whitelist functions: `sma`, `ema`, `wma`,
  `vwma`, `stdev`, `roc`, `efficiency_ratio`, `hma`, `power_mean`, `atr`,
  `highest`, `lowest`, `roofing_filter`. Each has its own `len` (2 to 600).
- `entry` and `exit` are conditions. A leaf is `[left, op, right]` where `op`
  is one of `>`, `<`, `>=`, `<=`, `crosses_above`, `crosses_below`. Conditions
  nest with `{all: [...]}` or `{any: [...]}` up to depth 3.
- `risk.max_account_pct` is an integer 1 to 100. `risk.stop` is either
  `{type: pct, pct: number}` or `{type: atr, len: int, mult: number}`.
- `markets` is 1 to 4 items of `{venue: kraken|coinbase|binance, pair: ...}`.

### Markets venue allow-list

Pack `markets[].venue` is a closed allow-list. Undocumented venue ids must be
rejected by pack validate (`krellbot.pack.lint.check` / the pack JSON Schema
enum). Do not admit a new id in the schema without updating this section.

| Venue id   | Spot class        | Pair spelling (canonical) | Example wave pair |
|------------|-------------------|---------------------------|-------------------|
| `kraken`   | Kraken spot       | Venue asset-pair alt/name | `SUIUSD`, `XXBTZUSD` |
| `coinbase` | Coinbase Advanced | `BASE-QUOTE` product id   | `BTC-USD` |
| `binance`  | Binance-class spot| Concatenated `BASEQUOTE` (no hyphen); uppercase alphanumerics | `BTCUSDT` |

`binance` is the first Binance-class spot venue id. Pack pairs for Binance use
the exchange symbol spelling (e.g. `BTCUSDT`), not `BTC-USDT` or `BTC/USDT`.
The shared pair pattern still allows an optional `-QUOTE` form used by
Coinbase; Binance packs must use the no-hyphen form above.

### Venue protocol (paper-capable adapter)

A paper-capable spot adapter for an allow-listed venue id implements the
`Venue` protocol in `src/krellbot/venues/base.py` behind an injectable
Transport (fakes in CI; no live credentials in tests). Methods a
paper+preflight path relies on:

- `rules(pair) -> PairRules`
- `snapshot() -> Truth` (balances, open orders, recent fills)
- `place_entry_with_stop(coid, qty, stop, *, pair) -> OrderRef`
- `place_exit(coid, qty, *, pair) -> OrderRef`
- `cancel_stops(pair)`
- `raise_stop(pair, new_stop)`
- `order_by_coid(coid) -> OpenOrder | None`
- `check_key() -> KeyPerms`

Adapters live under `src/krellbot/venues/` (`kraken.py`, `coinbase.py`,
`binance.py`). Qualified live remains owner-gated; agents keep
`PAPER_ONLY_RELEASE` True.

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

## In-app guided authoring

The Strategies editor guided form authors a supported subset of this DSL
without hand-writing JSON: `sma` / `ema` / `wma` / `vwma` / `stdev` / `roc` /
`efficiency_ratio` / `hma` indicators, close-versus-one or fast/slow crossover
recipes, optional single-level `{all|any}` nesting with a close-vs-threshold
confirm leaf, percentage or ATR protective stops, and one or two
`kraken` / `coinbase` / `binance` markets (paper config). Packs outside that
subset stay editable as JSON. Save still validates the revision before Arm is
enabled. Guided authoring may still default starters to Kraken.

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

## Community pack submissions

To publish an unpaid community pack (not a signed catalogue SKU), follow the
authoring checklist in [community.md](community.md#authoring-checklist):
schema_version 1 DSL with required `author` / `origin`, size limits, index
entry shape, and the allow-listed `raw.githubusercontent.com` URL prefix for
`d4rk-pri0r/krellbot-community-packs`.
