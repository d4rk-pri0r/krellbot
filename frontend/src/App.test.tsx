import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { PaperClient } from "./features/paper/client";
import type {
  ResearchClient,
  StoredResult,
} from "./features/research/client";
import type {
  Pack as StrategyPack,
  StrategyClient,
} from "./features/strategies/client";
import { WorkstationShell } from "./shell/WorkstationShell";

afterEach(cleanup);

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    }),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
    }),
    ...overrides,
  };
}

function makeResearchClient(
  overrides: Partial<ResearchClient> = {},
): ResearchClient {
  const blob = new Blob(['{"ok":true}'], { type: "application/json" });
  const download = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(blob),
  } as unknown as Response;
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-research-1", state: "queued" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({
      id: "job-research-1",
      state: "succeeded",
    }),
    getResultDownload: vi.fn().mockResolvedValue(download),
    ...overrides,
  };
}

function makeStrategyClient(
  overrides: Partial<StrategyClient> = {},
): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack: StrategyPack) => ({
      revision_id: "rev-research-1",
      state: "draft" as const,
      pack,
      errors: [],
      outcome: "created" as const,
    })),
    edit: vi.fn().mockImplementation(
      async (_parent: string, pack: StrategyPack) => ({
        revision_id: "rev-research-2",
        state: "draft" as const,
        pack,
        errors: [],
        outcome: "created" as const,
      }),
    ),
    validate: vi.fn().mockImplementation(
      async (revision_id: string) => ({
        revision_id,
        state: "validated" as const,
        pack: {},
        errors: [],
      }),
    ),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function makeSavedPack(): StrategyPack {
  return {
    id: "trend-follow",
    timeframe: "1h",
    indicators: { sma20: { fn: "sma" } },
    entry: ["close", ">", "sma20"],
    exit: ["close", "<", "sma20"],
  };
}

async function savePackViaStrategies(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
  fireEvent.change(screen.getByLabelText(/raw json/i), {
    target: { value: JSON.stringify(makeSavedPack()) },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await screen.findByTestId("editor-revision-id");
}

const sampleStoredResult: StoredResult = {
  legacy_receipt: {
    equity: 123.45,
    max_drawdown: -8.5,
    fee_bps: 40,
    trades: [
      { side: "buy", qty: 1 },
      { side: "sell", qty: 1 },
      { side: "buy", qty: 1 },
    ],
    data_manifest_sha256: "deadbeef",
  },
  trace: [
    {
      bar_ts: 1000,
      input: { ts_ms: 1000, open: 1, high: 1, low: 1, close: 1.5, volume: 0 },
      conditions: [{ path: ".all[0]", outcome: true }],
    },
    {
      bar_ts: 2000,
      input: { ts_ms: 2000, open: 1.6, high: 1.7, low: 1.55, close: 1.65, volume: 0 },
      conditions: [{ path: ".any[0]", outcome: false }],
    },
    {
      bar_ts: 3000,
      input: { ts_ms: 3000, open: 1.7, high: 1.75, low: 1.6, close: 1.72, volume: 0 },
      conditions: [{ path: ".any[0]", outcome: true }],
    },
  ],
};

function fillResearchInputs(): void {
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/synthetic.csv" },
  });
  fireEvent.change(screen.getByLabelText(/pack path/i), {
    target: { value: "fixtures/pack.json" },
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
  fireEvent.change(screen.getByLabelText(/holdout from/i), {
    target: { value: "1100" },
  });
  fireEvent.change(screen.getByLabelText(/holdout to/i), {
    target: { value: "1200" },
  });
}

async function runResearchToCompletion(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByTestId("research-job-id");
  await waitFor(() => {
    expect(screen.queryByTestId("research-result")).not.toBeNull();
  });
}

describe("App shell", () => {
  it("renders the paper workstation heading", () => {
    render(<App />);
    expect(screen.getByText("Paper workstation")).toBeDefined();
  });

  it("renders the live-orders unavailable status", () => {
    render(<App />);
    expect(screen.getByText("Live orders unavailable")).toBeDefined();
  });
});

describe("App status strip", () => {
  it("exposes the Paper mode badge inside the status strip", () => {
    render(<App />);
    const strip = screen.getByRole("region", { name: /status/i });
    expect(strip.textContent).toMatch(/Paper/);
  });

  it("exposes the live-orders sentence inside the status strip", () => {
    render(<App />);
    const strip = screen.getByRole("region", { name: /status/i });
    expect(strip.textContent).toMatch(/Live orders unavailable/);
  });
});

describe("App navigation", () => {
  it("renders in-app controls for Workstation, Strategies, and Research", () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: /workstation navigation/i });
    expect(nav.querySelector("a")).toBeNull();
    const buttons = nav.querySelectorAll("button");
    const labels = Array.from(buttons).map((b) => b.textContent?.trim());
    expect(labels).toEqual(
      expect.arrayContaining(["Workstation", "Strategies", "Research"]),
    );
  });
});

describe("App inspector", () => {
  it("renders an inspector region whose empty state reads 'Nothing selected'", () => {
    render(<App />);
    const inspector = screen.getByRole("region", { name: "Inspector" });
    expect(inspector.textContent).toMatch(/Nothing selected/);
  });
});

describe("App jobs drawer", () => {
  it("opens a drawer labelled 'Jobs' with the 'No jobs' empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ jobs: [] }),
      }),
    );
    render(<App />);
    expect(screen.queryByRole("dialog", { name: "Jobs" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
    const drawer = screen.getByRole("dialog", { name: "Jobs" });
    expect(await screen.findByText("No jobs")).toBeTruthy();
    expect(drawer.textContent).toMatch(/No jobs/);
    vi.unstubAllGlobals();
  });
});

describe("App command palette", () => {
  it("opens on Control+K, focuses its input, and does not submit a command", () => {
    render(<App />);
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    const input = dialog.querySelector("input");
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("opens on Meta+K and focuses its input", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    const input = dialog.querySelector("input");
    expect(document.activeElement).toBe(input);
  });

  it("closes on Escape and returns focus to the previously focused element", () => {
    render(<App />);
    const trigger = screen.getByRole("button", { name: /jobs/i });
    trigger.focus();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen
      .getByRole("dialog", { name: /command palette/i })
      .querySelector("input");
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input as HTMLInputElement, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("App view routing", () => {
  it("starts on Workstation and renders the inspector", () => {
    render(<App />);
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(
      screen.getByRole("region", { name: "Inspector" }),
    ).toBeDefined();
  });

  it("does not render the strategy editor before Strategies is selected", () => {
    render(<App />);
    expect(
      screen.queryByRole("region", { name: /strategy editor/i }),
    ).toBeNull();
  });

  it("choosing Strategies shows the strategy editor and hides the workstation heading", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    const editor = screen.getByRole("region", { name: /strategy editor/i });
    expect(editor).toBeDefined();
    expect(editor.textContent).toMatch(/Label/);
    expect(editor.textContent).toMatch(/Raw JSON/);
    expect(screen.queryByText("Paper workstation")).toBeNull();
    expect(screen.queryByRole("region", { name: "Inspector" })).toBeNull();
  });

  it("choosing Workstation after Strategies shows the paper workstation again", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(
      screen.getByRole("region", { name: /strategy editor/i }),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(
      screen.queryByRole("region", { name: /strategy editor/i }),
    ).toBeNull();
  });

  it("choosing Research shows the research run form", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.getByLabelText(/dataset path/i)).toBeDefined();
    expect(screen.getByLabelText(/fee basis points/i)).toBeDefined();
    expect(screen.getByLabelText(/^from$/i)).toBeDefined();
    expect(screen.getByLabelText(/^to$/i)).toBeDefined();
    expect(screen.getByRole("button", { name: /^run$/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /synthetic fixture/i })).toBeDefined();
  });

  it("choosing Research hides the workstation heading", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByText("Paper workstation")).toBeNull();
  });

  it("choosing Workstation after Research shows the paper workstation again", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.getByLabelText(/dataset path/i)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(screen.queryByLabelText(/dataset path/i)).toBeNull();
  });
});

describe("App paper controls (NS10b)", () => {
  it("renders the Paper controls region on the workstation view with a no-armed-pack fallback", async () => {
    const paperClient = makePaperClient();
    render(<WorkstationShell paperClient={paperClient} />);
    const panel = await screen.findByTestId("paper-status-panel");
    expect(panel.textContent).toMatch(/Paper status/);
    expect(panel.textContent).toMatch(/No pack armed/);
    // No controls while not armed.
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
  });

  it("shows Pause entries, Resume entries, and Disarm when status says armed", async () => {
    const paperClient = makePaperClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        entries_paused: false,
        mode: "paper",
        pack_id: "trend-follow",
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    expect(
      await screen.findByRole("button", { name: /pause entries/i }),
    ).toBeDefined();
    expect(
      await screen.findByRole("button", { name: /resume entries/i }),
    ).toBeDefined();
    expect(
      await screen.findByRole("button", { name: /^disarm$/i }),
    ).toBeDefined();
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
  });

  it("hides the controls on the Strategies and Research views", () => {
    const paperClient = makePaperClient();
    render(<WorkstationShell paperClient={paperClient} />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
  });

  it("does not expose any button whose name includes 'Live'", async () => {
    const paperClient = makePaperClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        entries_paused: false,
        mode: "paper",
        pack_id: "trend-follow",
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    const panel = await screen.findByTestId("paper-status-panel");
    const buttons = panel.querySelectorAll("button");
    for (const btn of Array.from(buttons)) {
      expect(btn.textContent ?? "").not.toMatch(/Live/);
    }
    // And the status strip's "Live orders unavailable" sentence stays
    // in its existing region — no live-order control ever replaces it.
    const strip = screen.getByRole("region", { name: "Status" });
    expect(strip.textContent).toMatch(/Live orders unavailable/);
  });

  it("shows 'Entries paused' after a successful pause click", async () => {
    const paperClient = makePaperClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: false,
          mode: "paper",
          pack_id: "trend-follow",
        })
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: true,
          mode: "paper",
          pack_id: "trend-follow",
        }),
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "entries_paused",
        ok: true,
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries paused/,
    );
    expect(paperClient.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
  });

  it("shows 'Entries active' after a successful resume click", async () => {
    const paperClient = makePaperClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: true,
          mode: "paper",
          pack_id: "trend-follow",
        })
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: false,
          mode: "paper",
          pack_id: "trend-follow",
        }),
      resumeEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "entries_resumed",
        ok: true,
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    const resume = await screen.findByRole("button", { name: /resume entries/i });
    fireEvent.click(resume);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
    expect(paperClient.resumeEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
  });
});

describe("App research navigation lifecycle (research mode)", () => {
  it("keeps research visible and preserves inputs after a page-cache restore", () => {
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/cached.csv" },
    });

    fireEvent(window, new PageTransitionEvent("pagehide", { persisted: true }));
    fireEvent(window, new PageTransitionEvent("pageshow", { persisted: true }));

    expect(
      (screen.getByLabelText(/dataset path/i) as HTMLInputElement).value,
    ).toBe("fixtures/cached.csv");
  });

  it("mounts research lazily and removes inactive research controls from the document", () => {
    const research = makeResearchClient();
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={research}
        strategyClient={makeStrategyClient()}
      />,
    );
    expect(research.submitRun).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/dataset path/i)).toBeNull();
    expect(screen.queryByLabelText(/fee basis points/i)).toBeNull();
    expect(screen.queryByLabelText(/holdout from/i)).toBeNull();
    expect(screen.queryByLabelText(/holdout to/i)).toBeNull();
    expect(screen.queryByLabelText(/pack path/i)).toBeNull();
    expect(screen.queryByLabelText(/^from$/i)).toBeNull();
    expect(screen.queryByLabelText(/^to$/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /^run$/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByLabelText(/dataset path/i)).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.queryByLabelText(/dataset path/i)).toBeNull();
    expect(screen.queryByLabelText(/fee basis points/i)).toBeNull();
    expect(screen.queryByLabelText(/holdout from/i)).toBeNull();
    expect(screen.queryByLabelText(/holdout to/i)).toBeNull();
    expect(screen.queryByLabelText(/pack path/i)).toBeNull();
    expect(screen.queryByLabelText(/^from$/i)).toBeNull();
    expect(screen.queryByLabelText(/^to$/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /^run$/i })).toBeNull();

    // Studio still works after leaving Research.
    expect(screen.queryByTestId("studio-connection-count")).not.toBeNull();

    // Strategies still works after leaving Research.
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(screen.getByLabelText(/raw json/i)).toBeDefined();
    expect(screen.getByLabelText(/label/i)).toBeDefined();
  });

  it("preserves research inputs result selection and refusal across navigation", async () => {
    const research = makeResearchClient();
    let completed = false;
    const jobId = "job-research-1";
    research.submitRun = vi.fn().mockImplementation(async () => {
      return { id: jobId, state: "queued" };
    });
    research.getJob = vi.fn().mockImplementation(async () => {
      if (!completed) {
        return { id: jobId, state: "running" };
      }
      return { id: jobId, state: "succeeded" };
    });
    research.getResult = vi.fn().mockImplementation(async () => {
      if (!completed) {
        return null;
      }
      return sampleStoredResult;
    });

    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={research}
        strategyClient={makeStrategyClient()}
      />,
    );
    await savePackViaStrategies();

    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByTestId("research-revision")).not.toBeNull();

    fillResearchInputs();
    // Complete the first research request by flipping the polling
    // backend to succeeded once the job id has been issued.
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    completed = true;
    await waitFor(() => {
      expect(screen.queryByTestId("research-result")).not.toBeNull();
    });
    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText(/holdout to/i), {
      target: { value: "1200" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    const refusal = await screen.findByRole("alert");
    expect(refusal.textContent).toMatch(/holdout bounds must both be set/);
    expect(research.submitRun).toHaveBeenCalledTimes(1);

    // Restore holdouts and select a trace bar before navigating away.
    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "1100" },
    });
    fireEvent.change(screen.getByLabelText(/holdout to/i), {
      target: { value: "1200" },
    });
    fireEvent.click(screen.getByTestId("research-result"));
    const traceButtons = await screen.findAllByRole("button", {
      name: /^[0-9]+$/,
    });
    // Select the second bar (ts=2000) to exercise non-default selection.
    fireEvent.click(traceButtons[1]);
    expect(traceButtons[1].getAttribute("aria-pressed")).toBe("true");

    // Navigate Research → Studio → Strategies → Research.
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    fireEvent.click(screen.getByRole("button", { name: "Research" }));

    expect(
      (screen.getByLabelText(/dataset path/i) as HTMLInputElement).value,
    ).toBe("fixtures/synthetic.csv");
    expect(
      (screen.getByLabelText(/pack path/i) as HTMLInputElement).value,
    ).toBe("fixtures/pack.json");
    expect(
      (screen.getByLabelText(/fee basis points/i) as HTMLInputElement).value,
    ).toBe("40");
    expect(
      (screen.getByLabelText(/^from$/i) as HTMLInputElement).value,
    ).toBe("0");
    expect(
      (screen.getByLabelText(/^to$/i) as HTMLInputElement).value,
    ).toBe("1000");
    expect(
      (screen.getByLabelText(/holdout from/i) as HTMLInputElement).value,
    ).toBe("1100");
    expect(
      (screen.getByLabelText(/holdout to/i) as HTMLInputElement).value,
    ).toBe("1200");
    expect(screen.getByTestId("research-job-id").textContent).toMatch(
      new RegExp(jobId),
    );
    expect(screen.queryByTestId("research-result")).not.toBeNull();
    const restoredTraceButtons = screen.getAllByRole("button", {
      name: /^[0-9]+$/,
    });
    const restoredBar = restoredTraceButtons.find(
      (b) => b.getAttribute("aria-pressed") === "true",
    );
    expect(restoredBar).toBeDefined();
    expect(restoredBar?.textContent).toBe("2000");
    expect(research.submitRun).toHaveBeenCalledTimes(1);
  });

  it("preserves a pending research request and its eventual result on return", async () => {
    const research = makeResearchClient();
    let pending = true;
    const jobId = "job-pending";
    research.submitRun = vi.fn().mockImplementation(async () => {
      return { id: jobId, state: "queued" };
    });
    research.getJob = vi.fn().mockImplementation(async () => {
      if (pending) {
        return { id: jobId, state: "running" };
      }
      return { id: jobId, state: "succeeded" };
    });
    research.getResult = vi.fn().mockImplementation(async () => {
      if (pending) {
        return null;
      }
      return sampleStoredResult;
    });

    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={research}
        strategyClient={makeStrategyClient()}
      />,
    );
    await savePackViaStrategies();

    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    fillResearchInputs();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-job-id");
    expect(research.submitRun).toHaveBeenCalledTimes(1);
    // While the request is still pending, no result is rendered.
    expect(screen.queryByTestId("research-result")).toBeNull();

    // Leave Research while the request is still pending.
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.queryByTestId("research-job-id")).toBeNull();
    expect(screen.queryByTestId("research-result")).toBeNull();

    // The eventual result arrives while Research is detached.
    pending = false;
    await new Promise((resolve) => setTimeout(resolve, 0));

    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    await waitFor(() => {
      expect(screen.queryByTestId("research-result")).not.toBeNull();
    });
    expect(screen.getByTestId("research-job-id").textContent).toMatch(
      new RegExp(jobId),
    );
    expect(research.submitRun).toHaveBeenCalledTimes(1);
  });

  it("clears research job state when the saved revision changes", async () => {
    const research = makeResearchClient();
    research.submitRun = vi.fn().mockResolvedValue({
      id: "job-rev1",
      state: "queued",
    });
    research.getJob = vi.fn().mockResolvedValue({
      id: "job-rev1",
      state: "succeeded",
    });
    research.getResult = vi.fn().mockResolvedValue(sampleStoredResult);

    const strategy = makeStrategyClient();
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={research}
        strategyClient={strategy}
      />,
    );
    await savePackViaStrategies();

    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    fillResearchInputs();
    await runResearchToCompletion();
    expect(
      screen.getByTestId("research-job-id").textContent,
    ).toMatch(/job-rev1/);
    expect(screen.queryByTestId("research-result")).not.toBeNull();
    const traceButtons = screen.getAllByRole("button", {
      name: /^[0-9]+$/,
    });
    fireEvent.click(traceButtons[0]);
    fireEvent.change(screen.getByLabelText(/holdout from/i), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText(/holdout to/i), {
      target: { value: "1200" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    const refusal = await screen.findByRole("alert");
    expect(refusal.textContent).toMatch(/holdout bounds must both be set/);

    // Save a different revision through Strategies.
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: {
        value: JSON.stringify({ ...makeSavedPack(), id: "trend-follow-v2" }),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await screen.findByTestId("editor-save-outcome");

    // Return to Research: old state must be gone, new revision visible.
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByTestId("research-job-id")).toBeNull();
    expect(screen.queryByTestId("research-result")).toBeNull();
    expect(
      screen.getByTestId("research-revision").textContent,
    ).toMatch(/rev-research-2/);

    // The fields are reset, but Run still accepts valid input with no
    // nonempty packPath: only the revision is sent.
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByLabelText(/^from$/i), {
      target: { value: "0" },
    });
    fireEvent.change(screen.getByLabelText(/^to$/i), {
      target: { value: "9999999999999" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(research.submitRun).toHaveBeenCalledTimes(2);
    });
    const callArg = (research.submitRun as ReturnType<typeof vi.fn>).mock
      .calls[1][0] as Record<string, unknown>;
    expect(callArg.revisionId).toBe("rev-research-2");
    expect(callArg.packPath === undefined || callArg.packPath === "").toBe(
      true,
    );
  });
});
