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
    getJson: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "draft",
      bytes: '{"id":"trend-follow","label":"Trend follow"}',
    }),
  };
}

describe("SavedStrategyLibrary — load states", () => {
  it("shows a loading state before the list resolves", () => {
    const gate: {
      resolve: ((rows: OwnedDraftSummary[]) => void) | null;
    } = { resolve: null };
    const pending = new Promise<OwnedDraftSummary[]>((resolve) => {
      gate.resolve = resolve;
    });
    const client: LibraryClient = {
      listOwned: vi.fn(() => pending),
      getJson: vi.fn(),
    };
    render(<SavedStrategyLibrary client={client} onReopen={vi.fn()} />);
    expect(screen.getByTestId("library-loading")).toBeDefined();
    gate.resolve?.([]);
  });

  it("shows an empty state when no owned revisions exist", async () => {
    render(
      <SavedStrategyLibrary client={makeClient([])} onReopen={vi.fn()} />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("library-empty")).toBeDefined(),
    );
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("shows an empty, non-fabricated state when listing fails", async () => {
    const client: LibraryClient = {
      listOwned: vi.fn().mockRejectedValue(new Error("library list failed: 403")),
      getJson: vi.fn(),
    };
    render(<SavedStrategyLibrary client={client} onReopen={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByTestId("library-error")).toBeDefined(),
    );
    expect(screen.queryByRole("listitem")).toBeNull();
    expect(screen.getByTestId("library-error").textContent).toContain(
      "library list failed: 403",
    );
  });
});

describe("SavedStrategyLibrary — rows", () => {
  const rows = [
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

  it("renders one accessible row per owned revision with its fields", async () => {
    render(
      <SavedStrategyLibrary client={makeClient(rows)} onReopen={vi.fn()} />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("listitem").length).toBe(2),
    );
    const first = screen.getAllByRole("listitem")[0];
    expect(first.textContent).toContain("trend-follow");
    expect(first.textContent).toContain("Edited");
    expect(first.textContent).toContain("SUIUSD");
    expect(first.textContent).toContain("1h");
    expect(first.textContent).toContain("Validated");
    expect(first.textContent).toContain("2026-10-07T12:00:00Z");
    expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2);
  });

  it("passes the clicked summary and the fetched bytes to onReopen", async () => {
    const onReopen = vi.fn();
    const client = makeClient(rows);
    render(
      <SavedStrategyLibrary client={client} onReopen={onReopen} />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2),
    );
    fireEvent.click(screen.getAllByRole("button", { name: /reopen/i })[0]);
    await waitFor(() => expect(onReopen).toHaveBeenCalledTimes(1));
    expect(client.getJson).toHaveBeenCalledWith("rev-2");
    expect(onReopen).toHaveBeenCalledWith(
      rows[0],
      '{"id":"trend-follow","label":"Trend follow"}',
    );
  });

  it("keeps the list and surfaces the error when a reopen fetch fails", async () => {
    const onReopen = vi.fn();
    const client = makeClient(rows);
    client.getJson = vi.fn().mockRejectedValue(new Error("library open failed: 404"));
    render(
      <SavedStrategyLibrary client={client} onReopen={onReopen} />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2),
    );
    fireEvent.click(screen.getAllByRole("button", { name: /reopen/i })[0]);
    await waitFor(() =>
      expect(screen.getByTestId("library-reopen-error").textContent).toContain(
        "library open failed: 404",
      ),
    );
    expect(onReopen).not.toHaveBeenCalled();
    expect(screen.getAllByRole("listitem").length).toBe(2);
  });

  it("does not arm, validate, or rewrite the reopened revision", async () => {
    const onReopen = vi.fn();
    const client = makeClient(rows);
    render(
      <SavedStrategyLibrary client={client} onReopen={onReopen} />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2),
    );
    fireEvent.click(screen.getAllByRole("button", { name: /reopen/i })[0]);
    await waitFor(() => expect(onReopen).toHaveBeenCalledTimes(1));
    const calls = (client.listOwned as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.length).toBe(1);
  });
});

describe("SavedStrategyLibrary — new owned strategy", () => {
  it("offers a new-owned-strategy control that defers to the host", async () => {
    const onNewStrategy = vi.fn();
    render(
      <SavedStrategyLibrary
        client={makeClient([summary()])}
        onReopen={vi.fn()}
        onNewStrategy={onNewStrategy}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("listitem").length).toBe(1),
    );
    fireEvent.click(screen.getByRole("button", { name: /new owned strategy/i }));
    expect(onNewStrategy).toHaveBeenCalledTimes(1);
  });
});

describe("SavedStrategyLibrary — compare mount", () => {
  const compareRows = [
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

  function compareClient(): LibraryClient & {
    getJson: ReturnType<typeof vi.fn>;
  } {
    return {
      listOwned: vi.fn().mockResolvedValue(compareRows),
      getJson: vi.fn((revisionId: string): Promise<OwnedRevisionBytes> =>
        Promise.resolve({
          revision_id: revisionId,
          state: "draft",
          bytes:
            revisionId === "rev-1"
              ? '{"id":"trend-follow","label":"Trend follow","timeframe":"1h"}'
              : '{"id":"trend-follow","label":"Edited","timeframe":"4h"}',
        }),
      ),
    };
  }

  it("mounts the compare surface inside the library and keeps Reopen", async () => {
    render(
      <SavedStrategyLibrary
        client={compareClient()}
        onReopen={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row-compare").length).toBe(2),
    );
    expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2);
    expect(screen.queryByTestId("revision-compare")).toBeNull();
    fireEvent.click(screen.getAllByTestId("library-row-compare")[0]);
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2);
  });

  it("compares two actual saved revisions through the read client", async () => {
    const client = compareClient();
    render(<SavedStrategyLibrary client={client} onReopen={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row-compare").length).toBe(2),
    );
    fireEvent.click(screen.getAllByTestId("library-row-compare")[0]);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
    );
    expect(client.getJson).toHaveBeenCalledWith("rev-1");
    expect(client.getJson).toHaveBeenCalledWith("rev-2");
    const body = screen.getByTestId("revision-compare-changes").textContent ?? "";
    expect(body).toContain("label");
    expect(body).toContain("Trend follow");
    expect(body).toContain("Edited");
    expect(body).toContain("timeframe");
  });

  it("closes the compare surface and leaves the library intact", async () => {
    render(
      <SavedStrategyLibrary
        client={compareClient()}
        onReopen={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row-compare").length).toBe(2),
    );
    fireEvent.click(screen.getAllByTestId("library-row-compare")[0]);
    fireEvent.click(screen.getByTestId("revision-compare-close"));
    expect(screen.queryByTestId("revision-compare")).toBeNull();
    expect(screen.getAllByRole("listitem").length).toBe(2);
    expect(screen.getAllByRole("button", { name: /reopen/i }).length).toBe(2);
  });

  it("keeps Reopen working after a comparison", async () => {
    const onReopen = vi.fn();
    const client = compareClient();
    render(
      <SavedStrategyLibrary client={client} onReopen={onReopen} />,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("library-row-compare").length).toBe(2),
    );
    fireEvent.click(screen.getAllByTestId("library-row-compare")[0]);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
    );
    fireEvent.click(screen.getAllByRole("button", { name: /reopen/i })[0]);
    await waitFor(() => expect(onReopen).toHaveBeenCalledTimes(1));
    expect(onReopen).toHaveBeenCalledWith(
      compareRows[0],
      '{"id":"trend-follow","label":"Edited","timeframe":"4h"}',
    );
  });
});

