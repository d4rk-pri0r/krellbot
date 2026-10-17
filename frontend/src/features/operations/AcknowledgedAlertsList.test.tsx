import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";
import type { AlertRow } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ACKNOWLEDGED_KILL_SWITCH: AlertRow = {
  id: "a1",
  kind: "kill_switch",
  severity: "critical",
  code: null,
  venue: null,
  pair: null,
  count: 2,
  first_ts: 1700000000,
  last_ts: 1700000100,
  acknowledged: true,
};

const ACKNOWLEDGED_RECONCILE: AlertRow = {
  id: "a2",
  kind: "needs_reconcile",
  severity: "critical",
  code: "coid-1",
  venue: "kraken",
  pair: "SUIUSD",
  count: 1,
  first_ts: 1700000200,
  last_ts: 1700000200,
  acknowledged: true,
};

const UNACKNOWLEDGED_WARNING: AlertRow = {
  id: "a3",
  kind: "warning",
  severity: "warning",
  code: "refusal_code",
  venue: "kraken",
  pair: "BTCUSD",
  count: 3,
  first_ts: 1700000300,
  last_ts: 1700000400,
  acknowledged: false,
};

function makeClient(rows: AlertRow[]) {
  return {
    listAcknowledged: vi.fn().mockResolvedValue(rows),
  };
}

function rowsIn(panel: HTMLElement): HTMLElement[] {
  return Array.from(
    panel.querySelectorAll<HTMLElement>('[data-testid^="ops-acknowledged-alert-"]'),
  );
}

describe("AcknowledgedAlertsList rendering", () => {
  it("renders exactly the acknowledged rows and never the unacknowledged one", async () => {
    const client = makeClient([
      ACKNOWLEDGED_KILL_SWITCH,
      ACKNOWLEDGED_RECONCILE,
      UNACKNOWLEDGED_WARNING,
    ]);
    render(<AcknowledgedAlertsList client={client} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    expect(rowsIn(panel)).toHaveLength(2);
    expect(screen.getByTestId("ops-acknowledged-alert-a1")).toBeTruthy();
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    expect(screen.queryByTestId("ops-acknowledged-alert-a3")).toBeNull();
    expect(panel.textContent ?? "").not.toContain("a3");
  });

  it("renders the severity badge verbatim", async () => {
    const client = makeClient([ACKNOWLEDGED_KILL_SWITCH, ACKNOWLEDGED_RECONCILE]);
    render(<AcknowledgedAlertsList client={client} />);
    await screen.findByTestId("ops-acknowledged-alert-a1");
    expect(screen.getByTestId("ops-ack-severity-a1").textContent).toBe("critical");
    expect(screen.getByTestId("ops-ack-severity-a2").textContent).toBe("critical");
  });

  it("renders null code/venue/pair without crashing", async () => {
    const client = makeClient([ACKNOWLEDGED_KILL_SWITCH]);
    render(<AcknowledgedAlertsList client={client} />);
    const row = await screen.findByTestId("ops-acknowledged-alert-a1");
    expect(row.textContent ?? "").toContain("kill_switch");
  });

  it("renders the empty state when the stub returns no rows", async () => {
    const client = makeClient([]);
    render(<AcknowledgedAlertsList client={client} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(panel.textContent).toContain("No acknowledged alerts.");
    });
  });

  it("renders the loading state before the first read resolves", () => {
    const client = {
      listAcknowledged: vi.fn().mockImplementation(() => new Promise<AlertRow[]>(() => {})),
    };
    render(<AcknowledgedAlertsList client={client} />);
    const panel = screen.getByTestId("ops-acknowledged-alerts");
    expect(panel.textContent).toContain("Loading…");
  });

  it("renders a truthful failure state when the read fails", async () => {
    const client = {
      listAcknowledged: vi.fn().mockRejectedValue(new Error("operations view failed: 403")),
    };
    render(<AcknowledgedAlertsList client={client} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(panel.textContent).toContain("Failed to load acknowledged alerts.");
    });
    expect(panel.textContent ?? "").not.toContain("kill_switch");
  });
});

describe("AcknowledgedAlertsList refresh", () => {
  it("re-invokes listAcknowledged and renders the new rows", async () => {
    const listAcknowledged = vi
      .fn<() => Promise<AlertRow[]>>()
      .mockResolvedValueOnce([ACKNOWLEDGED_KILL_SWITCH])
      .mockResolvedValueOnce([ACKNOWLEDGED_RECONCILE]);
    render(<AcknowledgedAlertsList client={{ listAcknowledged }} />);
    await screen.findByTestId("ops-acknowledged-alert-a1");
    expect(listAcknowledged).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("ops-acknowledged-refresh"));
    await screen.findByTestId("ops-acknowledged-alert-a2");
    expect(listAcknowledged).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("ops-acknowledged-alert-a1")).toBeNull();
  });
});

describe("AcknowledgedAlertsList row detail", () => {
  it("expands a null-safe detail line on row click and collapses on second click", async () => {
    const client = makeClient([ACKNOWLEDGED_KILL_SWITCH]);
    render(<AcknowledgedAlertsList client={client} />);
    const row = await screen.findByTestId("ops-acknowledged-alert-a1");
    fireEvent.click(row);
    const detail = await screen.findByTestId("ops-ack-detail-a1");
    expect(detail.textContent ?? "").toContain("kill_switch");
    expect(detail.textContent ?? "").toContain("code: -");
    fireEvent.click(row);
    expect(screen.queryByTestId("ops-ack-detail-a1")).toBeNull();
  });
});
