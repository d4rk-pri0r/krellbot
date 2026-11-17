# Trading-mode packs

Built-in trading modes (DCA, grid, rebalance) are **ordinary schema_version 1
DSL packs** plus a small optional `mode` object. They reuse validate-before-arm,
Research pins, receipts, and paper — not a parallel engine. Modes do not invent
live market performance; Research/fixture results stay labelled as backtest or
pinned data.

See also: [Pack format](pack-format.md).

## Reserved mode ids

| Mode       | Pack `id`         | `mode.kind`  | Default label   |
|------------|-------------------|--------------|-----------------|
| DCA        | `mode-dca`        | `dca`        | DCA             |
| Grid       | `mode-grid`       | `grid`       | Grid            |
| Rebalance  | `mode-rebalance`  | `rebalance`  | Rebalance       |

A pack that uses one of these ids **must** include a matching `mode` object.
Ordinary user packs must not claim these ids.

## Required DSL fields (every mode)

Same as any schema_version 1 pack: `schema_version`, `id`, `version`, `label`,
`author`, `timeframe`, `indicators`, `entry`, `exit`, `risk`, `markets`.

- `origin` is **required** for mode packs (built-in provenance string).
- Long-only DSL constraints stay in force (no short / leverage / futures).
- Interval and bar cadence use `timeframe` (`1h` / `4h` / `1d`). There is no
  hidden CLI scheduler product for modes.
- Slice / position sizing uses `risk.max_account_pct` (and the pack stop).

## Optional `mode` metadata (additive)

`mode` is optional on ordinary packs. When present, schema_version stays `1`
and packs without `mode` remain valid.

### DCA (`kind: "dca"`)

No extra `mode` keys. Interval = `timeframe`. Per-buy sizing =
`risk.max_account_pct`. Entry/exit conditions in the DSL decide when a slice
is eligible; evaluation is still last-bar long/flat.

```json
"mode": { "kind": "dca" }
```

### Grid (`kind: "grid"`)

Requires `mode.levels` (integer 2–50): how many long-only grid steps the pack
describes. Band edges and triggers stay in `indicators` + `entry` / `exit`
(typically `highest` / `lowest` or SMAs). This is **not** a full exchange grid
bot: no short legs, no venue-native grid API, no hidden multi-order ladder
outside the long-only DSL decision.

```json
"mode": { "kind": "grid", "levels": 5 }
```

Built-in pack: `src/krellbot/packs/modes/mode-grid.json` (package resource
`krellbot.packs.modes`). It is an ordinary schema_version 1 pack: last-bar
long/flat with `highest` / `lowest` band edges, `mode.levels` as declarative
metadata, and `risk.max_account_pct` for sizing. Honest limits versus a full
exchange grid bot stay as above — long-only DSL until shorting is independently
qualified; `levels` does not invent resting ladder orders on the venue.

### Rebalance (`kind: "rebalance"`)

Requires:

- `mode.targets`: 1–8 `{ "symbol": "...", "weight_pct": N }` rows
- `mode.threshold_pct`: drift band (exclusive of 0, ≤ 100)

Target weights must sum to 100 (±0.01). Thresholds and targets are pack fields
the engine can evaluate; strategy-owned versus external inventory separation is
unchanged. Entry/exit still express when a rebalance decision is eligible.

```json
"mode": {
  "kind": "rebalance",
  "threshold_pct": 5,
  "targets": [
    { "symbol": "BTC", "weight_pct": 60 },
    { "symbol": "USD", "weight_pct": 40 }
  ]
}
```

## Validation

`krellbot.pack.lint.check` validates structure (including `mode` when present).
Mode contract rules (id ↔ kind, required `origin`, rebalance weight sum, and
reserved-id without `mode`) live in `krellbot.pack.modes` and run as part of
lint. A mode pack missing required fields is refused.

## Honesty

- Mode packs are presets / teaching shapes, not performance claims.
- Grid is long-only DSL until shorting is independently qualified.
- The built-in grid pack is **not** a full exchange grid bot (no short /
  leverage / futures grids, no venue-native grid API, no hidden multi-order
  ladder beyond the long-only DSL decision).
- Do not present mode Research or fixture metrics as live market performance.
