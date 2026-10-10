import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

afterEach(cleanup);

/**
 * KRELL-SIGNAL-20261010 research presentation layer.
 *
 * Transport note: every client here is an in-memory vi.fn() fake standing
 * in for the loopback research API. No real venue/engine lifecycle is
 * exercised or implied by these tests.
 */
function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  const defaultResponse = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
  } as unknown as Response;
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-abc" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-abc", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(defaultResponse),
    ...overrides,
  };
}

const receipt = {
  equity: 123.45,
  max_drawdown: -8.5,
  fee_bps: 40,
  trades: [{ side: "buy" }, { side: "sell" }, { side: "buy" }],
  data_manifest_sha256:
    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
};

const trace = [
  {
    bar_ts: 1000,
    input: { close: 1.5 },
    conditions: [
      { path: ".all[0]", outcome: true },
      { path: ".all[1]", outcome: false },
    ],
  },
  {
    bar_ts: 2000,
    input: { close: 1.65 },
    conditions: [{ path: ".any[0]", outcome: "unknown" }],
  },
];

const stored: StoredResult = {
  legacy_receipt: receipt,
  trace,
};

function fillForm(): void {
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/synthetic.csv" },
  });
  fireEvent.change(screen.getByLabelText(/fee basis points/i), {
    target: { value: "40" },
  });
  fireEvent.change(screen.getByLabelText(/^from$/i), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText(/^to$/i), {
    target: { value: "1000" },
  });
}

async function runAndLoad(client: ResearchClient): Promise<void> {
  render(<ResearchView client={client} />);
  fillForm();
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByTestId("research-job-id");
  fireEvent.click(screen.getByRole("button", { name: /load result/i }));
  await screen.findByTestId("research-result");
}

describe("ResearchView Signal layout: setup panels", () => {
  it("groups the existing setup fields into titled panels without renaming any field", () => {
    render(<ResearchView client={makeClient()} />);

    const strategy = screen.getByTestId("research-setup-panel-strategy");
    expect(within(strategy).getByLabelText(/pack path/i)).toBeDefined();

    const data = screen.getByTestId("research-setup-panel-data");
    expect(within(data).getByLabelText(/dataset path/i)).toBeDefined();
    expect(
      within(data).getByRole("button", { name: /synthetic fixture/i }),
    ).toBeDefined();

    const window = screen.getByTestId("research-setup-panel-window");
    expect(within(window).getByLabelText(/^from$/i)).toBeDefined();
    expect(within(window).getByLabelText(/^to$/i)).toBeDefined();
    expect(within(window).getByLabelText(/holdout from/i)).toBeDefined();
    expect(within(window).getByLabelText(/holdout to/i)).toBeDefined();
    expect(
      within(window).getByTestId("research-date-window"),
    ).toBeDefined();

    const costs = screen.getByTestId("research-setup-panel-costs");
    expect(within(costs).getByLabelText(/fee basis points/i)).toBeDefined();
  });

  it("keeps Run/Cancel/Load result outside the setup panels in a run bar", async () => {
    render(<ResearchView client={makeClient()} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");

    const run = screen.getByRole("button", { name: /^run$/i });
    for (const panel of [
      "research-setup-panel-strategy",
      "research-setup-panel-data",
      "research-setup-panel-window",
      "research-setup-panel-costs",
    ]) {
      const scope = within(screen.getByTestId(panel));
      expect(scope.queryByRole("button", { name: /^run$/i })).toBeNull();
      expect(scope.queryByRole("button", { name: /^cancel$/i })).toBeNull();
      expect(scope.queryByRole("button", { name: /load result/i })).toBeNull();
    }
    const bar = screen.getByTestId("research-runbar");
    expect(within(bar).getByRole("button", { name: /^run$/i })).toBe(run);
    expect(within(bar).getByRole("button", { name: /cancel/i })).toBeDefined();
    expect(
      within(bar).getByRole("button", { name: /load result/i }),
    ).toBeDefined();
  });

  it("summarizes the exact configuration the next run will use (in-use strip)", () => {
    render(<ResearchView client={makeClient()} revisionId={null} />);

    expect(screen.getByTestId("research-inuse-dataset").textContent).toBe(
      "not set",
    );
    expect(screen.getByTestId("research-inuse-strategy").textContent).toBe(
      "not set",
    );
    expect(screen.getByTestId("research-inuse-fee").textContent).toBe(
      "not set",
    );
    expect(screen.getByTestId("research-inuse-window").textContent).toBe(
      "not set",
    );
    expect(screen.getByTestId("research-inuse-holdout").textContent).toBe(
      "not set",
    );

    fillForm();
    fireEvent.change(screen.getByLabelText(/pack path/i), {
      target: { value: "/tmp/pack.json" },
    });

    expect(screen.getByTestId("research-inuse-dataset").textContent).toBe(
      "fixtures/synthetic.csv",
    );
    expect(screen.getByTestId("research-inuse-strategy").textContent).toBe(
      "/tmp/pack.json",
    );
    expect(screen.getByTestId("research-inuse-fee").textContent).toBe("40");
    // Exact millisecond bounds are echoed verbatim, never reformatted.
    expect(screen.getByTestId("research-inuse-window").textContent).toBe(
      "0 → 1000",
    );
    expect(screen.getByTestId("research-inuse-holdout").textContent).toBe(
      "not set",
    );

    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "500" },
    });
    fireEvent.change(screen.getByLabelText(/holdout to/i), {
      target: { value: "900" },
    });
    expect(screen.getByTestId("research-inuse-holdout").textContent).toBe(
      "500 → 900",
    );
  });

  it("shows the revision as the strategy in use when one is selected", () => {
    render(<ResearchView client={makeClient()} revisionId="rev-saved" />);
    expect(screen.getByTestId("research-inuse-strategy").textContent).toBe(
      "revision rev-saved",
    );
  });

  it("shows a truthful waiting status while the current job has no result yet", async () => {
    const releaseJobHolder: {
      resolve: ((value: { id: string; state: string }) => void) | null;
    } = { resolve: null };
    const client = makeClient({
      getJob: () =>
        new Promise((resolve) => {
          releaseJobHolder.resolve = resolve;
        }),
      getResult: vi.fn().mockResolvedValue(stored),
    });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");

    const status = await screen.findByTestId("research-job-status");
    expect(status.textContent ?? "").toMatch(/waiting for the job result/i);

    releaseJobHolder.resolve?.({ id: "job-abc", state: "succeeded" });
    await screen.findByTestId("research-result");
    await waitFor(() => {
      expect(screen.queryByTestId("research-job-status")).toBeNull();
    });
  });
});

describe("ResearchView Signal layout: result presentation", () => {
  it("shows result provenance from the receipt and job, not from the editable form", async () => {
    await runAndLoad(
      makeClient({ getResult: vi.fn().mockResolvedValue(stored) }),
    );
    const context = screen.getByTestId("research-result-context");
    expect(context.textContent ?? "").toMatch(/job-abc/);
    expect(context.textContent ?? "").toMatch(/40/);
    expect(context.textContent ?? "").toMatch(/deadbeef/);
  });

  it("labels each metric's real source field and unit without inventing currency", async () => {
    await runAndLoad(
      makeClient({
        getResult: vi.fn().mockResolvedValue({
          legacy_receipt: {
            metrics: { total_return_pct: 12.5, max_drawdown_pct: -3.25, trade_count: 7 },
            fee_bps: 25,
            data_manifest_sha256: "cafe",
          },
          trace,
        } satisfies StoredResult),
      }),
    );

    const result = screen.getByTestId("research-result");
    expect(result.textContent ?? "").toContain("receipt.equity");
    expect(result.textContent ?? "").toContain("metrics.max_drawdown_pct · percent");
    expect(result.textContent ?? "").toContain("metrics.total_return_pct · percent");
    expect(result.textContent ?? "").toContain("receipt.fee_bps · basis points");
    expect(result.textContent ?? "").toContain("metrics.trade_count / trades · count");
    expect(result.textContent ?? "").toContain("receipt.data_manifest_sha256 · sha256");

    // Percentage return is displayed as a percentage, never as currency.
    expect(screen.getByTestId("research-result-total-return-pct").textContent).toBe("12.5");
    expect(screen.getByTestId("research-result-max-drawdown").textContent).toBe("-3.25%");
    expect(screen.getByTestId("research-result-equity").textContent).toBe("unavailable");
    expect(screen.getByTestId("research-result-trade-count").textContent).toBe("7");
    expect(result.textContent ?? "").not.toContain("$");
  });

  it("keeps unavailable metrics unavailable after the layout change", async () => {
    await runAndLoad(
      makeClient({
        getResult: vi.fn().mockResolvedValue({
          legacy_receipt: { fee_bps: 10 },
          trace,
        } satisfies StoredResult),
      }),
    );
    expect(screen.getByTestId("research-result-equity").textContent).toBe("unavailable");
    expect(screen.getByTestId("research-result-max-drawdown").textContent).toBe("unavailable");
    expect(screen.getByTestId("research-result-total-return-pct").textContent).toBe("unavailable");
    expect(screen.getByTestId("research-result-trade-count").textContent).toBe("unavailable");
    expect(screen.getByTestId("research-result-data-manifest-sha256").textContent).toBe("unavailable");
  });

  it("renders no synthetic chart or curve in the result section", async () => {
    await runAndLoad(
      makeClient({ getResult: vi.fn().mockResolvedValue(stored) }),
    );
    const result = screen.getByTestId("research-result");
    expect(result.querySelectorAll("svg, canvas").length).toBe(0);
  });

  it("exposes the raw stored result byte-identically under an explicit expandable detail", async () => {
    await runAndLoad(
      makeClient({ getResult: vi.fn().mockResolvedValue(stored) }),
    );
    const details = screen.getByTestId("research-receipt-detail");
    expect(details.tagName).toBe("DETAILS");
    expect((details as HTMLDetailsElement).open).toBe(false);

    const pre = within(details).getByTestId("research-export");
    expect(pre.tagName).toBe("PRE");
    expect(pre.textContent).toBe(JSON.stringify(stored));
  });

  it("keeps trace selection, detail and both exports usable after the layout change", async () => {
    const client = makeClient({ getResult: vi.fn().mockResolvedValue(stored) });
    await runAndLoad(client);

    const scroll = screen.getByTestId("research-trace-scroll");
    const rows = within(scroll).getAllByRole("button");
    expect(rows.length).toBeGreaterThan(0);
    fireEvent.click(rows[0]);
    const detail = await screen.findByTestId("research-bar-detail");
    expect(detail.textContent ?? "").toMatch(/1\.5/);
    expect(detail.textContent ?? "").toMatch(/\.all\[0\]/);

    expect(
      screen.getByRole("button", { name: /export result/i }),
    ).toBeDefined();
    expect(
      screen.getByRole("button", { name: /export csv/i }),
    ).toBeDefined();
  });

  it("keeps the windowed trace geometry: 24px rows agree with the spacer math", async () => {
    const bigTrace = Array.from({ length: 1200 }, (_, i) => ({
      bar_ts: 1_700_000_000_000 + i * 3_600_000,
      input: { close: 100 + i },
      conditions: [{ path: ".all[0]", outcome: true }],
    }));
    await runAndLoad(
      makeClient({
        getResult: vi.fn().mockResolvedValue({
          legacy_receipt: { equity: 0, trades: [{}] },
          trace: bigTrace,
        } satisfies StoredResult),
      }),
    );
    const scroll = screen.getByTestId("research-trace-scroll");
    const spacer = scroll.firstElementChild as HTMLElement;
    expect(spacer.style.height).toBe(`${1200 * 24}px`);
    const mounted = within(scroll).getAllByRole("button");
    expect(mounted.length).toBeGreaterThan(0);
    expect(mounted.length).toBeLessThan(120);
    for (const row of mounted) {
      expect((row as HTMLElement).style.height).toBe("24px");
    }
  });

  it("keeps the setup refusal alert working inside the panel layout", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").toMatch(/fee basis points/i);
    expect(client.submitRun).not.toHaveBeenCalled();
    expect(screen.queryByTestId("research-job-id")).toBeNull();
  });

  it("keeps the export failure path reporting the real download error", async () => {
    const client = makeClient({
      getResult: vi.fn().mockResolvedValue(stored),
      getResultDownload: vi.fn().mockRejectedValue(new Error("download failed: 500")),
    });
    await runAndLoad(client);
    fireEvent.click(screen.getByRole("button", { name: /export result/i }));
    await waitFor(() => {
      expect(client.getResultDownload).toHaveBeenCalledWith("job-abc");
    });
    expect(await screen.findByText(/download failed: 500/i)).toBeDefined();
  });
});
