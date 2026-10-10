# Krellbot development

Krellbot is an open-source local crypto workstation. Python services are shared by the CLI and local React/TypeScript GUI. Read README.md, SECURITY.md, and the relevant source/tests before editing. Product requirements live in docs/product-direction.md.

## Design contract (KRELL-SIGNAL-20261010)

All user-facing UI work implements the owner-approved Signal + Krell Asset Pack v2 design, contract `KRELL-SIGNAL-20261010`. Read `docs/design-system.md` first: its named tokens (`frontend/src/styles/tokens.css`), local Manrope/IBM Plex Mono fonts, compact product-led shell composition, color semantics (sage = affirmative, seafoam = selection/focus, coral = caution — never green for caution), and supplied brand-asset rules are binding for every relevant frontend change. Do not reintroduce the old neon-lime/cyan palette or invent substitute brand artwork.

## Working here

- Implement the requested product task, not an orchestration framework. Use normal terminal, file-editing, and test tools.
- Add a regression test that fails for the reported behavior, implement the smallest coherent fix, then rerun applicable checks. Preserve existing assertions and safeguards.
- Python: `uv sync --frozen --group dev`; run tests with an isolated `KRELLBOT_HOME`, e.g. `KRELLBOT_HOME=$(mktemp -d) uv run --no-sync pytest -q`.
- Frontend: `cd frontend && npm ci --include=dev`; `npm run test:unit -- --run`; `npm run typecheck`; `npm run build`.
- Keep changes inside this repository and the task's scope. Do not modify agent/service configuration or install new orchestration tools.
- Do not commit, push, merge, publish, or deploy unless the current task explicitly authorizes it. Report changed files and actual command results; an independent operator reviews and integrates the patch.

## Product boundaries

- Preserve the loopback API's authentication, session, CSRF, origin, and host checks.
- Live execution stays disabled. Use fake transports/keyrings and isolated data for tests; no exchange credentials, real orders, purchases, production migration, or signing.
- Preserve free/custom strategy operation, deterministic execution, Decimal accounting, ownership separation, and reconciliation of unknown order outcomes.
- Telemetry remains opt-in. Never invent research returns or represent backtests as live results.
- Build coherent user journeys first. Broad hardening and capability/release qualification are separate tasks, not implicit prerequisites for every frontend change.
- Historical planning reports and agent runtime state are not product dependencies and do not belong in this repository.
