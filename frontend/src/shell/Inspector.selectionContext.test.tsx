import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AlertRow } from "../features/operations/client";
import type { PaperArmedRecord, PaperPosition } from "../features/paper/client";
import {
  Inspector,
  selectionFromAlert,
  selectionFromDeployment,
  selectionFromPosition,
} from "./Inspector";

afterEach(cleanup);

const DEPLOYMENT: PaperArmedRecord = {
  venue: "kraken",
  pair: "BTC/USD",
  mode: "paper",
  pack_id: "pack.sma",
  entries_paused: false,
};

const POSITION: PaperPosition = {
  schema_version: "1",
  armed: true,
  venue: "kraken",
  pair: "BTC/USD",
  mode: "paper",
  free_cash: "750.25",
  holdings: [{ symbol: "BTC", qty: "0.01" }],
};

const ALERT: AlertRow = {
  id: "alert-42",
  kind: "live_refused",
  severity: "warning",
  code: "paper_only",
  venue: "kraken",
  pair: "BTC/USD",
  count: 3,
  first_ts: 1,
  last_ts: 2,
  acknowledged: false,
};

describe("Inspector selection context (M7.4)", () => {
  it("maps a deployment into inspectable context with kind Deployment", () => {
    const selection = selectionFromDeployment(DEPLOYMENT);
    expect(selection).toEqual({
      id: "kraken:BTC/USD",
      kind: "deployment",
      label: "pack.sma · paper",
      detail: "Entries active",
    });
    render(<Inspector selection={selection} />);
    const selected = screen.getByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("deployment");
    expect(selected.textContent).toContain("Deployment");
    expect(selected.textContent).toContain("kraken:BTC/USD");
    expect(selected.textContent).toContain("pack.sma · paper");
    expect(selected.textContent).toContain("Entries active");
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });

  it("maps an owned position into inspectable context with kind Position", () => {
    const selection = selectionFromPosition(POSITION);
    expect(selection.kind).toBe("position");
    expect(selection.id).toBe("kraken:BTC/USD");
    expect(selection.label).toBe("0.01 BTC");
    expect(selection.detail).toBe("Free cash 750.25 USD");
    render(<Inspector selection={selection} />);
    const selected = screen.getByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("position");
    expect(selected.textContent).toContain("Position");
    expect(selected.textContent).toContain("0.01 BTC");
    expect(screen.getByTestId("inspector-selection-detail").textContent).toBe(
      "Free cash 750.25 USD",
    );
  });

  it("maps an alert into inspectable context with kind Alert", () => {
    const selection = selectionFromAlert(ALERT);
    expect(selection).toEqual({
      id: "alert-42",
      kind: "alert",
      label: "Live refused · Warning",
      detail: "kraken BTC/USD · paper_only · ×3",
    });
    render(<Inspector selection={selection} />);
    const selected = screen.getByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("alert");
    expect(selected.textContent).toContain("Alert");
    expect(selected.textContent).toContain("alert-42");
    expect(selected.textContent).toContain("Live refused · Warning");
  });

  it("is not stuck on the empty state when any workstation selection is present", () => {
    const { rerender } = render(<Inspector selection={null} />);
    expect(screen.getByTestId("inspector-empty").textContent).toMatch(
      /Nothing selected/,
    );
    rerender(
      <Inspector selection={selectionFromDeployment(DEPLOYMENT)} />,
    );
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
    expect(screen.getByTestId("inspector-selection")).not.toBeNull();
    rerender(<Inspector selection={selectionFromPosition(POSITION)} />);
    expect(screen.getByTestId("inspector-selection").getAttribute("data-kind")).toBe(
      "position",
    );
    rerender(<Inspector selection={selectionFromAlert(ALERT)} />);
    expect(screen.getByTestId("inspector-selection").getAttribute("data-kind")).toBe(
      "alert",
    );
  });
});
