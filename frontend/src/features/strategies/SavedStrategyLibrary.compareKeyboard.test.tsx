import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
} from "./SavedStrategyLibrary";

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

const libraryRows = [
  summary({
    revision_id: "rev-2",
    label: "Edited",
    state: "validated",
    runnable: true,
    created_at: "2026-10-07T12:00:00Z",
    parent_revision_id: "rev-1",
  }),
  summary(),
];

// Only the authenticated read boundary is faked; the real component,
// shortcut handler, and RevisionCompare mount all run.
function makeClient(rows: OwnedDraftSummary[]): LibraryClient {
  return {
    listOwned: vi.fn().mockResolvedValue(rows),
    getJson: vi.fn((revisionId: string) =>
      Promise.resolve({
        revision_id: revisionId,
        state: "draft" as const,
        bytes: `{"id":"trend-follow","revision":"${revisionId}"}`,
      }),
    ),
  };
}

async function mountLibrary(rows: OwnedDraftSummary[] = libraryRows) {
  const client = makeClient(rows);
  render(<SavedStrategyLibrary client={client} onReopen={vi.fn()} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("library-row-compare").length).toBe(rows.length),
  );
  return client;
}

function compareButtons(): HTMLButtonElement[] {
  return screen.getAllByTestId<HTMLButtonElement>("library-row-compare");
}

function chord(target: Element, options = {}): boolean {
  return fireEvent.keyDown(target, { key: "c", ctrlKey: true, altKey: true, ...options });
}

describe("SavedStrategyLibrary — per-row Compare keyboard activation aria", () => {
  it("announces the activation shortcut and a row-specific name on every Compare button", async () => {
    await mountLibrary();
    const [edited, base] = compareButtons();
    for (const button of [edited, base]) {
      expect(button.getAttribute("aria-keyshortcuts")).toBe("Control+Alt+C Meta+Alt+C");
    }
    expect(edited.getAttribute("aria-label")).toBe("Compare revisions of Edited");
    expect(base.getAttribute("aria-label")).toBe("Compare revisions of Trend follow");
    expect(edited.textContent).toBe("Compare");
    expect(base.textContent).toBe("Compare");
  });

  it.each([
    ["strategy_id when the label is empty", { label: "", strategy_id: "trend-follow-1" }, "trend-follow-1"],
    ["pack id when label and strategy_id are empty", { label: "", strategy_id: "", id: "pack-7" }, "pack-7"],
    ["(untitled) when every identity field is empty", { label: "", strategy_id: "", id: "" }, "(untitled)"],
  ])("derives the announced name from %s", async (_, overrides, expected) => {
    await mountLibrary([summary({ revision_id: "rev-x", ...overrides })]);
    expect(compareButtons()[0].getAttribute("aria-label")).toBe(
      `Compare revisions of ${expected}`,
    );
  });

  it("exposes each row's Compare through its row-specific accessible name", async () => {
    await mountLibrary();
    expect(
      screen.getAllByRole("button", { name: "Compare revisions of Edited" }).length,
    ).toBe(1);
    expect(
      screen.getAllByRole("button", { name: "Compare revisions of Trend follow" }).length,
    ).toBe(1);
  });
});

describe("SavedStrategyLibrary — Control+Alt+C / Meta+Alt+C activation", () => {
  it.each([
    ["Control+Alt+C", { ctrlKey: true, metaKey: false, altKey: true, key: "c" }],
    ["Meta+Alt+C", { ctrlKey: false, metaKey: true, altKey: true, key: "C" }],
  ])("%s opens Compare for the row whose button holds focus", async (_, keys) => {
    await mountLibrary();
    const edited = compareButtons()[0];
    edited.focus();
    expect(document.activeElement).toBe(edited);
    const notDefaultPrevented = chord(edited, keys);
    expect(notDefaultPrevented).toBe(false);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
  });

  it("resolves the focused row's revision, not the first row", async () => {
    const client = await mountLibrary();
    const edited = compareButtons()[0];
    edited.focus();
    chord(edited);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    // The compare surface defaults its earlier/later pick from the row that
    // opened it, proving the shortcut carried the focused row's revision.
    expect(
      (screen.getByTestId("revision-compare-left") as HTMLSelectElement).value,
    ).toBe("rev-1");
    expect(
      (screen.getByTestId("revision-compare-right") as HTMLSelectElement).value,
    ).toBe("rev-2");
    expect(client.listOwned).toHaveBeenCalledTimes(1);
  });

  it("opens the first row's Compare when the library region itself holds focus", async () => {
    await mountLibrary();
    const section = screen.getByTestId("saved-strategy-library");
    // Real focus on the focusable region; no faked document.activeElement.
    section.focus();
    expect(document.activeElement).toBe(section);
    expect(chord(section)).toBe(false);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    // rows[0] is the first listed revision ("Edited", rev-2), and the compare
    // surface preselects it as the later pick.
    expect(
      (screen.getByTestId("revision-compare-right") as HTMLSelectElement).value,
    ).toBe("rev-2");
  });

  it("opens the first FILTERED row's Compare from region focus, not rows[0]", async () => {
    await mountLibrary([
      summary({
        revision_id: "rev-2",
        label: "Edited",
        state: "validated",
        runnable: true,
        created_at: "2026-10-07T12:00:00Z",
        parent_revision_id: "rev-1",
      }),
      summary(),
      summary({
        revision_id: "rev-a",
        strategy_id: "range-scout",
        id: "range-scout",
        label: "Alpha range",
        pair: "ETHUSD",
        state: "validated",
        runnable: true,
      }),
    ]);
    fireEvent.change(screen.getByTestId("library-search"), {
      target: { value: "range" },
    });
    expect(screen.getAllByTestId("library-row")).toHaveLength(1);
    const section = screen.getByTestId("saved-strategy-library");
    section.focus();
    expect(document.activeElement).toBe(section);
    expect(chord(section)).toBe(false);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    // filteredRows[0] is "Alpha range" (rev-a). It has no parent in rows, so
    // it lands in the earlier pick; rows[0] (rev-2) must NOT be the pick.
    expect(
      (screen.getByTestId("revision-compare-left") as HTMLSelectElement).value,
    ).toBe("rev-a");
    expect(
      (screen.getByTestId("revision-compare-right") as HTMLSelectElement).value,
    ).toBe("");
  });

  it("honors event.repeat and never auto-repeats the activation", async () => {
    await mountLibrary();
    const edited = compareButtons()[0];
    edited.focus();
    expect(chord(edited, { repeat: true })).toBe(false);
    expect(screen.queryByTestId("revision-compare")).toBeNull();
    expect(chord(edited, { repeat: false })).toBe(false);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
  });

  it("does nothing when focus is on another row control", async () => {
    await mountLibrary();
    const reopen = screen.getAllByRole("button", { name: /reopen/i })[1];
    reopen.focus();
    expect(document.activeElement).toBe(reopen);
    expect(chord(reopen)).toBe(false);
    expect(screen.queryByTestId("revision-compare")).toBeNull();
  });

  it("leaves non-chord keys and plain typing alone", async () => {
    await mountLibrary();
    const edited = compareButtons()[0];
    edited.focus();
    expect(chord(edited, { altKey: false })).toBe(true);
    expect(chord(edited, { ctrlKey: false, metaKey: false })).toBe(true);
    expect(chord(edited, { key: "x" })).toBe(true);
    expect(screen.queryByTestId("revision-compare")).toBeNull();
  });

  it("keeps the click activation path unchanged", async () => {
    await mountLibrary();
    fireEvent.click(compareButtons()[0]);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    fireEvent.click(screen.getByTestId("revision-compare-close"));
    expect(screen.queryByTestId("revision-compare")).toBeNull();
    expect(screen.getAllByTestId("library-row").length).toBe(2);
  });
});
