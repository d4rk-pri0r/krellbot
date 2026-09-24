# Live trading

Live mode runs a pack against the real venue. The local engine still owns
the lifecycle — licensing, locking, journaling, and stop placement — but
orders hit the exchange. Live mode is off by default and requires a typed
confirmation the first time you arm.

## Arm gate

```
KRELLBOT_ENABLE_LIVE=1 krellbot arm tests/fixtures/packs/sma_cross.json \
    --venue kraken \
    --mode live
```

Live arm refuses when:

* `KRELLBOT_ENABLE_LIVE` is not `1`.
* No key is stored for the venue. Store one first with
  `krellbot keys add kraken --file <key-file>`.
* `check_key` reports `can_withdraw=True`. Krellbot only accepts
  trade-only keys.
* `check_key` reports `can_trade=False`.
* The pack has no `risk.stop` or `risk.max_account_pct` ≤ 0.

The first live arm on an install reads a confirmation prompt. You must
type `LIVE` exactly. A later live arm on the same install does not
prompt. Disarm + re-arm on the same pair goes through arm again with the
saved `live_first_armed=true` flag.

## Tick

A live tick sends only when `KRELLBOT_ENABLE_LIVE=1` and the stored key is trade-only. The typed `LIVE` confirmation is required when you arm, not again on every tick. A withdraw-capable key is refused with that reason. It is not reported as the env gate. Paper ticks stay on this machine. If a Kraken key is stored, a paper entry also posts `validate=true` and does not record that post as a fill.

## Live-only invariants

* The engine never sells more base than this pack's journal says it
  filled. Extra coins the user holds on the venue are not touched.
* A `tick` record is journaled for every pack/bar the engine processes,
  including refusals and entries blocked by a lapsed license.
* The coid is the first 18 hex chars of
  `sha256(f"{pack_id}|{version}|{venue}|{pair}|{bar_ts}|{intent}")`.
  The same coid on retry is a no-op at the venue; the engine does not
  double-order after a crash.
* Money is `decimal.Decimal`. Order size and price are quantized to the
  venue's lot and price decimals with `ROUND_DOWN` before they leave
  the process.

## Per-venue lock

`krellbot tick` acquires `<home>/run/<venue>.lock` (`fcntl` on POSIX,
`msvcrt` on Windows). The lock is non-blocking. If another tick is
running on the same venue, tick prints `another tick running` and exits
0 — no journal entry is written, no order is sent.

## Disarm

```
krellbot disarm --venue kraken --pair SUIUSD
```

Disarm removes the armed record. The venue state is left untouched.

## What this phase does NOT do

* Does not run `krellbot tick --venue kraken` over the public network
  with `KRELLBOT_ENABLE_LIVE=1` unless you really mean to. The first
  live arm types confirmation into stdin; later live arms do not
  prompt.
* Does not call `CancelAllOrdersAfter`. The source is grepped for the
  string and the guardrail test enforces that.
* Does not lower a stop. `raise_stop` only replaces the resting stop if
  the new stop is strictly above it.
* Does not sell more base than the pack's journal says it filled.
* Does not put a real secret, key, or order body in the journal,
  fixtures, or exception text. Sanitize with `***`.