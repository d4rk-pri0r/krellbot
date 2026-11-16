# Code signing and notarization

Owner-held certificates enable platform-native signed macOS and Windows
release artifacts. **Certificate material, passwords, and API keys never
belong in this repository, in chat, or in PR bodies.** Configure them
only as GitHub Actions secrets (and optional vars) on
`d4rkpr10r-Labs/krellbot`.

Until those secrets are present and a tag/dispatch build runs with
signing requested, published cuts remain **unsigned prereleases**.
`ARTIFACTS_SIGNED` in `src/krellbot/release_channel.py` stays `False`
and GitHub Releases stay `--prerelease`. Flipping to GA is an owner
publication decision (M13.3), not this workflow alone.

## When signing runs

| Trigger | Signing behavior |
| --- | --- |
| `pull_request` | Never signs. Unsigned smoke / freeze CI only. No secrets required. |
| `push` of `v*` tag | Signs only when repo variable `KRELLBOT_SIGN_RELEASE` is `true` or `1`. |
| `workflow_dispatch` | Signs when the `sign_release` input is true **or** `KRELLBOT_SIGN_RELEASE` is `true`/`1`. |

When signing is **requested** and a required secret is missing, the
platform job **fails closed** with a clear error naming the missing
secret. When signing is **not** requested, the workflow produces the
existing checksum-pinned unsigned archives.

Workflow: `.github/workflows/release-frozen.yml`.

## Required GitHub Actions secrets (names only)

### Apple (macOS Developer ID + notarization)

| Secret name | Purpose |
| --- | --- |
| `APPLE_DEVELOPER_ID_P12_BASE64` | Base64-encoded Developer ID Application `.p12` |
| `APPLE_DEVELOPER_ID_P12_PASSWORD` | Password for that `.p12` |
| `APPLE_CODESIGN_IDENTITY` | Codesign identity string (e.g. `Developer ID Application: …`) |
| `APPLE_TEAM_ID` | Apple Developer Team ID |
| `APPLE_API_KEY_P8_BASE64` | Base64-encoded App Store Connect API key `.p8` |
| `APPLE_API_KEY_ID` | App Store Connect API Key ID |
| `APPLE_API_ISSUER_ID` | App Store Connect Issuer ID |

### Windows (Authenticode)

| Secret name | Purpose |
| --- | --- |
| `WINDOWS_CODESIGN_P12_BASE64` | Base64-encoded Authenticode `.pfx` / `.p12` |
| `WINDOWS_CODESIGN_P12_PASSWORD` | Password for that certificate file |

## Optional GitHub Actions variables (names only)

| Variable name | Purpose |
| --- | --- |
| `KRELLBOT_SIGN_RELEASE` | Set to `true` to request signing on tag builds (and as a dispatch default override). |
| `WINDOWS_CODESIGN_TIMESTAMP_URL` | Authenticode RFC3161 timestamp URL. Default: `http://timestamp.digicert.com`. |
| `KRELLBOT_RELEASE_BASE_URL` | Existing immutable release CDN base (must be `http(s)` and end with `/`). |

## Gatekeeper (macOS) — expected behavior

**Unsigned / not notarized builds (signing not requested or secrets absent):**

- First launch may show Gatekeeper “cannot be opened because the
  developer cannot be verified.”
- Operator path: System Settings → Privacy & Security → Open Anyway,
  or right-click → Open on the launcher after install.
- Installer still verifies the HTTPS-pinned SHA-256 **before** extract.

**Developer ID–signed and notarized builds (secrets present, signing requested):**

- Gatekeeper should accept the binary after the notarization ticket is
  recorded for those content hashes.
- This product ships a **zip of a PyInstaller one-dir tree**, not a
  `.app` / `.pkg` / `.dmg`. Apple’s stapler applies to those bundle
  types; for zip-distributed onedirs Gatekeeper performs an **online**
  notarization ticket check. Do not claim “stapled” for the zip.
- If notarization was skipped or failed, treat the build as unsigned
  for user messaging — the workflow fails closed rather than publishing
  a half-signed macOS cut when signing was requested.

## SmartScreen (Windows) — expected behavior

**Unsigned builds:**

- SmartScreen may warn “Windows protected your PC.”
- Operator path: More info → Run anyway (after the installer SHA-256
  check has already passed).

**Authenticode-signed builds:**

- A valid publisher signature with a trusted timestamp reduces
  SmartScreen friction. Reputation for a new certificate can still take
  time to build; SmartScreen may warn until the cert accrues trust.
- Docs must not claim “SmartScreen will never warn” — only that the
  binary carries an Authenticode signature when the Windows secrets
  were present and the sign step succeeded.

## Linux signing policy

Linux frozen artifacts in this product are **checksum-pinned**, not
platform code-signed:

- There is no Gatekeeper / Authenticode equivalent shipped for the
  Linux zip today.
- Integrity is the HTTPS-pinned SHA-256 manifest verified before
  extract (same installer path as other platforms).
- Optional `minisign` tooling exists in `scripts/release.py` for
  **wheel** SHA256SUMS in a separate flow; it is **not** wired as a
  required publisher signature for frozen Linux release zips in
  `release-frozen.yml`.
- Honesty rule: do not claim a Linux publisher signature product that
  is not produced by the release workflow.

## Release channel honesty

- Unsigned or partially unsigned tag publishes keep `--prerelease` and
  notes that say **Unsigned** / **Not notarized** / **Not
  Authenticode-signed** when markers show no macOS+Windows signatures.
- When both macOS and Windows markers report signed, notes may say
  Developer ID + notarized and Authenticode, while still labeling the
  GitHub Release a **prerelease** until the owner flips
  `ARTIFACTS_SIGNED` / publication approval.
- `PAPER_ONLY_RELEASE` stays `True` independently of signing.

## Operator checklist (owner)

1. Create Apple Developer ID Application cert + App Store Connect API key; export `.p12` / `.p8`.
2. Obtain Windows Authenticode certificate; export `.pfx`.
3. Paste **only** into GitHub → Settings → Secrets and variables → Actions using the names above.
4. Set variable `KRELLBOT_SIGN_RELEASE=true` when ready for signed tag builds.
5. Cut a `v*` tag (or dispatch with `sign_release=true`) and confirm signing-status artifacts.
6. Only then consider flipping `ARTIFACTS_SIGNED` and M13.3 publication — not before.
