import { describe, expect, it } from "vitest";
import { summarizeDraftState } from "./draftStateLabel";

describe("summarizeDraftState", () => {
  it("maps \"draft\" to the Draft label", () => {
    const result = summarizeDraftState("draft");
    expect(result.label).toBe("Draft");
    expect(result.isDraft).toBe(true);
    expect(result.isValidated).toBe(false);
    expect(result.isDeployed).toBe(false);
    expect(result.isArchived).toBe(false);
    expect(result.isKnown).toBe(true);
  });

  it("maps \"validated\" to the Validated label", () => {
    const result = summarizeDraftState("validated");
    expect(result.label).toBe("Validated");
    expect(result.isDraft).toBe(false);
    expect(result.isValidated).toBe(true);
    expect(result.isDeployed).toBe(false);
    expect(result.isArchived).toBe(false);
    expect(result.isKnown).toBe(true);
  });

  it("maps \"deployed\" to the Deployed label", () => {
    const result = summarizeDraftState("deployed");
    expect(result.label).toBe("Deployed");
    expect(result.isDraft).toBe(false);
    expect(result.isValidated).toBe(false);
    expect(result.isDeployed).toBe(true);
    expect(result.isArchived).toBe(false);
    expect(result.isKnown).toBe(true);
  });

  it("maps \"archived\" to the Archived label", () => {
    const result = summarizeDraftState("archived");
    expect(result.label).toBe("Archived");
    expect(result.isDraft).toBe(false);
    expect(result.isValidated).toBe(false);
    expect(result.isDeployed).toBe(false);
    expect(result.isArchived).toBe(true);
    expect(result.isKnown).toBe(true);
  });

  it("returns the unknown record for null", () => {
    const result = summarizeDraftState(null);
    expect(result).toEqual({
      label: "(unknown state)",
      isDraft: false,
      isValidated: false,
      isDeployed: false,
      isArchived: false,
      isKnown: false,
    });
  });

  it("returns the unknown record for undefined", () => {
    const result = summarizeDraftState(undefined);
    expect(result).toEqual({
      label: "(unknown state)",
      isDraft: false,
      isValidated: false,
      isDeployed: false,
      isArchived: false,
      isKnown: false,
    });
  });

  it("treats the empty string as unknown", () => {
    const result = summarizeDraftState("");
    expect(result.label).toBe("(unknown state)");
    expect(result.isKnown).toBe(false);
    expect(result.isDraft).toBe(false);
  });

  it("is case-sensitive (\"DRAFT\" is unknown)", () => {
    const result = summarizeDraftState("DRAFT");
    expect(result.label).toBe("(unknown state)");
    expect(result.isKnown).toBe(false);
  });

  it("treats other strings such as \"running\" as unknown", () => {
    const result = summarizeDraftState("running");
    expect(result.label).toBe("(unknown state)");
    expect(result.isKnown).toBe(false);
    expect(result.isValidated).toBe(false);
    expect(result.isDeployed).toBe(false);
    expect(result.isArchived).toBe(false);
  });
});
