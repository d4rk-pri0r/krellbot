export type DraftStateLabel = {
  label: string;
  isDraft: boolean;
  isValidated: boolean;
  isDeployed: boolean;
  isArchived: boolean;
  isKnown: boolean;
};

const UNKNOWN_LABEL = "(unknown state)";

const unknown = (): DraftStateLabel => ({
  label: UNKNOWN_LABEL,
  isDraft: false,
  isValidated: false,
  isDeployed: false,
  isArchived: false,
  isKnown: false,
});

export function summarizeDraftState(
  rawState: string | null | undefined,
): DraftStateLabel {
  switch (rawState) {
    case "draft":
      return { label: "Draft", isDraft: true, isValidated: false, isDeployed: false, isArchived: false, isKnown: true };
    case "validated":
      return { label: "Validated", isDraft: false, isValidated: true, isDeployed: false, isArchived: false, isKnown: true };
    case "deployed":
      return { label: "Deployed", isDraft: false, isValidated: false, isDeployed: true, isArchived: false, isKnown: true };
    case "archived":
      return { label: "Archived", isDraft: false, isValidated: false, isDeployed: false, isArchived: true, isKnown: true };
    default:
      return unknown();
  }
}
