/**
 * Installed pack library — shell integration.
 *
 * The WorkstationShell Strategies tab mounts <PackLibrary client={packs}/>.
 * These tests pin the real-consumer wiring:
 *
 *  - the panel appears on the Strategies tab behind the Packs toggle and
 *    reads through the exact client the shell was given (or the one it
 *    builds via createPacksHttpClient);
 *  - the pack library never fetches while it is closed, and never mounts
 *    on any other tab;
 *  - the strategies Editor mount is unchanged by the toggle;
 *  - a refused list (403) surfaces truthfully inside the shell.
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PaperClient } from "../features/paper/client";
import type { PackLibraryClient } from "../features/packs/client";
import { PackLibraryHttpError } from "../features/packs/client";
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

vi.mock("../session", () => ({
  redeemBootstrap: (): Promise<void> => Promise.resolve(),
  recoverCsrf: (): Promise<boolean> => Promise.resolve(false),
  getCsrf: (): string => "",
}));

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({ schema_version: "1", armed: false }),
    pauseEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_paused", ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_resumed", ok: true }),
    disarm: vi.fn().mockResolvedValue({ schema_version: "1", code: "disarmed", ok: true }),
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

function makePackClient(): PackLibraryClient & {
  listInstalled: ReturnType<typeof vi.fn>;
} {
  return {
    listInstalled: vi.fn(async () => [
      {
        bucket: "deployed" as const,
        pack_id: "alpha",
        version: "2.0.0",
        permissions: ["trade"],
        rollback_ref: { pack_id: "alpha", prior_revision_id: "0".repeat(64) },
      },
      {
        bucket: "installed" as const,
        pack_id: "bravo",
        version: "1.0.0",
        permissions: [],
        rollback_ref: null,
      },
    ]),
    rollback: vi.fn(async () => ({ ok: true })),
  };
}

function goToStrategies(): void {
  fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.restoreAllMocks();
});

describe("WorkstationShell — installed pack library mount", () => {
  it("renders the pack library panel on Strategies after the Packs toggle", async () => {
    const packs = makePackClient();
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        packClient={packs}
      />,
    );

    goToStrategies();
    expect(screen.getByTestId("strategies-packs-toggle")).toBeDefined();
    // Closed by default: no panel, no fetch.
    expect(screen.queryByTestId("pack-library-panel")).toBeNull();
    expect(packs.listInstalled).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("strategies-packs-toggle"));
    const panel = await screen.findByTestId("pack-library-panel");
    expect(panel).toBeDefined();
    await waitFor(() => {
      expect(packs.listInstalled).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("pack-library-row-alpha")).toBeDefined();
    expect(screen.getByTestId("pack-library-row-bravo")).toBeDefined();

    // The toggle closes the panel without touching other mounts.
    fireEvent.click(screen.getByTestId("strategies-packs-toggle"));
    expect(screen.queryByTestId("pack-library-panel")).toBeNull();
    expect(packs.listInstalled).toHaveBeenCalledTimes(1);
  });

  it("keeps the strategies Editor mounted and unchanged while the pack library toggles", async () => {
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        packClient={makePackClient()}
      />,
    );

    goToStrategies();
    const editor = screen.getByRole("region", { name: "Strategy editor" });
    expect(editor).toBeDefined();
    fireEvent.click(screen.getByTestId("strategies-packs-toggle"));
    await screen.findByTestId("pack-library-panel");
    expect(screen.getByRole("region", { name: "Strategy editor" })).toBe(editor);

    // Navigating away unmounts both, as before.
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.queryByRole("region", { name: "Strategy editor" })).toBeNull();
    expect(screen.queryByTestId("pack-library-panel")).toBeNull();
  });

  it("mounts the pack library on no tab other than Strategies", async () => {
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        packClient={makePackClient()}
      />,
    );

    for (const label of ["Workstation", "Research", "Studio", "Operations"]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.queryByTestId("strategies-packs-toggle")).toBeNull();
      expect(screen.queryByTestId("pack-library-panel")).toBeNull();
    }
  });

  it("falls back to createPacksHttpClient when no packClient prop is given", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        {
          bucket: "installed",
          pack_id: "alpha",
          version: "1.0.0",
          permissions: [],
          rollback_ref: null,
        },
      ],
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );

    goToStrategies();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("strategies-packs-toggle"));
    await screen.findByTestId("pack-library-row-alpha");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/packs",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("surfaces a session refusal (403) truthfully inside the shell", async () => {
    const packs = makePackClient();
    packs.listInstalled = vi.fn(async () => {
      throw new PackLibraryHttpError(403, "pack library failed: 403");
    });
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        packClient={packs}
      />,
    );

    goToStrategies();
    await act(async () => {
      fireEvent.click(screen.getByTestId("strategies-packs-toggle"));
    });
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/403/);
    expect(screen.queryByTestId("pack-library-empty")).toBeNull();
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
  });
});
