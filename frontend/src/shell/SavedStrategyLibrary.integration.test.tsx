import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PaperClient } from "../features/paper/client";
import type { ResearchClient } from "../features/research/client";
import type { StrategyClient } from "../features/strategies/client";
import type {
  LibraryClient,
  OwnedDraftSummary,
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

function makeLibraryClient(): LibraryClient {
  return {
    listOwned: vi.fn().mockResolvedValue([libraryRow]),
    getJson: vi.fn().mockResolvedValue({
      revision_id: "rev-library-1",
      state: "validated",
      bytes: canonicalBytes,
    }),
  };
}

function renderShell(library: LibraryClient = makeLibraryClient()): void {
  render(
    <WorkstationShell
      paperClient={makePaperClient()}
      researchClient={makeResearchClient()}
      strategyClient={makeStrategyClient()}
      libraryClient={library}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function openStrategiesView(): void {
  fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
}

function labelInput(): HTMLInputElement {
  return screen.getByLabelText(/^label$/i) as HTMLInputElement;
}

function rawJsonTextarea(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

async function flushEffects(): Promise<void> {
  await act(async () => {});
}

describe("WorkstationShell — saved strategy library", () => {
  it("keeps the library hidden until the Library toggle is pressed", async () => {
    renderShell();
    openStrategiesView();
    await flushEffects();
    expect(labelInput()).toBeDefined();
    expect(screen.queryByTestId("saved-strategy-library")).toBeNull();
  });

  it("renders the library list alongside the editor after the toggle", async () => {
    renderShell();
    openStrategiesView();
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByTestId("saved-strategy-library")).toBeDefined(),
    );
    // The editor stays mounted next to the library.
    expect(labelInput()).toBeDefined();
    await waitFor(() =>
      expect(screen.getAllByRole("listitem").length).toBe(1),
    );
    const row = screen.getByRole("listitem");
    expect(row.textContent).toContain("trend-follow");
    expect(row.textContent).toContain("Trend follow");
    expect(row.textContent).toContain("SUIUSD");
    expect(row.textContent).toContain("Validated");
  });

  it("hides the library again when the toggle is pressed twice", async () => {
    renderShell();
    openStrategiesView();
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByTestId("saved-strategy-library")).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.queryByTestId("saved-strategy-library")).toBeNull();
    expect(labelInput()).toBeDefined();
  });

  it("Reopen loads canonical bytes into the editor through the savedRevision contract", async () => {
    renderShell();
    openStrategiesView();
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /reopen/i })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));
    await waitFor(() => expect(rawJsonTextarea().value).toBe(canonicalBytes));
    // Editor renders the reopened revision identity read-only label.
    expect(screen.getByTestId("editor-revision-id").textContent).toContain(
      "rev-library-1",
    );
    expect(screen.getByTestId("editor-revision-id").textContent).toContain(
      "Validated",
    );
  });

  it("Reopen never arms or validates the reopened revision", async () => {
    const library = makeLibraryClient();
    const strategy = {
      create: vi.fn(),
      edit: vi.fn(),
      validate: vi.fn(),
      arm: vi.fn(),
    };
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={strategy as unknown as StrategyClient}
        libraryClient={library}
      />,
    );
    openStrategiesView();
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /reopen/i })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));
    await waitFor(() => expect(rawJsonTextarea().value).toBe(canonicalBytes));
    expect(strategy.validate).not.toHaveBeenCalled();
    expect(strategy.arm).not.toHaveBeenCalled();
    expect(library.getJson).toHaveBeenCalledTimes(1);
  });

  it("New owned strategy clears the editor back to an empty draft", async () => {
    renderShell();
    openStrategiesView();
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /reopen/i })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));
    await waitFor(() => expect(rawJsonTextarea().value).toBe(canonicalBytes));
    fireEvent.click(
      screen.getByTestId("library-new-owned-strategy"),
    );
    await waitFor(() => expect(rawJsonTextarea().value).toBe(""));
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
  });

  it("does not fetch the library list while the toggle is off", async () => {
    const library = makeLibraryClient();
    renderShell(library);
    openStrategiesView();
    await flushEffects();
    expect(labelInput()).toBeDefined();
    expect(library.listOwned).not.toHaveBeenCalled();
  });
});
