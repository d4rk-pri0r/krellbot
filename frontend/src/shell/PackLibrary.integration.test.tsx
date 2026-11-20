/**
 * Installed pack library — shell integration.
 *
 * PackLibrary lives exclusively on the Packs destination (no duplicate
 * Packs toggle on Strategies). These tests pin the real-consumer wiring:
 *
 *  - Strategies has no strategies-packs-toggle and never mounts PackLibrary;
 *  - PackLibrary mounts on the Packs tab and reads through the exact client
 *    the shell was given (or createPacksHttpClient by default);
 *  - PackLibrary never mounts on Run, Research, Strategy studio, or Operations;
 *  - a refused list (403) surfaces truthfully inside the shell.
 */

import {
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
import { clickShellNav } from "./navTestUtils";

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
  issueReconnectToken: (): Promise<never> => Promise.reject(new Error("not stubbed")),
  redeemReconnectToken: (): Promise<void> => Promise.resolve(),
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
    redeemActivation: vi.fn(async () => ({
      schema_version: "1",
      status: "dead" as const,
      message: "license not accepted",
      catalog_downloaded: false,
    })),
  };
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.restoreAllMocks();
});

describe("WorkstationShell — installed pack library mount", () => {
  it("mounts the pack library on Packs (and omits the duplicate Packs toggle from Strategies)", async () => {
    const packs = makePackClient();
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        packClient={packs}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(screen.queryByTestId("strategies-packs-toggle")).toBeNull();
    expect(screen.queryByTestId("pack-library-panel")).toBeNull();
    expect(packs.listInstalled).not.toHaveBeenCalled();

    clickShellNav("Packs");
    const panel = await screen.findByTestId("pack-library-panel");
    expect(panel).toBeDefined();
    await waitFor(() => {
      expect(packs.listInstalled).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("pack-library-row-alpha")).toBeDefined();
    expect(screen.getByTestId("pack-library-row-bravo")).toBeDefined();
  });

  it("mounts the pack library on no tab other than Packs", () => {
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        packClient={makePackClient()}
      />,
    );

    for (const label of ["Run", "Strategies", "Research", "Strategy studio", "Operations"]) {
      clickShellNav(label);
      expect(screen.queryByTestId("strategies-packs-toggle")).toBeNull();
      expect(screen.queryByTestId("pack-library-panel")).toBeNull();
    }
  });

  it("falls back to createPacksHttpClient on Packs when no packClient prop is given", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/v1/packs") {
        return {
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
        } as Response;
      }
      if (url === "/api/v1/packs/catalogue") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ schema_version: "1", catalogue_version: "1", updated: null, packs: [] }),
        } as Response;
      }
      if (url === "/api/v1/packs/community") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ schema_version: "1", packs: [] }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
      />,
    );

    clickShellNav("Packs");
    await screen.findByTestId("pack-library-row-alpha");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/packs",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("surfaces a session refusal (403) truthfully inside Packs", async () => {
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

    clickShellNav("Packs");
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/403/);
    expect(screen.queryByTestId("pack-library-empty")).toBeNull();
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
  });
});
