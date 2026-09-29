# NS27 — Lane D report

Branch: `feat/krellbot-2027-lane-d`
Worktree: `/Users/waifumachine/krellbot-worktrees/krellbot-2027-lane-d`
Base: `b13c955eb9c4756cdb8bf276aa4003659e6373c8`
Commit: `0270d08`
Status: green. Gate passes locally. Not pushed. Not tagged. Not claiming M5.

## Scope (from the lane-D brief)

1. `live.preflight` carve-out from the live.* prefix gate, with a fake
   transport that refuses before any `send` on account mismatch,
   missing `revision_id`, or wrong `mode`. Stored-live + wrong/omitted
   mode returns the typed code `stored_mode_not_sandbox`.
2. `paper_gate.evaluate` conformance — missing clock stays missing;
   three measured fault-matrix rows (`auth_refusal`, `stale_data`,
   `duplicate_ownership`) record `result` and `elapsed_ms` from
   `time.perf_counter` without writing a real clock.
3. `release-frozen.yml` unsigned / not-notarized gate — read-only
   assertions, no edits to the workflow.
4. `frontend/src/features/deployments/LivePreflight.tsx` + test, posting
   `live.preflight` with body key `payload` (not `args`).

## What landed

| File | Status |
| --- | --- |
| `src/krellbot/application/live_preflight.py` | new |
| `src/krellbot/api/app.py` | command branch only — adds `live.preflight` carve-out, keeps `mode == "live"` refusal, keeps other `live.*` 403 |
| `tests/test_ns27_live_preflight.py` | new |
| `tests/test_ns30_conformance.py` | new |
| `tests/test_ns29_unsigned_artifacts.py` | new |
| `frontend/src/features/deployments/LivePreflight.tsx` | new |
| `frontend/src/features/deployments/LivePreflight.test.ts` | new |
| `scripts/paper_gate.py` | unchanged — returns `clock-not-started` on missing clock, never creates the file |
| `src/krellbot/application/paper.py`, `jobs.py`, `research.py`, `strategy.py`, `storage/`, `doctor.py`, `frontend/src/features/studio/` | unchanged |
| `.github/workflows/release-frozen.yml` | unchanged — already satisfied the unsigned / not-notarized contract |

## Behavior

### `live.preflight` helper (`evaluate`)

Validation order is fixed for stable refusal codes:

1. `revision_id` present and non-empty — else `CODE_REVISION_ID_MISSING`
2. `account_id == transport.account` — else `CODE_ACCOUNT_MISMATCH`
3. `mode == "sandbox"` — else, when `stored_mode == "live"`,
   `CODE_STORED_MODE_NOT_SANDBOX`; otherwise `CODE_MODE_NOT_SANDBOX`

On success `transport.balances()` is called and returned in the
result; `transport.send` is **never** called on either branch.

Closed-set codes:

| Code | Refusal |
| --- | --- |
| `ok` | sandbox preflight ran |
| `account_mismatch` | `account_id` != `transport.account` |
| `revision_id_missing` | `revision_id` falsy |
| `mode_not_sandbox` | mode not sandbox, no stored-live override |
| `stored_mode_not_sandbox` | mode not sandbox AND stored mode is live |

### `POST /api/v1/commands` routing

```python
if command == "live.preflight":
    # delegate to evaluate; SandboxTransport by default, spy via state.live_transport
    return JSONResponse(result.to_dict(), status_code=200)
if command.startswith("live."):
    return 403 "live orders are disabled"
if inner.get("mode") == "live":
    return 403 "live orders are disabled"
```

- Body key is `payload`, matching the existing parser (`inner = payload.get("payload")`).
- `capabilities` still returns `live_orders: False`.
- A test plants a live-armed record in `config.json` and posts
  `mode: live`; the result is `stored_mode_not_sandbox` and the
  spy's `send` was not called.
- A companion test posts `live.arm` and asserts 403
  `"live orders are disabled"` is unchanged.

### `paper_gate.evaluate` conformance

- Missing clock: returns `clock-not-started`; `paper-clock.json`
  remains absent across repeated calls (3 invocations asserted).
- Three fault-matrix rows under invalid clock fixtures:
  - `auth_refusal`: `{}` JSON (no `started_at`) → `coverage-incomplete`
  - `stale_data`: `{"started_at": "..."}` (no `expected_evaluations`) → `coverage-incomplete`
  - `duplicate_ownership`: malformed JSON → `coverage-incomplete`
- Each row records `{scenario, result, elapsed_ms}` where `elapsed_ms`
  is measured with `time.perf_counter()`.

### `release-frozen.yml` unsigned / not-notarized

- `test_release_notes_contain_unsigned_and_not_notarized`: asserts the
  literal words `Unsigned` and `Not notarized` appear in the workflow
  body.
- `test_release_workflow_does_not_call_codesign`: asserts `codesign`
  is absent.
- `test_release_workflow_does_not_call_signtool`: asserts `signtool`
  is absent.

All four unsigned-gate assertions are green against the unchanged
workflow. No signing tooling is invoked. No edits made.

### Frontend

`frontend/src/features/deployments/LivePreflight.tsx` — section titled
"Live preflight" with `account_id`, `revision_id`, `mode` (default
`sandbox`) inputs and a "Run preflight" submit. On submit:

```js
fetch("/api/v1/commands", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json", "X-Krellbot-CSRF": getCsrf() },
  body: JSON.stringify({
    schema_version: "1",
    command: "live.preflight",
    payload: { account_id, revision_id, mode },
  }),
});
```

`LivePreflight.test.ts` (`.ts` per the brief) pins the body shape with
`createElement` since the file is not JSX. Five tests cover: payload
exact match (account_id / revision_id / mode=sandbox), explicit
absence of an `args` key, `mode_not_sandbox` refusal rendering, `ok`
code rendering, and `account_mismatch` code + message rendering.

## Gate (per the brief)

```
KRELLBOT_HOME=$(mktemp -d) uv run pytest -q \
    tests/test_ns27_live_preflight.py \
    tests/test_ns30_conformance.py \
    tests/test_ns29_unsigned_artifacts.py \
    tests/test_ns30_paper_gate.py
```

Result: `26 passed in 0.89s`.

Regression sweep (smoke, not part of the brief's gate):

```
uv run pytest -q tests/test_ns06_api.py tests/test_ns10_paper_status.py \
    tests/test_ns11_capabilities.py tests/test_f01_stored_mode.py \
    tests/test_ns03_paper_commands.py
```

Result: `73 passed in 2.57s`. No regressions.

## Constraints honored

- No edits to `jobs.py`, `research.py`, `strategy.py`, `storage/`,
  `doctor.py`, `frontend/src/features/studio/`.
- `scripts/paper_gate.py` unchanged — still returns `clock-not-started`
  when the clock file is absent and still does not create it.
- `paper-clock.json` is never written by the new tests; the three
  invalid clock files are fixtures for refusal-path assertions.
- `.github/workflows/release-frozen.yml` unchanged.
- No `git push`, no tag, no M5 claim.
- Commit is on the lane branch only.