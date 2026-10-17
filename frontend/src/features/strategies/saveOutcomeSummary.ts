export type SaveOutcomeKind = "created" | "unchanged" | "existing" | "other";

export type SaveOutcomeSummary = {
  label: string;
  revisionId: string;
  kind: SaveOutcomeKind;
  isNew: boolean;
  isExisting: boolean;
  isUnchanged: boolean;
  isOther: boolean;
  isKnown: boolean;
};

const NO_REVISION_ID = "(no revision id)";

export function summarizeSaveOutcome(
  kind: SaveOutcomeKind,
  revisionId: string | null | undefined,
): SaveOutcomeSummary {
  const id = typeof revisionId === "string" && revisionId.length > 0 ? revisionId : NO_REVISION_ID;
  const hasId = id !== NO_REVISION_ID;
  let label: string;
  if (kind === "created") {
    label = hasId ? `saved new revision ${id}` : "saved new revision";
  } else if (kind === "unchanged") {
    label = hasId ? `no change: revision ${id} kept` : "no change: no revision kept";
  } else if (kind === "existing") {
    label = hasId ? `selected existing revision ${id}` : "selected existing revision";
  } else {
    label = hasId ? `saved revision ${id}` : "saved revision";
  }
  return {
    label,
    revisionId: id,
    kind,
    isNew: kind === "created",
    isExisting: kind === "existing",
    isUnchanged: kind === "unchanged",
    isOther: kind === "other",
    isKnown: kind === "created" || kind === "unchanged" || kind === "existing",
  };
}
