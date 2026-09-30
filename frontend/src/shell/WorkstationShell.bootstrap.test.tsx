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
import type { JSX } from "react";
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

let getStatusCalls = 0;
let resolveBootstrapRef: (() => void) | null = null;

vi.mock("../session", () => ({
  redeemBootstrap: (): Promise<void> =>
    new Promise<void>((resolve) => {
      resolveBootstrapRef = () => resolve();
    }),
  recoverCsrf: (): Promise<boolean> => Promise.resolve(false),
}));

function makePaperClient(): PaperClient {
  const client: PaperClient = {
    getStatus: vi.fn(async () => {
      getStatusCalls += 1;
      return { schema_version: "1", armed: false };
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
  };
  return client;
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
  getStatusCalls = 0;
});

describe("WorkstationShell — M2-CE bootstrap guard", () => {
  it("does not call paperClient.getStatus before redeemBootstrap resolves", () => {
    setBootstrapMeta("test-token-1");
    const paper = makePaperClient();
    render(
      <WorkstationShell
        paperClient={paper}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    // The shell must render the placeholder, not the live StatusPanel,
    // while the bootstrap call is pending.
    expect(screen.getByTestId("status-panel-pending")).toBeDefined();
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
    expect(paper.getStatus).not.toHaveBeenCalled();
  });

  it("calls paperClient.getStatus once after redeemBootstrap resolves", async () => {
    setBootstrapMeta("test-token-2");
    const paper = makePaperClient();
    render(
      <WorkstationShell
        paperClient={paper}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    expect(paper.getStatus).not.toHaveBeenCalled();
    expect(resolveBootstrapRef).not.toBeNull();
    await act(async () => {
      resolveBootstrapRef?.();
    });
    await waitFor(() => {
      expect(paper.getStatus).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("paper-status-panel")).toBeDefined();
    expect(screen.queryByTestId("status-panel-pending")).toBeNull();
  });

  it("with no bootstrap meta tag present, still renders StatusPanel once mount completes", async () => {
    document.head.innerHTML = "";
    const paper = makePaperClient();
    render(
      <WorkstationShell
        paperClient={paper}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );
    await waitFor(() => {
      expect(paper.getStatus).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("paper-status-panel")).toBeDefined();
  });
});
