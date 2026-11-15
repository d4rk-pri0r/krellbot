/**
 * Client routing + reload survival wiring in WorkstationShell (M7.2).
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Pins: URL reflects the active view; a simulated reload (remount from
 * the current location) restores that view; browser back restores the
 * previous view. Draft/selection are not URL-encoded — see route.ts.
 */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PaperClient } from "../features/paper/client";
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
  recoverCsrf: (): Promise<boolean> => Promise.resolve(true),
  getCsrf: (): string => "test-csrf",
}));

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn(async () => ({ schema_version: "1", armed: false })),
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

function renderShell(): void {
  render(<WorkstationShell paperClient={makePaperClient()} />);
}

function activeNavLabel(): string | null {
  const current = screen
    .getByTestId("kbot-nav")
    .querySelector('[aria-current="page"]');
  return current?.textContent?.trim() ?? null;
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
});

describe("WorkstationShell — URL reflects view", () => {
  it("writes ?view= when a nav tab is activated", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(window.location.search).toBe("?view=strategies");
    expect(activeNavLabel()).toBe("Strategies");
  });

  it("writes ?view=home when returning to Workspace", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    fireEvent.click(screen.getByRole("button", { name: "Workspace" }));
    expect(window.location.search).toBe("?view=home");
    expect(activeNavLabel()).toBe("Workspace");
  });

  it("does not stack a duplicate history entry when re-clicking the active view", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    const length = window.history.length;
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(window.history.length).toBe(length);
    expect(window.location.search).toBe("?view=research");
  });
});

describe("WorkstationShell — reload restores route", () => {
  it("opens the view encoded in the URL on a fresh mount", () => {
    window.history.pushState({}, "", "/?view=operations");
    renderShell();
    expect(activeNavLabel()).toBe("Operations");
    // Operations content waits on session bootstrap; the pending
    // placeholder confirms the operations branch is mounted.
    expect(screen.getByTestId("status-panel-pending")).toBeTruthy();
  });

  it("restores Strategies after a remount that simulates reload", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(window.location.search).toBe("?view=strategies");
    cleanup();
    renderShell();
    expect(activeNavLabel()).toBe("Strategies");
    expect(screen.getByTestId("library-toggle")).toBeTruthy();
  });

  it("documents draft/selection policy: reload clears in-memory studio selection", () => {
    // Policy under test: the URL restores the view only. Transient
    // selection is not encoded, so a remount starts with no selection.
    window.history.pushState({}, "", "/?view=studio");
    const { unmount } = render(
      <WorkstationShell paperClient={makePaperClient()} />,
    );
    expect(activeNavLabel()).toBe("Strategy studio");
    expect(screen.getByTestId("studio-selected-node").textContent).toContain(
      "(none)",
    );
    unmount();
    render(<WorkstationShell paperClient={makePaperClient()} />);
    expect(activeNavLabel()).toBe("Strategy studio");
    expect(screen.getByTestId("studio-selected-node").textContent).toContain(
      "(none)",
    );
  });
});

describe("WorkstationShell — back navigation", () => {
  it("pushes distinct history entries so back can return to the prior view", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(window.location.search).toBe("?view=workstation");
    fireEvent.click(screen.getByRole("button", { name: "Deploy" }));
    expect(window.location.search).toBe("?view=deployments");
    expect(activeNavLabel()).toBe("Deploy");

    // Simulate browser back: restore the prior URL and fire popstate.
    act(() => {
      window.history.pushState({}, "", "/?view=workstation");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(activeNavLabel()).toBe("Workstation");
    expect(screen.getByRole("heading", { name: /paper workstation/i })).toBeTruthy();
  });

  it("syncs the active tab when popstate carries a different view", () => {
    window.history.pushState({}, "", "/?view=studio");
    renderShell();
    expect(activeNavLabel()).toBe("Strategy studio");

    act(() => {
      window.history.pushState({}, "", "/?view=research");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(activeNavLabel()).toBe("Research");

    act(() => {
      window.history.pushState({}, "", "/?view=studio");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(activeNavLabel()).toBe("Strategy studio");
  });
});
