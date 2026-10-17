import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type {
  PaperStatus,
  PaperClient,
  PaperCommandResult,
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
  // The default loopback paper client reads the CSRF token for its
  // request headers: supply it so the production code path is exercised
  // instead of failing on the header read.
  getCsrf: (): string => "test-csrf",
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

/**
 * The shell is mounted with NO paperClient prop, so the Editor inline
 * stop control runs on the default loopback client
 * (`createPaperHttpClient`): route its fetches through a global stub so
 * the test stands in for the loopback backend the production App talks
 * to. Body payloads are read so request shape stays observable.
 */
type DefaultPaperBackend = {
  status: PaperStatus;
  disarm: PaperCommandResult;
  pause: PaperCommandResult;
  resume: PaperCommandResult;
};

function stubDefaultPaperBackend(backend: DefaultPaperBackend): {
  fetchMock: ReturnType<typeof vi.fn>;
  requests: Array<{ url: string; body: unknown }>;
} {
  const requests: Array<{ url: string; body: unknown }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    let body: unknown = null;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    requests.push({ url, body });
    if (url === "/api/v1/paper/status") {
      return { ok: true, json: async () => backend.status } as Response;
    }
    const command =
      (body as { command?: string } | null)?.command ?? "unknown";
    if (command === "paper.disarm") {
      backend.status = { schema_version: "1", armed: false };
      return { ok: true, json: async () => backend.disarm } as Response;
    }
    if (command === "paper.pause_entries") {
      return { ok: true, json: async () => backend.pause } as Response;
    }
    if (command === "paper.resume_entries") {
      return { ok: true, json: async () => backend.resume } as Response;
    }
    // The default clients are only used for the paper surface here.
    return { ok: true, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, requests };
}

function setBootstrapMeta(content: string): void {
  document.head.innerHTML = `<meta name="krellbot-bootstrap" content="${content}">`;
}

/** Open the Strategies view; the Editor and its wire-up are there. */
async function openStrategiesView(
  token: string,
  props: { strategyClient: StrategyClient },
): Promise<void> {
  setBootstrapMeta(token);
  render(<WorkstationShell {...props} />);
  await act(async () => {
    resolveBootstrapRef?.();
  });
  fireEvent.click(await screen.findByRole("button", { name: "Strategies" }));
  await screen.findByRole("region", { name: "Strategy editor" });
}

/**
 * Save, then validate, then arm through the Editor's own buttons,
 * staying on the Strategies view the whole time.
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
  return screen.getByTestId("editor-inline-stop-disarm") as HTMLButtonElement;
}

function pauseButton(): HTMLButtonElement {
  return screen.getByTestId("editor-inline-stop-pause") as HTMLButtonElement;
}

function resumeButton(): HTMLButtonElement {
  return screen.getByTestId("editor-inline-stop-resume") as HTMLButtonElement;
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  resolveBootstrapRef = null;
});

describe("WorkstationShell default paperClient → Editor inline stop control", () => {
  it("mounts the inline stop control with the default loopback client when no paperClient prop is supplied", async () => {
    stubDefaultPaperBackend({
      status: armedStatus(),
      disarm: okResult("disarmed"),
      pause: okResult("entries_paused"),
      resume: okResult("entries_resumed"),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-default-paper-1", { strategyClient });

    // The control is present before any arming: the default client is
    // wired without a caller-side prop.
    expect(screen.getByTestId("editor-inline-stop")).not.toBeNull();
  });

  it("after the Editor's own Arm the inline Disarm/Pause/Resume become enabled without a manual refresh", async () => {
    stubDefaultPaperBackend({
      status: armedStatus(),
      disarm: okResult("disarmed"),
      pause: okResult("entries_paused"),
      resume: okResult("entries_resumed"),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-default-paper-2", { strategyClient });

    await armThroughEditor(strategyClient);

    // No "Refresh status" click, no navigation: the refreshSignal the
    // Editor bumps after its own Arm is the only trigger that ran.
    await waitFor(
      () => {
        expect(disarmButton().disabled).toBe(false);
      },
      { timeout: 5000 },
    );
    expect(pauseButton().disabled).toBe(false);
    expect(resumeButton().disabled).toBe(false);
    expect(screen.getByTestId("editor-inline-stop-entries").textContent).toMatch(
      /Entries active/,
    );
  }, 15000);

  it("clicking the inline Disarm confirms through the default client and reverts to No pack armed", async () => {
    const { requests } = stubDefaultPaperBackend({
      status: armedStatus(),
      disarm: okResult("disarmed"),
      pause: okResult("entries_paused"),
      resume: okResult("entries_resumed"),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-default-paper-3", { strategyClient });

    await armThroughEditor(strategyClient);
    await waitFor(
      () => {
        expect(disarmButton().disabled).toBe(false);
      },
      { timeout: 5000 },
    );
    fireEvent.click(disarmButton());

    await waitFor(
      () => {
        const found = requests.find(
          (request) =>
            request.url === "/api/v1/commands" &&
            (request.body as { command?: string } | null)?.command ===
              "paper.disarm",
        );
        expect(found).toBeDefined();
        expect(
          (found?.body as { payload?: { venue?: string; pair?: string } })
            .payload,
        ).toEqual({ venue: "kraken", pair: "SUIUSD" });
      },
      { timeout: 5000 },
    );
    await waitFor(
      () => {
        expect(disarmButton().disabled).toBe(true);
      },
      { timeout: 5000 },
    );
    expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
      /No pack armed/,
    );
  }, 15000);
});
