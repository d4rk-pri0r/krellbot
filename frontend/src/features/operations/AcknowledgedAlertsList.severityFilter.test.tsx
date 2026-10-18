import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";
import type { AlertRow } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const CRITICAL_KILL_SWITCH: AlertRow = {
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

const WARNING_XXBTZUSD: AlertRow = {
  id: "a2",
  kind: "intent_refused",
  severity: "warning",
  code: "LOCAL_PAPER_HISTORY_ACK_FIXTURE",
  venue: "local-paper-fixture",
  pair: "XXBTZUSD",
  count: 1,
  first_ts: 1700000200,
  last_ts: 1700000200,
  acknowledged: true,
};

const WARNING_SUIUSD: AlertRow = {
  id: "a3",
  kind: "intent_refused",
  severity: "warning",
  code: "LOCAL_PAPER_HISTORY_ACK_OTHER",
  venue: "kraken",
  pair: "SUIUSD",
  count: 3,
  first_ts: 1700000300,
  last_ts: 1700000400,
  acknowledged: true,
};

const UNACKNOWLEDGED_INFO: AlertRow = {
  id: "a4",
  kind: "intent_refused",
  severity: "info",
  code: "LOCAL_PAPER_HISTORY_UNACK_FIXTURE",
  venue: "kraken",
  pair: "SUIUSD",
  count: 1,
  first_ts: 1700000500,
  last_ts: 1700000500,
  acknowledged: false,
};

const SEVERITY_FIXTURES = [
  CRITICAL_KILL_SWITCH,
  WARNING_XXBTZUSD,
  WARNING_SUIUSD,
  UNACKNOWLEDGED_INFO,
];

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

describe("AcknowledgedAlertsList severity filter and search", () => {
  it("renders the severity select with 'all' plus unique acknowledged severities in order and filters to warning rows", async () => {
    render(<AcknowledgedAlertsList client={makeClient(SEVERITY_FIXTURES)} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    const select = screen.getByTestId(
      "ops-acknowledged-filter-severity",
    ) as HTMLSelectElement;
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(3);
    });
    expect(select.value).toBe("all");
    // "info" only exists on the unacknowledged row, so it must not be offered.
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      "all",
      "critical",
      "warning",
    ]);
    fireEvent.change(select, { target: { value: "warning" } });
    expect(select.value).toBe("warning");
    expect(rowsIn(panel)).toHaveLength(2);
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    expect(screen.getByTestId("ops-acknowledged-alert-a3")).toBeTruthy();
    expect(screen.queryByTestId("ops-acknowledged-alert-a1")).toBeNull();
  });

  it("narrows rows with a case-insensitive substring query across id, kind, code, venue and pair", async () => {
    render(<AcknowledgedAlertsList client={makeClient(SEVERITY_FIXTURES)} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(3);
    });
    const input = screen.getByTestId("ops-acknowledged-filter-query");
    fireEvent.change(input, { target: { value: "xxbtzusd" } });
    expect(rowsIn(panel)).toHaveLength(1);
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    for (const needle of ["a1", "kill_switch", "local_paper_history_ack_other", "kraken", "suiusd"]) {
      fireEvent.change(input, { target: { value: needle } });
      expect(rowsIn(panel)).toHaveLength(1);
    }
  });

  it("shows the clear button only while a filter is active and resets both controls", async () => {
    render(<AcknowledgedAlertsList client={makeClient(SEVERITY_FIXTURES)} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(3);
    });
    expect(screen.queryByTestId("ops-acknowledged-filter-clear")).toBeNull();
    const input = screen.getByTestId("ops-acknowledged-filter-query");
    fireEvent.change(input, { target: { value: "xxbtzusd" } });
    expect(rowsIn(panel)).toHaveLength(1);
    fireEvent.click(screen.getByTestId("ops-acknowledged-filter-clear"));
    expect(screen.queryByTestId("ops-acknowledged-filter-clear")).toBeNull();
    expect(rowsIn(panel)).toHaveLength(3);
    expect((input as HTMLInputElement).value).toBe("");
    expect((screen.getByTestId("ops-acknowledged-filter-severity") as HTMLSelectElement).value).toBe(
      "all",
    );
    // The same reset works from a non-default severity too.
    fireEvent.change(screen.getByTestId("ops-acknowledged-filter-severity"), {
      target: { value: "warning" },
    });
    expect(rowsIn(panel)).toHaveLength(2);
    fireEvent.click(screen.getByTestId("ops-acknowledged-filter-clear"));
    expect(screen.queryByTestId("ops-acknowledged-filter-clear")).toBeNull();
    expect(rowsIn(panel)).toHaveLength(3);
  });

  it("renders the filtered-empty sentence only when filters exclude every row, keeping the plain empty state distinct", async () => {
    render(<AcknowledgedAlertsList client={makeClient(SEVERITY_FIXTURES)} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(3);
    });
    expect(screen.queryByTestId("ops-acknowledged-empty")).toBeNull();
    fireEvent.change(screen.getByTestId("ops-acknowledged-filter-severity"), {
      target: { value: "critical" },
    });
    fireEvent.change(screen.getByTestId("ops-acknowledged-filter-query"), {
      target: { value: "warning" },
    });
    const empty = screen.getByTestId("ops-acknowledged-empty");
    expect(empty.id).not.toBe("");
    for (const testId of ["ops-acknowledged-filter-severity", "ops-acknowledged-filter-query"]) {
      expect(screen.getByTestId(testId).getAttribute("aria-describedby")).toBe(empty.id);
    }
    expect(empty.textContent).toBe("No acknowledged alerts match the current filters.");
    expect(panel.textContent ?? "").not.toContain("No acknowledged alerts.");
    expect(rowsIn(panel)).toHaveLength(0);
    expect(screen.getByTestId("ops-acknowledged-table").querySelector("tbody tr")).toBeNull();
    fireEvent.click(screen.getByTestId("ops-acknowledged-filter-clear"));
    expect(screen.queryByTestId("ops-acknowledged-empty")).toBeNull();

    const emptyClient = makeClient([UNACKNOWLEDGED_INFO]);
    cleanup();
    render(<AcknowledgedAlertsList client={emptyClient} />);
    const emptyPanel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(emptyPanel.textContent).toContain("No acknowledged alerts.");
    });
    expect(screen.queryByTestId("ops-acknowledged-empty")).toBeNull();
    expect(screen.queryByTestId("ops-acknowledged-filter-clear")).toBeNull();
  });
});
