/**
 * Library Reopen freezes the open editor for the revision read so mid-wait
 * edits cannot land and then vanish on remount (M6.5 / PARKING).
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
import type { ResearchClient } from "../features/research/client";
import type { StrategyClient } from "../features/strategies/client";
import type {
  LibraryClient,
  OwnedDraftSummary,
  OwnedRevisionBytes,
} from "../features/strategies/libraryClient";
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
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    }),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
  } as unknown as PaperClient;
}

function makeResearchClient(): ResearchClient {
  return {
    submitRun: vi.fn(),
    cancelJob: vi.fn(),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn(),
    getResultDownload: vi.fn().mockResolvedValue(null),
  } as unknown as ResearchClient;
}

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn(),
    edit: vi.fn(),
    validate: vi.fn(),
    arm: vi.fn(),
  } as unknown as StrategyClient;
}

const libraryRow: OwnedDraftSummary = {
  revision_id: "rev-library-1",
  strategy_id: "trend-follow",
  parent_revision_id: null,
  state: "validated",
  runnable: true,
  created_at: "2026-10-07T12:00:00Z",
  id: "trend-follow",
  label: "Trend follow",
  pair: "SUIUSD",
  timeframe: "1h",
};

const canonicalBytes = JSON.stringify({
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
});

function deferred() {
  let resolve!: (value: OwnedRevisionBytes) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<OwnedRevisionBytes>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function labelInput(): HTMLInputElement {
  return screen.getByLabelText(/^label$/i) as HTMLInputElement;
}

function rawJsonTextarea(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

describe("WorkstationShell — library reopen busy and draft survival", () => {
  it("marks the editor host busy and freezes the open draft until Reopen settles", async () => {
    const read = deferred();
    const library: LibraryClient = {
      listOwned: vi.fn().mockResolvedValue([libraryRow]),
      getJson: vi.fn().mockReturnValue(read.promise),
    };
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        libraryClient={library}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    fireEvent.change(labelInput(), { target: { value: "Keep while loading" } });
    expect(labelInput().value).toBe("Keep while loading");

    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /reopen/i })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));

    const host = screen.getByTestId("editor-host");
    expect(host.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByTestId("editor-reopen-busy").textContent).toContain(
      "Loading saved revision",
    );
    const portal = screen.getByTestId("editor-portal-root");
    expect(portal.hasAttribute("inert")).toBe(true);
    expect(portal.getAttribute("aria-hidden")).toBe("true");
    // Draft still present under the freeze until the remount applies.
    expect(labelInput().value).toBe("Keep while loading");

    await act(async () => {
      read.resolve({
        revision_id: "rev-library-1",
        state: "validated",
        bytes: canonicalBytes,
      });
    });
    await waitFor(() => expect(rawJsonTextarea().value).toBe(canonicalBytes));
    expect(screen.getByTestId("editor-host").hasAttribute("aria-busy")).toBe(
      false,
    );
    expect(screen.queryByTestId("editor-reopen-busy")).toBeNull();
    expect(screen.getByTestId("editor-portal-root").hasAttribute("inert")).toBe(
      false,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).toContain(
      "rev-library-1",
    );
  });

  it("clears busy and keeps the unsaved draft when Reopen fails", async () => {
    const read = deferred();
    const library: LibraryClient = {
      listOwned: vi.fn().mockResolvedValue([libraryRow]),
      getJson: vi.fn().mockReturnValue(read.promise),
    };
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        libraryClient={library}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    const draftBytes = '  {"label": "unsaved-draft",\n "entry": [';
    fireEvent.change(rawJsonTextarea(), { target: { value: draftBytes } });

    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /reopen/i })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));
    expect(screen.getByTestId("editor-host").getAttribute("aria-busy")).toBe(
      "true",
    );

    await act(async () => {
      read.reject(new Error("revision unavailable"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("library-reopen-error").textContent).toContain(
        "revision unavailable",
      ),
    );
    expect(screen.getByTestId("editor-host").hasAttribute("aria-busy")).toBe(
      false,
    );
    expect(screen.queryByTestId("editor-reopen-busy")).toBeNull();
    expect(rawJsonTextarea().value).toBe(draftBytes);
  });

  it("clears busy and keeps the unsaved draft when Library closes mid-Reopen", async () => {
    const read = deferred();
    const library: LibraryClient = {
      listOwned: vi.fn().mockResolvedValue([libraryRow]),
      getJson: vi.fn().mockReturnValue(read.promise),
    };
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={makeStrategyClient()}
        libraryClient={library}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    fireEvent.change(labelInput(), { target: { value: "Survive close" } });
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /reopen/i })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));
    expect(screen.getByTestId("editor-reopen-busy")).toBeDefined();

    // Closing the library unmounts it and retires the in-flight read.
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.queryByTestId("saved-strategy-library")).toBeNull();
    expect(screen.queryByTestId("editor-reopen-busy")).toBeNull();
    expect(screen.getByTestId("editor-host").hasAttribute("aria-busy")).toBe(
      false,
    );
    expect(labelInput().value).toBe("Survive close");

    // A late resolution must not remount over the surviving draft.
    await act(async () => {
      read.resolve({
        revision_id: "rev-library-1",
        state: "validated",
        bytes: canonicalBytes,
      });
    });
    expect(labelInput().value).toBe("Survive close");
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
  });
});
