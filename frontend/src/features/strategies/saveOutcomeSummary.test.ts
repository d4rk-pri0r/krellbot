import { describe, expect, it } from "vitest";
import { summarizeSaveOutcome } from "./saveOutcomeSummary";

describe("summarizeSaveOutcome", () => {
  it("maps a created outcome to the friendly label and created discriminators", () => {
    const summary = summarizeSaveOutcome("created", "r-123");
    expect(summary.label).toBe("saved new revision r-123");
    expect(summary.revisionId).toBe("r-123");
    expect(summary.kind).toBe("created");
    expect(summary.isNew).toBe(true);
    expect(summary.isUnchanged).toBe(false);
    expect(summary.isExisting).toBe(false);
    expect(summary.isOther).toBe(false);
    expect(summary.isKnown).toBe(true);
  });

  it("maps an unchanged outcome to the kept-revision label", () => {
    const summary = summarizeSaveOutcome("unchanged", "r-456");
    expect(summary.label).toBe("no change: revision r-456 kept");
    expect(summary.revisionId).toBe("r-456");
    expect(summary.kind).toBe("unchanged");
    expect(summary.isUnchanged).toBe(true);
    expect(summary.isNew).toBe(false);
    expect(summary.isKnown).toBe(true);
  });

  it("maps an existing outcome to the selected-existing label", () => {
    const summary = summarizeSaveOutcome("existing", "r-789");
    expect(summary.label).toBe("selected existing revision r-789");
    expect(summary.revisionId).toBe("r-789");
    expect(summary.kind).toBe("existing");
    expect(summary.isExisting).toBe(true);
    expect(summary.isNew).toBe(false);
    expect(summary.isKnown).toBe(true);
  });

  it("maps an other outcome to the plain saved label and marks it unknown", () => {
    const summary = summarizeSaveOutcome("other", "r-012");
    expect(summary.label).toBe("saved revision r-012");
    expect(summary.revisionId).toBe("r-012");
    expect(summary.kind).toBe("other");
    expect(summary.isOther).toBe(true);
    expect(summary.isKnown).toBe(false);
  });

  it("treats a null revision id as '(no revision id)' for created", () => {
    const summary = summarizeSaveOutcome("created", null);
    expect(summary.label).toBe("saved new revision");
    expect(summary.revisionId).toBe("(no revision id)");
  });

  it("treats an undefined revision id as '(no revision id)' for unchanged", () => {
    const summary = summarizeSaveOutcome("unchanged", undefined);
    expect(summary.label).toBe("no change: no revision kept");
    expect(summary.revisionId).toBe("(no revision id)");
  });

  it("treats an empty-string revision id as '(no revision id)' for existing", () => {
    const summary = summarizeSaveOutcome("existing", "");
    expect(summary.label).toBe("selected existing revision");
    expect(summary.revisionId).toBe("(no revision id)");
  });

  it("maps another id for other without inventing a 'new' prefix", () => {
    const summary = summarizeSaveOutcome("other", "r-345");
    expect(summary.label).toBe("saved revision r-345");
    expect(summary.isOther).toBe(true);
  });

  it("returns structurally equal summaries for repeated identical inputs", () => {
    const first = summarizeSaveOutcome("created", "r-123");
    const second = summarizeSaveOutcome("created", "r-123");
    expect(first).toEqual(second);
    expect(first).not.toBe(second);
  });
});
