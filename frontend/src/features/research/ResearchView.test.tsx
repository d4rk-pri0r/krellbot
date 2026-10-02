import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

afterEach(cleanup);

function textOf(node: HTMLElement | null): string {
  return node?.textContent ?? "";
}

function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  const defaultBlob = new Blob(['{"ok":true}'], { type: "application/json" });
  const defaultResponse = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(defaultBlob),
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

const sampleReceipt = {
  equity: 123.45,
  max_drawdown: -8.5,
  fee_bps: 40,
  trades: [
    { side: "buy", qty: 1 },
    { side: "sell", qty: 1 },
    { side: "buy", qty: 1 },
  ],
  data_manifest_sha256: "deadbeef",
};

const sampleTrace = [
  {
    bar_ts: 1000,
    input: {
      ts_ms: 1000,
      open: 1.0,
      high: 1.0,
      low: 1.0,
      close: 1.5,
      volume: 0.0,
    },
    conditions: [
      { path: ".all[0]", outcome: true },
      { path: ".all[1]", outcome: false },
    ],
  },
  {
    bar_ts: 2000,
    input: {
      ts_ms: 2000,
      open: 1.6,
      high: 1.7,
      low: 1.55,
      close: 1.65,
      volume: 0.0,
    },
    conditions: [
      { path: ".any[0]", outcome: "unknown" },
    ],
  },
];

const sampleStored: StoredResult = {
  legacy_receipt: sampleReceipt,
  trace: sampleTrace,
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

describe("ResearchView form", () => {
  it("renders fields for dataset path, fee basis points, from, and to", () => {
    render(<ResearchView client={makeClient()} />);
    expect(screen.getByLabelText(/dataset path/i)).toBeDefined();
    expect(screen.getByLabelText(/fee basis points/i)).toBeDefined();
    expect(screen.getByLabelText(/^from$/i)).toBeDefined();
    expect(screen.getByLabelText(/^to$/i)).toBeDefined();
    expect(screen.getByLabelText(/holdout from/i)).toBeDefined();
    expect(screen.getByLabelText(/holdout to/i)).toBeDefined();
    expect(screen.getByRole("button", { name: /^run$/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /synthetic fixture/i })).toBeDefined();
  });

  it("'Synthetic fixture' fills dataset path with 'fixtures/synthetic.csv' and does not call the client", () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /synthetic fixture/i }));
    const datasetInput = screen.getByLabelText(/dataset path/i) as HTMLInputElement;
    expect(datasetInput.value).toBe("fixtures/synthetic.csv");
    expect(client.submitRun).not.toHaveBeenCalled();
    expect(client.cancelJob).not.toHaveBeenCalled();
    expect(client.getResult).not.toHaveBeenCalled();
  });

  it("Run calls client.submitRun with the form fields and renders the returned job id", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    expect(client.submitRun).toHaveBeenCalledWith({
      datasetPath: "fixtures/synthetic.csv",
      feeBps: 40,
      fromMs: 0,
      toMs: 1000,
      packPath: "",
    });
    expect(
      textOf(await screen.findByTestId("research-job-id")),
    ).toMatch(/job-abc/);
  });

  it("a blank pack path sends the saved revision id", async () => {
    const client = makeClient();
    render(<ResearchView client={client} revisionId="rev-saved" />);
    expect(screen.getByTestId("research-revision").textContent).toMatch(/rev-saved/);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = (client.submitRun as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(callArg.revisionId).toBe("rev-saved");
    expect(
      callArg.packPath === undefined || callArg.packPath === "",
    ).toBe(true);
  });

  it("with a saved revision, the pack path input is disabled and carries 'Using revision <id>' hint", () => {
    const client = makeClient();
    render(<ResearchView client={client} revisionId="rev-saved" />);
    const packInput = screen.getByLabelText(/pack path/i) as HTMLInputElement;
    expect(packInput.disabled).toBe(true);
    const hint = screen.getByTestId("research-pack-hint");
    expect(hint.textContent).toMatch(/Using revision rev-saved/);
  });

  it("with a saved revision, Run omits packPath from the request", async () => {
    const client = makeClient();
    render(<ResearchView client={client} revisionId="rev-saved" />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = (client.submitRun as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(callArg.revisionId).toBe("rev-saved");
    expect(
      callArg.packPath === undefined || callArg.packPath === "",
    ).toBe(true);
  });

  it("when a revision is selected after a pack path was typed, Run still posts only the revision (W1)", async () => {
    const client = makeClient();
    const { rerender } = render(
      <ResearchView client={client} revisionId={null} />,
    );
    fillForm();
    fireEvent.change(screen.getByLabelText(/pack path/i), {
      target: { value: "/tmp/pack.json" },
    });
    rerender(<ResearchView client={client} revisionId="rev-saved" />);
    expect(
      (screen.getByLabelText(/pack path/i) as HTMLInputElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = (client.submitRun as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(callArg.revisionId).toBe("rev-saved");
    expect(
      callArg.packPath === undefined || callArg.packPath === "",
    ).toBe(true);
  });

  it("Cancel calls client.cancelJob with that job id", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    await waitFor(() => {
      expect(client.cancelJob).toHaveBeenCalledWith("job-abc");
    });
  });

  it("does not write to localStorage on Run", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });
});

describe("ResearchView result panel", () => {
  it("renders equity, max drawdown, fee basis points, trade count, and data_manifest_sha256 from legacy_receipt", async () => {
    const client = makeClient({
      submitRun: vi.fn().mockResolvedValue({ id: "job-abc" }),
      getResult: vi.fn().mockResolvedValue(sampleStored),
    });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-result");

    expect(
      textOf(screen.getByTestId("research-result-equity")),
    ).toMatch(/123\.45/);
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toMatch(/-8\.5/);
    expect(
      textOf(screen.getByTestId("research-result-fee-bps")),
    ).toMatch(/^40/);
    expect(
      textOf(screen.getByTestId("research-result-trade-count")),
    ).toMatch(/^3/);
    expect(
      textOf(screen.getByTestId("research-result-data-manifest-sha256")),
    ).toMatch(/deadbeef/);
  });

  it("renders 'unavailable' for absent keys, never '0'", async () => {
    const partial: StoredResult = {
      legacy_receipt: { data_manifest_sha256: "kept" },
      trace: [],
    };
    const client = makeClient({
      getResult: vi.fn().mockResolvedValue(partial),
    });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-result");

    expect(
      textOf(screen.getByTestId("research-result-equity")),
    ).toMatch(/unavailable/);
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toMatch(/unavailable/);
    expect(
      textOf(screen.getByTestId("research-result-fee-bps")),
    ).toMatch(/unavailable/);
    expect(
      textOf(screen.getByTestId("research-result-trade-count")),
    ).toMatch(/unavailable/);
    expect(
      textOf(screen.getByTestId("research-result")),
    ).not.toMatch(/^0|\s0|\b0$/);
    expect(
      textOf(screen.getByTestId("research-result-data-manifest-sha256")),
    ).toMatch(/kept/);
  });

  it("trade count is len(trades) only when trades is an array", async () => {
    const nonArray: StoredResult = {
      legacy_receipt: { trades: "not-an-array", fee_bps: 10 },
      trace: [],
    };
    const client = makeClient({ getResult: vi.fn().mockResolvedValue(nonArray) });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-result");

    expect(
      textOf(screen.getByTestId("research-result-trade-count")),
    ).toMatch(/unavailable/);
  });

  // DISC-EQUITY-UNIT: a production-shaped locked receipt exposes percentage
  // performance under ``metrics`` and has no currency equity field at all.
  const productionReceipt = {
    engine_version: "0.9.5",
    pack_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    data_manifest_sha256: "feedface",
    venue: "kraken",
    pair: "SUIUSD",
    tf: "1h",
    from: "2026-01-01",
    to: "2026-01-02",
    fee_bps: 10,
    slippage_bps: 0,
    slippage_mult: 1.0,
    metrics: {
      total_return_pct: 12.5,
      cagr_pct: 9125.0,
      max_drawdown_pct: -4.25,
      return_to_dd: 2.94,
      per_year: { trades: 0, r: 0 },
      trade_count: 7,
      exposure_pct: 55.0,
      buy_and_hold: {
        total_return_pct: -1.2,
        cagr_pct: -876.0,
        max_drawdown_pct: -9.9,
        return_to_dd: -0.12,
        per_year: { trades: 0, r: 0 },
        trade_count: 0,
        exposure_pct: 99.0,
      },
    },
    equity_curve: [0, 1.2, 2.4, 12.5],
  };

  const productionStored: StoredResult = {
    legacy_receipt: productionReceipt,
    trace: [],
  };

  async function loadStoredResult(
    stored: StoredResult,
  ): Promise<() => void> {
    const client = makeClient({ getResult: vi.fn().mockResolvedValue(stored) });
    const view = render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-result");
    return view.unmount;
  }

  it("production-shaped metrics keep currency equity unavailable", async () => {
    await loadStoredResult(productionStored);

    // No currency equity exists on a production-shaped receipt, so the
    // Equity metric must be unavailable — never the percentage
    // total_return_pct and never an equity_curve point reinterpreted
    // as cash.
    const equityText = textOf(screen.getByTestId("research-result-equity"));
    expect(equityText).toBe("unavailable");
    expect(equityText).not.toMatch(/12\.5/);
    const lastCurvePoint = productionReceipt.equity_curve[
      productionReceipt.equity_curve.length - 1
    ];
    expect(equityText).not.toBe(String(lastCurvePoint));
    // The percentage return is shown separately under an explicitly
    // labeled percentage metric.
    expect(screen.getByText("Total return (%)")).toBeDefined();
    expect(textOf(screen.getByTestId("research-result-total-return-pct"))).toBe(
      "12.5",
    );
    // The typed percent metric is not also smuggled into money fields.
    expect(equityText).not.toMatch(/%/);
  });

  it("nested drawdown declares percentage units", async () => {
    const unmountProduction = await loadStoredResult(productionStored);

    // metrics.max_drawdown_pct is a typed percentage; its actual value is
    // displayed with explicit percent units.
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("-4.25%");

    // The legacy top-level fixture value stays untyped: the original
    // unadorned value is preserved without invented percent/currency
    // units, and the original assertion still passes.
    unmountProduction();
    await loadStoredResult(sampleStored);
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("-8.5");
  });

  it("non-finite real-shape metrics remain unavailable", async () => {
    const nonFiniteStored: StoredResult = {
      legacy_receipt: {
        ...productionReceipt,
        metrics: {
          ...productionReceipt.metrics,
          total_return_pct: Number.NaN,
          max_drawdown_pct: Number.POSITIVE_INFINITY,
        },
      },
      trace: [],
    };
    await loadStoredResult(nonFiniteStored);

    // NaN/Infinity percentages are unavailable, never rendered as
    // "NaN"/"Infinity" or coerced to a fabricated zero.
    expect(
      textOf(screen.getByTestId("research-result-total-return-pct")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-equity")),
    ).toBe("unavailable");
    // A finite sibling metric still renders its real value.
    expect(
      textOf(screen.getByTestId("research-result-trade-count")),
    ).toBe("7");
  });

  it("absent metrics object keeps percentage metrics unavailable", async () => {
    const noMetricsStored: StoredResult = {
      legacy_receipt: { fee_bps: 10, data_manifest_sha256: "feedface" },
      trace: [],
    };
    await loadStoredResult(noMetricsStored);

    expect(
      textOf(screen.getByTestId("research-result-total-return-pct")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-equity")),
    ).toBe("unavailable");
    expect(textOf(screen.getByTestId("research-result-fee-bps"))).toBe("10");
  });

  it("null and non-numeric metric values render unavailable, never zero", async () => {
    const nullishStored: StoredResult = {
      legacy_receipt: {
        ...productionReceipt,
        metrics: {
          ...productionReceipt.metrics,
          total_return_pct: null,
          max_drawdown_pct: "not-a-number",
        },
      },
      trace: [],
    };
    await loadStoredResult(nullishStored);

    expect(
      textOf(screen.getByTestId("research-result-total-return-pct")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result")),
    ).not.toMatch(/^0|\s0|\b0$/);
  });

  it("wrong-shape metrics object renders unavailable", async () => {
    const stringMetricsStored: StoredResult = {
      legacy_receipt: { ...productionReceipt, metrics: "not-an-object" },
      trace: [],
    };
    const unmountStringMetrics = await loadStoredResult(stringMetricsStored);

    expect(
      textOf(screen.getByTestId("research-result-total-return-pct")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("unavailable");

    unmountStringMetrics();

    const arrayMetricsStored: StoredResult = {
      legacy_receipt: { ...productionReceipt, metrics: [1, 2, 3] },
      trace: [],
    };
    await loadStoredResult(arrayMetricsStored);

    expect(
      textOf(screen.getByTestId("research-result-total-return-pct")),
    ).toBe("unavailable");
    expect(
      textOf(screen.getByTestId("research-result-max-drawdown")),
    ).toBe("unavailable");
  });
});

describe("ResearchView trace", () => {
  it("renders one button per bar using bar_ts", async () => {
    const client = makeClient({ getResult: vi.fn().mockResolvedValue(sampleStored) });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-trace");

    expect(screen.getByRole("button", { name: "1000" })).toBeDefined();
    expect(screen.getByRole("button", { name: "2000" })).toBeDefined();
  });

  it("choosing a bar shows input.close and each condition path with its outcome", async () => {
    const client = makeClient({ getResult: vi.fn().mockResolvedValue(sampleStored) });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-trace");

    fireEvent.click(screen.getByRole("button", { name: "1000" }));
    const detail = (await screen.findByTestId(
      "research-bar-detail",
    )) as HTMLElement;
    const text = detail.textContent ?? "";
    expect(text).toMatch(/1\.5/);
    expect(text).toMatch(/\.all\[0\]/);
    expect(text).toMatch(/true/);
    expect(text).toMatch(/\.all\[1\]/);
    expect(text).toMatch(/false/);
  });

  it("an outcome of 'unknown' stays the text 'unknown'", async () => {
    const client = makeClient({ getResult: vi.fn().mockResolvedValue(sampleStored) });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await screen.findByTestId("research-trace");

    fireEvent.click(screen.getByRole("button", { name: "2000" }));
    const detail = (await screen.findByTestId(
      "research-bar-detail",
    )) as HTMLElement;
    expect(detail.textContent ?? "").toMatch(/unknown/);
  });
});

describe("ResearchView export", () => {
  it("Export result fetches /api/v1/jobs/{id}/result/download and feeds the response blob to URL.createObjectURL", async () => {
    const blob = new Blob(['{"canon":true}'], { type: "application/json" });
    const downloadResponse = {
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(blob),
    } as unknown as Response;
    const client = makeClient({
      getResult: vi.fn().mockResolvedValue(sampleStored),
      getResultDownload: vi.fn().mockResolvedValue(downloadResponse),
    });
    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(
      () => "blob:research-result",
    );
    const revokeObjectURL = vi.fn();
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
    let capturedAnchor: HTMLAnchorElement | null = null;
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation(
      ((tag: string) => {
        const el = realCreateElement(tag) as HTMLElement;
        if (tag.toLowerCase() === "a") {
          capturedAnchor = el as HTMLAnchorElement;
        }
        return el as ReturnType<typeof document.createElement>;
      }) as typeof document.createElement,
    );
    try {
      render(<ResearchView client={client} />);
      fillForm();
      fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
      await screen.findByTestId("research-job-id");
      fireEvent.click(screen.getByRole("button", { name: /load result/i }));
      await screen.findByTestId("research-result");

      fireEvent.click(screen.getByRole("button", { name: /export result/i }));

      await waitFor(() => {
        expect(client.getResultDownload).toHaveBeenCalledTimes(1);
      });
      expect(client.getResultDownload).toHaveBeenCalledWith("job-abc");
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      const passedBlob = createObjectURL.mock.calls[0]?.[0] as Blob | undefined;
      expect(passedBlob).toBe(blob);
      expect(capturedAnchor).not.toBeNull();
      expect(capturedAnchor!.href).toBe("blob:research-result");
      expect(capturedAnchor!.download).toBe("research-receipt-job-abc.json");
      expect(createElementSpy).toHaveBeenCalled();
    } finally {
      createElementSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });

  it("Export result surfaces an error and never falls back to JSON.stringify when the download response is not ok", async () => {
    const client = makeClient({
      getResult: vi.fn().mockResolvedValue(sampleStored),
      getResultDownload: vi.fn().mockRejectedValue(new Error("download failed: 500")),
    });
    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(
      () => "blob:research-result",
    );
    const originalCreate = URL.createObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    try {
      render(<ResearchView client={client} />);
      fillForm();
      fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
      await screen.findByTestId("research-job-id");
      fireEvent.click(screen.getByRole("button", { name: /load result/i }));
      await screen.findByTestId("research-result");

      fireEvent.click(screen.getByRole("button", { name: /export result/i }));

      await waitFor(() => {
        expect(client.getResultDownload).toHaveBeenCalledTimes(1);
      });
      expect(createObjectURL).not.toHaveBeenCalled();
      expect(
        await screen.findByText(/download failed: 500/i),
      ).toBeDefined();
    } finally {
      URL.createObjectURL = originalCreate;
    }
  });
});

describe("ResearchView holdout bounds", () => {
  it("with empty holdout fields, submitRun is called without holdoutFromMs or holdoutToMs", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = (
      client.submitRun as ReturnType<typeof vi.fn>
    ).mock.calls[0][0] as Record<string, unknown>;
    expect(callArg).not.toHaveProperty("holdoutFromMs");
    expect(callArg).not.toHaveProperty("holdoutToMs");
  });

  it("with integer holdout fields, submitRun receives holdoutFromMs and holdoutToMs as numbers", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "500" },
    });
    fireEvent.change(screen.getByLabelText(/holdout to/i), {
      target: { value: "900" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    expect(client.submitRun).toHaveBeenCalledWith({
      datasetPath: "fixtures/synthetic.csv",
      feeBps: 40,
      fromMs: 0,
      toMs: 1000,
      packPath: "",
      holdoutFromMs: 500,
      holdoutToMs: 900,
    });
  });

  it("with one empty holdout field, does not submit and shows 'holdout bounds must both be set'", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    expect(client.submitRun).not.toHaveBeenCalled();
    expect(
      await screen.findByText("holdout bounds must both be set"),
    ).toBeDefined();
  });

  it("with 'true' in Holdout from, does not submit and shows 'holdout bound must be an integer'", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "true" },
    });
    fireEvent.change(screen.getByLabelText(/holdout to/i), {
      target: { value: "900" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    expect(client.submitRun).not.toHaveBeenCalled();
    expect(
      await screen.findByText("holdout bound must be an integer"),
    ).toBeDefined();
  });
});

describe("ResearchView pollForResult (M2-CE)", () => {
  it("polls getJob until succeeded and then calls getResult exactly once", async () => {
    const getJob = vi
      .fn()
      .mockResolvedValueOnce({ id: "job-abc", state: "running" })
      .mockResolvedValueOnce({ id: "job-abc", state: "running" })
      .mockResolvedValueOnce({ id: "job-abc", state: "succeeded" });
    const getResult = vi.fn().mockResolvedValue(sampleStored);
    const client = makeClient({ getJob, getResult });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(getJob).toHaveBeenCalled();
    });
    await screen.findByTestId("research-result");
    expect(getJob).toHaveBeenCalledWith("job-abc");
    expect(getResult).toHaveBeenCalledTimes(1);
    expect(getResult).toHaveBeenCalledWith("job-abc");
  });

  it("renders research-job-error with the error code and never calls getResult when the job fails", async () => {
    const getJob = vi.fn().mockResolvedValue({
      id: "job-abc",
      state: "failed",
      error: { code: "numeric_out_of_range", message: "equity out of range" },
    });
    const getResult = vi.fn().mockResolvedValue(null);
    const client = makeClient({ getJob, getResult });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(getJob).toHaveBeenCalled();
    });
    const error = await screen.findByTestId("research-job-error");
    expect(error.textContent).toMatch(/numeric_out_of_range/);
    expect(error.textContent).toMatch(/equity out of range/);
    expect(getResult).not.toHaveBeenCalled();
  });

  it("renders research-job-error with 'cancelled' and never calls getResult when the job is cancelled", async () => {
    const getJob = vi.fn().mockResolvedValue({
      id: "job-abc",
      state: "cancelled",
    });
    const getResult = vi.fn().mockResolvedValue(null);
    const client = makeClient({ getJob, getResult });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(getJob).toHaveBeenCalled();
    });
    const error = await screen.findByTestId("research-job-error");
    expect(error.textContent).toMatch(/cancelled/);
    expect(getResult).not.toHaveBeenCalled();
  });

  it("'Load result' button still calls getResult directly when no result has been auto-fetched", async () => {
    const getJob = vi.fn().mockResolvedValue({ id: "job-abc", state: "running" });
    const getResult = vi.fn().mockResolvedValue(sampleStored);
    const client = makeClient({ getJob, getResult });
    render(<ResearchView client={client} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    expect(getResult).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    await waitFor(() => {
      expect(getResult).toHaveBeenCalledTimes(1);
    });
    expect(getResult).toHaveBeenCalledWith("job-abc");
  });
});
