import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const LOADING_TEXT = "Loading deployment history…";
const EMPTY_TEXT = "No deployment history yet.";
const READ_ONLY_HELPER =
  "Read-only: historical records can be inspected but not edited, started, or promoted.";

function record(over: Partial<DeploymentRecordRow> = {}): DeploymentRecordRow {
  return {
    deployment_id: "dep-1",
    venue: "kraken",
    pair: "SUIUSD",
    created_at_ms: 1_700_000_010_000,
    state: "paper",
    config: { pack_id: "trend-follow", pack_version: "1.0.0", mode: "paper", entries_paused: false },
    schedule: { timeframe: "1h", interval: 3600 },
    last_execution_summary: "one tick, no entries",
    ...over,
  };
}

function makeClient(
  over: Partial<Pick<OperationsClient, "listDeploymentRecords" | "getDeploymentRecord">> = {},
): OperationsClient {
  return {
    getOperations: vi.fn(),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
    ...over,
  };
}

describe("DeploymentHistory loading / empty / rows", () => {
  it("shows the loading state while the first list request is in flight", async () => {
    let release: ((rows: DeploymentRecordRow[]) => void) | undefined;
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockImplementation(
        () => new Promise<DeploymentRecordRow[]>((resolve) => { release = resolve; }),
      ),
    });
    render(<DeploymentHistory client={client} />);
    expect(screen.getByTestId("ops-history-loading").textContent).toBe(LOADING_TEXT);
    expect((screen.getByTestId("ops-history-refresh") as HTMLButtonElement).disabled).toBe(true);
    release?.([]);
    await waitFor(() => expect(screen.queryByTestId("ops-history-loading")).toBeNull());
  });

  it("renders the empty state when the journal has no records", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue([]) });
    render(<DeploymentHistory client={client} />);
    expect(await screen.findByTestId("ops-history-empty").then((n) => n.textContent)).toBe(EMPTY_TEXT);
  });

  it("renders one row per record with id, venue, pair, created_at, state", async () => {
    const client = makeClient({
      listDeploymentRecords: vi
        .fn()
        .mockResolvedValue([
          record(),
          record({ deployment_id: "dep-2", venue: "coinbase", pair: "BTC-USD", state: "paused" }),
        ]),
    });
    render(<DeploymentHistory client={client} />);
    const row1 = await screen.findByTestId("ops-history-row-dep-1");
    expect(row1.textContent).toContain("dep-1");
    expect(row1.textContent).toContain("kraken");
    expect(row1.textContent).toContain("SUIUSD");
    expect(row1.textContent).toContain("2023-11-14 22:13:30");
    expect(row1.textContent).toContain("paper");
    const row2 = screen.getByTestId("ops-history-row-dep-2");
    expect(row2.textContent).toContain("coinbase");
    expect(row2.textContent).toContain("paused");
    expect(screen.getByText(READ_ONLY_HELPER)).toBeTruthy();
  });

  it("renders no start, promote, pause, or edit control anywhere", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue([record()]) });
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-row-dep-1");
    for (const control of screen.queryAllByRole("button")) {
      expect(control.textContent).toBe("Refresh");
    }
  });
});

describe("DeploymentHistory click-to-detail", () => {
  it("expands an inline detail panel with config, schedule, and last execution summary", async () => {
    const getDeploymentRecord = vi.fn().mockResolvedValue(record());
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    fireEvent.click(await screen.findByTestId("ops-history-row-dep-1"));
    expect(await screen.findByTestId("ops-history-detail-dep-1")).toBeTruthy();
    expect(getDeploymentRecord).toHaveBeenCalledWith("dep-1");
    const config = await screen.findByTestId("ops-history-detail-config");
    expect(config.textContent).toContain("pack_id: trend-follow");
    expect(config.textContent).toContain("mode: paper");
    expect(screen.getByTestId("ops-history-detail-schedule").textContent).toContain("timeframe: 1h");
    expect(screen.getByTestId("ops-history-detail-summary").textContent).toContain(
      "one tick, no entries",
    );
  });

  it("collapses the detail panel on a second click of the same row", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord: vi.fn().mockResolvedValue(record()),
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    fireEvent.click(row);
    await screen.findByTestId("ops-history-detail-dep-1");
    fireEvent.click(screen.getByTestId("ops-history-row-dep-1"));
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-dep-1")).toBeNull());
    expect(client.getDeploymentRecord).toHaveBeenCalledTimes(1);
  });

  it("surfaces a truthful refusal code when the detail request 404s", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord: vi.fn().mockRejectedValue(
        new Error("deployment history failed: 404 deployment_not_found"),
      ),
    });
    render(<DeploymentHistory client={client} />);
    fireEvent.click(await screen.findByTestId("ops-history-row-dep-1"));
    const error = await screen.findByTestId("ops-history-detail-error");
    expect(error.textContent).toContain("deployment history failed: 404 deployment_not_found");
  });
});

describe("DeploymentHistory refresh", () => {
  it("retries the list and replaces rows on refresh", async () => {
    const listDeploymentRecords = vi
      .fn<() => Promise<DeploymentRecordRow[]>>()
      .mockResolvedValueOnce([record()])
      .mockResolvedValueOnce([
        record(),
        record({ deployment_id: "dep-2", venue: "coinbase", pair: "BTC-USD" }),
      ]);
    const client = makeClient({ listDeploymentRecords });
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-row-dep-1");
    expect(screen.queryByTestId("ops-history-row-dep-2")).toBeNull();
    fireEvent.click(screen.getByTestId("ops-history-refresh"));
    await screen.findByTestId("ops-history-row-dep-2");
    expect(listDeploymentRecords).toHaveBeenCalledTimes(2);
  });

  it("keeps the refresh button disabled while a request is in flight", async () => {
    let release: ((rows: DeploymentRecordRow[]) => void) | undefined;
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockImplementation(
        () => new Promise<DeploymentRecordRow[]>((resolve) => { release = resolve; }),
      ),
    });
    render(<DeploymentHistory client={client} />);
    const refresh = screen.getByTestId("ops-history-refresh");
    expect((refresh as HTMLButtonElement).disabled).toBe(true);
    release?.([]);
    await waitFor(() =>
      expect((screen.getByTestId("ops-history-refresh") as HTMLButtonElement).disabled).toBe(false),
    );
  });

  it("surfaces the list refusal message and lets the operator retry after a failure", async () => {
    const listDeploymentRecords = vi
      .fn<() => Promise<DeploymentRecordRow[]>>()
      .mockRejectedValueOnce(new Error("deployment history failed: 403 session required"))
      .mockResolvedValueOnce([record()]);
    const client = makeClient({ listDeploymentRecords });
    render(<DeploymentHistory client={client} />);
    const error = await screen.findByTestId("ops-history-error");
    expect(error.textContent).toContain("deployment history failed: 403 session required");
    expect(screen.queryByTestId("ops-history-table")).toBeNull();
    fireEvent.click(screen.getByTestId("ops-history-refresh"));
    await screen.findByTestId("ops-history-row-dep-1");
    expect(screen.queryByTestId("ops-history-error")).toBeNull();
  });

  it("surfaces a truthful message when the client build lacks the history methods", async () => {
    const client = makeClient({});
    render(<DeploymentHistory client={client} />);
    const error = await screen.findByTestId("ops-history-error");
    expect(error.textContent).toContain("history client is unavailable in this build");
    expect(screen.queryByTestId("ops-history-table")).toBeNull();
  });
});
