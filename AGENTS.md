# Krellbot development

Krellbot is an open-source local crypto workstation: a Python engine plus a local React/TypeScript web app. Product requirements live in `docs/product-direction.md`. The web workstation is the only user surface. The CLI is plumbing (launcher, scheduler entry, diagnostics): do not add user features to it.

## Where work comes from

- Work only on the lowest-numbered unchecked task in the current file under `docs/milestones/`. One task, one branch from `main`, one PR.
- You may not create tasks, issues, milestones, queues, review records, or verification scripts. If you notice a problem outside your task, append one line to `docs/milestones/PARKING.md` in the same PR and keep going. Parked items are not work.
- Tasks marked `[owner]` are for the human. Skip them.

## Done

- A task is done when its acceptance command passes and CI is green on the PR. Paste the command and its real output in the PR body.
- Two failed attempts at the same task: stop, leave the PR as a draft, and write the blocker in its description. Do not retry a third time and do not widen the task.
- Do not edit, skip, or delete an existing test to get green unless the task says so by name.
- Tick the task's checkbox in the milestone file in the same PR.

## Risk paths

A PR that touches any of these gets the `risk-path` label and is never merged by an agent. The owner merges it.

- `src/krellbot/run/`, `src/krellbot/venues/`, `src/krellbot/execution/`, `src/krellbot/storage/outbox.py`
- `src/krellbot/application/live_gate.py`, `src/krellbot/application/live_preflight.py`
- `src/krellbot/release_policy.py`, `src/krellbot/license.py`, `src/krellbot/secrets.py`, anything under `src/krellbot/keys/`

`PAPER_ONLY_RELEASE` stays `True`. Only the owner changes it.

## Commands

- Python: `uv sync --frozen --group dev --python 3.13`, then `KRELLBOT_HOME=$(mktemp -d) uv run --no-sync pytest -q`
- Lint: `uvx ruff check src tests && uvx ruff format --check src tests`
- Frontend: `cd frontend && npm ci --include=dev && npm run typecheck && npm run test:unit -- --run && npm run build`
- Browser tests: `cd frontend && npm run test:e2e` and `npm run test:journeys`

## Rules that hold everywhere

- Tests use fake transports, fake keyrings and an isolated `KRELLBOT_HOME`. No exchange credentials, real orders, purchases, signing or publishing.
- Preserve the loopback API's authentication, session, CSRF, origin and host checks.
- Preserve deterministic execution, Decimal accounting, strategy-owned versus external inventory separation, and reconcile-never-resubmit for unknown order outcomes.
- Name new tests after the behavior they pin (`test_paper_buy_funding.py`), never after a task, lane, run or issue number.
- UI work follows `docs/design-system.md` (contract `KRELL-SIGNAL-20261010`).
- Telemetry stays opt-in. Never present backtest or fixture results as market performance.
