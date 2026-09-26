# Security

The client is open so you can read what it does before you run it.

- An exchange key is stored in the OS keychain when one is available. The file fallback is mode 0600 and stays on your machine.
- The key should have trade permission on and withdraw permission off.
- krellbot.dev receives a license key if you add packs. It does not receive the exchange key.
- This repository does not contain the paid packs.
- Paper fills stay on this machine, inside `$KRELLBOT_HOME/run/paper-<venue>.json`. No exchange sees a paper fill.
- A live order requires typing `LIVE` exactly at the first arm prompt and a key whose withdraw permission is off. The typed confirmation is a CLI-only path; the dashboard refuses live arm.
- Telemetry is off until the operator types `y`. See [docs/telemetry.md](docs/telemetry.md).

## Code signing and notarization

The site installer pins each release to a SHA-256 manifest over HTTPS,
and the installer verifies that digest **before** staging or extracting
the artifact. That is the integrity guarantee today.

The frozen binaries themselves are **not** code-signed and **not**
notarized in this release:

- macOS: not Apple Developer ID–signed, so Gatekeeper may show a
  first-run warning. Use "Open Anyway" from System Settings the first
  time, or run the installer's smoke check.
- Windows: not Authenticode–signed, so SmartScreen may show a
  first-run warning. Click "More info" → "Run anyway".
- Linux: no `gpg`/`minisign` publisher signature.

The HTTPS-pinned SHA-256 protects transport and integrity against a
modified download, but it is **not** an independent publisher signature.
Code signing, notarization, and signed publisher releases are a future
hardening step; today the docs must not claim a higher bar than the
verifier enforces.

## Unknown permissions are fail-closed

`krellbot doctor` only reports `trade` and `withdraw` after a real
permission probe ran. Without a probe, the dashboard and the doctor
treat the key's permissions as unknown and refuse to mark
`trading_ready = True`. The key itself is still on disk; it just
cannot satisfy a green readiness light until the probe runs.

## Where the dashboard talks

The dashboard (`krellbot ui`, `krellbot ui --open`, `krellbot ui
--port N`) binds `127.0.0.1` only, refuses non-loopback `Host`
headers, and reads only from disk under `$KRELLBOT_HOME`. It never
calls Kraken, Coinbase, or `krellbot.dev`. The gate token is 32 bytes
from `secrets.token_hex(32)` and lives only in the URL the CLI prints
and the matching `krellbot_session` cookie.

## First-run wizard and trust screen

A fresh install renders the wizard at `/<token>/welcome` instead of
the dashboard. The wizard is read-only — it never accepts a key, a
secret, or a license token in the browser. The Security step renders
the local trust posture from `trust_snapshot()`: the detected
keychain backend class, the resolved `$KRELLBOT_HOME` path and
POSIX mode, the loopback bind, the `live_arm_ui_allowed = False`
rail, and a fail-closed diagnostic if the keychain is not persistent.
The diagnostic names `krellbot doctor` as the next CLI action. A
null backend is never reported as a green check.

The wizard's Welcome page states three truthful things: the engine
is free and open-source, exchange keys stay on this machine, and
official packs are optional and recommended. The Next page labels
exchange connection (slice C) and pack adoption (slice D) as future
slices — they are not completed steps in this release. The free path
today is the dashboard, the CLI, and `krellbot doctor`.

Static assets are entirely local — no CDN, no Google font, no
external script. The wizard templates and the dashboard shell embed
`window.__KB_VIEW__` as an inline script with every value escaped by
`_embed_json`, so a journal string or trust value containing `<`
cannot close the script tag.

If you find a problem, open an issue on this repository. Do not send a key, a secret, or a license key in the issue.
