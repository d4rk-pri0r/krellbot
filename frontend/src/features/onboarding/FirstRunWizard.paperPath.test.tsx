/**
 * Wizard steps 2–4 save a free starter, arm paper only, and quote real
 * status. No credentials and no live arm.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { PaperClient, PaperStatus } from "../paper/client";
import type { StrategyClient } from "../strategies/client";
import {
  CONSUMER_STARTER_CARDS,
  CONSUMER_STARTER_CARD_ORDER,
} from "../strategies/consumerStarterCopy";
import type { StarterCatalogue, StarterExample } from "../strategies/StarterPicker.client";
import {
  FirstRunWizard,
  readFirstRunWizardState,
  writeFirstRunWizardState,
  WIZARD_LIVE_TRADING_UNAVAILABLE,
} from "./FirstRunWizard";
import { FIRST_RUN_WIZARD_STORAGE_KEY } from "./firstRunWizardPersistence";

const STORAGE = FIRST_RUN_WIZARD_STORAGE_KEY;

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

beforeEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const JARGON_PAIR = ["XX", "BT", "ZUSD"].join("");
const JARGON_JSON = ["seeds the raw ", "JSON"].join("");

function jargonCatalogue(): StarterCatalogue {
  const examples: StarterExample[] = CONSUMER_STARTER_CARD_ORDER.map((id) => {
    const card = CONSUMER_STARTER_CARDS[id]!;
    return {
      id,
      label: `${card.title} crossover (educational example)`,
      description: `Teaching pack. ${JARGON_JSON} for ${JARGON_PAIR}.`,
      pack: {
        schema_version: 1,
        id,
        label: `${card.title} (educational example)`,
        note: JARGON_JSON,
        pair: JARGON_PAIR,
        timeframe: "1h",
      },
    };
  });
  return {
    schema_version: "1",
    catalogue_version: "1",
    examples,
  };
}

function fakeStrategy(over: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack) => ({
      revision_id: "rev-starter-1",
      state: "draft",
      pack,
      errors: [],
    })),
    edit: vi.fn(),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-starter-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn(),
    ...over,
  };
}

function paperStatus(overrides: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    mode: "paper",
    entries_paused: false,
    venue: "kraken",
    pair: JARGON_PAIR,
    pack_id: "starter-dual-ma-crossover",
    ...overrides,
  };
}

function fakePaper(over: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(paperStatus()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    arm: vi.fn().mockResolvedValue({
      ok: true,
      code: "armed",
      message: "armed",
    }),
    ...over,
  } as PaperClient;
}

function surfaceText(): string {
  return screen.getByTestId("first-run-wizard").textContent ?? "";
}

function expectNoJargonOrPnl(text: string): void {
  expect(text.includes(JARGON_JSON)).toBe(false);
  expect(text.includes(JARGON_PAIR)).toBe(false);
  expect(text.toLowerCase().includes("educational example")).toBe(false);
  expect(text.includes("P&L")).toBe(false);
  expect(text.includes("$")).toBe(false);
}

describe("FirstRunWizard choose saves a free starter through the strategy client", () => {
  it("shows three plain Use tiles and saves the catalogue pack before start paper", async () => {
    const strategyClient = fakeStrategy();
    const paperClient = fakePaper();
    writeFirstRunWizardState(
      { status: "active", stepId: "choose", selectedStarterId: null },
      STORAGE,
    );
    render(
      <FirstRunWizard
        strategyClient={strategyClient}
        paperClient={paperClient}
        loadStarters={async () => jargonCatalogue()}
      />,
    );

    for (const id of CONSUMER_STARTER_CARD_ORDER) {
      const card = CONSUMER_STARTER_CARDS[id]!;
      expect(screen.getByText(card.title)).toBeTruthy();
      expect(screen.getByTestId(`first-run-wizard-use-${id}`).textContent).toBe(
        "Use",
      );
    }
    expectNoJargonOrPnl(surfaceText());
    expect(screen.queryByLabelText(/api key|secret|credential/i)).toBeNull();

    fireEvent.click(
      screen.getByTestId("first-run-wizard-use-starter-mean-reversion-band"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
      ).toBe("start_paper");
    });
    const catalogue = jargonCatalogue();
    const pack = catalogue.examples.find(
      (row) => row.id === "starter-mean-reversion-band",
    )!.pack;
    expect(strategyClient.create).toHaveBeenCalledWith(pack);
    expect(strategyClient.validate).toHaveBeenCalledWith("rev-starter-1");
    expect(strategyClient.arm).not.toHaveBeenCalled();
    expect(paperClient.arm).not.toHaveBeenCalled();
    expect(readFirstRunWizardState(STORAGE)).toEqual({
      status: "active",
      stepId: "start_paper",
      selectedStarterId: "starter-mean-reversion-band",
      revisionId: "rev-starter-1",
    });
    expectNoJargonOrPnl(surfaceText());
  });

  it("stays on choose when validation does not leave a runnable draft", async () => {
    const strategyClient = fakeStrategy({
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-starter-1",
        state: "draft",
        pack: {},
        errors: [{ message: "pair required" }],
      }),
    });
    const paperClient = fakePaper();
    writeFirstRunWizardState(
      { status: "active", stepId: "choose", selectedStarterId: null },
      STORAGE,
    );
    render(
      <FirstRunWizard
        strategyClient={strategyClient}
        paperClient={paperClient}
        loadStarters={async () => jargonCatalogue()}
      />,
    );
    fireEvent.click(
      screen.getByTestId("first-run-wizard-use-starter-range-breakout"),
    );
    expect(
      (await screen.findByTestId("first-run-wizard-choose-error")).textContent,
    ).toMatch(/pair required/i);
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("choose");
    expect(paperClient.arm).not.toHaveBeenCalled();
    expect(readFirstRunWizardState(STORAGE).stepId).toBe("choose");
  });
});

describe("FirstRunWizard Start paper run arms paper only", () => {
  function onStartPaper(): void {
    writeFirstRunWizardState(
      {
        status: "active",
        stepId: "start_paper",
        selectedStarterId: "starter-dual-ma-crossover",
        revisionId: "rev-starter-1",
      },
      STORAGE,
    );
  }

  it("arms with paper mode and no credentials, then shows honest running status", async () => {
    onStartPaper();
    const strategyClient = fakeStrategy();
    const paperClient = fakePaper();
    render(
      <FirstRunWizard
        strategyClient={strategyClient}
        paperClient={paperClient}
        loadStarters={async () => jargonCatalogue()}
      />,
    );
    expect(screen.getByTestId("first-run-wizard-primary").textContent).toBe(
      "Start paper run",
    );
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));

    await waitFor(() => {
      expect(paperClient.arm).toHaveBeenCalledTimes(1);
    });
    expect(paperClient.arm).toHaveBeenCalledWith({
      revision_id: "rev-starter-1",
      venue: "kraken",
      mode: "paper",
      paper_balance: "1000",
    });
    const payload = vi.mocked(paperClient.arm!).mock.calls[0]![0] as unknown as Record<
      string,
      unknown
    >;
    expect(payload).not.toHaveProperty("api_key");
    expect(payload).not.toHaveProperty("secret");
    expect(payload).not.toHaveProperty("credential");
    expect(strategyClient.arm).not.toHaveBeenCalled();
    expect(strategyClient.create).not.toHaveBeenCalled();

    expect(
      await screen.findByTestId("first-run-wizard-sentence"),
    ).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "It’s running on this computer (paper only — not live trading).",
      );
    });
    const chip = screen.getByTestId("first-run-wizard-status-chip");
    expect(chip.textContent).toBe(WIZARD_LIVE_TRADING_UNAVAILABLE);
    expect(chip.getAttribute("data-paper-status")).toBe("running");
    expectNoJargonOrPnl(surfaceText());
    expect(screen.queryByLabelText(/api key|secret|credential/i)).toBeNull();
    expect(screen.queryByText(/live arm/i)).toBeNull();
  });

  it("stays on start paper and does not claim a run when the arm outcome is unknown", async () => {
    onStartPaper();
    const paperClient = fakePaper({
      arm: vi.fn().mockRejectedValue(new Error("paper.arm failed: 503")),
    });
    render(
      <FirstRunWizard
        paperClient={paperClient}
        loadStarters={async () => jargonCatalogue()}
      />,
    );
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    const alert = await screen.findByTestId("first-run-wizard-arm-error");
    expect(alert.textContent).toMatch(/Start paper run outcome unknown/i);
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("start_paper");
    expect(surfaceText()).not.toMatch(/It’s running/);
    expect(paperClient.arm).toHaveBeenCalledTimes(1);
  });

  it("stays on start paper when the arm result is not ok", async () => {
    onStartPaper();
    const paperClient = fakePaper({
      arm: vi.fn().mockResolvedValue({
        ok: false,
        code: "draft_not_runnable",
        message: "draft not runnable",
      }),
    });
    render(<FirstRunWizard paperClient={paperClient} />);
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(
      (await screen.findByTestId("first-run-wizard-arm-error")).textContent,
    ).toMatch(/draft not runnable/i);
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("start_paper");
  });
});

describe("FirstRunWizard status quotes the paper client before Looks good", () => {
  function onStatus(): void {
    writeFirstRunWizardState(
      {
        status: "active",
        stepId: "status",
        selectedStarterId: "starter-dual-ma-crossover",
        revisionId: "rev-starter-1",
      },
      STORAGE,
    );
  }

  it("says waiting when the paper run is paused and keeps live trading unavailable", async () => {
    onStatus();
    render(
      <FirstRunWizard
        paperClient={fakePaper({
          getStatus: vi.fn().mockResolvedValue(
            paperStatus({ entries_paused: true }),
          ),
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "Waiting on this computer (paper only — not live trading).",
      );
    });
    expect(
      screen.getByTestId("first-run-wizard-status-chip").getAttribute(
        "data-paper-status",
      ),
    ).toBe("waiting");
    expect(screen.getByTestId("first-run-wizard-status-chip").textContent).toBe(
      WIZARD_LIVE_TRADING_UNAVAILABLE,
    );
    expectNoJargonOrPnl(surfaceText());
  });

  it("does not claim a run when status is unarmed or not paper", async () => {
    onStatus();
    const { rerender } = render(
      <FirstRunWizard
        paperClient={fakePaper({
          getStatus: vi.fn().mockResolvedValue(
            paperStatus({ armed: false, mode: "paper" }),
          ),
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "Not running on this computer yet.",
      );
    });
    expect(surfaceText()).not.toMatch(/It’s running/);

    rerender(
      <FirstRunWizard
        paperClient={fakePaper({
          getStatus: vi.fn().mockResolvedValue(
            paperStatus({ armed: true, mode: "live" }),
          ),
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "Live trading unavailable.",
      );
    });
    expect(
      screen.getByTestId("first-run-wizard-status-chip").getAttribute(
        "data-paper-status",
      ),
    ).toBe("live-blocked");
    expect(surfaceText()).not.toMatch(/It’s running/);
  });

  it("shows paper status unavailable when the read fails and still lets Looks good continue", async () => {
    onStatus();
    const onComplete = vi.fn();
    render(
      <FirstRunWizard
        paperClient={fakePaper({
          getStatus: vi.fn().mockRejectedValue(new Error("paper status failed: 503")),
        })}
        onComplete={onComplete}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "Paper status unavailable.",
      );
    });
    expect(surfaceText()).not.toMatch(/It’s running|P&L/);
    expect(screen.getByTestId("first-run-wizard-primary").textContent).toBe(
      "Looks good",
    );
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("win");
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(readFirstRunWizardState(STORAGE).status).toBe("completed");
  });

  it("holds Looks good until the status read settles", async () => {
    onStatus();
    let resolveStatus: (status: PaperStatus) => void = () => {};
    const pending = new Promise<PaperStatus>((resolve) => {
      resolveStatus = resolve;
    });
    render(
      <FirstRunWizard
        paperClient={fakePaper({
          getStatus: vi.fn().mockReturnValue(pending),
        })}
      />,
    );
    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "Checking this computer…",
    );
    const button = screen.getByTestId("first-run-wizard-primary");
    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.click(button);
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("status");
    resolveStatus(paperStatus());
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "It’s running on this computer (paper only — not live trading).",
      );
    });
    expect(
      screen.getByTestId("first-run-wizard-primary").hasAttribute("disabled"),
    ).toBe(false);
  });
});

describe("App wizard paper path opens the shell after Looks good", () => {
  it("saves, arms paper only, quotes status, then mounts WorkstationShell", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    const catalogue = jargonCatalogue();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        let body: unknown = null;
        if (typeof init?.body === "string") {
          body = JSON.parse(init.body) as unknown;
        }
        calls.push({ url, body });
        if (url.endsWith("/api/v1/packs/starters")) {
          return Response.json(catalogue);
        }
        if (
          url.endsWith("/api/v1/strategies/drafts") &&
          init?.method === "POST"
        ) {
          return Response.json({
            revision_id: "rev-wizard-1",
            state: "draft",
            pack: (body as { pack?: unknown }).pack ?? {},
            errors: [],
          });
        }
        if (url.includes("/validate")) {
          return Response.json({
            revision_id: "rev-wizard-1",
            state: "validated",
            pack: {},
            errors: [],
          });
        }
        if (url.endsWith("/api/v1/commands")) {
          return Response.json({ ok: true, code: "armed", message: "armed" });
        }
        if (url.includes("/api/v1/paper/status")) {
          return Response.json({
            schema_version: "1",
            armed: true,
            mode: "paper",
            entries_paused: false,
            venue: "kraken",
            pair: JARGON_PAIR,
          });
        }
        if (
          url.endsWith("/api/v1/session/csrf") ||
          url.endsWith("/api/v1/session/bootstrap")
        ) {
          return Response.json({
            schema_version: "1",
            csrf_token: "test-csrf",
          });
        }
        return Response.json({ detail: "unused" }, { status: 404 });
      }),
    );

    render(<App />);
    expect(screen.queryByTestId("kbot-shell")).toBeNull();
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    fireEvent.click(
      screen.getByTestId("first-run-wizard-use-starter-dual-ma-crossover"),
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
      ).toBe("start_paper");
    });
    expectNoJargonOrPnl(surfaceText());

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    await waitFor(() => {
      expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
        "It’s running on this computer (paper only — not live trading).",
      );
    });
    expect(screen.getByTestId("first-run-wizard-status-chip").textContent).toBe(
      WIZARD_LIVE_TRADING_UNAVAILABLE,
    );
    expectNoJargonOrPnl(surfaceText());

    const armCalls = calls.filter((call) => {
      const body = call.body as { command?: string } | null;
      return body?.command === "paper.arm";
    });
    expect(armCalls).toHaveLength(1);
    expect(armCalls[0]?.body).toEqual({
      schema_version: "1",
      command: "paper.arm",
      payload: {
        revision_id: "rev-wizard-1",
        venue: "kraken",
        mode: "paper",
        paper_balance: "1000",
      },
    });
    expect(
      calls.some((call) => {
        const body = call.body as { command?: string } | null;
        return body?.command === "live.arm";
      }),
    ).toBe(false);

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("win");
    expect(screen.queryByTestId("kbot-shell")).toBeNull();
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(readFirstRunWizardState(STORAGE).status).toBe("completed");
  });
});
