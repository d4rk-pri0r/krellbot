# Community packs

Community pack. Unverified. No guarantee.

The community library lives at
`https://github.com/d4rk-pri0r/krellbot-community-packs`. Anyone can
submit a pack. The maintainers of this repository do not review every
pack and do not run it. Install it only after you have read the pack.

```
krellbot community install <id>
```

`<id>` is the slug the index lists. The command downloads the pack and
writes it under `$KRELLBOT_HOME/packs/community/`. It runs no code from the pack
and asks no exchange for data.

The library is unpaid and unverified. There is no paid community tier.
A community pack does not require a license key. A community pack
places no order that paper mode would not place; live arm on a
community pack still requires the typed `LIVE` confirmation from
`docs/live.md`. Community packs are **not** the signed free/paid catalogue
(M5); they never claim an ed25519-signed paid SKU.

If a pack misbehaves, open an issue on the community repository. Do
not open one here for a pack we did not write.

## Authoring checklist

Use this checklist to author a community pack without reading
`src/krellbot/community.py`. Full DSL rules live in
[pack-format.md](pack-format.md). Getting started for local packs:
[getting-started.md](getting-started.md#what-a-pack-is).

### 1. Write a schema_version 1 DSL pack

Community packs are the same JSON DSL as owned packs. Required keys:

`schema_version`, `id`, `version`, `label`, `author`, `origin`,
`timeframe`, `indicators`, `entry`, `exit`, `risk`, `markets`.

- `schema_version` is `1`.
- `id` is lowercase letters, digits, and dashes; 1 to 32 characters.
  The install path is `<home>/packs/community/<id>.json`, so `id` must
  be a single path segment (no `/`, `\`, or `..`).
- `version` is `MAJOR.MINOR.PATCH`.
- `author` and `origin` are **required** for community submissions
  (each at most 120 characters). `origin` should say the pack is
  community / unverified — for example
  `Community pack. Unverified. No guarantee.`
- `label` is at most 120 characters.
- Indicators, conditions, risk, and markets follow
  [pack-format.md](pack-format.md#dsl-packs). Do not put executable
  code in the file; the client only reads JSON.

Validate locally before opening a PR:

```sh
krellbot lint path/to/your-pack.json
```

### 2. Size and payload limits (install-time)

The Labs installer refuses bodies **over 1_000_000 bytes**
(`MAX_BODY_BYTES`). Prefer a single UTF-8 JSON object. If you ship a
tar archive instead, every entry name must stay inside the install
directory (no `..`, no absolute paths, no escaping symlinks). The
embedded pack `id` in a JSON body must equal the index `id`.

### 3. Place the file in the community repository

In `d4rk-pri0r/krellbot-community-packs`:

1. Add `packs/<id>.json` (filename should match the pack `id`).
2. Regenerate the catalogue (do not hand-edit `index.json`):

   ```sh
   python3 scripts/build_index.py
   ```

3. Open a pull request. Community CI runs `krellbot lint` on changed
   packs and checks that `index.json` matches the generated catalogue.

### 4. Index entry shape

The published index is fetched from:

`https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/index.json`

Labs accepts either a top-level JSON **array** of entries or an object
with a `packs` array. Each entry must include:

| Field | Meaning |
| --- | --- |
| `id` | Pack slug; must match the JSON `id` inside the downloaded body |
| `url` | HTTPS download URL (see allow-list below) |
| `author` | Copied into the index for browse UI (from the pack) |
| `label` | Human label for browse UI (from the pack) |

Example entry:

```json
{
  "id": "trend-follow",
  "author": "community-example",
  "label": "Trend follow",
  "url": "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json"
}
```

### 5. Allow-listed download URL

Install refuses any pack URL that is not:

- scheme `https`
- host exactly `raw.githubusercontent.com`
- path beginning with `/d4rk-pri0r/krellbot-community-packs/`

Foreign hosts, other GitHub orgs/repos, and non-HTTPS URLs are refused
before any body is written under `packs/community/`.

### 6. After install

Installed files land at `$KRELLBOT_HOME/packs/community/<id>.json`.
Read the pack, paper-arm only when you intend to, and treat live arm
the same as any other pack (`docs/live.md`). No billing or paid SKU
redemption applies to this lane.
