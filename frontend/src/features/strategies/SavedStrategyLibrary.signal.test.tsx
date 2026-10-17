import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
  type OwnedRevisionBytes,
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

function makeClient(rows: OwnedDraftSummary[]): LibraryClient {
  return {
    listOwned: vi.fn().mockResolvedValue(rows),
    getJson: vi.fn((revisionId: string): Promise<OwnedRevisionBytes> =>
      Promise.resolve({
        revision_id: revisionId,
        state: "draft",
        bytes: `{"id":"${revisionId}"}`,
      }),
    ),
  };
}

type ReopenHandler = (summary: OwnedDraftSummary, bytes: string) => void;
type CopyHandler = (summary: OwnedDraftSummary, bytes: string) => void;

async function renderedLibrary(
  rows: OwnedDraftSummary[],
  props: {
    onReopen?: ReopenHandler;
    onCopyAsNew?: CopyHandler;
  } = {},
) {
  const onReopen: ReopenHandler = props.onReopen ?? vi.fn();
  const client = makeClient(rows);
  render(
    <SavedStrategyLibrary
      client={client}
      onReopen={onReopen}
      onCopyAsNew={props.onCopyAsNew}
    />,
  );
  await waitFor(() =>
    expect(screen.getAllByTestId("library-row").length).toBe(rows.length),
  );
  return { client, onReopen };
}

const library = [
  summary({
    revision_id: "rev-2",
    label: "Edited",
    state: "validated",
    runnable: true,
    created_at: "2026-10-07T12:00:00Z",
    parent_revision_id: "rev-1",
  }),
  summary({
    revision_id: "rev-9",
    strategy_id: "range-plan",
    id: "range-plan",
    label: "Range plan",
    pair: "ETHUSD",
    timeframe: "4h",
    state: "draft",
    created_at: "2026-10-08T09:30:00Z",
  }),
];

describe("SavedStrategyLibrary signal slice — search", () => {
  it("offers a labeled search control and shows every loaded revision by default", async () => {
    await renderedLibrary(library);
    const search = screen.getByRole("searchbox", {
      name: /search saved strategies/i,
    }) as HTMLInputElement;
    expect(search.value).toBe("");
    expect(screen.getAllByTestId("library-row").length).toBe(2);
  });

  it("filters locally by label and keeps an exact-row count", async () => {
    await renderedLibrary(library);
    fireEvent.change(screen.getByRole("searchbox", { name: /search saved strategies/i }), {
      target: { value: "range" },
    });
    const rows = screen.getAllByTestId("library-row");
    expect(rows.length).toBe(1);
    expect(rows[0].getAttribute("data-revision-id")).toBe("rev-9");
    expect(screen.getByTestId("library-search-count").textContent).toContain(
      "1 of 2",
    );
    expect(screen.queryByTestId("library-search-empty")).toBeNull();
  });

  it("matches pair, timeframe and id fields case-insensitively", async () => {
    await renderedLibrary(library);
    const search = screen.getByRole("searchbox", {
      name: /search saved strategies/i,
    });
    fireEvent.change(search, { target: { value: "ethusd" } });
    expect(
      screen.getAllByTestId("library-row")[0].getAttribute("data-revision-id"),
    ).toBe("rev-9");
    fireEvent.change(search, { target: { value: "4H" } });
    expect(
      screen.getAllByTestId("library-row")[0].getAttribute("data-revision-id"),
    ).toBe("rev-9");
    fireEvent.change(search, { target: { value: "trend-follow" } });
    expect(
      screen.getAllByTestId("library-row")[0].getAttribute("data-revision-id"),
    ).toBe("rev-2");
  });

  it("shows a distinct no-match state that names the query, separate from the no-records state", async () => {
    await renderedLibrary(library);
    fireEvent.change(screen.getByRole("searchbox", { name: /search saved strategies/i }), {
      target: { value: "does-not-exist" },
    });
    expect(screen.queryByTestId("library-row")).toBeNull();
    expect(screen.queryByTestId("library-empty")).toBeNull();
    const noMatch = screen.getByTestId("library-search-empty");
    expect(noMatch.textContent).toContain("does-not-exist");
  });

  it("restores all loaded records when the query is cleared", async () => {
    await renderedLibrary(library);
    const search = screen.getByRole("searchbox", {
      name: /search saved strategies/i,
    });
    fireEvent.change(search, { target: { value: "range" } });
    expect(screen.getAllByTestId("library-row").length).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
    expect(screen.getAllByTestId("library-row").length).toBe(2);
    expect(screen.getByTestId("library-search-count").textContent).toContain(
      "2 of 2",
    );
    expect((search as HTMLInputElement).value).toBe("");
  });

  it("restores all loaded records when the input text is emptied", async () => {
    await renderedLibrary(library);
    const search = screen.getByRole("searchbox", {
      name: /search saved strategies/i,
    });
    fireEvent.change(search, { target: { value: "range" } });
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getAllByTestId("library-row").length).toBe(2);
  });

  it("clears the query from the keyboard with Escape", async () => {
    await renderedLibrary(library);
    const search = screen.getByRole("searchbox", {
      name: /search saved strategies/i,
    });
    fireEvent.change(search, { target: { value: "range" } });
    expect(screen.getAllByTestId("library-row").length).toBe(1);
    fireEvent.keyDown(search, { key: "Escape" });
    expect(screen.getAllByTestId("library-row").length).toBe(2);
  });

  it("does not refetch the list while searching", async () => {
    const { client } = await renderedLibrary(library);
    const search = screen.getByRole("searchbox", {
      name: /search saved strategies/i,
    });
    fireEvent.change(search, { target: { value: "eth" } });
    fireEvent.change(search, { target: { value: "ethusd" } });
    expect(client.listOwned).toHaveBeenCalledTimes(1);
  });
});

describe("SavedStrategyLibrary signal slice — actions after filtering", () => {
  it("reopens exactly the visible revision after filtering", async () => {
    const onReopen = vi.fn();
    const { client } = await renderedLibrary(library, { onReopen });
    fireEvent.change(screen.getByRole("searchbox", { name: /search saved strategies/i }), {
      target: { value: "Range plan" },
    });
    const rows = screen.getAllByTestId("library-row");
    expect(rows.length).toBe(1);
    fireEvent.click(
      screen.getAllByRole("button", { name: /reopen/i })[0],
    );
    await waitFor(() => expect(onReopen).toHaveBeenCalledTimes(1));
    expect(client.getJson).toHaveBeenCalledWith("rev-9");
    expect(onReopen).toHaveBeenCalledWith(
      library[1],
      '{"id":"rev-9"}',
    );
  });

  it("copies exactly the visible revision after filtering, without touching hidden rows", async () => {
    const onCopyAsNew = vi.fn();
    const client = makeClient(library);
    render(
      <SavedStrategyLibrary
        client={client}
        onReopen={vi.fn()}
        onCopyAsNew={onCopyAsNew}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row").length).toBe(2),
    );
    fireEvent.change(screen.getByRole("searchbox", { name: /search saved strategies/i }), {
      target: { value: "ETHUSD" },
    });
    fireEvent.click(screen.getByRole("button", { name: /copy as new/i }));
    await waitFor(() => expect(onCopyAsNew).toHaveBeenCalledTimes(1));
    expect(client.getJson).toHaveBeenCalledTimes(1);
    expect(client.getJson).toHaveBeenCalledWith("rev-9");
    const [passedSummary, passedBytes] = onCopyAsNew.mock.calls[0];
    expect(passedSummary.revision_id).toBe("rev-9");
    expect(passedBytes).toBe('{"id":"rev-9"}');
  });

  it("compares exactly the visible revision after filtering", async () => {
    const client = makeClient(library);
    render(<SavedStrategyLibrary client={client} onReopen={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row").length).toBe(2),
    );
    fireEvent.change(screen.getByRole("searchbox", { name: /search saved strategies/i }), {
      target: { value: "4h" },
    });
    expect(screen.getAllByTestId("library-row").length).toBe(1);
    fireEvent.click(screen.getAllByTestId("library-row-compare")[0]);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    // The filtered-out revision is still offered to Compare as a real
    // candidate through the loaded rows; closing returns to the filtered
    // library view.
    fireEvent.click(screen.getByTestId("revision-compare-close"));
    expect(screen.getAllByTestId("library-row").length).toBe(1);
  });
});

describe("SavedStrategyLibrary signal slice — truthful states", () => {
  it("keeps the server failure distinct from a no-match search result", async () => {
    const client: LibraryClient = {
      listOwned: vi.fn().mockRejectedValue(new Error("library list failed: 403")),
      getJson: vi.fn(),
    };
    render(<SavedStrategyLibrary client={client} onReopen={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByTestId("library-error")).toBeDefined(),
    );
    expect(screen.getByTestId("library-error").textContent).toContain(
      "library list failed: 403",
    );
    expect(screen.queryByTestId("library-search-empty")).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByTestId("library-row")).toBeNull();
  });

  it("shows revision identity and state text per row, not just color", async () => {
    await renderedLibrary(library);
    const edited = screen
      .getAllByTestId("library-row")
      .find((row) => row.getAttribute("data-revision-id") === "rev-2");
    expect(edited).toBeDefined();
    expect(edited?.textContent).toContain("rev-2");
    expect(edited?.textContent).toContain("Validated");
    expect(edited?.textContent).toContain("2026-10-07T12:00:00Z");
  });

  it("groups revisions of one strategy under a single readable heading", async () => {
    await renderedLibrary(library);
    const headings = screen
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(headings).toContain("trend-follow");
    const trendGroupCount = screen
      .getAllByRole("heading", { level: 3 })
      .find((heading) => heading.textContent === "trend-follow");
    expect(trendGroupCount?.textContent).toBeDefined();
  });
});
