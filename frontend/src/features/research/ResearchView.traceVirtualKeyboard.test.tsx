import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ResearchView, type ResearchClient } from "./ResearchView";

afterEach(cleanup);

// Source regression only; the runtime verifier uses the real API.
async function loadTrace(count = 200): Promise<HTMLElement> {
  const client: ResearchClient = {
    submitRun: async () => ({ id: "keyboard-source-regression", state: "queued" }),
    cancelJob: async () => undefined,
    getJob: async () => ({ id: "keyboard-source-regression", state: "succeeded" }),
    getResultDownload: async () => new Response("{}"),
    getResult: async () => ({
      legacy_receipt: {},
      trace: Array.from({ length: count }, (_, index) => ({
        bar_ts: 1000 + index * 1000,
        input: { close: 10 + index },
        conditions: [{ path: `condition-${index}`, outcome: index % 2 === 0 }],
      })),
    }),
  };
  render(<ResearchView client={client} />);
  for (const [label, value] of [[/dataset path/i, "test-only.csv"], [/fee basis points/i, "40"], [/^from$/i, "0"], [/^to$/i, "200000"]] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByTestId("research-job-id");
  fireEvent.click(screen.getByRole("button", { name: /load result/i }));
  return screen.findByTestId("research-trace-scroll");
}

function key(name: string): void {
  fireEvent.keyDown(document.activeElement!, { key: name });
}

function focused(label: string): void {
  expect(document.activeElement?.textContent).toBe(label);
}

describe("virtual trace logical keyboard navigation", () => {
  it("mounts and focuses End/Home targets, clamps boundaries, and preserves real selection", async () => {
    const scroll = await loadTrace();
    const rows = within(scroll);
    expect(rows.queryByRole("button", { name: "200000" })).toBeNull();
    expect(rows.getAllByRole("button").length).toBeLessThan(200);
    rows.getByRole("button", { name: "1000" }).focus();
    key("ArrowUp");
    focused("1000");
    key("End");
    await waitFor(() => focused("200000"));
    expect(scroll.scrollTop).toBe(200 * 24 - 480);
    expect(rows.queryByRole("button", { name: "1000" })).toBeNull();
    expect(screen.queryByTestId("research-bar-detail")).toBeNull();
    key("ArrowDown");
    focused("200000");
    fireEvent.click(document.activeElement!);
    expect(screen.getByTestId("research-bar-detail").textContent).toContain("close: 209");
    expect(screen.getByTestId("research-bar-detail").textContent).toContain("condition-199");
    key("Home");
    await waitFor(() => focused("1000"));
    expect(scroll.scrollTop).toBe(0);
    fireEvent.click(document.activeElement!);
    expect(screen.getByTestId("research-bar-detail").textContent).toContain("close: 10");
    expect(screen.getByTestId("research-bar-detail").textContent).toContain("condition-0");
  });

  it("walks through unmounted rows in both directions without losing focus", async () => {
    const scroll = await loadTrace();
    within(scroll).getByRole("button", { name: "1000" }).focus();
    for (let i = 1; i < 200; i++) {
      key("ArrowDown");
      focused(String(1000 + i * 1000));
    }
    expect(scroll.scrollTop).toBe(4320);
    for (let i = 198; i >= 0; i--) {
      key("ArrowUp");
      focused(String(1000 + i * 1000));
    }
    expect(scroll.scrollTop).toBe(0);
    key("Escape");
    focused("1000");
    expect(screen.queryByTestId("research-bar-detail")).toBeNull();
    scroll.scrollTop = 2400;
    fireEvent.scroll(scroll);
    expect(within(scroll).queryByRole("button", { name: "1000" })).toBeNull();
    expect(within(scroll).getByRole("button", { name: "101000" })).toBeDefined();
  });

  it("handles a single row and empty result without phantom rows", async () => {
    const scroll = await loadTrace(1);
    within(scroll).getByRole("button").focus();
    for (const name of ["End", "ArrowDown", "Home", "ArrowUp"]) {
      key(name);
      focused("1000");
    }
    expect(scroll.scrollTop).toBe(0);
    cleanup();
    const empty = await loadTrace(0);
    expect(within(empty).queryAllByRole("button")).toHaveLength(0);
    fireEvent.keyDown(empty, { key: "End" });
    expect(screen.queryByTestId("research-bar-detail")).toBeNull();
  });
});
