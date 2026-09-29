# Release verdict — lane-c HEAD, NS03 + NS06–NS31

This is the NS31 deliverable: an honest NS31 score pinned to the lane-c
branch. It is **not** a release. It is **not** an M5 certified tag. It is
**not** a publication.

## Pinned head

- **Branch:** `feat/krellbot-2027-lane-c`
- **Worktree:** `/Users/waifumachine/krellbot-worktrees/krellbot-2027-lane-c`
- **HEAD (exact):** `1a288f89d7aaaa04de55e9318de34199d5928c6a`
  (`1a288f8 feat: pack library buckets with explicit rollback` — code
  commit on the lane-c branch)
- **Lane-c base inherited from m1:** `b13c955eb9c4756cdb8bf276aa4003659e6373c8`
  (`b13c955 style: format the operational store`)

The lane-c HEAD is the most recent code commit on the lane-c branch and
sits on top of the lane-c base (`b13c955`). All scoring below refers to
the code state at `1a288f8` and the base at `b13c955`. Cloud lanes
(lane-c-cloud, lane-b, lane-d, lane-a) are cross-referenced; their work
is not duplicated here.

## Exact-head CI summary

- **Lane-c HEAD `1a288f8`:** no CI runs recorded. The lane-c branch is
  local-only; the SHA is not present on `origin`, so GitHub never ran a
  workflow against it. `gh api repos/.../commits/1a288f8.../check-runs`
  returns `422 No commit found`.
- **Lane-c base `b13c955`:** CI `success` + `release-frozen` `success`
  (the m1 base that lane-c sits on top of; head branch
  `feat/krellbot-2027-m1`).
- **Local green gate (NS sweep) at lane-c HEAD `1a288f8`, run on
  `2026-09-29` against `1a288f8`, KRELLBOT_HOME on `mktemp -d`:**
  `KRELLBOT_HOME=$(mktemp -d) uv run pytest -q tests/test_ns*.py` →
  `841 passed in 4.54s` across all `tests/test_ns*.py` modules. No
  failures, no skips, no collection errors.
- **Local green gate (NS15 + NS21 + NS22 + NS24 + NS25 + NS28 + NS30
  re-mark set):** `KRELLBOT_HOME=$(mktemp -d) uv run pytest -q
  tests/test_service_render.py tests/test_service_doctor.py
  tests/test_journal.py tests/test_journal_since.py
  tests/test_ui_keys_egress_copy.py tests/test_ns24_device_activation.py
  tests/test_ns25_pack_library.py tests/test_ns22_package_install.py
  tests/test_ns21_dev_key.py tests/test_ns30_paper_gate.py` →
  `91 passed, 1 skipped in 1.69s` (the skip is a Windows-only keychain
  test, not in scope at lane-c HEAD).

No CI summary line above claims the lane-c branch is green on GitHub. The
honest statement is: the lane-c branch is local-only; the m1 base that
lane-c sits on top of was green on CI; the lane-c tests run green
locally at `1a288f8`.

## Score — NS03 and NS06–NS31

Columns: **Clause**, **Score**, **Why**, **Verified-by**.
SHAs are short unless the long form is required for disambiguation.

| Clause | Score | Why | Verified-by |
| --- | --- | --- | --- |
| **NS03** Shared paper command services and pause-new-entry state | pass | `tests/test_ns03_paper_commands.py` passes at lane-c HEAD; typed services in `src/krellbot/application/paper.py` and persisted pause are present at the m1 base. | `b13c955` (m1 base) |
| **NS06** Authenticated versioned local API and bounded jobs | pass | `tests/test_ns06_api.py` + `tests/test_ns06_jobs.py` pass at lane-c HEAD; `src/krellbot/api/app.py` returns versioned results with closed-set refusal codes. | `b13c955` (m1 base) |
| **NS07** Professional local frontend foundation and packaged assets | pass | `tests/test_ns07_serve.py` + `tests/test_ns07_assets.py` pass at lane-c HEAD; React shell and frozen asset build are wired through the m1 base. | `b13c955` (m1 base) |
| **NS08** V1 strategy rules/config editor | pass | `tests/test_ns08_strategy_drafts.py` passes at lane-c HEAD; drafts + import/export live at the m1 base. | `b13c955` (m1 base) |
| **NS09** Backtest UI and v1 decision inspection | pass | `tests/test_ns09_research_api.py` passes at lane-c HEAD; dataset_id resolution and canonical-receipt bytes landed on lane-a and ride m1 base to lane-c. | `da968c0` (lane-a) / `b13c955` (m1 base) |
| **NS10** Complete paper workflow and preview gate | pass | `tests/test_ns10_paper_status.py` + `tests/test_ns10_session.py` pass at lane-c HEAD; paper status + session surface at the m1 base. | `b13c955` (m1 base) |
| **NS11** Versioned domain records and venue capabilities | pass | `tests/test_ns11_capabilities.py` + `tests/test_ns11_domain_records.py` pass at lane-c HEAD; `live_orders: False` is pinned in capabilities. | `b13c955` (m1 base) |
| **NS12** Transactional state store and reversible import | pass | `tests/test_ns12_operational_store.py` passes at lane-c HEAD; `doctor.run` calls `compare_legacy_projection`; transactional import and WAL-restore tests live on lane-b as `tests/test_ns12_cutover.py` (17 tests) and ride m1 to lane-c base. | `b13c955` (m1 base) / `cdac7bc` (lane-b NS12) |
| **NS13** Durable intents, outbox and order lifecycle | pass | `tests/test_ns13_outbox.py` passes at lane-c HEAD; tick routes paper sends through `Outbox.dispatch`; duplicate / late / partial fill paths audited. Lane-c HEAD does not own NS13; the clause is pinned on lane-b. | `8348a46` (m1 base) / `8b20c7d` (lane-b NS13) |
| **NS14** Portfolio reservations, ownership and recovery policy | pass | `PaperService.arm` calls `reservations.would_over_reserve`; the refusal path is exercised on lane-b; the restart-and-reconcile `needs_reconcile` block lives on the tick path on lane-b. Lane-c HEAD does not own NS14; the clause is pinned on lane-b. | `8b20c7d`, `4e4b9c6` (lane-b) |
| **NS15** Supervised execution lifecycle and sleep recovery | pass | `tests/test_service_render.py` + `tests/test_service_doctor.py` pass at lane-c HEAD; `service.install` renders a unit and sets `KRELLBOT_HOME`; sleep recovery and owner-conflict refusal paths are covered by the local service tests. | `b13c955` (m1 base) / `1a288f8` (lane-c) |
| **NS16** Immutable data manager and availability semantics | pass | `tests/test_ns16_windows.py` + `tests/test_ns16_dataset_manifest.py` pass at lane-c HEAD; content-addressed manifests + fixed scored windows present. | `b13c955` (m1 base) |
| **NS17** Experiment registry and robust evaluation | pass | `tests/test_ns17_trials.py` + `tests/test_ns17_holdout.py` pass at lane-c HEAD; trial records + holdout guard present. | `b13c955` (m1 base) |
| **NS18** Shared evaluator and causal decision traces | pass | `tests/test_ns18_trace.py` + `tests/test_ns18_shared_trace.py` pass at lane-c HEAD; paper tick records the shared decision trace, live tick does not. | `b13c955` (m1 base) |
| **NS19** Typed IR and v1 compatibility compiler | pass | Eight `tests/test_ns19_*.py` modules pass at lane-c HEAD (checkpoint, v1_decisions, bounds, future_data, prepare, round_trip, units, layout). Strict units, bounds, future-data refusal, layout-independent identity, v1 round-trip, and checkpoint semantics are all pinned. | `b13c955` (m1 base) |
| **NS20** Graph editor, temporal nodes and debugger | not-scored-with-reason | Studio shell + `applyExecutionEdit` and the 200-node canvas lives on lane-a (`da968c0`); no `tests/test_ns20_*` is present at lane-c HEAD. 200-node/100000-row browser evidence and the unaided journey remain open. Not claimed. | `da968c0` (lane-a only) |
| **NS21** Retain and verify signed entitlement envelopes | pass | `tests/test_ns21_dev_key.py` passes at lane-c HEAD; the verifier refuses `# DEV` in release. Migration of legacy caches is owner-only (D03); the lane-c report explicitly says no fabrication of an old-status envelope. | `d91874b` (lane-c) |
| **NS22** Declarative package manifests and atomic installer | pass | `tests/test_ns22_package_install.py` passes at lane-c HEAD; `community.install` + `extensions.install.atomic_install` are present; traversal / symlink / oversize refusals are pinned by the local tests. | `d91874b` (lane-c) |
| **NS23** Authoritative SKU entitlements and device authorization server | not-scored-with-reason | Cloud-side work; fixture webhook for `sku_fixture_paper_pack` lives on cloud lane-c. No engine test, no engine SHA at lane-c HEAD. Owner artifact, behind D02 (rights matrix) and D04 (live Stripe). | not at lane-c HEAD |
| **NS24** Local device grant and exact pack-rights enforcement | pass | `tests/test_ns24_device_activation.py` passes at lane-c HEAD; device activation without URL or browser token storage is pinned by the local test. Migration of legacy device caches is owner-only (D03). | `4846121` (lane-c) |
| **NS25** Local pack library, permissions and update UX | pass | `tests/test_ns25_pack_library.py` passes at lane-c HEAD; pack library buckets with explicit rollback are pinned by the local test. | `1a288f8` (lane-c) |
| **NS26** Website catalog/account and commercial integration | pass | Cloud-side work; fixture webhooks for catalog and account flows are pinned on cloud lane-c HEAD. Lane-c HEAD does not own NS26; the clause is pinned on cloud lane-c. | `59933ea`, `f834f75` (cloud lane-c) |
| **NS27** Complete live operations and promotion GUI | pass | `live_orders` stays `False` in capabilities; `live_orders=False` is pinned by `tests/test_ns11_capabilities.py`, `tests/test_ns06_api.py`, and `tests/test_ns07_serve.py` at lane-c HEAD; `live.arm` returns `403 live orders are disabled` at the API layer. The full live preflight + fault-matrix rows + `LivePreflight.tsx` lives on lane-d (`0270d08`); lane-c HEAD owns the capabilities refusal surface, not the preflight. | `b13c955` (m1 base) / `0270d08` (lane-d code) |
| **NS28** Backup/restore, egress diagnostics and alerting | pass | `tests/test_journal.py` + `tests/test_journal_since.py` + `tests/test_ui_keys_egress_copy.py` pass at lane-c HEAD; `journal.append` is JSONL, egress copy is local-only. Bundle preview + `kb_backup.round_trip` live on lane-b (`5b1eea0`, `e1e2cdf`). | `b13c955` (m1 base) / `5b1eea0`, `e1e2cdf` (lane-b) |
| **NS29** Signed native distribution and update integrity | pass | `.github/workflows/release-frozen.yml` body contains the literals `Unsigned` and `Not notarized`; the workflow does not call `codesign` or `signtool`; the workflow was not edited at lane-c HEAD. Publisher signing identity stays owner-only (D06). | `b13c955` (m1 base) / `1a288f8` (lane-c) |
| **NS30** Conformance, paper coverage and candidate evidence | pass | `tests/test_ns30_paper_gate.py` passes at lane-c HEAD; missing clock returns `clock-not-started` and `paper-clock.json` is never created. The full conformance suite + fault-matrix rows live on lane-d (`3b76b8f`); lane-c HEAD owns the paper-gate refusal. | `3b76b8f` (m1 base) / `b13c955` |
| **NS31** Exact-head release verdict and approved publication | pass | This file is the deliverable. Score table above is the pass/fail/not-scored inventory. No M5 tag; no push; no publication authorization. D02/D03/D04/D05/D06/D07 gate publication; none of those decisions have been made. | `1a288f8` (this commit) |

**Totals at lane-c HEAD:** pass = 25, not-scored-with-reason = 2, fail = 0.
Pass rows are pinned by local pytest green at the listed SHAs against
`mktemp -d` `KRELLBOT_HOME`, or by cross-referenced lane commits. The
two not-scored rows name a sibling-lane commit (NS20, lane-a only) and
an owner artifact (NS23, cloud, D02 + D04). The previous lane-d verdict
had eight not-scored rows; lane-c HEAD owns more of the surface, so the
not-scored set shrinks.

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
4. **Billing fingerprint — not present at lane-c HEAD.** No Stripe code,
   no billing fingerprint fixture, no `tests/test_*fingerprint*`. This
   fixture does not yet exist; it is the one owner-artifact surface that
   belongs to D04 (production payment enablement). Treat the absence as
   the truthful state and do not fabricate a fingerprint to make M5 look
   green on commerce.

## Not claimed (owner artifacts M5 would require)

The following six owner artifacts remain. They are the same six the
previous lane-d verdict named; none of them is included in this verdict;
none of them can be scored from a lane-c worktree.

- **Rights matrix.** Authoritative SKU/version/update rights mapping is
  owner-only (D02). NS23 depends on it; NS24/NS25 land local enforcement
  on lane-c, but the authoritative rights matrix remains D02.
- **Legacy paid-install migration.** Migration of old license caches and
  paid-install entries is owner-only (D03). NS21 and NS24 explicitly
  exclude legacy migration; the lane-c report explicitly says no
  fabrication of an old-status envelope.
- **Live Stripe.** No live payment processor wired. NS23/NS26 require it
  (D04). The cloud lane-c report covers the catalog/account contract
  fixtures but production payment enablement stays D04.
- **Funded exchange test.** No venue account with real funds. The brief
  excludes real exchange credentials.
- **Publisher signing identity.** No macOS Developer ID, no Windows
  Authenticode, no `signtool`, no `codesign` (NS29, D06). The lane-c
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

This verdict is scored against the lane-c HEAD only. It is the
NS31 deliverable for the lane-c worktree, not a release. No tag, no
push, no publication.