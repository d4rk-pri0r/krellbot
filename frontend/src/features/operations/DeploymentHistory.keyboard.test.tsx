import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * Sequential-keyboard access to the Operations deployment history.
 *
 * Every client below is an in-memory vi.fn() fake standing in for the
 * loopback operations API and every check runs in jsdom: these are
 * component-level regressions with synthetic data, not a real-browser
 * or real-backend acceptance. jsdom performs no default action for Tab,
 * so the sequential-focus helper below emulates only the browser's
 * ordinary forward/backward tab order over the rendered tab stops; the
 * activation keys themselves are dispatched on whichever element
 * actually holds DOM focus.
 */

const EXPAND_HINT = "Expand to inspect read-only details";
const COLLAPSE_HINT = "Collapse details";

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

const ROWS: DeploymentRecordRow[] = [
  record(),
  record({ deployment_id: "dep-2", venue: "coinbase", pair: "BTC-USD", state: "paused" }),
  record({ deployment_id: "dep-3", venue: "kraken", pair: "ETHUSD", state: "paper" }),
];

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

function rowFor(deploymentId: string): HTMLElement {
  return screen.getByTestId(`ops-history-row-${deploymentId}`);
}

// jsdom has no Tab default action; emulate only the browser's ordinary
// sequential focus over the rendered tab stops (controls, then rows).
function tab(backward = false): void {
  const stops = Array.from(document.querySelectorAll<HTMLElement>("button, [tabindex='0']"));
  const current = stops.indexOf(document.activeElement as HTMLElement);
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Tab", shiftKey: backward });
  const next = backward ? stops[current - 1] : stops[current + 1];
  if (next) next.focus();
}

// Dispatch a key on the focused element; fireEvent returns false once the
// handler called preventDefault (the Space scroll suppression contract).
function key(key: string): boolean {
  return fireEvent.keyDown(document.activeElement ?? document.body, { key });
}

function commandReads(client: OperationsClient): number {
  const commands = [
    client.getOperations,
    client.promote,
    client.pauseEntries,
    client.resumeEntries,
    client.engageKill,
    client.releaseKill,
    client.ackAlert,
  ] as unknown as Mock[];
  return commands.reduce((total, command) => total + command.mock.calls.length, 0);
}

describe("DeploymentHistory keyboard reachability", () => {
  it("makes every record row an ordinary Tab stop while keeping real table-row semantics", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue(ROWS) });
    render(<DeploymentHistory client={client} />);
    const first = await screen.findByTestId("ops-history-row-dep-1");
    for (const deploymentId of ["dep-1", "dep-2", "dep-3"]) {
      const row = rowFor(deploymentId);
      expect(row.tagName).toBe("TR");
      expect(row.getAttribute("role")).toBeNull();
      expect(row.getAttribute("tabindex")).toBe("0");
      expect(row.getAttribute("aria-expanded")).toBe("false");
      expect(row.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
      expect(row.textContent).toContain(EXPAND_HINT);
      expect(row.textContent).not.toContain(COLLAPSE_HINT);
    }
    expect(first.closest("table")?.querySelectorAll("thead th").length).toBe(5);
    tab();
    expect(document.activeElement).toBe(screen.getByTestId("ops-history-refresh"));
    tab();
    expect(document.activeElement).toBe(rowFor("dep-1"));
    tab();
    expect(document.activeElement).toBe(rowFor("dep-2"));
    tab();
    expect(document.activeElement).toBe(rowFor("dep-3"));
    tab(true);
    expect(document.activeElement).toBe(rowFor("dep-2"));
    tab(true);
    tab(true);
    expect(document.activeElement).toBe(screen.getByTestId("ops-history-refresh"));
  });

  it("does not put the empty-state row into the tab order", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue([]) });
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-empty");
    const stops = Array.from(document.querySelectorAll<HTMLElement>("[tabindex='0']"));
    expect(stops.map((stop) => stop.tagName)).toEqual([]);
    expect(screen.getByTestId("ops-history-refresh").tagName).toBe("BUTTON");
  });
});

describe("DeploymentHistory keyboard activation", () => {
  it("expands the focused record with Enter, associates the detail, and keeps focus on the row", async () => {
    const getDeploymentRecord = vi.fn().mockResolvedValue(record());
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue(ROWS),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    row.focus();
    expect(key("Enter")).toBe(false);
    expect(getDeploymentRecord).toHaveBeenCalledTimes(1);
    expect(getDeploymentRecord).toHaveBeenCalledWith("dep-1");
    const detail = await screen.findByTestId("ops-history-detail-dep-1");
    expect(row.getAttribute("aria-expanded")).toBe("true");
    expect(row.getAttribute("aria-controls")).toBe(detail.getAttribute("id"));
    expect(row.textContent).toContain(COLLAPSE_HINT);
    expect(document.activeElement).toBe(row);
    expect(screen.getByTestId("ops-history-detail-config").textContent).toContain(
      "pack_id: trend-follow",
    );
    expect(screen.getByTestId("ops-history-detail-schedule").textContent).toContain("timeframe: 1h");
    expect(screen.getByTestId("ops-history-detail-summary").textContent).toContain(
      "one tick, no entries",
    );
  });

  it("collapses the focused record with Space without scrolling and without a second request", async () => {
    const getDeploymentRecord = vi.fn().mockResolvedValue(record());
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    row.focus();
    key("Enter");
    await screen.findByTestId("ops-history-detail-dep-1");
    expect(key(" ")).toBe(false);
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-dep-1")).toBeNull());
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(row.textContent).toContain(EXPAND_HINT);
    expect(document.activeElement).toBe(row);
    expect(getDeploymentRecord).toHaveBeenCalledTimes(1);
    expect(key(" ")).toBe(false);
    expect(await screen.findByTestId("ops-history-detail-dep-1")).toBeTruthy();
    expect(getDeploymentRecord).toHaveBeenCalledTimes(2);
    expect(document.activeElement).toBe(row);
  });

  it("ignores unrelated keys without requesting details or suppressing their default action", async () => {
    const getDeploymentRecord = vi.fn();
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue(ROWS),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-2");
    row.focus();
    for (const unrelated of ["a", "A", "0", "ArrowDown", "ArrowUp", "ArrowLeft", "Escape", "Delete"]) {
      expect(key(unrelated)).toBe(true);
    }
    expect(getDeploymentRecord).not.toHaveBeenCalled();
    expect(screen.queryByTestId("ops-history-detail-dep-2")).toBeNull();
    expect(row.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps the pointer toggle working alongside keyboard activation", async () => {
    const getDeploymentRecord = vi.fn().mockResolvedValue(
      record({ deployment_id: "dep-2", venue: "coinbase", pair: "BTC-USD" }),
    );
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue(ROWS),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-2");
    fireEvent.click(row);
    expect(await screen.findByTestId("ops-history-detail-dep-2")).toBeTruthy();
    expect(getDeploymentRecord).toHaveBeenCalledWith("dep-2");
    fireEvent.click(rowFor("dep-2"));
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-dep-2")).toBeNull());
    row.focus();
    expect(key("Enter")).toBe(false);
    expect(await screen.findByTestId("ops-history-detail-dep-2")).toBeTruthy();
    expect(commandReads(client)).toBe(0);
  });

  it("keeps the history read-only: no command control appears and no command is issued", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue(ROWS),
      getDeploymentRecord: vi.fn().mockResolvedValue(record()),
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    row.focus();
    key("Enter");
    await screen.findByTestId("ops-history-detail-dep-1");
    for (const control of screen.queryAllByRole("button")) {
      expect(control.textContent).toBe("Refresh");
    }
    for (const deploymentId of ["dep-1", "dep-2", "dep-3"]) {
      rowFor(deploymentId).focus();
      key("Enter");
      key(" ");
      key("Enter");
    }
    expect(commandReads(client)).toBe(0);
  });
});

describe("DeploymentHistory keyboard async detail / refresh controls", () => {
  it("shows the truthful loading line and then the same read-only facts for keyboard opens", async () => {
    let releaseDetail: ((value: DeploymentRecordRow) => void) | undefined;
    const getDeploymentRecord = vi.fn().mockImplementation(
      () =>
        new Promise<DeploymentRecordRow>((resolve) => {
          releaseDetail = resolve;
        }),
    );
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    row.focus();
    key("Enter");
    expect(await screen.findByTestId("ops-history-detail-loading")).toBeTruthy();
    releaseDetail?.(record());
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-loading")).toBeNull());
    expect(screen.getByTestId("ops-history-detail-config").textContent).toContain(
      "pack_version: 1.0.0",
    );
    expect(document.activeElement).toBe(row);
  });

  it("surfaces a keyboard-opened detail refusal truthfully", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord: vi.fn().mockRejectedValue(
        new Error("deployment history failed: 404 deployment_not_found"),
      ),
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    row.focus();
    key("Enter");
    const error = await screen.findByTestId("ops-history-detail-error");
    expect(error.textContent).toContain("deployment history failed: 404 deployment_not_found");
    expect(document.activeElement).toBe(row);
    expect(row.getAttribute("aria-expanded")).toBe("true");
  });

  it("collapses the keyboard-opened record on refresh and restores a fresh tab order", async () => {
    const listDeploymentRecords = vi
      .fn<() => Promise<DeploymentRecordRow[]>>()
      .mockResolvedValueOnce(ROWS)
      .mockResolvedValueOnce(ROWS);
    const getDeploymentRecord = vi.fn().mockResolvedValue(record());
    const client = makeClient({ listDeploymentRecords, getDeploymentRecord });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    row.focus();
    key("Enter");
    await screen.findByTestId("ops-history-detail-dep-1");
    expect(getDeploymentRecord).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("ops-history-refresh"));
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-dep-1")).toBeNull());
    await screen.findByTestId("ops-history-row-dep-3");
    expect(listDeploymentRecords).toHaveBeenCalledTimes(2);
    rowFor("dep-1").focus();
    expect(key("Enter")).toBe(false);
    expect(await screen.findByTestId("ops-history-detail-dep-1")).toBeTruthy();
    expect(getDeploymentRecord).toHaveBeenCalledTimes(2);
    expect(document.activeElement).toBe(rowFor("dep-1"));
  });
});
