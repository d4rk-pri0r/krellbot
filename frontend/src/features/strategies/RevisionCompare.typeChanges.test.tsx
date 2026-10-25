import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LibraryClient, OwnedRevisionBytes } from "./libraryClient";
import type { OwnedDraftSummary } from "./SavedStrategyLibrary";
import { RevisionCompare } from "./RevisionCompare";

/*
 * RevisionCompare — JSON type-collision regression (compare-types).
 *
 * On base, diffValue decided equality from formatted display text:
 * formatValue unquotes JSON strings, so a stored JSON number 14 and a
 * stored JSON string "14" both formatted to `14` and the surface
 * reported ZERO differences (same for true/"true", null/"null",
 * {}/"{}", [..]/"[..]"). These tests drive the component exactly as
 * production drives it — packs served as stored bytes through the
 * authenticated LibraryClient getJson, then the Compare action — and
 * require the underlying JSON semantics to be compared instead:
 * every type collision must render the existing changed row at the
 * correct path with distinguishable values, the string side shown
 * JSON-quoted (with escaping) while other JSON values keep their JSON
 * representation. Same-type string edits stay unquoted, and identical
 * JSON, ordinary edits, additions/removals, and absent-versus-null
 * meanings are pinned as controls. No value below is invented or
 * converted: each comes from the stored pack bytes only.
 */

afterEach(cleanup);

function summary(overrides: Partial<OwnedDraftSummary> = {}): OwnedDraftSummary {
  return {
    revision_id: "rev-1",
    strategy_id: "trend-follow",
    parent_revision_id: null,
    state: "draft",
    runnable: false,
    created_at: "2026-10-07T10:00:00Z",
    id: "trend-follow",
    label: "Trend follow",
    pair: "SUIUSD",
    timeframe: "1h",
    ...overrides,
  };
}

function revision(
  revisionId: string,
  pack: Record<string, unknown>,
): OwnedRevisionBytes {
  return {
    revision_id: revisionId,
    state: "draft",
    bytes: JSON.stringify(pack),
  };
}

function clientWith(
  packs: Record<string, Record<string, unknown>>,
): LibraryClient & { getJson: ReturnType<typeof vi.fn> } {
  return {
    listOwned: vi.fn(),
    getJson: vi.fn((revisionId: string): Promise<OwnedRevisionBytes> => {
      const pack = packs[revisionId];
      if (!pack) {
        return Promise.reject(new Error("library open failed: 404"));
      }
      return Promise.resolve(revision(revisionId, pack));
    }),
  };
}

async function renderCompared(
  packs: Record<string, Record<string, unknown>>,
): Promise<void> {
  const client = clientWith(packs);
  const rows = [
    summary({ revision_id: "rev-2", parent_revision_id: "rev-1", label: "Edited" }),
    summary(),
  ];
  render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
  fireEvent.click(screen.getByTestId("revision-compare-run"));
  // Wait for either terminal outcome; the per-row assertions then pin
  // exactly which rows and values the comparison must produce.
  await waitFor(() =>
    expect(
      screen.queryByTestId("revision-compare-summary") ??
        screen.queryByTestId("revision-compare-identical"),
    ).not.toBeNull(),
  );
}

function changeRow(path: string): HTMLTableRowElement {
  const found = screen
    .getAllByTestId("revision-compare-change")
    .find((element) => element.querySelector("code")?.textContent === path);
  if (!found) {
    throw new Error(`no compare row rendered for path ${path}`);
  }
  return found as HTMLTableRowElement;
}

function changePaths(): string[] {
  return screen
    .getAllByTestId("revision-compare-change")
    .map((element) => element.querySelector("code")?.textContent ?? "");
}

describe("RevisionCompare — JSON type collisions between saved revisions", () => {
  it("reports a JSON number 14 versus a JSON string \"14\" as one change with distinguishable values", async () => {
    await renderCompared({
      "rev-1": { level: 14 },
      "rev-2": { level: "14" },
    });
    expect(changePaths()).toEqual(["level"]);
    const row = changeRow("level");
    expect(row.getAttribute("data-kind")).toBe("changed");
    expect(row.cells[2].textContent).toBe("14");
    expect(row.cells[3].textContent).toBe('"14"');
    expect(screen.getByTestId("revision-summary-changed").textContent).toBe(
      "1 changed",
    );
  });

  it("keeps the collision detectable in the opposite direction with sides swapped", async () => {
    await renderCompared({
      "rev-1": { level: "14" },
      "rev-2": { level: 14 },
    });
    const row = changeRow("level");
    expect(row.getAttribute("data-kind")).toBe("changed");
    expect(row.cells[2].textContent).toBe('"14"');
    expect(row.cells[3].textContent).toBe("14");
  });

  it("detects boolean versus string \"true\" in both directions", async () => {
    await renderCompared({
      "rev-1": { enabled: true },
      "rev-2": { enabled: "true" },
    });
    expect(changeRow("enabled").cells[2].textContent).toBe("true");
    expect(changeRow("enabled").cells[3].textContent).toBe('"true"');
  });

  it("detects the reversed boolean versus string \"true\" collision", async () => {
    await renderCompared({
      "rev-1": { enabled: "true" },
      "rev-2": { enabled: true },
    });
    expect(changeRow("enabled").cells[2].textContent).toBe('"true"');
    expect(changeRow("enabled").cells[3].textContent).toBe("true");
  });

  it("detects null versus string \"null\" in both directions", async () => {
    await renderCompared({
      "rev-1": { fallback: null },
      "rev-2": { fallback: "null" },
    });
    expect(changeRow("fallback").cells[2].textContent).toBe("null");
    expect(changeRow("fallback").cells[3].textContent).toBe('"null"');
  });

  it("detects the reversed null versus string \"null\" collision", async () => {
    await renderCompared({
      "rev-1": { fallback: "null" },
      "rev-2": { fallback: null },
    });
    expect(changeRow("fallback").cells[2].textContent).toBe('"null"');
    expect(changeRow("fallback").cells[3].textContent).toBe("null");
  });

  it("detects an empty object versus string \"{}\" in both directions", async () => {
    await renderCompared({
      "rev-1": { risk: {} },
      "rev-2": { risk: "{}" },
    });
    expect(changeRow("risk").cells[2].textContent).toBe("{}");
    expect(changeRow("risk").cells[3].textContent).toBe('"{}"');
  });

  it("detects the reversed empty object versus string \"{}\" collision", async () => {
    await renderCompared({
      "rev-1": { risk: "{}" },
      "rev-2": { risk: {} },
    });
    expect(changeRow("risk").cells[2].textContent).toBe('"{}"');
    expect(changeRow("risk").cells[3].textContent).toBe("{}");
  });

  it("detects an array versus its JSON-text string with escaping shown on the string side", async () => {
    await renderCompared({
      "rev-1": { tags: ["a"] },
      "rev-2": { tags: '["a"]' },
    });
    const row = changeRow("tags");
    expect(row.getAttribute("data-kind")).toBe("changed");
    expect(row.cells[2].textContent).toBe('["a"]');
    expect(row.cells[3].textContent).toBe('"[\\"a\\"]"');
  });

  it("detects the reversed array versus JSON-text string collision", async () => {
    await renderCompared({
      "rev-1": { tags: '["a"]' },
      "rev-2": { tags: ["a"] },
    });
    expect(changeRow("tags").cells[2].textContent).toBe('"[\\"a\\"]"');
    expect(changeRow("tags").cells[3].textContent).toBe('["a"]');
  });

  it("escapes quotes inside a quoted string on a type-changed row", async () => {
    await renderCompared({
      "rev-1": { note: 'say "hi"' },
      "rev-2": { note: true },
    });
    const row = changeRow("note");
    expect(row.cells[2].textContent).toBe('"say \\"hi\\""');
    expect(row.cells[3].textContent).toBe("true");
  });

  it("detects number/string collisions at a nested object path", async () => {
    await renderCompared({
      "rev-1": { risk: { stop: { multiple: 14 } }, label: "Trend follow" },
      "rev-2": { risk: { stop: { multiple: "14" } }, label: "Trend follow" },
    });
    expect(changePaths()).toEqual(["risk.stop.multiple"]);
    const row = changeRow("risk.stop.multiple");
    expect(row.cells[2].textContent).toBe("14");
    expect(row.cells[3].textContent).toBe('"14"');
  });

  it("detects collisions inside arrays and nested array elements with stable path order", async () => {
    await renderCompared({
      "rev-1": { alerts: [14], indicators: [{ period: 14 }], zero: 0 },
      "rev-2": { alerts: ["14"], indicators: [{ period: "14" }], zero: 0 },
    });
    expect(changePaths()).toEqual(["alerts[0]", "indicators[0].period"]);
    expect(changeRow("alerts[0]").cells[3].textContent).toBe('"14"');
    expect(changeRow("indicators[0].period").cells[3].textContent).toBe('"14"');
  });

  it("detects a nested container-type replacement at its exact path", async () => {
    await renderCompared({
      "rev-1": { matrix: [[1]], risk: { stop: {} }, label: "Trend follow" },
      "rev-2": { matrix: "[[1]]", risk: { stop: "{}" }, label: "Trend follow" },
    });
    expect(changePaths()).toEqual(["matrix", "risk.stop"]);
    const matrix = changeRow("matrix");
    expect(matrix.cells[2].textContent).toBe("[[1]]");
    expect(matrix.cells[3].textContent).toBe('"[[1]]"');
    const stop = changeRow("risk.stop");
    expect(stop.cells[2].textContent).toBe("{}");
    expect(stop.cells[3].textContent).toBe('"{}"');
  });

  it("detects a nested object/string replacement in the reversed direction", async () => {
    await renderCompared({
      "rev-1": { risk: { stop: "{}" } },
      "rev-2": { risk: { stop: {} } },
    });
    const stop = changeRow("risk.stop");
    expect(stop.cells[2].textContent).toBe('"{}"');
    expect(stop.cells[3].textContent).toBe("{}");
  });
});

describe("RevisionCompare — type-collision controls stay intact", () => {
  it("still reports no differences for identical JSON, including colliding-looking scalars", async () => {
    for (const pack of [{ level: 14 }, { level: "14" }, { on: true, off: null }]) {
      cleanup();
      const client = clientWith({ "rev-1": pack, "rev-2": pack });
      const rows = [
        summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
        summary(),
      ];
      render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
      fireEvent.click(screen.getByTestId("revision-compare-run"));
      await waitFor(() =>
        expect(screen.getByTestId("revision-compare-identical")).toBeDefined(),
      );
      expect(screen.queryByTestId("revision-compare-changes")).toBeNull();
    }
  });

  it("keeps ordinary same-type edits as single changed rows with JSON values", async () => {
    await renderCompared({
      "rev-1": { level: 14, enabled: false },
      "rev-2": { level: 15, enabled: false },
    });
    expect(changePaths()).toEqual(["level"]);
    expect(changeRow("level").cells[2].textContent).toBe("14");
    expect(changeRow("level").cells[3].textContent).toBe("15");
  });

  it("preserves the existing unquoted display for same-type string edits", async () => {
    await renderCompared({
      "rev-1": { timeframe: "1h" },
      "rev-2": { timeframe: "4h" },
    });
    const row = changeRow("timeframe");
    expect(row.cells[2].textContent).toBe("1h");
    expect(row.cells[3].textContent).toBe("4h");
  });

  it("keeps additions and removals of string values unquoted with absence markers", async () => {
    await renderCompared({
      "rev-1": { gone: "14" },
      "rev-2": {},
    });
    const removed = changeRow("gone");
    expect(removed.getAttribute("data-kind")).toBe("removed");
    expect(removed.cells[2].textContent).toBe("14");
    expect(removed.cells[3].textContent).toBe("— (not present)");
  });

  it("keeps added string values unquoted on added rows", async () => {
    await renderCompared({
      "rev-1": {},
      "rev-2": { fresh: "14" },
    });
    const added = changeRow("fresh");
    expect(added.getAttribute("data-kind")).toBe("added");
    expect(added.cells[2].textContent).toBe("— (not present)");
    expect(added.cells[3].textContent).toBe("14");
  });

  it("preserves absent-versus-null meanings around JSON null", async () => {
    await renderCompared({
      "rev-1": { opt: null },
      "rev-2": {},
    });
    const removed = changeRow("opt");
    expect(removed.getAttribute("data-kind")).toBe("removed");
    expect(removed.cells[2].textContent).toBe("null");
    expect(removed.cells[3].textContent).toBe("— (not present)");
  });

  it("shows a stored JSON null distinctly when a key is added", async () => {
    await renderCompared({
      "rev-1": {},
      "rev-2": { opt: null },
    });
    const added = changeRow("opt");
    expect(added.getAttribute("data-kind")).toBe("added");
    expect(added.cells[3].textContent).toBe("null");
  });
});
