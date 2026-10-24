import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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

const populatedRows = [
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

// Only the authenticated read boundary is faked; focus, the real keydown
// dispatch and the library's own handler all run unstubbed below.
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

function failingClient(): LibraryClient {
  return {
    listOwned: vi.fn().mockRejectedValue(new Error("library list failed: 403")),
    getJson: vi.fn(),
  };
}

/** Mount the library with the New owned strategy control the ordinary
 * reproduction focuses, so the region has a real focusable target while
 * no toolbar exists. */
function mountLibrary(client: LibraryClient) {
  return render(
    <SavedStrategyLibrary
      client={client}
      onReopen={vi.fn()}
      onNewStrategy={vi.fn()}
    />,
  );
}

function newStrategyButton(): HTMLButtonElement {
  return screen.getByTestId<HTMLButtonElement>("library-new-owned-strategy");
}

function region(): HTMLElement {
  return screen.getByTestId("saved-strategy-library");
}

/**
 * Real focus plus a real cancelable keydown dispatched at the focused
 * element. document.activeElement is never faked: the caller sees the
 * genuine focused element and the genuine defaultPrevented outcome.
 */
function press(target: HTMLElement, keys: object): boolean {
  target.focus();
  expect(document.activeElement).toBe(target);
  const seen: boolean[] = [];
  const captureDefault = (event: Event): void => {
    seen.push(event.defaultPrevented);
  };
  target.addEventListener("keydown", captureDefault);
  try {
    const continued = fireEvent.keyDown(target, { cancelable: true, ...keys });
    return continued && !seen[seen.length - 1];
  } finally {
    target.removeEventListener("keydown", captureDefault);
  }
}

describe("SavedStrategyLibrary — chords stay unclaimed without a rendered target", () => {
  it("leaves Control+F / Meta+F with the browser while the list is still loading", async () => {
    let release!: (rows: OwnedDraftSummary[]) => void;
    const pending = new Promise<OwnedDraftSummary[]>((resolve) => {
      release = resolve;
    });
    mountLibrary({ listOwned: vi.fn(() => pending), getJson: vi.fn() });
    expect(screen.getByTestId("library-loading")).toBeDefined();
    expect(screen.queryByTestId("library-search")).toBeNull();
    const from = newStrategyButton();
    expect(press(from, { key: "f", ctrlKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
    expect(press(from, { key: "f", metaKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
    release([]);
    await waitFor(() =>
      expect(screen.getByTestId("library-empty")).toBeDefined(),
    );
  });

  it("leaves Control+F / Meta+F with the browser when the library is empty (ordinary reproduction)", async () => {
    mountLibrary(makeClient([]));
    await screen.findByTestId("library-empty");
    expect(screen.queryByTestId("library-search")).toBeNull();
    const from = newStrategyButton();
    expect(press(from, { key: "f", ctrlKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
    expect(press(from, { key: "f", metaKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
  });

  it("leaves Control+F / Meta+F with the browser when listing fails", async () => {
    mountLibrary(failingClient());
    await screen.findByTestId("library-error");
    expect(screen.queryByTestId("library-search")).toBeNull();
    const from = newStrategyButton();
    expect(press(from, { key: "f", ctrlKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
    expect(press(from, { key: "f", metaKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
  });

  it("leaves Control+Alt+S / Meta+Alt+S with the browser for loading, empty and failed lists", async () => {
    let release!: (rows: OwnedDraftSummary[]) => void;
    const pending = new Promise<OwnedDraftSummary[]>((resolve) => {
      release = resolve;
    });
    const loading = mountLibrary({
      listOwned: vi.fn(() => pending),
      getJson: vi.fn(),
    });
    expect(screen.getByTestId("library-loading")).toBeDefined();
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
    const loadingFrom = newStrategyButton();
    expect(
      press(loadingFrom, { key: "s", ctrlKey: true, altKey: true }),
    ).toBe(true);
    expect(document.activeElement).toBe(loadingFrom);
    expect(
      press(loadingFrom, { key: "s", metaKey: true, altKey: true }),
    ).toBe(true);
    expect(document.activeElement).toBe(loadingFrom);

    release([]);
    await screen.findByTestId("library-empty");
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
    const emptyFrom = newStrategyButton();
    expect(
      press(emptyFrom, { key: "s", ctrlKey: true, altKey: true }),
    ).toBe(true);
    expect(document.activeElement).toBe(emptyFrom);

    loading.rerender(
      <SavedStrategyLibrary
        client={failingClient()}
        onReopen={vi.fn()}
        onNewStrategy={vi.fn()}
      />,
    );
    await screen.findByTestId("library-error");
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
    const errorFrom = newStrategyButton();
    expect(
      press(errorFrom, { key: "s", ctrlKey: true, altKey: true }),
    ).toBe(true);
    expect(document.activeElement).toBe(errorFrom);
    expect(
      press(errorFrom, { key: "s", metaKey: true, altKey: true }),
    ).toBe(true);
    expect(document.activeElement).toBe(errorFrom);
  });

  it("leaves both chords unclaimed when a refresh transition unmounts the toolbar", async () => {
    const view = mountLibrary(makeClient(populatedRows));
    await screen.findByTestId("library-search");
    const search = screen.getByTestId<HTMLInputElement>("library-search");
    search.focus();
    expect(document.activeElement).toBe(search);

    let release!: (rows: OwnedDraftSummary[]) => void;
    const pending = new Promise<OwnedDraftSummary[]>((resolve) => {
      release = resolve;
    });
    view.rerender(
      <SavedStrategyLibrary
        client={{ ...makeClient(populatedRows), listOwned: () => pending }}
        onReopen={vi.fn()}
        onNewStrategy={vi.fn()}
      />,
    );
    expect(screen.getByTestId("library-loading")).toBeDefined();
    expect(screen.queryByTestId("library-search")).toBeNull();
    expect(screen.queryByTestId("library-state-filter")).toBeNull();

    // Focus falls back to the region while the toolbar is unmounted; the
    // chords must not be claimed from there either.
    const from = region();
    expect(press(from, { key: "f", ctrlKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);
    expect(press(from, { key: "s", ctrlKey: true, altKey: true })).toBe(true);
    expect(document.activeElement).toBe(from);

    release(populatedRows);
    await screen.findByTestId("library-search");
  });

  it("keeps claiming Control+Alt+C from the region even without a toolbar target", async () => {
    mountLibrary(makeClient([]));
    await screen.findByTestId("library-empty");
    expect(
      press(region(), { key: "c", ctrlKey: true, altKey: true }),
    ).toBe(false);
    expect(screen.queryByTestId("revision-compare")).toBeNull();
  });
});

describe("SavedStrategyLibrary — populated positive controls", () => {
  it("still claims Control+F / Meta+F and focuses the search input", async () => {
    mountLibrary(makeClient(populatedRows));
    await screen.findByTestId("library-search");
    const search = screen.getByTestId<HTMLInputElement>("library-search");
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[1];
    expect(press(from, { key: "f", ctrlKey: true })).toBe(false);
    expect(document.activeElement).toBe(search);
    expect(press(from, { key: "f", metaKey: true })).toBe(false);
    expect(document.activeElement).toBe(search);
  });

  it("still claims Control+Alt+S / Meta+Alt+S and focuses the state filter", async () => {
    mountLibrary(makeClient(populatedRows));
    await screen.findByTestId("library-search");
    const filter = screen.getByTestId<HTMLSelectElement>(
      "library-state-filter",
    );
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[1];
    expect(press(from, { key: "s", ctrlKey: true, altKey: true })).toBe(false);
    expect(document.activeElement).toBe(filter);
    expect(press(from, { key: "s", metaKey: true, altKey: true })).toBe(false);
    expect(document.activeElement).toBe(filter);
  });

  it("still suppresses auto-repeat only when the target exists", async () => {
    mountLibrary(makeClient(populatedRows));
    await screen.findByTestId("library-search");
    const search = screen.getByTestId<HTMLInputElement>("library-search");
    const filter = screen.getByTestId<HTMLSelectElement>(
      "library-state-filter",
    );
    const from = screen.getAllByTestId<HTMLButtonElement>(
      "library-row-compare",
    )[0];
    expect(press(from, { key: "f", ctrlKey: true, repeat: true })).toBe(false);
    expect(document.activeElement).toBe(from);
    expect(press(from, { key: "f", ctrlKey: true, repeat: false })).toBe(false);
    expect(document.activeElement).toBe(search);
    expect(
      press(search, { key: "s", ctrlKey: true, altKey: true, repeat: true }),
    ).toBe(false);
    expect(document.activeElement).toBe(search);
    expect(
      press(search, { key: "s", ctrlKey: true, altKey: true, repeat: false }),
    ).toBe(false);
    expect(document.activeElement).toBe(filter);
  });
});
