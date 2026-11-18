# Security

The client is open so you can read what it does before you run it.

- The Exchange wizard requires a native OS keychain; it will not save a key to a plaintext file. The legacy CLI can read an explicitly configured `KRELLBOT_<VEN>_KEYFILE` when no keyring entry exists, subject to file-mode checks on POSIX (or an explicit acknowledgement on Windows). `keys add` itself writes to the keyring, not to that file.
- Credential-source precedence when the engine loads a key is: a complete `KRELLBOT_<VEN>_KEY` and `KRELLBOT_<VEN>_SECRET` environment pair first, then the keyring (including a wizard-stored pair), then an explicitly configured `KRELLBOT_<VEN>_KEYFILE` if no keyring entry exists. A partial environment pair is an error. A successful wizard store does not override existing environment credentials; the live arm gate still probes the key it loads.
- The key should have trade permission on and withdraw permission off.
- krellbot.dev receives a license key if you add packs. It does not receive the exchange key.
- This repository does not contain the paid packs.
- Paper fills stay on this machine, inside `$KRELLBOT_HOME/run/paper-<venue>.json`. No exchange sees a paper fill.
- A live order requires an operator live grant (typed `LIVE` in the workstation) and a key whose withdraw permission is off. CLI `arm --mode live` does not prompt `Type LIVE` on stdin; successful live arm is the web `live.arm` path after that grant.
- Telemetry is off until the operator types `y`. See [docs/telemetry.md](docs/telemetry.md).
- The Exchange wizard step displays only historical status — "last stored through wizard at <ts>; current key presence not checked" or "unknown; not currently verified". It never claims a live connection; CLI-side rotation is not detectable from the page because no credential is read at render time.

## Code signing and notarization

The site installer pins each release to a SHA-256 manifest over HTTPS,
and the installer verifies that digest **before** staging or extracting
the artifact. That checksum pin is always part of the integrity story.

**Current published channel:** frozen binaries are still treated as an
**unsigned prerelease** until owner-held signing secrets are configured
and a signed cut is cut with `ARTIFACTS_SIGNED` flipped. Until then:

- macOS: Gatekeeper may show a first-run warning (Open Anyway).
- Windows: SmartScreen may show a first-run warning (More info → Run anyway).
- Linux: checksum-pinned only; no platform code-signature product.

`release-frozen.yml` can produce Developer ID + notarized macOS and
Authenticode Windows artifacts when signing is requested and the
required GitHub Actions secrets are present (fail closed if requested
but missing). Secret **names**, Gatekeeper / SmartScreen expectations,
and the Linux checksum policy are documented in
[docs/signing.md](docs/signing.md). Never put cert material in the repo.

Install evidence for outsiders (pinned digest, `ARTIFACTS_SIGNED`
posture, how to reproduce a starter pack without market-performance
claims): [docs/evidence.md](docs/evidence.md). The same contract is
surfaced in the workstation under **Home → Advanced → About this
build**.

## Unknown permissions are fail-closed

`krellbot doctor` only reports `trade` and `withdraw` after a real
permission probe ran. Without a probe, the dashboard and the doctor
treat the key's permissions as unknown and refuse to mark
`trading_ready = True`. The key may be in the keyring or in an explicitly
configured legacy keyfile; its presence alone cannot satisfy a green
readiness light until the probe runs.

## Where the workstation talks

The workstation (`krellbot workstation`, `krellbot ui --open`, or bare
`krellbot` on a frozen install — `ui` is an alias for `workstation`)
binds `127.0.0.1` only and refuses non-loopback `Host` headers. Status
reads are local, nonsecret metadata under `$KRELLBOT_HOME`; they do not
probe a venue or read the exchange key. No workstation path sends
exchange credentials to `krellbot.dev`. The bootstrap token is 32 bytes
from `secrets.token_hex(32)` and is delivered via the served HTML meta
tag and the matching session cookie — never in the printed URL.

## First-run wizard and trust screen

A fresh install renders the wizard at `/<token>/welcome` instead of
the dashboard. Welcome and Security are read-only; the Exchange step
accepts a key and secret in one credential-bearing POST, probes the
selected venue, then stores only a trade-only pair in the native keychain.
No wizard page asks for a license token. The Security step renders
the local trust posture from `trust_snapshot()`: the detected
keychain backend class, the resolved `$KRELLBOT_HOME` path and
POSIX mode, the loopback bind, the `live_arm_ui_allowed = False`
rail, and a fail-closed aggregate diagnostic.

The aggregate diagnostic is computed from BOTH the backend and the
home mode. A persistent keychain on a 0o755 home, or a 0o700 home
with no persistent keychain, is still fail-closed: the diagnostic
banner names `krellbot doctor` as the next CLI action. A null backend
is never reported as a green check. The "Key permissions" line on
the Security step is a REQUIREMENT statement ("Trade-only permission
required, withdraw permission never granted. No exchange key is
probed from this page."), not a validated connection — the Security
page does not probe a key. The Exchange POST does.

The wizard's Welcome page states three truthful things: the engine
is free and open-source, exchange keys are stored locally and not sent to
krellbot.dev, and
official packs are optional and recommended. Welcome exposes only
sibling-relative `<a href="security">` / `<a href="next">` links —
there is no Continue button that posts a preference. Only Next's
explicit **Enter dashboard** button POSTs `/<token>/enter-dashboard`
through the existing token/session/CSRF/Origin gate and the server
responds 303 to `/<token>/dashboard` (PRG). A direct GET to
`/<token>/dashboard` never marks the preference, so Back/forward
navigation cannot flip it.

The Next page labels pack adoption (slice D) as a future slice —
not a completed step in this release. Slice C's Exchange (keys)
step is part of the wizard today: the page is reached from the nav
or Security's "Continue to exchange" link, runs a single credentialed
probe-and-store POST, and renders only historical status (the
durable "last stored through wizard at <ts>" timestamp from the
last POST, or "unknown; not currently verified"). It never claims
a live connection and never echoes credentials. The free path today
is the dashboard, the CLI, and `krellbot doctor`.

Static assets are entirely local — no CDN, no Google font, no
external script. The wizard templates and the dashboard shell embed
`window.__KB_VIEW__` as an inline script with every value escaped by
`_embed_json`, so a journal string or trust value containing `<`
cannot close the script tag.

If you find a problem, open an issue on this repository. Do not send a key, a secret, or a license key in the issue.
