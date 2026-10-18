import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";
import type { AlertRow } from "./client";

afterEach(cleanup);

function alert(id: string, acknowledged = true): AlertRow {
  return {
    id, acknowledged, kind: "warning", severity: "warning", code: null,
    venue: null, pair: null, count: 1, first_ts: 1700000000, last_ts: 1700000000,
  };
}

// jsdom has no Tab default action; emulate only browser sequential focus here.
function tab(): void {
  const controls = Array.from(document.querySelectorAll<HTMLElement>("button, [tabindex='0']"));
  const current = controls.indexOf(document.activeElement as HTMLElement);
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Tab" });
  controls[current + 1]?.focus();
}

function key(key: string): boolean {
  return fireEvent.keyDown(document.activeElement ?? document.body, { key });
}

describe("AcknowledgedAlertsList keyboard", () => {
  it("tabs to rows, toggles with Enter/Space, and moves focus with arrows without reads", async () => {
    let reads = 0;
    const client = { async listAcknowledged() {
      reads += 1;
      return [alert("first"), alert("hidden", false), alert("last")];
    } };
    render(<AcknowledgedAlertsList client={client} />);
    const first = await screen.findByTestId("ops-acknowledged-alert-first");
    const last = screen.getByTestId("ops-acknowledged-alert-last");
    tab();
    expect(document.activeElement).toBe(screen.getByTestId("ops-acknowledged-refresh"));
    tab();
    expect(document.activeElement).toBe(first);
    expect(first.getAttribute("role")).toBe("button");
    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(key("Enter")).toBe(false);
    expect(screen.getByTestId("ops-ack-detail-first").textContent).toContain("warning");
    expect(first.getAttribute("aria-expanded")).toBe("true");
    expect(key(" ")).toBe(false);
    expect(screen.queryByTestId("ops-ack-detail-first")).toBeNull();
    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(key("ArrowUp")).toBe(false);
    expect(document.activeElement).toBe(first);
    expect(key("ArrowDown")).toBe(false);
    expect(document.activeElement).toBe(last);
    key("ArrowDown");
    expect(document.activeElement).toBe(last);
    key(" ");
    expect(screen.getByTestId("ops-ack-detail-last")).toBeTruthy();
    key("ArrowUp");
    expect(document.activeElement).toBe(first);
    key("Enter");
    expect(screen.queryByTestId("ops-ack-detail-last")).toBeNull();
    expect(screen.getByTestId("ops-ack-detail-first")).toBeTruthy();
    expect(key("Escape")).toBe(true);
    expect(screen.getByTestId("ops-ack-detail-first")).toBeTruthy();
    tab();
    expect(document.activeElement).toBe(last);
    expect(screen.queryByTestId("ops-acknowledged-alert-hidden")).toBeNull();
    expect(reads).toBe(1);
  });
});
