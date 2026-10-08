import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaperClient } from "../features/paper/client";
import type { ResearchClient } from "../features/research/client";
import type { StrategyClient } from "../features/strategies/client";
import type { Pack } from "../features/strategies/client";
import { WorkstationShell } from "./WorkstationShell";

const savedPack: Pack = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "krellbot tests",
  origin: "Test fixture.",
  timeframe: "1h",
  indicators: { sma20: { fn: "sma", src: "close", len: 20 } },
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
};

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-created",
      state: "draft",
      pack: savedPack,
      errors: [],
      outcome: "created",
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-edited",
      state: "draft",
      pack: savedPack,
      errors: [],
      outcome: "created",
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-created",
      state: "validated",
      pack: savedPack,
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn(async () => ({ schema_version: "1", armed: false })),
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
  };
}

function makeResearchClient(): ResearchClient {
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-1", state: "queued" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-1", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(new Blob(["{}"])),
    } as unknown as Response),
  };
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
});

describe("WorkstationShell strategies explanation", () => {
  it("renders the explanation next to the Editor on the strategies view", async () => {
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /strategies/i }));
    await waitFor(() => {
      expect(screen.getByRole("region", { name: /strategy editor/i })).toBeDefined();
    });
    expect(
      screen.getByRole("region", { name: /strategy explanation/i }),
    ).toBeDefined();
  });

  it("does not render the explanation outside the strategies view", async () => {
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-panel")).toBeDefined();
    });
    expect(screen.queryByTestId("strategy-explanation")).toBeNull();
  });

  it("updates the explanation when a revision is saved from the Editor", async () => {
    const client = makeStrategyClient();
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={client}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /strategies/i }));
    const textarea = await screen.findByLabelText(/raw json/i);
    fireEvent.change(textarea, { target: { value: JSON.stringify(savedPack, null, 2) } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(
        screen.getByTestId("strategy-explanation-revision").textContent,
      ).toContain("rev-created");
    });
    expect(screen.getByTestId("strategy-explanation-markets").textContent).toContain(
      "kraken: SUIUSD",
    );
    expect(screen.getByTestId("strategy-explanation-entry").textContent).toContain(
      'the close price is greater than the indicator "sma20"',
    );
    expect(screen.getByTestId("strategy-explanation-allocation").textContent).toContain(
      "at most 25% of the account",
    );
  });

  it("keeps a malformed saved revision visibly unknown without crashing the shell", async () => {
    const client = makeStrategyClient();
    (client.create as ReturnType<typeof vi.fn>).mockResolvedValue({
      revision_id: "rev-malformed",
      state: "draft",
      pack: {},
      errors: [],
      outcome: "created",
    });
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={client}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /strategies/i }));
    const textarea = await screen.findByLabelText(/raw json/i);
    fireEvent.change(textarea, { target: { value: "this is not json {" } });
    // The Editor refuses to save invalid JSON; the shell must still render.
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(screen.getByTestId("strategy-explanation")).toBeDefined();
    expect(screen.getByTestId("strategy-explanation-unparsed")).toBeDefined();
  });
});
