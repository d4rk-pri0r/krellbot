# Live trading

## This release is paper-only

This release refuses every live order send regardless of environment,
stored keys, authorization files, or live state armed before an upgrade.
`KRELLBOT_ENABLE_LIVE=1` and a valid `live-authorization.json` do not change
that: the gate refuses with `live_disabled_paper_only_release` before it
reads either. Real-venue entry, exit, cancel, and stop-edit methods fail
closed the same way. Paper trading and every read-only operation (status,
snapshots, key permission checks) keep working.

This is temporary, not a permanent removal. Live trading returns only
through an owner-approved code/release change that sets
`PAPER_ONLY_RELEASE = False` in `src/krellbot/release_policy.py`; there is
no environment variable, config file, or UI switch for it.

The rest of this document describes the dormant live implementation.

Live mode runs a pack against the real venue. The local engine still owns
the lifecycle — licensing, locking, journaling, and stop placement — but
orders hit the exchange. Live mode is off by default. Successful live arm
is the workstation path: grant authorization (typed `LIVE` in the UI), then
`live.arm`. The CLI does not prompt `Type LIVE to arm:` on stdin.

## Qualified live venues (distribution)

The distribution product path qualifies **two** live venues behind the same
gates and paper-only rail:

| Venue id   | Wave pair spelling | Notes |
|------------|--------------------|-------|
| `kraken`   | e.g. `XXBTZUSD`    | First live venue |
| `coinbase` | `BTC-USD`          | Second distribution venue (Coinbase Advanced) |

`binance` is paper-only breadth (M14). Do not claim qualified Binance live.
Live preflight and Ops live authorization offer only the two qualified ids.
Store a trade-only key with `krellbot keys add <venue> --file <key-file>`
(or the workstation Keys panel) for the venue you grant.

## Arm gate

```
# Prefer the workstation: grant LIVE authorization, then live.arm.
# CLI arm --mode live refuses without that path (no Type LIVE stdin prompt).
KRELLBOT_ENABLE_LIVE=1 krellbot arm tests/fixtures/packs/sma_cross.json \
    --venue kraken \
    --mode live
# Second venue (exact Coinbase product id):
#   --venue coinbase   # pack market pair BTC-USD
```

Live arm refuses when:

* `PAPER_ONLY_RELEASE` is active (this release): honest paper-only refusal.
* `KRELLBOT_ENABLE_LIVE` is not `1`.
* No operator live grant names the exact venue+pair (workstation grant).
* No key is stored for the venue. Store one first with
  `krellbot keys add kraken --file <key-file>` or
  `krellbot keys add coinbase --file <key-file>`.
* `check_key` reports `can_withdraw=True`. Krellbot only accepts
  trade-only keys.
* `check_key` reports `can_trade=False`.
* The pack has no `risk.stop` or `risk.max_account_pct` ≤ 0.
* The caller is the CLI without the web `skip_confirm` seam — CLI prints
  an honest “use the workstation grant” message instead of prompting.

## Tick

A live tick sends only when `KRELLBOT_ENABLE_LIVE=1`, an operator grant
covers the venue+pair, and the stored key is trade-only. Typed `LIVE` is
collected at grant time in the workstation, not again on every tick or on
CLI arm. A withdraw-capable key is refused with that reason. It is not
reported as the env gate. Paper ticks stay on this machine. If a Kraken key
is stored, a paper entry also posts `validate=true` and does not record that
post as a fill.

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
  with `KRELLBOT_ENABLE_LIVE=1` unless you really mean to. Live arm
  confirmation is the workstation grant, not a CLI stdin prompt.
* Does not call `CancelAllOrdersAfter`. The source is grepped for the
  string and the guardrail test enforces that.
* Does not lower a stop. `raise_stop` only replaces the resting stop if
  the new stop is strictly above it.
* Does not sell more base than the pack's journal says it filled.
* Does not put a real secret, key, or order body in the journal,
  fixtures, or exception text. Sanitize with `***`.