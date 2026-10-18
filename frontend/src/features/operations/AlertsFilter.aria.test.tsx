import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AlertsFilter } from "./AlertsFilter";
import type { AlertRow } from "./client";

afterEach(cleanup);

const alerts: AlertRow[] = [{
  id: "local-aria-fixture", kind: "live_refused", severity: "warning",
  code: "LOCAL_ARIA_FIXTURE", venue: "local-paper-fixture", pair: "PAPERUSD",
  count: 1, first_ts: 1700000000, last_ts: 1700000000, acknowledged: false,
}];

function mount() {
  return render(
    <AlertsFilter alerts={alerts}>
      {(visible, isEmpty) => <output data-testid="visible">{visible.length}:{String(isEmpty)}</output>}
    </AlertsFilter>,
  );
}

function controls() {
  return [screen.getByTestId("ops-alerts-filter-severity"), screen.getByTestId("ops-alerts-filter-query")];
}

function expectNoDescription() {
  expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  for (const control of controls()) expect(control.hasAttribute("aria-describedby")).toBe(false);
}

function expectEmptyDescription() {
  const empty = screen.getByTestId("ops-alerts-empty");
  expect(empty.id).toBe("ops-alerts-empty-id");
  expect(empty.textContent).toBe("No alerts match the current filters.");
  for (const control of controls()) {
    expect(control.getAttribute("aria-describedby")).toBe(empty.id);
    expect(document.getElementById(control.getAttribute("aria-describedby")!)).toBe(empty);
  }
  expect(screen.getByTestId("visible").textContent).toBe("0:true");
}

describe("AlertsFilter accessible controls", () => {
  it("names both controls explicitly and associates visible labels with stable input ids", () => {
    mount();
    const severity = screen.getByRole("combobox", { name: "Filter alerts by severity" });
    const query = screen.getByRole("textbox", { name: "Search alerts by code or venue" });
    for (const [control, stem, name] of [
      [severity, "severity", "Filter alerts by severity"],
      [query, "query", "Search alerts by code or venue"],
    ] as const) {
      expect(control.id).toBe(`ops-alerts-filter-${stem}-input`);
      expect(control.getAttribute("aria-label")).toBe(name);
      const label = document.getElementById(`ops-alerts-filter-${stem}-label`) as HTMLLabelElement;
      expect(label.htmlFor).toBe(control.id);
      expect(label.control).toBe(control);
    }
    expectNoDescription();
  });

  it("describes both controls only while no rows match, and removes wiring on query recovery and clear", () => {
    mount();
    const [severity, query] = controls();
    expectNoDescription();
    fireEvent.change(query, { target: { value: "no-such-local-fixture" } });
    expectEmptyDescription();
    fireEvent.change(query, { target: { value: " LOCAL_ARIA " } });
    expectNoDescription();
    expect(screen.getByTestId("visible").textContent).toBe("1:false");
    fireEvent.change(severity, { target: { value: "warning" } });
    fireEvent.change(query, { target: { value: "missing" } });
    expectEmptyDescription();
    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    expectNoDescription();
  });

  it("removes descriptions when the source alert list becomes empty or starts matching", () => {
    const view = mount();
    fireEvent.change(controls()[1], { target: { value: "missing" } });
    expectEmptyDescription();
    view.rerender(<AlertsFilter alerts={[]}>{() => null}</AlertsFilter>);
    expectNoDescription();
    view.rerender(<AlertsFilter alerts={alerts}>{() => null}</AlertsFilter>);
    expect(screen.getByTestId("ops-alerts-empty").id).toBe("ops-alerts-empty-id");
    view.rerender(<AlertsFilter alerts={[{ ...alerts[0], code: "missing" }]}>{() => null}</AlertsFilter>);
    expectNoDescription();
  });
});
