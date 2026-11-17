/**
 * M16.4 — alert kind filter + honest unread count.
 * Opt-in notifications remain separate from telemetry (pinned in
 * NotificationsPanel); this suite pins Operations filter honesty.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  AlertsFilter,
  kindOptions,
  unreadAlertCount,
  unreadAlertLabel,
} from "./AlertsFilter";
import type { AlertRow } from "./client";

afterEach(() => {
  cleanup();
});

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

const sample = [
  alert({
    id: "u1",
    kind: "tick_failure",
    severity: "critical",
    code: "tick exited",
    acknowledged: false,
  }),
  alert({
    id: "u2",
    kind: "scheduler_stale",
    severity: "warning",
    code: "tick_stale",
    acknowledged: false,
  }),
  alert({
    id: "a1",
    kind: "metadata_refusal",
    severity: "warning",
    code: "metadata_unavailable",
    acknowledged: true,
  }),
  alert({
    id: "u3",
    kind: "restore_fence",
    severity: "critical",
    code: "restore_fence_engaged",
    acknowledged: false,
  }),
];

function mount(alerts: readonly AlertRow[] = sample) {
  return render(
    <AlertsFilter alerts={alerts}>
      {(visible) => (
        <ul data-testid="rendered">
          {visible.map((row) => (
            <li key={row.id} data-testid={`row-${row.id}`}>
              {row.kind}
            </li>
          ))}
        </ul>
      )}
    </AlertsFilter>,
  );
}

describe("AlertsFilter unread honesty (M16.4)", () => {
  it("counts only unacknowledged alerts as unread", () => {
    expect(unreadAlertCount(sample)).toBe(3);
    expect(unreadAlertLabel(3)).toBe("3 unread");
    expect(unreadAlertLabel(1)).toBe("1 unread");
    expect(unreadAlertCount([])).toBe(0);
    expect(unreadAlertLabel(0)).toBe("0 unread");
  });

  it("renders the unread count from the full alert list, not the filtered subset", () => {
    mount();
    expect(screen.getByTestId("ops-alerts-unread-count").textContent).toBe(
      "3 unread",
    );
    fireEvent.change(screen.getByTestId("ops-alerts-filter-kind"), {
      target: { value: "tick_failure" },
    });
    expect(screen.getByTestId("rendered").children).toHaveLength(1);
    // Unread stays honest to the unfiltered Operations list.
    expect(screen.getByTestId("ops-alerts-unread-count").textContent).toBe(
      "3 unread",
    );
  });
});

describe("AlertsFilter kind filter (M16.4)", () => {
  it("derives kind options from unique kinds plus all", () => {
    expect(kindOptions(sample)).toEqual([
      "all",
      "tick_failure",
      "scheduler_stale",
      "metadata_refusal",
      "restore_fence",
    ]);
  });

  it("filters visible rows by kind without inventing alerts", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-kind"), {
      target: { value: "restore_fence" },
    });
    expect(screen.getByTestId("row-u3")).toBeTruthy();
    expect(screen.queryByTestId("row-u1")).toBeNull();
    expect(screen.queryByTestId("row-u2")).toBeNull();
    expect(screen.queryByTestId("row-a1")).toBeNull();
  });

  it("combines kind and severity filters", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-kind"), {
      target: { value: "scheduler_stale" },
    });
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "critical" },
    });
    expect(screen.getByTestId("ops-alerts-empty").textContent).toMatch(
      /No alerts match/,
    );
    expect(screen.getByTestId("rendered").children).toHaveLength(0);
  });

  it("clear resets kind and severity together", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-kind"), {
      target: { value: "tick_failure" },
    });
    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    expect(
      (screen.getByTestId("ops-alerts-filter-kind") as HTMLSelectElement).value,
    ).toBe("all");
    expect(
      (screen.getByTestId("ops-alerts-filter-severity") as HTMLSelectElement)
        .value,
    ).toBe("all");
    expect(screen.getByTestId("rendered").children).toHaveLength(sample.length);
  });
});
