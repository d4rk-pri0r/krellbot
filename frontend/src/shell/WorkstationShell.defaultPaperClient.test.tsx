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
  getCsrf: (): string => "test-csrf",
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
    if (url === "/api/v1/paper/position") {
      return {
        ok: true,
        json: async () => ({
          venue: "kraken",
          pair: "SUIUSD",
          free_cash: "1000",
          holdings: [],
        }),
      } as Response;
    }
    if (url === "/api/v1/paper/fleet") {
      return {
        ok: true,
        json: async () => ({
          schema_version: "1",
          armed_count: backend.status.armed ? 1 : 0,
          deployments: backend.status.armed
            ? [
                {
                  venue: "kraken",
                  pair: "SUIUSD",
                  pack_id: "trend-follow",
                  entries_paused: false,
                  last_tick_ts_ms: null,
                  last_tick_result: null,
                  detail_href: "/?view=workstation&venue=kraken&pair=SUIUSD",
                },
              ]
            : [],
        }),
      } as Response;
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
    return { ok: true, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, requests };
}

function setBootstrapMeta(content: string): void {
  document.head.innerHTML = `<meta name="krellbot-bootstrap" content="${content}">`;
}

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
  vi.unstubAllGlobals();
  resolveBootstrapRef = null;
});

describe("WorkstationShell default paperClient — Strategies handoff to Run", () => {
  it("omits inline Arm/stop controls from Strategies and hands off validated revisions to Run", async () => {
    stubDefaultPaperBackend({
      status: armedStatus(),
      disarm: okResult("disarmed"),
      pause: okResult("entries_paused"),
      resume: okResult("entries_resumed"),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-default-paper-1", { strategyClient });

    expect(screen.queryByTestId("editor-inline-stop")).toBeNull();
    expect(screen.queryByRole("button", { name: /^arm$/i })).toBeNull();
    expect(screen.getByTestId("editor-open-in-run")).toBeDefined();
  });

  it("navigates to Run with the default loopback paper client and shows armed controls", async () => {
    stubDefaultPaperBackend({
      status: armedStatus(),
      disarm: okResult("disarmed"),
      pause: okResult("entries_paused"),
      resume: okResult("entries_resumed"),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-default-paper-2", { strategyClient });

    await saveValidateAndOpenInRun();

    const stopBtn = await screen.findByRole("button", { name: /^stop paper run$/i });
    expect((stopBtn as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
  }, 15000);

  it("confirming Stop paper run on Run sends paper.disarm through the default loopback client and reverts to unarmed", async () => {
    const { requests } = stubDefaultPaperBackend({
      status: armedStatus(),
      disarm: okResult("disarmed"),
      pause: okResult("entries_paused"),
      resume: okResult("entries_resumed"),
    });
    const strategyClient = makeStrategyClient();
    await openStrategiesView("test-token-default-paper-3", { strategyClient });

    await saveValidateAndOpenInRun();
    const stopBtn = await screen.findByRole("button", { name: /^stop paper run$/i });
    fireEvent.click(stopBtn);

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
        expect(screen.getByTestId("paper-status-empty").textContent).toMatch(
          /Start a paper run/,
        );
      },
      { timeout: 5000 },
    );
  }, 15000);
});
