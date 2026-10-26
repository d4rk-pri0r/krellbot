import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertsFilter } from "./AlertsFilter";
import { OperationsView } from "./OperationsView";
import type { AlertRow, OperationsClient, OperationsViewModel } from "./client";

// Synthetic local fixtures only: every alert row and client response below is
// controllable JSDOM test data, not an executed trade or a real backend read.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const EMPTY_TEXT = "No alerts match the current filters.";

function alert(over: Partial<AlertRow> = {}): AlertRow {
  return {
    id: "a1",
    kind: "live_refused",
    severity: "warning",
    code: "live_disabled",
    venue: "kraken",
    pair: "SUIUSD",
    count: 1,
    first_ts: 1700000000,
    last_ts: 1700000600,
    acknowledged: false,
    ...over,
  };
}

const criticalRow = alert({
  id: "c1",
  kind: "kill_switch",
  severity: "critical",
  code: "kill_switch",
  venue: "kraken",
});
const warningRow = alert({
  id: "w1",
  kind: "live_refused",
  severity: "warning",
  code: "live_disabled",
  venue: "kraken",
});

function mountFilter(alerts: readonly AlertRow[]) {
  return render(
    <AlertsFilter alerts={alerts}>
      {(visible) => (
        <ul data-testid="rendered">
          {visible.map((a) => (
            <li key={a.id} data-testid={`row-${a.id}`}>
              {a.code ?? "-"} {a.venue ?? "-"}
            </li>
          ))}
        </ul>
      )}
    </AlertsFilter>,
  );
}

function severitySelect(): HTMLSelectElement {
  return screen.getByTestId("ops-alerts-filter-severity") as HTMLSelectElement;
}

function optionValues(select: HTMLSelectElement): string[] {
  return Array.from(select.options).map((o) => o.value);
}

describe("AlertsFilter severity across refreshed rows", () => {
  it("keeps the selected severity as a truthful explicit option after the last row of that severity disappears", () => {
    const view = mountFilter([criticalRow, warningRow]);
    fireEvent.change(severitySelect(), { target: { value: "critical" } });
    expect(screen.getByTestId("row-c1")).toBeTruthy();
    expect(screen.queryByTestId("row-w1")).toBeNull();

    view.rerender(
      <AlertsFilter alerts={[warningRow]}>
        {(visible) => (
          <ul data-testid="rendered">
            {visible.map((a) => (
              <li key={a.id} data-testid={`row-${a.id}`}>
                {a.code ?? "-"} {a.venue ?? "-"}
              </li>
            ))}
          </ul>
        )}
      </AlertsFilter>,
    );

    const select = severitySelect();
    expect(select.value).toBe("critical");
    const selectedOption = select.selectedOptions[0];
    expect(selectedOption).toBeDefined();
    expect(selectedOption.textContent).toBe("critical");
    expect(optionValues(select)).toEqual(["all", "warning", "critical"]);
    expect(screen.queryByTestId("row-w1")).toBeNull();
    expect(screen.getByTestId("ops-alerts-empty").textContent).toBe(EMPTY_TEXT);
  });

  it("reveals the remaining warnings after Clear while the selected severity was retained", () => {
    const view = mountFilter([criticalRow, warningRow]);
    fireEvent.change(severitySelect(), { target: { value: "critical" } });
    view.rerender(
      <AlertsFilter alerts={[warningRow]}>
        {(visible) => (
          <ul data-testid="rendered">
            {visible.map((a) => (
              <li key={a.id} data-testid={`row-${a.id}`}>
                {a.code ?? "-"} {a.venue ?? "-"}
              </li>
            ))}
          </ul>
        )}
      </AlertsFilter>,
    );
    expect(screen.getByTestId("ops-alerts-empty")).toBeTruthy();

    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));

    expect(severitySelect().value).toBe("all");
    expect((screen.getByTestId("ops-alerts-filter-query") as HTMLInputElement).value).toBe("");
    expect(screen.getByTestId("row-w1")).toBeTruthy();
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();
  });

  it("offers the selected severity exactly once when it reappears on a later refresh", () => {
    const view = mountFilter([criticalRow, warningRow]);
    fireEvent.change(severitySelect(), { target: { value: "critical" } });
    view.rerender(
      <AlertsFilter alerts={[warningRow]}>
        {(visible) => (
          <ul data-testid="rendered">
            {visible.map((a) => (
              <li key={a.id} data-testid={`row-${a.id}`}>
                {a.code ?? "-"} {a.venue ?? "-"}
              </li>
            ))}
          </ul>
        )}
      </AlertsFilter>,
    );

    const returnedCritical = alert({
      id: "c2",
      kind: "kill_switch",
      severity: "critical",
      code: "kill_switch",
      venue: "kraken",
    });
    view.rerender(
      <AlertsFilter alerts={[warningRow, returnedCritical]}>
        {(visible) => (
          <ul data-testid="rendered">
            {visible.map((a) => (
              <li key={a.id} data-testid={`row-${a.id}`}>
                {a.code ?? "-"} {a.venue ?? "-"}
              </li>
            ))}
          </ul>
        )}
      </AlertsFilter>,
    );

    const select = severitySelect();
    expect(optionValues(select)).toEqual(["all", "warning", "critical"]);
    expect(optionValues(select).filter((value) => value === "critical")).toHaveLength(1);
    expect(select.value).toBe("critical");
    expect(screen.getByTestId("row-c2")).toBeTruthy();
    expect(screen.queryByTestId("row-w1")).toBeNull();
  });

  it("retains the query text across a refresh that drops the selected severity", () => {
    const view = mountFilter([criticalRow, warningRow]);
    fireEvent.change(severitySelect(), { target: { value: "critical" } });
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "kraken" },
    });
    expect(screen.getByTestId("row-c1")).toBeTruthy();

    view.rerender(
      <AlertsFilter alerts={[warningRow]}>
        {(visible) => (
          <ul data-testid="rendered">
            {visible.map((a) => (
              <li key={a.id} data-testid={`row-${a.id}`}>
                {a.code ?? "-"} {a.venue ?? "-"}
              </li>
            ))}
          </ul>
        )}
      </AlertsFilter>,
    );

    expect((screen.getByTestId("ops-alerts-filter-query") as HTMLInputElement).value).toBe(
      "kraken",
    );
    expect(severitySelect().value).toBe("critical");
    expect(screen.queryByTestId("row-w1")).toBeNull();
    expect(screen.getByTestId("ops-alerts-empty").textContent).toBe(EMPTY_TEXT);
  });

  it("keeps the selected severity through an empty inventory and back to non-empty rows", () => {
    const children = () => (visible: AlertRow[]) => (
      <ul data-testid="rendered">
        {visible.map((a) => (
          <li key={a.id} data-testid={`row-${a.id}`}>
            {a.code ?? "-"} {a.venue ?? "-"}
          </li>
        ))}
      </ul>
    );
    const rerenderWith = (view: ReturnType<typeof mountFilter>, alerts: readonly AlertRow[]) =>
      view.rerender(<AlertsFilter alerts={alerts}>{children()}</AlertsFilter>);

    const view = mountFilter([criticalRow, warningRow]);
    fireEvent.change(severitySelect(), { target: { value: "critical" } });

    rerenderWith(view, []);
    const emptySelect = severitySelect();
    expect(emptySelect.value).toBe("critical");
    expect(optionValues(emptySelect)).toEqual(["all", "critical"]);
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();

    rerenderWith(view, [warningRow]);
    expect(severitySelect().value).toBe("critical");
    expect(screen.getByTestId("ops-alerts-empty").textContent).toBe(EMPTY_TEXT);
    expect(screen.queryByTestId("row-w1")).toBeNull();

    rerenderWith(view, []);
    expect(severitySelect().value).toBe("critical");
    expect(optionValues(severitySelect())).toEqual(["all", "critical"]);
  });

  it("keeps 'All severities' as the unfiltered control across refreshed rows", () => {
    const view = mountFilter([criticalRow, warningRow]);
    fireEvent.change(severitySelect(), { target: { value: "critical" } });
    fireEvent.change(severitySelect(), { target: { value: "all" } });
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();

    view.rerender(
      <AlertsFilter alerts={[warningRow]}>
        {(visible) => (
          <ul data-testid="rendered">
            {visible.map((a) => (
              <li key={a.id} data-testid={`row-${a.id}`}>
                {a.code ?? "-"} {a.venue ?? "-"}
              </li>
            ))}
          </ul>
        )}
      </AlertsFilter>,
    );

    const select = severitySelect();
    expect(select.value).toBe("all");
    expect(select.selectedOptions[0].textContent).toBe("All severities");
    expect(optionValues(select)).toEqual(["all", "warning"]);
    expect(screen.getByTestId("row-w1")).toBeTruthy();
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });
});

function operationsView(over: Partial<OperationsViewModel> = {}): OperationsViewModel {
  return {
    schema_version: "1",
    live: {
      schema_version: "1",
      live_enabled: false,
      authorized: [],
      kill_switch: { engaged: false, reason: null, engaged_at: null },
      promotion_available: false,
      promotion_code: "live_promotion_owner_deferred",
    },
    deployments: [],
    alerts: [],
    ...over,
  };
}

describe("OperationsView severity filter across a kill release", () => {
  it("keeps the selector truthful when releasing the kill switch drops the critical alert and a synthetic warning remains", async () => {
    let reads = 0;
    const client: OperationsClient = {
      getOperations: vi.fn().mockImplementation(async () => {
        reads += 1;
        if (reads === 1) {
          return operationsView({
            live: {
              schema_version: "1",
              live_enabled: false,
              authorized: [],
              kill_switch: { engaged: true, reason: "operator-test", engaged_at: 1700000000 },
              promotion_available: false,
              promotion_code: "live_promotion_owner_deferred",
            },
            alerts: [criticalRow, warningRow],
          });
        }
        if (reads === 2) {
          return operationsView({ alerts: [warningRow] });
        }
        return operationsView({ alerts: [criticalRow, warningRow] });
      }),
      promote: vi.fn().mockResolvedValue({ schema_version: "1", code: "live_disabled", ok: false }),
      pauseEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_paused", ok: true }),
      resumeEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_resumed", ok: true }),
      engageKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_engaged", ok: true }),
      releaseKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_released", ok: true }),
      ackAlert: vi.fn().mockResolvedValue({ schema_version: "1", code: "acknowledged", ok: true }),
    };

    render(<OperationsView client={client} />);
    expect(await screen.findByTestId("ops-alert-c1")).toBeTruthy();
    fireEvent.change(severitySelect(), { target: { value: "critical" } });
    expect(screen.queryByTestId("ops-alert-w1")).toBeNull();

    fireEvent.click(screen.getByTestId("ops-kill-release"));
    await waitFor(() => {
      expect(client.releaseKill).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("ops-kill-state").textContent).toContain("Kill switch: released");
    });

    const select = severitySelect();
    expect(select.value).toBe("critical");
    expect(select.selectedOptions[0].textContent).toBe("critical");
    expect(optionValues(select)).toEqual(["all", "warning", "critical"]);
    expect(screen.queryByTestId("ops-alert-w1")).toBeNull();
    expect(screen.getByTestId("ops-alerts-empty").textContent).toBe(EMPTY_TEXT);

    fireEvent.click(screen.getByTestId("ops-refresh"));
    await waitFor(() => {
      expect(screen.getByTestId("ops-alert-c1")).toBeTruthy();
    });
    expect(severitySelect().value).toBe("critical");
    expect(optionValues(severitySelect()).filter((value) => value === "critical")).toHaveLength(1);
    expect(screen.queryByTestId("ops-alert-w1")).toBeNull();
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();

    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    expect(severitySelect().value).toBe("all");
    expect(screen.getByTestId("ops-alert-w1")).toBeTruthy();
    expect(screen.getByTestId("ops-alert-c1")).toBeTruthy();
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });
});
