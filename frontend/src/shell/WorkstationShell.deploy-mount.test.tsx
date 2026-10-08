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
import type { PaperClient } from "../features/paper/client";
import type { ResearchClient } from "../features/research/client";
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

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn(async () => ({
      schema_version: "1",
      armed: false,
    })),
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
      blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
    } as unknown as Response),
  };
}

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-2",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function setBootstrapMeta(content: string): void {
  document.head.innerHTML = `<meta name="krellbot-bootstrap" content="${content}">`;
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resolveBootstrapRef = null;
});

describe("WorkstationShell — deployments live preflight mount", () => {
  it("renders the live preflight panel after clicking the Deploy nav tab", async () => {
    setBootstrapMeta("test-token-deploy-1");
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    await act(async () => {
      resolveBootstrapRef?.();
    });
    const deployButton = await screen.findByRole("button", { name: "Deploy" });
    fireEvent.click(deployButton);
    await waitFor(() => {
      expect(
        screen.getByTestId("live-preflight-panel"),
      ).toBeDefined();
    });
  });

  it("keeps the live preflight panel out of the workstation view until Deploy is opened", async () => {
    setBootstrapMeta("test-token-deploy-2");
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    await act(async () => {
      resolveBootstrapRef?.();
    });
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-panel")).toBeDefined();
    });
    expect(screen.queryByTestId("live-preflight-panel")).toBeNull();
  });
});
