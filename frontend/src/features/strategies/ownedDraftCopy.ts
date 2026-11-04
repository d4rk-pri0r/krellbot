// Owned-draft copy: seed a NEW draft from an existing OWNED saved
// revision's real bytes.
//
// Only the pack identity fields are re-derived (fresh id, copy-marked
// label). Every rule, indicator, risk and market setting is preserved
// from the origin bytes, which are never mutated: the origin string is
// parsed and a new string is produced. The origin revision's stored
// bytes/state/arm state are untouched — saving the copy is a create,
// not an edit of the origin.

import type { Pack } from "./client";

export type OwnedCopyOrigin = {
  revision_id: string;
  state: string;
  created_at?: string;
  strategy_id?: string;
  label?: string;
};

export type OwnedDraftCopy = {
  /** Copied pack bytes with a fresh id and copy-marked label. */
  bytes: string;
  origin: OwnedCopyOrigin;
  /** The origin revision's own label, for display. */
  originLabel: string | null;
};

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;
const ID_MAX = 32;
const LABEL_MAX = 120;

function parseObject(text: string): Pack | null {
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as Pack;
    }
    return null;
  } catch {
    return null;
  }
}

function freshId(base: string): string {
  const slug = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  // Reserve the random suffix before truncating the human-readable prefix.
  // Truncating the assembled id discarded all randomness for long origins.
  const suffix = crypto.randomUUID().replaceAll("-", "").slice(0, 20);
  const marker = "-copy-";
  const prefix = (slug || "strategy").slice(0, ID_MAX - marker.length - suffix.length);
  return `${prefix}${marker}${suffix}`;
}

export function copyOriginLabel(origin: OwnedCopyOrigin): string {
  return `copy of ${origin.revision_id}`;
}

export function buildOwnedDraftCopy(
  originBytes: string,
  origin: OwnedCopyOrigin,
): OwnedDraftCopy | null {
  const pack = parseObject(originBytes);
  if (!pack) {
    return null;
  }
  const baseId = typeof pack.id === "string" && ID_PATTERN.test(pack.id)
    ? pack.id
    : "strategy";
  const baseLabel = typeof pack.label === "string" && pack.label.length > 0
    ? pack.label
    : baseId;
  // The origin marker must survive the schema's 120-char label bound:
  // truncate the origin label, never the marker.
  const marker = ` (${copyOriginLabel(origin)})`;
  const label =
    baseLabel.length + marker.length <= LABEL_MAX
      ? `${baseLabel}${marker}`
      : `${baseLabel.slice(0, LABEL_MAX - marker.length)}${marker}`;
  const next: Pack = {
    ...pack,
    id: freshId(baseId),
    label,
  };
  return {
    bytes: JSON.stringify(next, null, 2),
    origin,
    originLabel: typeof pack.label === "string" ? pack.label : null,
  };
}
