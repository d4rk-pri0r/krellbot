import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";
import type { AlertRow } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const UNAVAILABLE = "—";

function alert(over: Partial<AlertRow> = {}): AlertRow {
  return {
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
    ...over,
  };
}

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

function cells(rowId: string): string[] {
  const tr = screen.getByTestId(`ops-acknowledged-alert-${rowId}`);
  return Array.from(tr.querySelectorAll("td")).map((td) => td.textContent ?? "");
}

const OUT_OF_RANGE_POSITIVE_SECONDS = 1e13;
const OUT_OF_RANGE_NEGATIVE_SECONDS = -1e13;
const MAX_VALID_EPOCH_SECONDS = 8640000000000;
const MIN_VALID_EPOCH_SECONDS = -8640000000000;

describe("AcknowledgedAlertsList timestamp range handling", () => {
  it("renders the unavailable em dash, not a RangeError, for out-of-Date-range, NaN and non-finite epoch seconds in either column", async () => {
    const invalidRows: Array<{ row: AlertRow; column: "first_ts" | "last_ts" }> = [
      { row: alert({ id: "pos-first", first_ts: OUT_OF_RANGE_POSITIVE_SECONDS }), column: "first_ts" },
      { row: alert({ id: "neg-first", first_ts: OUT_OF_RANGE_NEGATIVE_SECONDS }), column: "first_ts" },
      { row: alert({ id: "pos-last", last_ts: OUT_OF_RANGE_POSITIVE_SECONDS }), column: "last_ts" },
      { row: alert({ id: "neg-last", last_ts: OUT_OF_RANGE_NEGATIVE_SECONDS }), column: "last_ts" },
      { row: alert({ id: "past-max-first", first_ts: MAX_VALID_EPOCH_SECONDS + 1 }), column: "first_ts" },
      { row: alert({ id: "past-min-last", last_ts: MIN_VALID_EPOCH_SECONDS - 1 }), column: "last_ts" },
      { row: alert({ id: "nan-first", first_ts: Number.NaN }), column: "first_ts" },
      { row: alert({ id: "nan-last", last_ts: Number.NaN }), column: "last_ts" },
      { row: alert({ id: "inf-last", last_ts: Number.POSITIVE_INFINITY }), column: "last_ts" },
      { row: alert({ id: "neg-inf-first", first_ts: Number.NEGATIVE_INFINITY }), column: "first_ts" },
      { row: alert({ id: "overflow-last", last_ts: 1e308 }), column: "last_ts" },
      {
        row: alert({
          id: "both-invalid",
          first_ts: Number.NaN,
          last_ts: OUT_OF_RANGE_POSITIVE_SECONDS,
        }),
        column: "first_ts",
      },
    ];
    render(<AcknowledgedAlertsList client={makeClient(invalidRows.map((entry) => entry.row))} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(invalidRows.length);
    });
    expect(screen.getByTestId("ops-acknowledged-table")).toBeTruthy();
    for (const { row, column } of invalidRows) {
      const rowCells = cells(row.id);
      const invalidIndex = column === "first_ts" ? 6 : 7;
      const healthyIndex = column === "first_ts" ? 7 : 6;
      expect(rowCells[invalidIndex]).toBe(UNAVAILABLE);
      const healthyDefault = column === "first_ts" ? "2023-11-14 22:15:00" : "2023-11-14 22:13:20";
      expect(rowCells[healthyIndex]).toBe(
        row.id === "both-invalid" ? UNAVAILABLE : healthyDefault,
      );
    }
    const invalid = cells("nan-last");
    expect(invalid[0]).toBe("nan-last");
    expect(invalid[1]).toBe("kill_switch");
    expect(invalid[5]).toBe("×2");
    expect(screen.getByTestId("ops-ack-severity-nan-last").textContent).toBe("critical");
  });

  it("keeps healthy finite timestamps byte-equivalent UTC 'YYYY-MM-DD HH:MM:SS', including the exact Date valid boundaries", async () => {
    render(
      <AcknowledgedAlertsList
        client={makeClient([
          alert({ id: "epoch-zero", first_ts: 0, last_ts: 0 }),
          alert({ id: "sample", first_ts: 1700000000, last_ts: 1700000100 }),
          alert({
            id: "max-boundary",
            first_ts: MAX_VALID_EPOCH_SECONDS,
            last_ts: 253402300799,
          }),
          alert({
            id: "min-boundary",
            first_ts: MIN_VALID_EPOCH_SECONDS,
            last_ts: -62135596800,
          }),
        ])}
      />,
    );
    await screen.findByTestId("ops-acknowledged-alert-epoch-zero");
    expect(cells("epoch-zero")).toEqual([
      "epoch-zero",
      "kill_switch",
      "-",
      "-",
      "-",
      "×2",
      "1970-01-01 00:00:00",
      "1970-01-01 00:00:00",
      "critical",
    ]);
    expect(cells("sample")[6]).toBe("2023-11-14 22:13:20");
    expect(cells("sample")[7]).toBe("2023-11-14 22:15:00");
    expect(cells("max-boundary")[6]).toBe("+275760-09-13 00:00");
    expect(cells("max-boundary")[7]).toBe("9999-12-31 23:59:59");
    expect(cells("min-boundary")[6]).toBe("-271821-04-20 00:00");
    expect(cells("min-boundary")[7]).toBe("0001-01-01 00:00:00");
  });

  it("keeps the whole table usable when one row carries an invalid timestamp: neighbours render, detail toggle, filters and refresh still work", async () => {
    const healthyCritical = alert({
      id: "a1",
      first_ts: 1700000000,
      last_ts: 1700000100,
    });
    const invalidWarning = alert({
      id: "m1",
      kind: "intent_refused",
      severity: "warning",
      code: "TS_RANGE_FIXTURE",
      venue: "kraken",
      pair: "SUIUSD",
      count: 3,
      first_ts: 1700000200,
      last_ts: OUT_OF_RANGE_POSITIVE_SECONDS,
    });
    const healthyWarning = alert({
      id: "a2",
      kind: "intent_refused",
      severity: "warning",
      code: "TS_RANGE_FIXTURE",
      venue: "kraken",
      pair: "SUIUSD",
      count: 1,
      first_ts: 1700000300,
      last_ts: 1700000600,
    });
    const listAcknowledged = vi
      .fn<() => Promise<AlertRow[]>>()
      .mockResolvedValueOnce([healthyCritical, invalidWarning, healthyWarning])
      .mockResolvedValueOnce([healthyCritical]);
    render(<AcknowledgedAlertsList client={{ listAcknowledged }} />);
    const panel = await screen.findByTestId("ops-acknowledged-alerts");
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(3);
    });
    expect(cells("a1")[6]).toBe("2023-11-14 22:13:20");
    expect(cells("a1")[7]).toBe("2023-11-14 22:15:00");
    expect(cells("m1")[6]).toBe("2023-11-14 22:16:40");
    expect(cells("m1")[7]).toBe(UNAVAILABLE);
    expect(cells("a2")[6]).toBe("2023-11-14 22:18:20");
    expect(cells("a2")[7]).toBe("2023-11-14 22:23:20");

    fireEvent.click(screen.getByTestId("ops-acknowledged-alert-m1"));
    expect(await screen.findByTestId("ops-ack-detail-m1")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-acknowledged-alert-m1"));
    fireEvent.click(screen.getByTestId("ops-acknowledged-alert-a2"));
    expect(await screen.findByTestId("ops-ack-detail-a2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-acknowledged-alert-a2"));

    fireEvent.change(screen.getByTestId("ops-acknowledged-filter-severity"), {
      target: { value: "warning" },
    });
    expect(rowsIn(panel)).toHaveLength(2);
    expect(screen.queryByTestId("ops-acknowledged-alert-a1")).toBeNull();
    expect(screen.getByTestId("ops-acknowledged-alert-m1")).toBeTruthy();
    fireEvent.change(screen.getByTestId("ops-acknowledged-filter-query"), {
      target: { value: "a2" },
    });
    expect(rowsIn(panel)).toHaveLength(1);
    expect(screen.getByTestId("ops-acknowledged-alert-a2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-acknowledged-filter-clear"));
    expect(rowsIn(panel)).toHaveLength(3);

    fireEvent.click(screen.getByTestId("ops-acknowledged-refresh"));
    await waitFor(() => {
      expect(rowsIn(panel)).toHaveLength(1);
    });
    expect(listAcknowledged).toHaveBeenCalledTimes(2);
    expect(cells("a1")[7]).toBe("2023-11-14 22:15:00");
  });
});
