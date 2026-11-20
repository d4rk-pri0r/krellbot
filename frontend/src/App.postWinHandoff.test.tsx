/**
 * Post-win handoff: Open Krellbot mounts the M24 shell and stays quiet.
 * The wizard win screen is the celebration — no second toast, coach, or
 * checklist. Skip before the win screen does not consume that toast.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import {
  isFirstWinCelebrateShown,
} from "./features/onboarding/firstWinCelebratePersistence";
import { writeFirstRunWizardState } from "./features/onboarding/FirstRunWizard";
import {
  CONSUMER_STARTER_CARDS,
  CONSUMER_STARTER_CARD_ORDER,
} from "./features/strategies/consumerStarterCopy";
import type { StarterCatalogue, StarterExample } from "./features/strategies/StarterPicker.client";
import { clickShellNav } from "./shell/navTestUtils";

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

vi.mock("./session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./session")>();
  return {
    ...actual,
    redeemBootstrap: (): Promise<void> => Promise.resolve(),
    recoverCsrf: (): Promise<boolean> => Promise.resolve(true),
    getCsrf: (): string => "test-csrf",
  };
});

beforeEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  vi.unstubAllGlobals();
});

function catalogue(): StarterCatalogue {
  const examples: StarterExample[] = CONSUMER_STARTER_CARD_ORDER.map((id) => {
    const card = CONSUMER_STARTER_CARDS[id]!;
    return {
      id,
      label: card.title,
      description: card.description,
      pack: {
        schema_version: 1,
        id,
        label: card.title,
        markets: [{ venue: "kraken", pair: "SUIUSD" }],
      },
    };
  });
  return { schema_version: "1", catalogue_version: "1", examples };
}

function stubWorkstationFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      let body: unknown = null;
      if (typeof init?.body === "string") {
        body = JSON.parse(init.body) as unknown;
      }
      if (url.endsWith("/api/v1/packs/starters")) {
        return Response.json(catalogue());
      }
      if (url.endsWith("/api/v1/strategies/drafts") && init?.method === "POST") {
        return Response.json({
          revision_id: "rev-wizard-1",
          state: "draft",
          pack: (body as { pack?: unknown }).pack ?? {},
          errors: [],
        });
      }
      if (url.includes("/validate")) {
        return Response.json({
          revision_id: "rev-wizard-1",
          state: "validated",
          pack: {},
          errors: [],
        });
      }
      if (url.endsWith("/api/v1/commands")) {
        return Response.json({ ok: true, code: "armed", message: "armed" });
      }
      if (url.includes("/api/v1/paper/status")) {
        return Response.json({
          schema_version: "1",
          armed: true,
          mode: "paper",
          entries_paused: false,
          venue: "kraken",
          pair: "SUIUSD",
          pack_id: "starter-dual-ma-crossover",
        });
      }
      if (url.includes("/api/v1/paper/position")) {
        return Response.json({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          mode: "paper",
          free_cash: "1000",
          holdings: [],
        });
      }
      if (
        url.endsWith("/api/v1/session/csrf") ||
        url.endsWith("/api/v1/session/bootstrap")
      ) {
        return Response.json({
          schema_version: "1",
          csrf_token: "test-csrf",
        });
      }
      return Response.json({});
    }),
  );
}

async function openKrellbotFromWelcome(): Promise<void> {
  fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
  fireEvent.click(
    screen.getByTestId("first-run-wizard-use-starter-dual-ma-crossover"),
  );
  await waitFor(() => {
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("start_paper");
  });
  fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
  await waitFor(() => {
    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "It’s running on this computer (paper only — not live trading).",
    );
  });
  fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
  expect(
    screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
  ).toBe("win");
  expect(screen.queryByTestId("kbot-shell")).toBeNull();
  expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
  fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
}

function expectQuietShell(): void {
  expect(screen.queryByTestId("first-run-wizard")).toBeNull();
  expect(screen.getByTestId("kbot-shell")).toBeDefined();
  expect(screen.getByTestId("kbot-nav")).toBeDefined();
  expect(screen.getByTestId("app-home")).toBeDefined();
  expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
  expect(screen.queryByTestId("first-run-coach")).toBeNull();
  expect(screen.queryByTestId("first-run-coach-spotlight")).toBeNull();
  expect(screen.queryByTestId("activation-checklist")).toBeNull();
  expect(screen.queryByTestId("soft-studio-tip")).toBeNull();
  expect(screen.queryByTestId("app-home-path")).toBeNull();
  expect(screen.queryByTestId("app-home-keys-rail")).toBeNull();
  expect(screen.getByRole("button", { name: "Settings" })).toBeDefined();
  expect(screen.getByTestId("app-home-cta-paper").textContent).toMatch(
    /Start with a free paper strategy/i,
  );
  expect(isFirstWinCelebrateShown()).toBe(true);
}

describe("wizard win mounts WorkstationShell and stays silent", () => {
  it("walks cold open through paper status into a quiet shell with Advanced", async () => {
    stubWorkstationFetch();
    const { unmount } = render(<App />);
    expect(screen.getByTestId("first-run-wizard")).toBeDefined();
    expect(screen.queryByTestId("kbot-shell")).toBeNull();
    expect(isFirstWinCelebrateShown()).toBe(false);

    await openKrellbotFromWelcome();
    expectQuietShell();
    expect(screen.getByTestId("kbot-nav-more-toggle")).toBeDefined();

    await waitFor(() => {
      expect(
        screen.getByTestId("kbot-shell").getAttribute("data-bootstrap-done"),
      ).toBe("1");
    });
    clickShellNav("Run");
    expect(await screen.findByText("Entries active")).toBeTruthy();
    expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();

    clickShellNav("Strategy studio");
    expect(
      screen.getByTestId("kbot-nav-more-toggle").getAttribute("aria-expanded"),
    ).toBe("true");

    unmount();
    render(<App />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
    expect(isFirstWinCelebrateShown()).toBe(true);
  });
});

describe("wizard skip before the win leaves the shell celebrate unused", () => {
  it("mounts the shell cleanly and does not mark the toast shown", () => {
    render(<App />);
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    fireEvent.click(screen.getByTestId("first-run-wizard-skip"));
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(screen.getByRole("button", { name: "Settings" })).toBeDefined();
    expect(screen.queryByTestId("app-home-path")).toBeNull();
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
    expect(isFirstWinCelebrateShown()).toBe(false);
  });
});

describe("skip from the win screen stays silent when Run is already armed", () => {
  it("consumes the celebrate toast before the shell reads paper status", async () => {
    stubWorkstationFetch();
    writeFirstRunWizardState({
      status: "active",
      stepId: "win",
      selectedStarterId: "starter-dual-ma-crossover",
      revisionId: "rev-wizard-1",
    });
    render(<App />);
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("win");
    fireEvent.click(screen.getByTestId("first-run-wizard-skip"));
    expectQuietShell();

    await waitFor(() => {
      expect(
        screen.getByTestId("kbot-shell").getAttribute("data-bootstrap-done"),
      ).toBe("1");
    });
    clickShellNav("Run");
    expect(await screen.findByText("Entries active")).toBeTruthy();
    expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
  });
});
