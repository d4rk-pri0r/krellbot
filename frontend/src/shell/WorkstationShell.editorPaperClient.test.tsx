import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../features/paper/client";
import { summarizePaperCommandRefusal } from "../features/paper/paperCommandRefusalSummary";
import type { StrategyClient } from "../features/strategies/client";
import { WorkstationShell } from "./WorkstationShell";

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

let resolveBootstrapRef: (() => void) | null = null;

vi.mock("../session", () => ({
  redeemBootstrap: (): Promise<void> =>
    new Promise<void>((resolve) => {
      resolveBootstrapRef = () => resolve();
    }),
  recoverCsrf: (): Promise<boolean> => Promise.resolve(false),
}));

const validPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: validPack,
      errors: [],
      outcome: "created",
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-edit",
      state: "draft",
      pack: validPack,
      errors: [],
      outcome: "created",
    }),
    validate: vi.fn().mockImplementation(async (revision_id: string) => ({
      revision_id,
      state: "validated",
      pack: validPack,
      errors: [],
    })),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
}

function okResult(code: string): PaperCommandResult {
  return {
    schema_version: "1",
    code,
    ok: true,
    message: `${code}: kraken SUIUSD`,
    effect: "changed",
  };
}

function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi
      .fn()
      .mockResolvedValue(okResult("entries_paused")),
    resumeEntries: vi
      .fn()
      .mockResolvedValue(okResult("entries_resumed")),
    disarm: vi.fn().mockResolvedValue(okResult("disarmed")),
    ...overrides,
  };
}

function setBootstrapMeta(content: string): void {
  document.head.innerHTML = `<meta name="krellbot-bootstrap" content="${content}">`;
}

/** Open the Strategies view; the Editor and its wire-up are there. */
async function openStrategiesView(
  token: string,
  clients: { paperClient?: PaperClient; strategyClient: StrategyClient },
): Promise<void> {
  setBootstrapMeta(token);
  render(<WorkstationShell {...clients} />);
  await act(async () => {
    resolveBootstrapRef?.();
  });
  fireEvent.click(await screen.findByRole("button", { name: "Strategies" }));
  await screen.findByRole("region", { name: "Strategy editor" });
}

/**
 * Arm a validated revision through the Editor's own Save → Validate →
 * Arm buttons, staying on the Strategies view the whole time.
 */
async function armThroughEditor(
  strategyClient: StrategyClient,
): Promise<void> {
  fireEvent.change(screen.getByLabelText(/raw json/i), {
    target: { value: JSON.stringify(validPack, null, 2) },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => {
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-create \(state: Draft\)/,
    );
  });
  fireEvent.click(screen.getByRole("button", { name: /validate/i }));
  await waitFor(() => {
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-create \(state: Validated\)/,
    );
  });
  fireEvent.click(screen.getByRole("button", { name: /^arm$/i }));
  const arm = strategyClient.arm as unknown as ReturnType<typeof vi.fn>;
  await waitFor(() => {
    expect(arm).toHaveBeenCalledWith("rev-create", "kraken", "1000");
  });
}

function disarmButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^disarm$/i,
  }) as HTMLButtonElement;
}

function pauseButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /pause entries/i,
  }) as HTMLButtonElement;
}

function resumeButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /resume entries/i,
  }) as HTMLButtonElement;
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.restoreAllMocks();
  resolveBootstrapRef = null;
});

describe("WorkstationShell → Editor inline stop control wire-up", () => {
  it("without a paperClient prop the inline stop control stays out of the Editor (backward-compat)", async () => {
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-1", { strategyClient });

    // Arm a validated revision; the Editor is otherwise fully usable.
    await armThroughEditor(strategyClient);
    expect(screen.queryByTestId("editor-inline-stop")).toBeNull();
  });

  it("with a paperClient prop the inline stop control renders inside the Strategies Editor after arming", async () => {
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-2", {
      strategyClient,
      paperClient: makePaperClient(),
    });

    await armThroughEditor(strategyClient);

    const control = await screen.findByTestId("editor-inline-stop");
    const summary = screen.getByTestId("editor-revision-id");
    expect(summary.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(pauseButton().disabled).toBe(false);
    expect(resumeButton().disabled).toBe(false);
  });

  it("clicking the inline Disarm calls paperClient.disarm once with the armed venue/pair", async () => {
    const paperClient = makePaperClient();
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-3", {
      strategyClient,
      paperClient,
    });

    await armThroughEditor(strategyClient);
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    fireEvent.click(disarmButton());

    await waitFor(() => {
      expect(paperClient.disarm).toHaveBeenCalledTimes(1);
    });
    expect(paperClient.disarm).toHaveBeenCalledWith("kraken", "SUIUSD");
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(true);
    });
    expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
      /No pack armed/,
    );
  });

  it("a refused inline Disarm keeps the armed state and surfaces the summarizePaperCommandRefusal label", async () => {
    const refusal: PaperCommandResult = {
      schema_version: "1",
      code: "not_armed",
      ok: false,
    };
    const paperClient = makePaperClient({
      disarm: vi.fn().mockResolvedValue(refusal),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-4", {
      strategyClient,
      paperClient,
    });

    await armThroughEditor(strategyClient);
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    fireEvent.click(disarmButton());

    const error = await screen.findByTestId("editor-inline-stop-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe(
      summarizePaperCommandRefusal("Disarm", refusal).label,
    );
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
  });
});
