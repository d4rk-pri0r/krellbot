export type StatusPackParts = {
  label: string;
  packId: string;
  venue: string;
  pair: string;
  isComplete: boolean;
  isPackOnly: boolean;
  isVenueOnly: boolean;
  isPairOnly: boolean;
  isMissing: boolean;
  isPartial: boolean;
};

export function summarizeStatusPack(
  rawPackId: string | null | undefined,
  rawVenue: string | null | undefined,
  rawPair: string | null | undefined,
): StatusPackParts {
  const packId =
    typeof rawPackId === "string" && rawPackId.length > 0 ? rawPackId : "";
  const venue =
    typeof rawVenue === "string" && rawVenue.length > 0 ? rawVenue : "";
  const pair = typeof rawPair === "string" && rawPair.length > 0 ? rawPair : "";

  const isComplete = packId !== "" && venue !== "" && pair !== "";
  const isMissing = packId === "" && venue === "" && pair === "";
  const isPackOnly = packId !== "" && venue === "" && pair === "";
  const isVenueOnly = packId === "" && venue !== "" && pair === "";
  const isPairOnly = packId === "" && venue === "" && pair !== "";
  // isPartial means exactly two of the three parts are set; the single-part
  // cases are covered by the is*Only discriminators.
  const isPartial =
    !isComplete &&
    !isMissing &&
    !isPackOnly &&
    !isVenueOnly &&
    !isPairOnly;

  let label: string;
  if (packId !== "") {
    if (venue !== "") {
      label = pair !== "" ? `${packId} on ${venue} ${pair}` : `${packId} on ${venue}`;
    } else {
      label = pair !== "" ? `${packId} on ${pair}` : packId;
    }
  } else if (venue !== "") {
    label = pair !== "" ? `${venue} ${pair}` : venue;
  } else if (pair !== "") {
    label = pair;
  } else {
    label = "(no pack)";
  }

  return {
    label,
    packId,
    venue,
    pair,
    isComplete,
    isPackOnly,
    isVenueOnly,
    isPairOnly,
    isMissing,
    isPartial,
  };
}
