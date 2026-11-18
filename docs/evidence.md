# Evidence and trust panel

Copy contract for the public evidence / trust surface. The same facts appear
in the workstation under **Home → Advanced → About this build**
(`data-testid="app-home-about"` / `#app-home` About rail). Site pages on
[krellbot.dev](https://krellbot.dev) should stay consistent with this file
and with [signing.md](signing.md); do not invent a second story.

This panel shows **verifiable install evidence** and **how to reproduce a
starter pack**. It never presents backtests, fixtures, or paper fills as
market performance.

## Pinned digest

Every site-installer cut is integrity-pinned with an **HTTPS SHA-256
manifest**. The installer verifies the digest of the downloaded archive
**before** extract or staging. A digest pins the bytes of that zip; it is
**not** a macOS Developer ID, notarization ticket, Windows Authenticode
signature, or Linux publisher signature.

Where to confirm:

- Installer path and PATH notes: [getting-started.md](getting-started.md#install-the-free-client)
- Engine README install block: [README.md](../README.md#install)
- Live site Security doc: https://krellbot.dev/docs/security.html

## Signing posture (`ARTIFACTS_SIGNED`)

Channel honesty is owned by `src/krellbot/release_channel.py`:

| Flag / claim | Meaning while unsigned |
| --- | --- |
| `ARTIFACTS_SIGNED = False` | Published frozen cuts stay an **unsigned prerelease** |
| `channel = prerelease` | Only honest channel while artifacts are unsigned |
| Gatekeeper / SmartScreen | May show a first-run warning on macOS / Windows |

Until the owner wires signing secrets and cuts a signed release that flips
`ARTIFACTS_SIGNED` (M19.1 / M12.1), **do not claim**:

- signed GA / public non-prerelease
- “no Gatekeeper / SmartScreen first-run warning”
- notarized or Authenticode-signed binaries as the current published cut

Operator secrets, platform expectations, and Linux checksum-only policy:
[signing.md](signing.md). Security overview: [SECURITY.md](../SECURITY.md).

The About rail reads `GET /api/v1/version` and refuses to render a GA claim
when `artifacts_signed` is false.

## Reproduce a starter pack

Outsider reproduction uses only documented web workstation steps. No
exchange credentials and no paid pack are required for paper.

1. Install via the site one-liner, then start the workstation (`krellbot`
   with no arguments, or `krellbot workstation --open`).
2. Open **Strategies**, pick a free **starter** example that ships with
   the release, then **Save** and **Validate**.
3. In the paper-arm form, set venue `kraken` and starting paper balance
   `1000`, then **Arm**. This is simulated cash, not an exchange deposit.
4. Open **Operations**: the deployment must say `paper` and `active`, and
   live trading must remain disabled. **Workstation** also shows the armed
   paper row.
5. Optional research pin: run a backtest on fixed local data from
   **Research**, then reopen the stored job — that is recorded evidence,
   not a live market claim.

Canonical short form: [README.md — Arm your first paper strategy](../README.md#arm-your-first-paper-strategy).
Paper vs fixture honesty: [paper.md](paper.md).

## Honesty rules for this panel

- Name the pinned digest path and the current unsigned / prerelease
  posture; never fabricate a signed GA badge early.
- Cross-link [signing.md](signing.md) whenever signing is mentioned.
- Never present backtest curves, fixture candles, or paper P&L as live
  market performance.
- Telemetry stays opt-in; this panel does not encourage silent upload.
