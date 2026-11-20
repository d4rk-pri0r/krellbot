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
  issueReconnectToken: (): Promise<never> => Promise.reject(new Error("not stubbed")),
  redeemReconnectToken: (): Promise<void> => Promise.resolve(),
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

async function saveValidateAndOpenInRun(): Promise<void> {
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
  fireEvent.click(screen.getByTestId("editor-open-in-run"));
  await screen.findByTestId("paper-status-panel");
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.restoreAllMocks();
  resolveBootstrapRef = null;
});

describe("WorkstationShell → Strategies handoff to Run paperClient", () => {
  it("never mounts duplicate inline paper stop controls on Strategies", async () => {
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-1", {
      strategyClient,
      paperClient: makePaperClient(),
    });

    expect(screen.queryByTestId("editor-inline-stop")).toBeNull();
    expect(screen.queryByRole("button", { name: /^arm$/i })).toBeNull();
    expect(
      (screen.getByTestId("editor-open-in-run") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("hands off a validated revision to Run where the injected paperClient renders armed controls", async () => {
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-2", {
      strategyClient,
      paperClient: makePaperClient(),
    });

    await saveValidateAndOpenInRun();

    const stopBtn = await screen.findByRole("button", { name: /^stop paper run$/i });
    expect((stopBtn as HTMLButtonElement).disabled).toBe(false);
    expect(
      (screen.getByRole("button", { name: /pause new buys/i }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(
      (screen.getByRole("button", { name: /resume new buys/i }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("clicking Stop paper run on Run calls paperClient.disarm once with the armed venue/pair", async () => {
    const paperClient = makePaperClient();
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-editor-paper-3", {
      strategyClient,
      paperClient,
    });

    await saveValidateAndOpenInRun();
    const stopBtn = await screen.findByRole("button", { name: /^stop paper run$/i });
    fireEvent.click(stopBtn);

    await waitFor(() => {
      expect(paperClient.disarm).toHaveBeenCalledTimes(1);
    });
    expect(paperClient.disarm).toHaveBeenCalledWith("kraken", "SUIUSD");
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-empty").textContent).toMatch(
        /Start a paper run/,
      );
    });
  });

  it("a refused Stop paper run keeps the armed state and surfaces an alert error", async () => {
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

    await saveValidateAndOpenInRun();
    const stopBtn = await screen.findByRole("button", { name: /^stop paper run$/i });
    fireEvent.click(stopBtn);

    const error = await screen.findByTestId("paper-status-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(/Stop paper run refused/);
    expect(
      (screen.getByRole("button", { name: /^stop paper run$/i }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});
