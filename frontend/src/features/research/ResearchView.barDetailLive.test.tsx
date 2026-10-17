import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ResearchView, type ResearchClient } from "./ResearchView";

afterEach(cleanup);

// Only the transport is substituted to isolate React selection transitions;
// native Tab/Enter and the real loopback are covered by the runtime verifier.
async function loadTrace(trace: Array<Record<string, unknown>>) {
  const client: ResearchClient = {
    submitRun: async () => ({ id: "local-bar-detail-fixture", state: "succeeded" }),
    cancelJob: async () => undefined,
    getJob: async () => ({ id: "local-bar-detail-fixture", state: "succeeded" }),
    getResultDownload: async () => new Response("{}"),
    getResult: async () => ({ legacy_receipt: {}, trace }),
  };
  const view = render(<ResearchView client={client} />);
  for (const [label, value] of [[/dataset path/i, "local-fixture.csv"], [/fee basis points/i, "40"], [/^from$/i, "0"], [/^to$/i, "20000"]] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  const scroll = await screen.findByTestId("research-trace-scroll");
  return { ...view, client, rows: within(scroll).getAllByRole("button") };
}

async function mutationsDuring(region: HTMLElement, action: () => void): Promise<MutationRecord[]> {
  const records: MutationRecord[] = [];
  const observer = new MutationObserver((changes) => records.push(...changes));
  observer.observe(region, { childList: true, characterData: true, subtree: true });
  try {
    await act(async () => { action(); });
    records.push(...observer.takeRecords());
    return records;
  } finally {
    observer.disconnect();
  }
}

describe("selected bar polite announcements", () => {
  it("announces each changed label/close in a stable AT-only sibling, without repeat mutations", async () => {
    const trace = Array.from({ length: 5 }, (_, i) => ({
      bar_ts: i * 1000, input: { close: 100 + i },
      conditions: [{ path: `condition-${i}`, outcome: i % 2 === 0 }],
    }));
    const { rows, rerender, client } = await loadTrace(trace);
    const region = screen.getByTestId("research-bar-detail-live");
    expect(region.getAttribute("role")).toBe("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.getAttribute("aria-atomic")).toBe("true");
    expect(region.textContent).toBe("");
    expect(region.style.position).toBe("absolute");
    expect(region.style.clipPath).toBe("inset(50%)");
    expect(region.closest('[data-testid="research-result"]')).not.toBeNull();

    for (const i of [0, 2, 4]) {
      const mutations = await mutationsDuring(region, () => fireEvent.click(rows[i]));
      expect(mutations.length).toBeGreaterThan(0);
      expect(region.textContent).toBe(`Selected bar ${i * 1000} close ${100 + i}`);
      expect(screen.getByTestId("research-bar-detail-live")).toBe(region);
      const detail = screen.getByTestId("research-bar-detail");
      expect(detail.contains(region)).toBe(false);
      expect(detail.parentElement).toBe(region.parentElement);
      expect(within(detail).getByText("Selected bar detail")).toBeDefined();
      expect(within(detail).getByText(`close: ${100 + i}`)).toBeDefined();
      expect(within(detail).getByText(`condition-${i}`)).toBeDefined();
      expect(await mutationsDuring(region, () => fireEvent.click(rows[i]))).toHaveLength(0);
      expect(await mutationsDuring(region, () => rerender(<ResearchView client={client} />))).toHaveLength(0);
    }

    fireEvent.click(screen.getByRole("button", { name: "Load result" }));
    await screen.findByText("Selected bar cleared");
    expect(region.textContent).toBe("Selected bar cleared");
    expect(screen.queryByTestId("research-bar-detail")).toBeNull();
    expect(await mutationsDuring(region, () => rerender(<ResearchView client={client} />))).toHaveLength(0);
    fireEvent.click(rows[4]);
    expect(region.textContent).toBe("Selected bar 4000 close 104");
  });

  it("uses existing timestamp/close readers for string, missing, and zero values", async () => {
    const { rows } = await loadTrace([
      { bar_ts: "local-labelled-bar", input: { close: "12.3400" } },
      { conditions: [] },
      { bar_ts: 0, input: { close: 0 } },
    ]);
    for (const [i, message] of [
      [0, "Selected bar local-labelled-bar close 12.3400"],
      [1, "Selected bar 1 close unavailable"],
      [2, "Selected bar 0 close 0"],
    ] as const) {
      fireEvent.click(rows[i]);
      expect(screen.getByTestId("research-bar-detail-live").textContent).toBe(message);
    }
  });
});
