import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AlertsFilter, severityOptions } from "./AlertsFilter";
import type { AlertRow } from "./client";

afterEach(() => {
  cleanup();
});

const ALL_LABEL = "All severities";
const CLEAR_TEXT = "Clear filters";
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

const sample = [
  alert({ id: "a1", severity: "warning", code: "live_disabled", venue: "kraken" }),
  alert({ id: "a2", severity: "critical", code: "pack_stale", venue: "coinbase" }),
  alert({ id: "a3", severity: "warning", code: "kill_switch", venue: "kraken" }),
  alert({ id: "a4", severity: "info", code: null, venue: null }),
];

function rows(): HTMLElement[] {
  return sample
    .map((a) => screen.queryByTestId(`row-${a.id}`))
    .filter((el): el is HTMLElement => el !== null);
}

function mount(alerts: readonly AlertRow[] = sample) {
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

describe("AlertsFilter default state", () => {
  it("renders the filter chrome with all required testids", () => {
    mount();
    expect(screen.getByTestId("ops-alerts-filter")).toBeTruthy();
    expect(screen.getByTestId("ops-alerts-filter-severity")).toBeTruthy();
    expect(screen.getByTestId("ops-alerts-filter-query")).toBeTruthy();
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();
  });

  it("passes every alert through unchanged when no filter is applied", () => {
    mount();
    expect(rows()).toHaveLength(sample.length);
    const rendered = screen.getByTestId("rendered");
    expect(rendered.children).toHaveLength(sample.length);
  });

  it("hides the clear button while defaults are active", () => {
    mount();
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();
  });

  it("does not emit an empty-state row when alerts remain visible", () => {
    mount();
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });
});

describe("AlertsFilter severity options", () => {
  it("derives options from the unique severities present plus 'all' first", () => {
    expect(severityOptions(sample)).toEqual(["all", "warning", "critical", "info"]);
  });

  it("derives options dynamically (no closed enum) for an unseen severity", () => {
    expect(severityOptions([alert({ severity: "sev3" } )])).toEqual(["all", "sev3"]);
  });

  it("renders one option per unique severity, de-duplicated", () => {
    mount();
    const select = screen.getByTestId("ops-alerts-filter-severity") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["all", "warning", "critical", "info"]);
    expect(select.options[0].textContent).toBe(ALL_LABEL);
    expect(select.value).toBe("all");
  });

  it("still offers the 'all' placeholder when the alert list is empty", () => {
    mount([]);
    const select = screen.getByTestId("ops-alerts-filter-severity") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["all"]);
  });
});

describe("AlertsFilter severity filtering", () => {
  it("keeps only alerts matching the selected severity", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "critical" },
    });
    const visible = rows();
    expect(visible.map((el) => el.dataset.testid)).toEqual(["row-a2"]);
  });

  it("keeps all warnings when 'warning' is selected", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "warning" },
    });
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a1", "row-a3"]);
  });

  it("restores the full list when 'all' is re-selected", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "critical" },
    });
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "all" },
    });
    expect(rows()).toHaveLength(sample.length);
  });

  it("shows the clear button once a severity is chosen", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "warning" },
    });
    expect(screen.getByTestId("ops-alerts-filter-clear")).toBeTruthy();
  });
});

describe("AlertsFilter text query", () => {
  it("matches case-insensitively against alert code", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "PACK_STALE" },
    });
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a2"]);
  });

  it("matches case-insensitively against alert venue", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "CoinBase" },
    });
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a2"]);
  });

  it("treats a whitespace-only query as no narrowing", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "   " },
    });
    expect(rows()).toHaveLength(sample.length);
  });

  it("ignores null code/venue without throwing", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "kraken" },
    });
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a1", "row-a3"]);
  });

  it("composes severity AND query (intersection only)", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "warning" },
    });
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "kill" },
    });
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a3"]);
  });
});

describe("AlertsFilter empty result", () => {
  it("emits the ops-alerts-empty row before consumer output when nothing matches", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "zzz-no-match" },
    });
    expect(screen.getByTestId("ops-alerts-empty").textContent).toBe(EMPTY_TEXT);
    expect(rows()).toHaveLength(0);
  });

  it("does not emit the empty row for an empty input list", () => {
    mount([]);
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
  });

  it("reports isEmpty via the second render-prop argument", () => {
    let seen: boolean | undefined;
    render(
      <AlertsFilter alerts={sample}>
        {(_visible, isEmpty) => {
          seen = isEmpty;
          return <ul data-testid="rendered" />;
        }}
      </AlertsFilter>,
    );
    expect(seen).toBe(false);
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "zzz-no-match" },
    });
    expect(seen).toBe(true);
  });

  it("clears the empty row again when the query starts matching", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "zzz-no-match" },
    });
    expect(screen.getByTestId("ops-alerts-empty")).toBeTruthy();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "pack" },
    });
    expect(screen.queryByTestId("ops-alerts-empty")).toBeNull();
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a2"]);
  });
});

describe("AlertsFilter clear button", () => {
  it("is absent until a filter is active and resets both filters at once", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "warning" },
    });
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "kill" },
    });
    expect(rows().map((el) => el.dataset.testid)).toEqual(["row-a3"]);
    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    const select = screen.getByTestId("ops-alerts-filter-severity") as HTMLSelectElement;
    const input = screen.getByTestId("ops-alerts-filter-query") as HTMLInputElement;
    expect(select.value).toBe("all");
    expect(input.value).toBe("");
    expect(rows()).toHaveLength(sample.length);
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();
  });

  it("appears for a query-only filter and disappears after clearing", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-query"), {
      target: { value: "kraken" },
    });
    expect(screen.getByTestId("ops-alerts-filter-clear")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-alerts-filter-clear"));
    expect(screen.queryByTestId("ops-alerts-filter-clear")).toBeNull();
    expect(rows()).toHaveLength(sample.length);
  });

  it("is labeled with the literal 'Clear filters' text", () => {
    mount();
    fireEvent.change(screen.getByTestId("ops-alerts-filter-severity"), {
      target: { value: "info" },
    });
    expect(screen.getByTestId("ops-alerts-filter-clear").textContent).toBe(CLEAR_TEXT);
  });
});
