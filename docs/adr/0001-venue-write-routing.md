# 0001 — Venue write routing

- Status: Accepted 2026-09-29.
- Owners: run, cli, paper, storage.
- Replaces: the prior live-direct / paper-outbox split in `run/__init__.py`
  and the silent `_commit_outbox_rows` ledger under `<home>/run/store.db`.

## Context

Before this change the paper tick routed every `place_*` through the Outbox
(`_paper_dispatch_place`) and the live tick called the venue directly
(`venue_obj.place_entry_with_stop(...)`, `venue_obj.place_exit(...)`,
`venue_obj.place_stop(...)`). Three consequences:

1. **A live send never had a durable intent in the operational store.**
   If the process died between `place_*` and the venue's HTTP 200, the engine
   had no record that an intent was ever committed — the next tick could
   re-place the same client_order_id and the venue would dedup it, or worse,
   silently double-fill if the venue never saw the first send.
2. **The live refusal lived in the CLI, not in the engine.** `cli.venue_for_tick`
   read the env and built a Kraken / Coinbase venue object before checking
   the operator grant. The ledger had no proof that the engine refused before
   any transport call.
3. **`_commit_outbox_rows` wrote a second copy of every fill under
   `<home>/run/store.db`** after the tick ran, swallowing `StoreBusy` and
   `StoreCorrupt` so the journal path would not regress. Two stores, two
   truth sources, and one of them swallowed faults as plain `RuntimeError`.

Findings F-M3-1 (live sends bypass the outbox), F-M3-2 (live refusal must
hold on the path that sends), and the parent finding on store faults are
addressed by this ADR.

## Decision

### Every `place_*` goes through `_dispatch_place`

`_dispatch_place(*, mode, venue, coid, body, venue_obj)` lives in
`src/krellbot/run/__init__.py` and is the only function that touches the
operational store for an order placement. It wraps both paper and live:

- builds an `OperationalStore(home / "ops.sqlite")`;
- calls `Outbox(store).dispatch(coid, body, _send, mode=mode, venue=venue)`;
- on `"needs_reconcile"` it records the audit;
- propagates `StoreError` so the caller can refuse before any venue call.

The `_send` closure is the ONLY place inside `run/__init__.py` where
`venue_obj.place_entry_with_stop`, `venue_obj.place_exit`, or
`venue_obj.place_stop` may appear. An AST tripwire in
`tests/test_m3_out_outbox_live.py` enforces this.

`_paper_dispatch_place` becomes a thin wrapper that forwards with
`mode="paper", venue=None`. `_paper_send_via_outbox` and `ModeError` stay
in place; the existing `tests/test_ns13_fault_fills.py` paper-mode / live-mode
test still pins that helper raising `ModeError` on a live arm.

### `cancel_stops` and `raise_stop` are not outboxed

Both calls carry no order identity — they converge idempotently. Cancel
all resting stops on a pair, or raise a stop monotonically — re-issuing
either is safe and the venue handles duplicates. The only allowed
`venue_obj.<method>(...)` calls outside `_dispatch_place._send` are:

- `snapshot`
- `rules`
- `order_by_coid`
- `cancel_stops`
- `raise_stop`

For live, the engine refuses before any venue call (see `run.tick`'s live
gate), so a `cancel_stops` / `raise_stop` against a live venue only runs
when the gate has already cleared. A test in
`tests/test_m3_out_outbox_live.py` fails if `run/__init__.py` calls any
other venue write method outside the allowed set.

### One operational store

There is one operational store at `<home>/ops.sqlite`. `_commit_outbox_rows`
and its `_outbox_store_path` helper are deleted. `_dispatch_place` writes
the intent row BEFORE the venue call, so the same row records both the
commit and the eventual send. `<home>/run/store.db` no longer exists;
`tests/test_lane_e_unaided.py` reads the outbox rows from `ops.sqlite`.

The outbox record carries `mode` and `venue` when present, so an auditor
can distinguish paper from live without reading the journal. Older rows
written before this change remain readable: the Outbox's `_state` ignores
the new keys when they are absent.

### Live refusal comes before any transport call

`run.tick` calls `live_gate.check_live_send` for every live-armed record
before any `venue_obj` attribute access (no `snapshot`, no `rules`, no
`check_key`). `cli.venue_for_tick` and `cli._build_live_venue_for_offline`
do the same — the CLI's bare env guard is replaced by `check_live_send`.
`run.arm_pack`'s live branch replaces its env check with `check_live_send`.
A new `PaperService.arm` refusal with code `kill_switch_engaged` refuses
before any config byte change.

### Store faults are typed and fail closed

`StoreError(RuntimeError)` is the new base class. `StoreBusy`,
`StoreCorrupt`, and the new `StoreFull` are subclasses. `OperationalStore`
and `_Write` translate every fault — `sqlite3.OperationalError`,
`sqlite3.DatabaseError`, and `OSError(errno.ENOSPC, ...)` — into the right
typed error. `connect()` and `_Write.__enter__` / `__exit__` always release
the in-process lock and chain with `raise StoreX(...) from exc`.

`run.tick` opens the operational store before any venue call; on
`StoreError` it journals a `store_refused` record and returns 1 with zero
venue calls. At each `_dispatch_place` site, `StoreError` is caught BEFORE
the generic `except (RuntimeError, ValueError)` so a commit failure
refuses without placing; the pack's tick detail carries `intent_refused:
<code>` and `tick` returns 1 at the end.

`kb_reservations.should_block_for_reconcile(home)` now also gates live
arms. A `StoreError` from the gate is treated as blocked.

## Consequences

- A live tick that dies between commit and send now leaves the outbox
  row in `sent: false`; the next tick returns `needs_reconcile` and
  reconciles from the venue snapshot.
- One operational store, one place for store errors, one audit trail
  (the ledger).
- The CLI no longer builds a live venue object before the operator grant
  is checked.
- `cancel_stops` / `raise_stop` keep their existing direct call site —
  they have no coid and cannot be retried meaningfully.
- `_paper_send_via_outbox` still raises `ModeError` for a live arm;
  callers (and tests) that need paper routing must call
  `_dispatch_place(mode="paper", ...)`.

## Test names that enforce it

- `tests/test_m3_out_live_gate_wiring.py::test_live_tick_refusal_returns_1_zero_venue_calls`
- `tests/test_m3_out_live_gate_wiring.py::test_live_tick_with_grant_env_and_kill_engaged_refuses`
- `tests/test_m3_out_live_gate_wiring.py::test_live_tick_with_grant_passes_gate_and_places_entry_once`
- `tests/test_m3_out_live_gate_wiring.py::test_cmd_tick_live_no_grant_refuses_without_transport_calls`
- `tests/test_m3_out_live_gate_wiring.py::test_cmd_tick_offline_live_no_grant_refuses_without_transport_calls`
- `tests/test_m3_out_live_gate_wiring.py::test_arm_pack_live_env_unset_does_not_call_key_check`
- `tests/test_m3_out_live_gate_wiring.py::test_arm_pack_live_env_one_no_grant_does_not_call_key_check`
- `tests/test_m3_out_live_gate_wiring.py::test_cmd_arm_live_no_grant_does_not_call_probe`
- `tests/test_m3_out_live_gate_wiring.py::test_paper_tick_with_kill_engaged_suppresses_new_entries`
- `tests/test_m3_out_live_gate_wiring.py::test_paper_tick_with_kill_engaged_still_exits`
- `tests/test_m3_out_live_gate_wiring.py::test_paper_service_arm_with_kill_engaged_returns_kill_switch_code`
- `tests/test_m3_out_outbox_live.py::test_live_entry_ledger_row_committed_before_send`
- `tests/test_m3_out_outbox_live.py::test_live_entry_send_runtime_error_yields_needs_reconcile_on_next_tick`
- `tests/test_m3_out_outbox_live.py::test_live_exit_ledger_row_has_live_mode_and_venue`
- `tests/test_m3_out_outbox_live.py::test_live_stop_repair_ledger_row_has_live_mode_and_venue`
- `tests/test_m3_out_outbox_live.py::test_ast_tripwire_place_methods_only_inside_dispatch_place`
- `tests/test_m3_out_outbox_live.py::test_paper_tick_does_not_create_run_store_db`
- `tests/test_m3_out_store_faults.py::test_corrupt_store_refuses_paper_tick_with_zero_venue_calls`
- `tests/test_m3_out_store_faults.py::test_corrupt_store_refuses_live_tick_with_zero_venue_calls`
- `tests/test_m3_out_store_faults.py::test_busy_store_paper_entry_has_intent_refused_and_no_place`
- `tests/test_m3_out_store_faults.py::test_busy_store_recovers_on_next_bar`
- `tests/test_m3_out_store_faults.py::test_full_store_paper_entry_has_intent_refused_store_full`
- `tests/test_m3_out_store_faults.py::test_write_classifies_known_operational_errors`
- `tests/test_m3_out_store_faults.py::test_write_classifies_oserror_enospc`
- `tests/test_m3_out_store_faults.py::test_write_releases_lock_after_translate`
- `tests/test_m3_out_store_faults.py::test_store_error_subclass_relationships_and_codes`