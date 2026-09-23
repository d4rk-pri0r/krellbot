# Backtest

Run a DSL pack against a candle series and emit a receipt. No orders are
sent. No network is touched.

## CLI

```
krellbot backtest <pack.json> --venue kraken|coinbase [--data csv] [--json] \
  [--slippage-mult N] [--fee-bps N] [--slippage-bps N] \
  [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--allow-gaps]
```

`--data` is a CSV with the cache format: header `ts_ms,open,high,low,close,volume`,
then one row per bar. The `from` / `to` flags trim the series by date in UTC.

Defaults when not overridden: Kraken `fee_bps=40`, Coinbase `fee_bps=120`,
`slippage_bps=5`, `slippage_mult=1.0`.

## Receipt

`--json` prints a single JSON object on stdout. Keys exactly:
`engine_version, pack_sha256, data_manifest_sha256, venue, pair, tf, from,
to, fee_bps, slippage_bps, slippage_mult, metrics, equity_curve`. The
`metrics` block carries `total_return_pct, cagr_pct, max_drawdown_pct,
return_to_dd, per_year, trade_count, exposure_pct, buy_and_hold`. The
`equity_curve` is at most 64 numbers; its last point equals
`metrics.total_return_pct` within 0.01.

## Fill rules

* Signal on the close of bar `t` fills at the open of bar `t+1`.
* Stop, while long, exits at `min(stop, open[t+1])` and applies sell
  slippage. The signal fill of the same bar is skipped.
* A flat-price, zero-cost round trip changes equity by exactly 0.
* `cash` stays `>= 0` on every bar; `equity == cash + qty * close`.

## Cache

`krellbot data import kraken-ohlcvt <zip> --pair PAIR --timeframe TF`
streams the zip and writes one CSV plus a JSON manifest under
`$KRELLBOT_HOME/cache/`. The manifest's `sha256` is the hex digest of
the CSV bytes; the backtest records that hash in the receipt.

## Gap policy

Series missing more than 1% of expected bars is refused unless
`--allow-gaps` is passed. The error names the pair and the missing
count.
