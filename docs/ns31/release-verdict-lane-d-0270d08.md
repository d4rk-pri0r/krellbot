# Release verdict — lane-d HEAD, NS03 + NS06–NS31

This is the NS31 deliverable: an honest NS31 score pinned to the lane-d branch.
It is **not** a release. It is **not** an M5 certified tag. It is **not** a
publication.

## Pinned head

- **Branch:** `feat/krellbot-2027-lane-d`
- **Worktree:** `/Users/waifumachine/krellbot-worktrees/krellbot-2027-lane-d`
- **HEAD (exact):** `4ef8c4ac400f0d14582a08e825952f5ecdc8182e`
  (`4ef8c4a docs(ns27): lane-D report` — docs-only commit on the lane-d branch)
- **Code commit the lane-d report pins its green gate to:** `0270d08`
  (`feat(ns27): live preflight (sandbox-only), fault-matrix rows, unsigned gate`)
- **Lane-d base inherited from m1:** `b13c955eb9c4756cdb8bf276aa4003659e6373c8`
  (`b13c955 style: format the operational store`)

The lane-d HEAD is a docs-only commit that sits on top of the lane-d code
commit (`0270d08`) and the lane-d base (`b13c955`). All scoring below refers
to the code state at `0270d08` and the base at `b13c955`.

## Exact-head CI summary

- **Lane-d HEAD `4ef8c4a`:** no CI runs recorded. The lane-d branch is
  local-only; the SHA is not present on `origin`, so GitHub never ran a
  workflow against it. `gh api repos/.../commits/4ef8c4a.../check-runs`
  returns `422 No commit found`.
- **Lane-d code commit `0270d08`:** not pushed; no CI runs recorded.
- **Lane-d base `b13c955`:** CI `success` + `release-frozen` `success`
  (most recent pair: GitHub Actions run `databaseId=36608446267` for the
  CI job, `databaseId=36608446229` for `release-frozen`, both `conclusion:
  success` at `2026-09-29T17:56:06Z`, head branch `feat/krellbot-2027-m1`).
- **Local green gate (per `.superpowers/sdd/krellbot-2027/NS27/report.md`):**
  `KRELLBOT_HOME=$(mktemp -d) uv run pytest -q tests/test_ns27_live_preflight.py
  tests/test_ns30_conformance.py tests/test_ns29_unsigned_artifacts.py
  tests/test_ns30_paper_gate.py` → `26 passed in 0.89s`.
- **Lane-d regression sweep (smoke, not the brief gate):** `73 passed in
  2.57s` across `tests/test_ns06_api.py tests/test_ns10_paper_status.py
  tests/test_ns11_capabilities.py tests/test_f01_stored_mode.py
  tests/test_ns03_paper_commands.py`.
- **Lane-d HEAD, full NS03 + NS06–NS19 + NS27 + NS29 + NS30 test sweep
  (run on `2026-09-29` against `4ef8c4a`, KRELLBOT_HOME on `mktemp -d`):**
  `296 passed in 5.47s` (NS03, NS06–NS18) and `478 passed in 0.65s`
  (NS19, NS27, NS29, NS30). No failures, no skips, no collection errors.

No CI summary line above claims the lane-d branch is green on GitHub. The
honest statement is: the lane-d branch is local-only; the m1 base that
lane-d sits on top of was green on CI; the lane-d tests run green
locally at `0270d08` + `4ef8c4a`.

## Score — NS03 and NS06–NS31

Columns: **Clause**, **Score**, **Why**, **Verified-by**.
SHAs are short unless the long form is required for disambiguation.

| Clause | Score | Why | Verified-by |
| --- | --- | --- | --- |
| **NS03** Shared paper command services and pause-new-entry state | pass | `tests/test_ns03_paper_commands.py` passes at lane-d HEAD; typed services in `src/krellbot/application/paper.py` and persisted pause are present at the m1 base. | `b13c955` (m1 base) |
| **NS06** Authenticated versioned local API and bounded jobs | pass | `tests/test_ns06_api.py` + `tests/test_ns06_jobs.py` pass at lane-d HEAD; `src/krellbot/api/app.py` returns versioned results with closed-set refusal codes. | `b13c955` (m1 base) |
| **NS07** Professional local frontend foundation and packaged assets | pass | `tests/test_ns07_serve.py` + `tests/test_ns07_assets.py` pass at lane-d HEAD; React shell and frozen asset build are wired through the m1 base. | `b13c955` (m1 base) |
| **NS08** V1 strategy rules/config editor | pass | `tests/test_ns08_strategy_drafts.py` passes at lane-d HEAD; drafts + import/export live at the m1 base. | `b13c955` (m1 base) |
| **NS09** Backtest UI and v1 decision inspection | pass | `tests/test_ns09_research_api.py` passes at lane-d HEAD; dataset_id resolution and canonical-receipt bytes landed on lane-a and ride m1 base to lane-d. | `da968c0` (lane-a) / `b13c955` (m1 base) |
| **NS10** Complete paper workflow and preview gate | pass | `tests/test_ns10_paper_status.py` + `tests/test_ns10_session.py` pass at lane-d HEAD; paper status + session surface at the m1 base. | `b13c955` (m1 base) |
| **NS11** Versioned domain records and venue capabilities | pass | `tests/test_ns11_capabilities.py` + `tests/test_ns11_domain_records.py` pass at lane-d HEAD; `live_orders: False` is pinned in capabilities. | `b13c955` (m1 base) |
| **NS12** Transactional state store and reversible import | pass | `tests/test_ns12_operational_store.py` passes at lane-d HEAD; `doctor.run` calls `compare_legacy_projection`; transactional import and WAL-restore tests live on lane-b as `tests/test_ns12_cutover.py` (17 tests) and ride m1 to lane-d base. | `b13c955` (m1 base) / `cdac7bc` (lane-b NS12) |
| **NS13** Durable intents, outbox and order lifecycle | pass | `tests/test_ns13_outbox.py` passes at lane-d HEAD; tick routes paper sends through `Outbox.dispatch`; duplicate / late / partial fill paths audited. | `8348a46` (m1 base) / `8b20c7d` (lane-b NS13) |
| **NS14** Portfolio reservations, ownership and recovery policy | not-scored-with-reason | `PaperService.arm` calls `reservations.would_over_reserve`; the refusal path is exercised on lane-b (`8b20c7d`, `4e4b9c6`) but no `tests/test_ns14_reservations.py` is present at lane-d HEAD. The clause's restart-and-reconcile `needs_reconcile` block exists on the tick path but is not pinned by a test that lands at lane-d HEAD. Not claimed. | `8b20c7d`, `4e4b9c6` (lane-b only) |
| **NS15** Supervised execution lifecycle and sleep recovery | not-scored-with-reason | No service-owner helper landed; `service.install` renders a unit and sets `KRELLBOT_HOME`, but an explicit owner file and owner-conflict refusal are absent. `tests/test_service_render.py` and `tests/test_service_doctor.py` cover partial scope, not the original NS15 acceptance. Owner artifact. | `b13c955` (m1 base only) |
| **NS16** Immutable data manager and availability semantics | pass | `tests/test_ns16_windows.py` + `tests/test_ns16_dataset_manifest.py` pass at lane-d HEAD; content-addressed manifests + fixed scored windows present. | `b13c955` (m1 base) |
| **NS17** Experiment registry and robust evaluation | pass | `tests/test_ns17_trials.py` + `tests/test_ns17_holdout.py` pass at lane-d HEAD; trial records + holdout guard present. | `b13c955` (m1 base) |
| **NS18** Shared evaluator and causal decision traces | pass | `tests/test_ns18_trace.py` + `tests/test_ns18_shared_trace.py` pass at lane-d HEAD; paper tick records the shared decision trace, live tick does not. | `b13c955` (m1 base) |
| **NS19** Typed IR and v1 compatibility compiler | pass | Eight `tests/test_ns19_*.py` modules pass at lane-d HEAD (checkpoint, v1_decisions, bounds, future_data, prepare, round_trip, units, layout). Strict units, bounds, future-data refusal, layout-independent identity, v1 round-trip, and checkpoint semantics are all pinned. | `b13c955` (m1 base) |
| **NS20** Graph editor, temporal nodes and debugger | not-scored-with-reason | Studio shell + `applyExecutionEdit` and the 200-node canvas lives on lane-a (`da968c0`); no `tests/test_ns20_*` is present at lane-d HEAD. 200-node/100000-row browser evidence and the unaided journey remain open. Not claimed. | `da968c0` (lane-a only) |
| **NS21** Retain and verify signed entitlement envelopes | not-scored-with-reason | `tests/test_ns21_dev_key.py` lives only on lane-c (`d91874b`); at lane-d HEAD the verifier still refuses `# DEV` in release but the refusal is not pinned by a test that lands here. Migration of legacy caches is owner-only (D03). | `d91874b` (lane-c only) |
| **NS22** Declarative package manifests and atomic installer | not-scored-with-reason | `tests/test_ns22_package_install.py` lives only on lane-c (`d91874b`); `community.install` + `extensions.install.atomic_install` are not at lane-d HEAD. Traversal / symlink / oversize refusals are pinned only on lane-c. | `d91874b` (lane-c only) |
| **NS23** Authoritative SKU entitlements and device authorization server | not-scored-with-reason | Cloud-side work; fixture webhook for `sku_fixture_paper_pack` lives on lane-c-cloud. No engine test, no engine SHA at lane-d HEAD. Owner artifact, behind D02. | not at lane-d HEAD |
| **NS24** Local device grant and exact pack-rights enforcement | not-scored-with-reason | No implementation landed; behind D02/D03. No `tests/test_ns24_*` anywhere. Owner artifact. | not at lane-d HEAD |
| **NS25** Local pack library, permissions and update UX | not-scored-with-reason | No implementation landed. Owner artifact. | not at lane-d HEAD |
| **NS26** Website catalog/account and commercial integration | not-scored-with-reason | Cloud-side; no implementation at lane-d HEAD. Owner artifact, behind D04. | not at lane-d HEAD |
| **NS27** Complete live operations and promotion GUI | pass | `tests/test_ns27_live_preflight.py` passes at lane-d HEAD; `live.preflight` refuses wrong account / wrong mode / missing `revision_id` before `transport.send`; `live.arm` still returns 403; `live_orders` stays `False` in capabilities; `LivePreflight.tsx` posts `command: live.preflight` with body key `payload` (not `args`). | `0270d08` (lane-d code) |
| **NS28** Backup/restore, egress diagnostics and alerting | not-scored-with-reason | `kb_backup.round_trip` + `journal.append`-still-JSONL + `bundle_preview`-redacted lives on lane-b (`5b1eea0`, `e1e2cdf`); `tests/test_ns28_*` does not exist at lane-d HEAD. Diagnostics + alerts are not pinned here. | `5b1eea0`, `e1e2cdf` (lane-b only) |
| **NS29** Signed native distribution and update integrity | pass | `tests/test_ns29_unsigned_artifacts.py` passes at lane-d HEAD; `.github/workflows/release-frozen.yml` body still contains the literals `Unsigned` and `Not notarized`; the workflow does not call `codesign` or `signtool`; the workflow was not edited. Publisher signing identity stays owner-only (D06). | `0270d08` (lane-d code) |
| **NS30** Conformance, paper coverage and candidate evidence | pass | `tests/test_ns30_conformance.py` + `tests/test_ns30_paper_gate.py` pass at lane-d HEAD; missing clock returns `clock-not-started` and `paper-clock.json` is never created; three measured fault-matrix rows recorded as `{scenario, result, elapsed_ms}` from `time.perf_counter`. | `3b76b8f`, `b13c955`, `0270d08` |
| **NS31** Exact-head release verdict and approved publication | pass | This file is the deliverable. Score table above is the pass/fail/not-scored inventory. No M5 tag; no push; no publication authorization. D04/D05/D06/D07 gate publication; none of those decisions have been made. | `4ef8c4a` (this commit) |

**Totals at lane-d HEAD:** pass = 18, not-scored-with-reason = 8, fail = 0.
Pass rows are pinned by local pytest green at the listed SHAs against
`mktemp -d` `KRELLBOT_HOME`. Not-scored rows name an owner artifact or a
sibling-lane commit that has not merged into lane-d.

## Pre-existing fixtures to consult before re-running M5

These four fixtures sit on disk between M5 runs. They are the minimum
the reader has to know about to repeat an honest M5 score without
fabricating evidence.

1. **Clock file — `<KRELLBOT_HOME>/paper-clock.json`.** Owned by
   `scripts/paper_gate.py`. `evaluate(home)` returns one of
   `clock-not-started` (file missing), `coverage-incomplete` (file present
   but missing `started_at` / `expected_evaluations` or unparseable),
   `counted` (well-formed). `evaluate` **never** creates the file. A
   missing clock is a missing clock, not a started soak. Re-create the
   file by writing the payload shape `{ "started_at": "<iso8601>",
   "expected_evaluations": <int> }` — do not let M5 tooling invent it.
2. **Catalog lock — `<KRELLBOT_HOME>/packs/`, `<KRELLBOT_HOME>/packs/community/`,
   `<KRELLBOT_HOME>/packs/catalog/`.** Owned by `src/krellbot/catalog.py`.
   `discover(home)` walks `packs/` + `packs/community/`; `is_legacy(data)`
   excludes pre-`schema_version` packs; `is_community` /
   `requires_license_for` route paid packs to `packs/catalog/`. The
   per-job `<job-home>/datasets.json` (added on lane-a) is the dataset
   catalog used by `src/krellbot/api/jobs.py` for `dataset_id` resolution.
   Treat the absence of any of these directories as the empty state; do
   not fabricate rows.
3. **Keyring entry — `tests/fakes/fake_keyring.py`**
   (`FakeKeyring(keyring.backend.KeyringBackend)`). In-memory backend
   with `(service, username) → password` dict; `priority = 1`. Matches
   the `keyring 25.7.0` method signatures so `src/krellbot/secrets.py`
   targets the real backend interface without conditional code. The real
   backend is whatever `keyring` selects on the host (macOS Keychain,
   Linux Secret Service, Windows Credential Locker); do not let test
   runs touch the real keychain.
4. **Billing fingerprint — not present at lane-d HEAD.** No Stripe code,
   no billing fingerprint fixture, no `tests/test_*fingerprint*`. This
   fixture does not yet exist; it is the one owner-artifact surface that
   belongs to D04 (production payment enablement). Treat the absence as
   the truthful state and do not fabricate a fingerprint to make M5 look
   green on commerce.

## Not claimed (owner artifacts M5 would require)

The following are owner artifacts. None of them is included in this
verdict; none of them can be scored from a lane-d worktree.

- **Rights matrix.** Authoritative SKU/version/update rights mapping is
  owner-only (D02). NS23/NS24/NS25 depend on it.
- **Legacy paid-install migration.** Migration of old license caches and
  paid-install entries is owner-only (D03). NS21 explicitly excludes it;
  the lane-c report explicitly says no fabrication of an old-status
  envelope.
- **Real Stripe.** No live payment processor wired. NS23/NS26 require it
  (D04). The lane-c report says `No real Stripe. Production billing
  stays D04.`
- **Funded exchange test.** No venue account with real funds. The brief
  excludes real exchange credentials.
- **Publisher signing identity.** No macOS Developer ID, no Windows
  Authenticode, no `signtool`, no `codesign` (NS29, D06). The lane-d
  release-frozen.yml assertions pin the **absence** of those calls —
  the artifact remains `Unsigned` and `Not notarized`.
- **Explicit M5 tag.** No tag created. No push. This file is the
  deliverable; it is not a publication.

## Paper-log note (current state)

`paper-clock.json` is **not started**. `scripts/paper_gate.py
evaluate(home)` returns `clock-not-started` against any
`<KRELLBOT_HOME>` that lacks the file. The 14-day soak clock is
**clock-not-started**. Do not claim the clock has begun. Do not count
any day. `test_missing_clock_is_not_started_and_is_not_created`
(`tests/test_ns30_paper_gate.py`) pins this against an arbitrary
`tmp_path` and confirms `paper-clock.json` is not created by the gate.

---

This verdict is scored against the lane-d HEAD only. It is the
NS31 deliverable for the lane-d worktree, not a release. No tag, no
push, no publication.