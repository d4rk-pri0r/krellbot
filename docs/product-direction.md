# Krellbot product direction

## Goal

Krellbot is the local trading workstation for serious crypto automation: author a strategy, reproduce its research, explain its decisions, operate it under explicit controls, and extend it without renting the core engine.

The open-source Python engine and professional local GUI are the product. The website sells optional premium capabilities and distributes packages; it is not a prerequisite in the trading loop. Kraken/Coinbase spot is the existing execution foundation, not evidence of qualified live operation.

The complete target joins strategy definition → costed research → decision explanation → paper deployment → controlled live promotion → monitoring/recovery → export. A graph editor or monitoring console alone does not complete it.

## Delivery sequence

1. BUILD coherent workstation journeys: author, validate, research pinned data, inspect decisions, paper-deploy/observe, pause/restart, and export. Preserve safeguards and prove changed enabled paths with behavior/error tests and applicable regression/type/build checks.
2. HARDEN a frozen functional candidate using a bounded scope and named findings. Do not turn routine development into an indefinite audit campaign.
3. QUALIFY risky capabilities before enabling them: ownership, reconciliation, no blind resubmission, accounting, transactions, recovery and data preservation. Real trading, billing, credentials, signing, publication and production actions require separate owner approval.

Functional, hardened, capability-qualified, packaged and published are distinct states. A research/paper preview is a checkpoint, not a replacement for the full workstation goal.

## Preserved requirements

- One shared application/domain implementation for GUI and CLI; no separate GUI trading semantics.
- Free and user-authored strategies work without a paid account. Existing purchased rights are preserved; pricing changes require the owner.
- Credentials stay at the execution boundary. Telemetry is opt-in and egress is disclosed accurately.
- Billing/store failure must not prevent risk reduction, exits, historical export or diagnostics.
- Deterministic execution under declared inputs; generative AI does not choose orders or override risk in the execution path.
- Unknown order outcome means reconcile, never blindly resubmit.
- User actions have typed results, state transitions, audit records and truthful error presentation.
- Preserve strategy-owned versus external inventory separation and the one-pack-per-(venue,pair) restriction until reservations/ownership are independently qualified.
- Preserve v1 JSON strategy semantics while extending the versioned strategy representation.
- Extend the frozen distribution incrementally; no mandatory desktop-shell rewrite.

## Milestone targets (not completion claims)

- Reconciled compatible base.
- Workstation preview: free edit/validate, pinned-data backtest, inspect v1 evidence, paper arm/observe, pause entries and export.
- Research/editor candidate: reproducible experiments, shared traces, typed temporal graph, robust research.
- Operator beta: durable execution/recovery, qualified live GUI, supervision and restore.
- Optional paid extensions: exact SKU/version rights, trusted package installation/update, website/local integration and separately authorized billing.
- Certified release: exact-head CI/build, truthful platform/signing posture, operational evidence and explicit publication approval.

## Migration baseline and next product work

The standalone development checkout starts from accepted integration commit `8ec5022c17895ec6985e7ef6a4666d5f196f4bc3`, not an older `main`. This document does not claim any whole milestone accepted.

The immediate product task is preserving a Research session across in-session navigation while resetting it when the saved revision changes. Next identified work concerns truthful Jobs observation, refresh/recovery, and the combined Research/Jobs journey. Each task still needs a concrete acceptance test and independent review; they are not an automatically executing queue.

Prior unresolved ownership, recovery, hardening and release findings remain unresolved. Migration does not reopen exhausted repair lanes or authorize live trading, billing, production migration or publication. Historical requirements/findings are preserved outside the development workspace by the operator, not imported as executable instructions.
