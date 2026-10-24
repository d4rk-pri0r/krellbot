import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Editor } from "./Editor";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
} from "./SavedStrategyLibrary";

afterEach(cleanup);

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

function summary(
  overrides: Partial<OwnedDraftSummary> = {},
): OwnedDraftSummary {
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

/**
 * rows[0] is a revision whose label does NOT contain "range", so any test
 * that filters by "range" can tell a rows[0] pick from a filteredRows[0]
 * pick apart.
 */
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
  summary({
    revision_id: "rev-a",
    strategy_id: "range-scout",
    id: "range-scout",
    label: "Alpha range",
    pair: "ETHUSD",
    state: "validated",
    runnable: true,
  }),
  summary({
    revision_id: "rev-b",
    strategy_id: "range-scout",
    id: "range-scout",
    label: "Beta range",
    pair: "ETHUSD",
    state: "draft",
    parent_revision_id: "rev-a",
  }),
];

// Only the authenticated read boundary is faked; every keydown, focus move
// and compare mount below runs the real component logic.
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
    expect(screen.getAllByTestId("library-row-compare").length).toBe(
      rows.length,
    ),
  );
  return client;
}

function searchInput(): HTMLInputElement {
  return screen.getByTestId<HTMLInputElement>("library-search");
}

function stateFilter(): HTMLSelectElement {
  return screen.getByTestId<HTMLSelectElement>("library-state-filter");
}

function clearButton(): HTMLButtonElement {
  return screen.getByTestId<HTMLButtonElement>("library-search-clear");
}

function region(): HTMLElement {
  return screen.getByTestId("saved-strategy-library");
}

/** Real focus + real keydown on the focused element; never a faked
 * document.activeElement. Returns the fireEvent result so callers can
 * assert whether the library actually claimed the key. */
function press(target: HTMLElement, keys: object): boolean {
  target.focus();
  expect(document.activeElement).toBe(target);
  return fireEvent.keyDown(target, keys);
}

function compareLeft(): HTMLSelectElement {
  return screen.getByTestId<HTMLSelectElement>("revision-compare-left");
}

describe("SavedStrategyLibrary — announced focus shortcuts are real", () => {
  it.each([
    ["Control+F", { ctrlKey: true, metaKey: false }],
    ["Meta+F", { ctrlKey: false, metaKey: true }],
  ])("%s moves focus from a row control to the search input", async (_, mods) => {
    await mountLibrary();
    expect(searchInput().getAttribute("aria-keyshortcuts")).toBe(
      "Control+F Meta+F",
    );
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[1];
    expect(press(from, { key: "f", ...mods })).toBe(false);
    expect(document.activeElement).toBe(searchInput());
  });

  it("does not claim the chord when focus is outside the mounted library", async () => {
    await mountLibrary();
    document.body.focus();
    expect(document.activeElement).toBe(document.body);
    expect(
      fireEvent.keyDown(document.body, {
        key: "f",
        ctrlKey: true,
        metaKey: false,
      }),
    ).toBe(true);
    expect(document.activeElement).toBe(document.body);
    expect(document.activeElement).not.toBe(searchInput());
  });

  it("does not claim the chord from the editor's own input outside the library", async () => {
    render(
      <main>
        <Editor
          client={{
            create: vi.fn(),
            edit: vi.fn(),
            validate: vi.fn(),
            arm: vi.fn(),
          }}
        />
        <SavedStrategyLibrary client={makeClient(libraryRows)} onReopen={vi.fn()} />
      </main>,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row-compare").length).toBe(
        libraryRows.length,
      ),
    );
    const editorLabel = screen.getByLabelText<HTMLInputElement>(/^label$/i);
    expect(press(editorLabel, { key: "f", ctrlKey: true, metaKey: false })).toBe(
      true,
    );
    expect(document.activeElement).toBe(editorLabel);
    expect(document.activeElement).not.toBe(searchInput());
    // Plain typing in the editor input still reaches the editor only.
    fireEvent.change(editorLabel, { target: { value: "range scout" } });
    expect(editorLabel.value).toBe("range scout");
    expect(searchInput().value).toBe("");
  });

  it("leaves Shift+F, Alt+F and plain f untouched", async () => {
    await mountLibrary();
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[1];
    expect(press(from, { key: "F", ctrlKey: true, shiftKey: true })).toBe(true);
    expect(press(from, { key: "f", ctrlKey: true, altKey: true })).toBe(true);
    expect(press(from, { key: "f" })).toBe(true);
    expect(document.activeElement).toBe(from);
  });

  it.each([
    ["Control+Alt+S", { ctrlKey: true, metaKey: false, altKey: true, key: "s" }],
    ["Meta+Alt+S", { ctrlKey: false, metaKey: true, altKey: true, key: "S" }],
  ])("%s moves focus to the state filter from inside the library", async (_, keys) => {
    await mountLibrary();
    expect(stateFilter().getAttribute("aria-keyshortcuts")).toBe(
      "Control+Alt+S Meta+Alt+S",
    );
    expect(press(searchInput(), keys)).toBe(false);
    expect(document.activeElement).toBe(stateFilter());
  });
});

describe("SavedStrategyLibrary — Escape on the Clear control", () => {
  it("clears the query from Clear with Escape and returns focus to the search input", async () => {
    await mountLibrary();
    fireEvent.change(searchInput(), { target: { value: "no such revision" } });
    expect(clearButton().getAttribute("aria-keyshortcuts")).toBe("Escape");
    expect(press(clearButton(), { key: "Escape" })).toBe(false);
    expect(searchInput().value).toBe("");
    expect(screen.queryByTestId("library-search-clear")).toBeNull();
    expect(document.activeElement).toBe(searchInput());
    expect(screen.getAllByTestId("library-row")).toHaveLength(4);
  });

  it("keeps the click path on Clear working unchanged", async () => {
    await mountLibrary();
    fireEvent.change(searchInput(), { target: { value: "range" } });
    fireEvent.click(clearButton());
    expect(searchInput().value).toBe("");
    expect(screen.getAllByTestId("library-row")).toHaveLength(4);
  });
});

describe("SavedStrategyLibrary — focusable region and filtered first row", () => {
  it("makes the library region genuinely keyboard-focusable", async () => {
    await mountLibrary();
    const section = region();
    expect(section.getAttribute("tabindex")).toBe("0");
    section.focus();
    expect(document.activeElement).toBe(section);
  });

  it("opens the first FILTERED row from region focus, not rows[0]", async () => {
    await mountLibrary();
    fireEvent.change(searchInput(), { target: { value: "range" } });
    expect(screen.getAllByTestId("library-row")).toHaveLength(2);
    expect(press(region(), { key: "c", ctrlKey: true, altKey: true })).toBe(
      false,
    );
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    // filteredRows[0] is "Alpha range" (rev-a); rows[0] is "Edited" (rev-2).
    expect(compareLeft().value).toBe("rev-a");
    expect(compareLeft().value).not.toBe("rev-2");
  });

  it("still opens the first listed row from region focus when nothing is filtered", async () => {
    await mountLibrary();
    expect(press(region(), { key: "c", ctrlKey: true, altKey: true })).toBe(
      false,
    );
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    expect(
      (screen.getByTestId("revision-compare-right") as HTMLSelectElement).value,
    ).toBe("rev-2");
  });
});

describe("SavedStrategyLibrary — keyboard-only journeys", () => {
  it("chord to search, type a filter, chord compare, without any pointer", async () => {
    const client = await mountLibrary();
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[0];
    expect(press(from, { key: "f", ctrlKey: true })).toBe(false);
    fireEvent.change(document.activeElement as HTMLInputElement, {
      target: { value: "beta" },
    });
    expect(screen.getAllByTestId("library-row")).toHaveLength(1);
    expect(
      screen.getByTestId("library-search-count").textContent,
    ).toContain("1 of 4");
    fireEvent.keyDown(searchInput(), { key: "Escape" });
    expect(screen.getAllByTestId("library-row")).toHaveLength(4);
    expect(press(region(), { key: "c", ctrlKey: true, altKey: true })).toBe(
      false,
    );
    expect(client.listOwned).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
  });

  it("keeps the chord inert on a state filter that matches nothing", async () => {
    await mountLibrary();
    fireEvent.change(stateFilter(), { target: { value: "archived" } });
    expect(screen.getByTestId("library-search-empty")).toBeDefined();
    expect(screen.queryAllByTestId("library-row")).toHaveLength(0);
    expect(press(region(), { key: "c", ctrlKey: true, altKey: true })).toBe(
      false,
    );
    expect(screen.queryByTestId("revision-compare")).toBeNull();
  });

  it("shows the truthful no-match state for a nonmatching query and restores it by keyboard", async () => {
    await mountLibrary();
    fireEvent.change(searchInput(), { target: { value: "zzz-no-match" } });
    const empty = screen.getByTestId("library-search-empty");
    expect(empty.textContent).toContain("zzz-no-match");
    expect(empty.textContent).toContain("4 saved revisions");
    expect(press(clearButton(), { key: "Escape" })).toBe(false);
    expect(screen.queryByTestId("library-search-empty")).toBeNull();
    expect(screen.getAllByTestId("library-row")).toHaveLength(4);
  });

  it("never re-fires the focus shortcuts on auto-repeat", async () => {
    await mountLibrary();
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[0];
    expect(
      press(from, { key: "f", ctrlKey: true, repeat: true }),
    ).toBe(false);
    expect(document.activeElement).toBe(from);
    expect(press(from, { key: "f", ctrlKey: true, repeat: false })).toBe(false);
    expect(document.activeElement).toBe(searchInput());
    expect(
      press(searchInput(), { key: "s", ctrlKey: true, altKey: true, repeat: true }),
    ).toBe(false);
    expect(document.activeElement).toBe(searchInput());
    expect(
      press(searchInput(), {
        key: "s",
        ctrlKey: true,
        altKey: true,
        repeat: false,
      }),
    ).toBe(false);
    expect(document.activeElement).toBe(stateFilter());
  });
});
