/**
 * Signal design foundation — mounted shell evidence.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * These tests pin the owner-approved Signal shell composition as it is
 * actually mounted: the supplied outlined wordmark in the compact
 * horizontal header, truthful paper/live-unavailable context, all six
 * views reachable, the Jobs drawer and command palette reachable, and
 * no fabricated metrics (balances, returns, positions, latency,
 * health, license status) invented by the chrome.
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

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
});

describe("WorkstationShell — Signal shell composition (KRELL-SIGNAL-20261010)", () => {
  it("mounts the supplied outlined wordmark inside the compact header", () => {
    renderShell();
    const wordmark = screen.getByTestId("kbot-wordmark");
    expect(wordmark.getAttribute("aria-label")).toBe("krellbot");
    // The supplied vector keeps its seafoam mark + light type colors.
    expect(wordmark.innerHTML).toContain("#A8D8D1");
    expect(wordmark.innerHTML).toContain("#E9F0F5");
    // The header exists and contains the brand affordance.
    const brand = screen.getByTestId("kbot-shell-brand");
    expect(brand.contains(wordmark)).toBe(true);
  });

  it("keeps the truthful paper/live-unavailable context visible", () => {
    renderShell();
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "Live orders unavailable",
    );
    expect(screen.getByLabelText("Mode Paper").textContent).toBe("Paper");
  });

  it("keeps every existing view reachable through the mounted navigation", () => {
    renderShell();
    const nav = screen.getByTestId("kbot-nav");
    expect(nav).toBeDefined();
    for (const label of [
      "Home",
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ]) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute(
          "aria-current",
        ),
      ).toBe(label === "Home" ? "page" : null);
    }
  });

  it("opens Home on a normal root launch instead of dense paper controls", () => {
    renderShell();
    expect(screen.getByTestId("app-home")).toBeDefined();
    // The workstation operational panels stay unmounted behind Home.
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Paper workstation" }),
    ).toBeNull();
    expect(screen.queryByTestId("react-flow-stub")).toBeNull();
  });

  it("returns to Home from any view through the brand button", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.queryByTestId("app-home")).toBeNull();
    fireEvent.click(screen.getByTestId("kbot-shell-brand"));
    expect(screen.getByTestId("app-home")).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Home" }).getAttribute("aria-current"),
    ).toBe("page");
  });

  it("drives the whole user journey from the Home cards", async () => {
    renderShell();
    fireEvent.click(screen.getByTestId("app-home-card-strategies"));
    expect(screen.getByTestId("library-toggle")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    fireEvent.click(screen.getByTestId("app-home-card-research"));
    expect(screen.getByTestId("research-host")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    fireEvent.click(screen.getByTestId("app-home-card-studio"));
    expect(screen.getByTestId("studio-node-count").textContent).toBe("3");

    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    fireEvent.click(screen.getByTestId("app-home-card-workstation"));
    expect(screen.getByText("Paper workstation")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    fireEvent.click(screen.getByTestId("app-home-card-operations"));
    // Operations mounts after bootstrap resolves; wait for its view.
    await waitFor(() =>
      expect(screen.getByTestId("operations-view")).toBeDefined(),
    );

    fireEvent.click(screen.getByTestId("kbot-shell-brand"));
    expect(screen.getByTestId("app-home")).toBeDefined();
  });

  it("keeps the Home overview mounted while the local session is starting", async () => {
    renderShell();
    // Home renders before the (mocked, instantly-resolving) bootstrap
    // settles and remains mounted afterwards.
    await waitFor(() =>
      expect(
        screen.getByTestId("kbot-shell").getAttribute("data-bootstrap-done"),
      ).toBe("1"),
    );
    expect(screen.getByTestId("app-home")).toBeDefined();
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    expect(screen.getByTestId("app-home-availability").textContent).toMatch(
      /Live trading unavailable/i,
    );
  });

  it("still opens Studio for the synthetic workload deep link and labels it honestly", () => {
    window.history.pushState({}, "", "/?workload=200");
    renderShell();
    expect(screen.queryByTestId("app-home")).toBeNull();
    expect(screen.getByTestId("studio-node-count").textContent).toBe("200");
    expect(
      screen
        .getByRole("button", { name: "Studio" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByTestId("studio-synthetic-label").textContent,
    ).toMatch(/synthetic/i);
    window.history.pushState({}, "", "/");
  });

  it("keeps the deploy preflight out of the Home view until Deploy is opened", () => {
    renderShell();
    expect(screen.queryByTestId("live-preflight-panel")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Deploy" }));
    expect(screen.getByText("Live preflight")).toBeDefined();
  });

  it("switches views end-to-end without losing the shell", async () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(screen.getByTestId("library-toggle")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.getByTestId("research-host")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.getByTestId("studio-node-count")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    // Operations mounts after bootstrap resolves; wait for its view.
    await waitFor(() =>
      expect(screen.getByTestId("operations-view")).toBeDefined(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Deploy" }));
    expect(screen.getByText("Live preflight")).toBeDefined();

    // Back to workstation, the paper heading returns.
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
  });

  it("keeps the Jobs drawer reachable from the header", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ jobs: [] }), { status: 200 }),
      ),
    );
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Jobs" }));
    expect(await screen.findByText("No jobs")).toBeDefined();
  });

  it("opens the command palette from the header affordance and via ⌘K", () => {
    renderShell();
    expect(screen.queryByTestId("command-palette")).toBeNull();
    fireEvent.click(screen.getByTestId("kbot-shell-palette-hint"));
    expect(screen.getByTestId("command-palette")).toBeDefined();
    // Esc closes it.
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).toBeNull();
    // The ⌘K keyboard path still works.
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByTestId("command-palette")).toBeDefined();
  });

  it("does not invent metrics or account state in the shell chrome", () => {
    const { container } = render(
      <WorkstationShell paperClient={makePaperClient()} />,
    );
    const html = container.innerHTML;
    for (const fabricated of [
      "$",
      "equity",
      "Equity",
      "latency",
      "Latency",
      "returns",
      "Returns",
      "drawdown",
      "Drawdown",
      "licensed",
      "Licensed",
      "balance",
      "Balance",
      "position open",
      "health",
    ]) {
      expect(html.includes(fabricated)).toBe(false);
    }
  });

  it("keeps the honest inspector empty state, not a marketing hero", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    const inspector = screen.getByRole("region", { name: "Inspector" });
    expect(inspector.textContent).toMatch(/Nothing selected/);
  });
});
