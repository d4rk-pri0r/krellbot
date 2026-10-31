import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const UNAVAILABLE_CREATED = "—";

function record(over: Partial<DeploymentRecordRow> = {}): DeploymentRecordRow {
  return {
    deployment_id: "dep-1",
    venue: "kraken",
    pair: "SUIUSD",
    created_at_ms: 1_700_000_010_000,
    state: "paper",
    config: { pack_id: "trend-follow", pack_version: "1.0.0", mode: "paper" },
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

function rowFor(deploymentId: string): HTMLTableRowElement {
  return screen.getByTestId(`ops-history-row-${deploymentId}`) as HTMLTableRowElement;
}

function createdCell(deploymentId: string): string {
  return rowFor(deploymentId).cells[3]?.textContent ?? "";
}

describe("DeploymentHistory created_at_ms range", () => {
  it("renders the unavailable em dash for a finite created_at_ms beyond the positive Date range", async () => {
    const client = makeClient({
      listDeploymentRecords: vi
        .fn()
        .mockResolvedValue([record({ deployment_id: "dep-future", created_at_ms: 9.1e15 })]),
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-future");
    expect(screen.getByTestId("ops-history-table")).toBeTruthy();
    expect(createdCell("dep-future")).toBe(UNAVAILABLE_CREATED);
    expect(row.textContent).toContain("dep-future");
    expect(row.textContent).toContain("kraken");
    expect(row.textContent).toContain("SUIUSD");
    expect(row.textContent).toContain("paper");
  });

  it("renders the unavailable em dash for a finite created_at_ms beyond the negative Date range", async () => {
    const client = makeClient({
      listDeploymentRecords: vi
        .fn()
        .mockResolvedValue([record({ deployment_id: "dep-past", created_at_ms: -9.1e15 })]),
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-past");
    expect(screen.getByTestId("ops-history-table")).toBeTruthy();
    expect(createdCell("dep-past")).toBe(UNAVAILABLE_CREATED);
    expect(row.textContent).toContain("dep-past");
    expect(row.textContent).toContain("kraken");
    expect(row.textContent).toContain("SUIUSD");
    expect(row.textContent).toContain("paper");
  });

  it("keeps byte-equal UTC strings for every healthy in-range created_at_ms", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([
        record(),
        record({ deployment_id: "dep-epoch", created_at_ms: 0 }),
        record({ deployment_id: "dep-pre-epoch", created_at_ms: -1_000 }),
      ]),
    });
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-row-dep-1");
    expect(createdCell("dep-1")).toBe("2023-11-14 22:13:30");
    expect(createdCell("dep-epoch")).toBe("1970-01-01 00:00:00");
    expect(createdCell("dep-pre-epoch")).toBe("1969-12-31 23:59:59");
  });

  it("still formats the exact Date-range boundary timestamps instead of the em dash", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([
        record({ deployment_id: "dep-max", created_at_ms: 8.64e15 }),
        record({ deployment_id: "dep-min", created_at_ms: -8.64e15 }),
      ]),
    });
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-row-dep-max");
    expect(createdCell("dep-max")).toBe("+275760-09-13 00:00");
    expect(createdCell("dep-min")).toBe("-271821-04-20 00:00");
    expect(createdCell("dep-max")).not.toBe(UNAVAILABLE_CREATED);
    expect(createdCell("dep-min")).not.toBe(UNAVAILABLE_CREATED);
  });

  it("keeps neighbouring rows, keyboard expansion, detail panels, and refresh usable beside out-of-range records", async () => {
    const rows: DeploymentRecordRow[] = [
      record(),
      record({
        deployment_id: "dep-2",
        venue: "coinbase",
        pair: "BTC-USD",
        created_at_ms: 9.1e15,
        state: "paused",
      }),
      record({ deployment_id: "dep-3", venue: "kraken", pair: "ETHUSD", created_at_ms: -9.1e15 }),
      record({ deployment_id: "dep-4", created_at_ms: 0 }),
    ];
    const listDeploymentRecords = vi
      .fn<() => Promise<DeploymentRecordRow[]>>()
      .mockResolvedValueOnce(rows)
      .mockResolvedValueOnce(rows);
    const getDeploymentRecord = vi.fn().mockResolvedValue(record());
    const client = makeClient({ listDeploymentRecords, getDeploymentRecord });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    expect(screen.getByTestId("ops-history-table")).toBeTruthy();
    expect(createdCell("dep-1")).toBe("2023-11-14 22:13:30");
    expect(createdCell("dep-2")).toBe(UNAVAILABLE_CREATED);
    expect(createdCell("dep-3")).toBe(UNAVAILABLE_CREATED);
    expect(createdCell("dep-4")).toBe("1970-01-01 00:00:00");
    row.focus();
    expect(fireEvent.keyDown(row, { key: "Enter" })).toBe(false);
    expect(getDeploymentRecord).toHaveBeenCalledWith("dep-1");
    expect(await screen.findByTestId("ops-history-detail-dep-1")).toBeTruthy();
    expect(rowFor("dep-1").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTestId("ops-history-detail-config").textContent).toContain(
      "pack_id: trend-follow",
    );
    fireEvent.keyDown(rowFor("dep-2"), { key: "Enter" });
    expect(await screen.findByTestId("ops-history-detail-dep-2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-history-refresh"));
    await screen.findByTestId("ops-history-row-dep-1");
    expect(listDeploymentRecords).toHaveBeenCalledTimes(2);
    expect(createdCell("dep-2")).toBe(UNAVAILABLE_CREATED);
    expect(createdCell("dep-4")).toBe("1970-01-01 00:00:00");
  });
});
