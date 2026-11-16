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
existing checksum-pinned unsigned archives (macOS stays a one-dir zip).

Workflow: `.github/workflows/release-frozen.yml`.

## macOS artifact shape

| Signing requested? | Release zip contents |
| --- | --- |
| No | PyInstaller **one-dir** tree (`krellbot` + `_internal/`, same as today). |
| Yes | Stapled **`Krellbot.app`** at the zip root (`Krellbot.app/Contents/…`). |

Signed path (secrets present):

1. Freeze one-dir at `dist/krellbot`.
2. Wrap into `dist/Krellbot.app` (`scripts/macos_app_bundle.py`):
   `Contents/MacOS/krellbot` + `_internal/`, plus `Contents/Info.plist`
   (`CFBundleIdentifier`, `LSMinimumSystemVersion`, version keys).
3. Deep codesign nested Mach-O, then the `.app`, with hardened runtime,
   timestamp, and `scripts/macos_entitlements.plist`.
4. Zip the `.app` for submit → `notarytool … --wait` →
   `xcrun stapler staple` + `stapler validate` on the `.app`.
5. Ship `krellbot-macos-*.zip` of the **stapled** `.app` (SHA-256
   manifest unchanged in shape).

**Stapling is claimed only for the `.app`.** Do not claim stapling for
a bare one-dir zip or for the outer download zip file itself.

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

- Artifact is still the one-dir zip.
- First launch may show Gatekeeper “cannot be opened because the
  developer cannot be verified.”
- Operator path: System Settings → Privacy & Security → Open Anyway,
  or right-click → Open on the launcher after install.
- Installer still verifies the HTTPS-pinned SHA-256 **before** extract.

**Developer ID–signed, notarized, stapled `.app` (secrets present, signing requested):**

- Release zip contains `Krellbot.app/…` after a successful staple.
- Gatekeeper can validate offline via the stapled ticket on the `.app`.
- Stapling applies to the `.app` bundle only — not to the outer `.zip`.
- If notarization or staple fails, the job fails closed (no half-signed
  macOS cut when signing was requested).

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

## krellbot-cloud installer contract (caveat)

Unsigned macOS zips keep the historical **one-dir** layout that the
site installer (`krellbot-cloud`) already stages.

**Signed macOS zips change the payload layout** to a top-level
`Krellbot.app`. Before enabling `KRELLBOT_SIGN_RELEASE` for real macOS
users, `krellbot-cloud` must:

1. After SHA-256 verify + extract, detect `Krellbot.app/` (vs top-level
   `krellbot` + `_internal/`).
2. Stage either the whole `.app` or
   `Krellbot.app/Contents/MacOS/{krellbot,_internal}` into the version
   directory the launcher expects.
3. Point the managed `krellbot` launcher at
   `…/Krellbot.app/Contents/MacOS/krellbot` (or an equivalent shim).
4. Keep the HTTPS-pinned SHA-256 check **before** extract; the digest
   is of the zip bytes, not of an inner member.

Until that cloud change lands, leave `KRELLBOT_SIGN_RELEASE` unset so
macOS continues to publish one-dir unsigned zips.

## Release channel honesty

- Unsigned or partially unsigned tag publishes keep `--prerelease` and
  notes that say **Unsigned** / **Not notarized** / **Not
  Authenticode-signed** when markers show no macOS+Windows signatures.
- When both macOS and Windows markers report signed, notes may say
  Developer ID + notarized + stapled `.app` and Authenticode, while
  still labeling the GitHub Release a **prerelease** until the owner
  flips `ARTIFACTS_SIGNED` / publication approval.
- `PAPER_ONLY_RELEASE` stays `True` independently of signing.

## Operator checklist (owner)

1. Create Apple Developer ID Application cert + App Store Connect API key; export `.p12` / `.p8`.
2. Obtain Windows Authenticode certificate; export `.pfx`.
3. Paste **only** into GitHub → Settings → Secrets and variables → Actions using the names above.
4. Update `krellbot-cloud` to accept stapled `Krellbot.app` zips (see caveat above).
5. Set variable `KRELLBOT_SIGN_RELEASE=true` when ready for signed tag builds.
6. Cut a `v*` tag (or dispatch with `sign_release=true`) and confirm signing-status artifacts + staple.
7. Only then consider flipping `ARTIFACTS_SIGNED` and M13.3 publication — not before.
