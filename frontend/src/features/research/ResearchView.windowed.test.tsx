import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

afterEach(cleanup);

function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  const defaultResponse = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
  } as unknown as Response;
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-xyz" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-xyz", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(defaultResponse),
    ...overrides,
  };
}

function makeTrace(rows: number): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  for (let i = 0; i < rows; i += 1) {
    out.push({
      bar_ts: 1_700_000_000_000 + i * 3_600_000,
      input: { close: 100 + i, ts_ms: 1_700_000_000_000 + i * 3_600_000 },
      conditions: [{ path: ".all[0]", outcome: true }],
    });
  }
  return out;
}

describe("ResearchView windowed trace", () => {
  it("renders research-trace-count = 5000 with mounted buttons < 500", async () => {
    const trace = makeTrace(5000);
    const client = makeClient({
      submitRun: vi.fn().mockResolvedValue({ id: "job-xyz" }),
      getResult: vi.fn().mockResolvedValue({
        legacy_receipt: { equity: 0, trades: [{}] },
        trace,
      } satisfies StoredResult),
    });
    render(<ResearchView client={client} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-trace-scroll");
    const count = (await screen.findByTestId("research-trace-count")).textContent ?? "";
    expect(count).toBe("5000");
    const scrollContainer = screen.getByTestId("research-trace-scroll");
    const mounted = within(scrollContainer).getAllByRole("button");
    expect(mounted.length).toBeLessThan(500);
  });

  it("scrolling reveals rows further down without remounting everything", async () => {
    const trace = makeTrace(5000);
    const client = makeClient({
      submitRun: vi.fn().mockResolvedValue({ id: "job-xyz" }),
      getResult: vi.fn().mockResolvedValue({
        legacy_receipt: { equity: 0, trades: [{}] },
        trace,
      } satisfies StoredResult),
    });
    render(<ResearchView client={client} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    const scrollContainer = (await screen.findByTestId(
      "research-trace-scroll",
    )) as HTMLElement;
    const initialMounted = within(scrollContainer).getAllByRole("button");
    const firstLabel = initialMounted[0]?.textContent ?? "";
    // Set scrollTop directly on the real element so the handler
    // reads the new value. jsdom does not honor the synthetic-event
    // ``target.scrollTop`` override.
    const targetScrollTop = 100_000;
    Object.defineProperty(scrollContainer, "scrollTop", {
      configurable: true,
      get: () => targetScrollTop,
    });
    // React 19 attaches scroll handlers to the root element; firing a
    // bubbling scroll event on the container is enough.
    fireEvent.scroll(scrollContainer);
    // Allow the React effect to run.
    await Promise.resolve();
    const laterMounted = within(scrollContainer).getAllByRole("button");
    const laterLabels = laterMounted.map((b) => b.textContent ?? "");
    expect(laterLabels).not.toContain(firstLabel);
  });

  it("clicking a mounted trace button reveals the bar detail", async () => {
    const trace = makeTrace(20);
    const client = makeClient({
      submitRun: vi.fn().mockResolvedValue({ id: "job-xyz" }),
      getResult: vi.fn().mockResolvedValue({
        legacy_receipt: { equity: 0, trades: [{}] },
        trace,
      } satisfies StoredResult),
    });
    render(<ResearchView client={client} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-trace-scroll");
    const buttons = within(screen.getByTestId("research-trace-scroll")).getAllByRole(
      "button",
    );
    expect(buttons.length).toBeGreaterThan(0);
    fireEvent.click(buttons[0]);
    expect(screen.getByTestId("research-bar-detail")).toBeDefined();
  });
});