/**
 * Application Home — Signal workspace composition (KRELL-SIGNAL-20261010).
 *
 * These tests pin the mounted application Home as a real, welcoming
 * workspace overview: readable purpose, conspicuous local-preview /
 * live-unavailable copy, five state-driven navigation cards bound to
 * the existing views, keyboard activation, and a Kraken + Coinbase keys
 * rail that uses an injectable fake client (no fabricated market state).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../api/version";
import type { KeysClient, KeysStatus } from "../features/keys/client";
import { AppHome } from "./AppHome";
import type { View } from "./Navigation";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

const ABSENT_KEYS: KeysStatus = {
  schema_version: "1",
  venue: "kraken",
  present: false,
  corrupt: false,
  message: "no key stored",
  backend_label: null,
  balances: null,
  balances_available: false,
};

function fakeKeysClient(over: Partial<KeysClient> = {}): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue(ABSENT_KEYS),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
    ...over,
  };
}

function fakeVersionClient(over: Partial<VersionClient> = {}): VersionClient {
  return {
    getVersion: vi.fn().mockResolvedValue({
      schema_version: "1",
      version: "0.9.7",
      channel: "prerelease",
      artifacts_signed: false,
    }),
    ...over,
  };
}

const CARD_DESTINATIONS: ReadonlyArray<{
  testid: string;
  name: RegExp;
  view: View;
}> = [
  {
    testid: "app-home-card-workstation",
    name: /paper workstation/i,
    view: "workstation",
  },
  {
    testid: "app-home-card-strategies",
    name: /create or open a strategy/i,
    view: "strategies",
  },
  {
    testid: "app-home-card-studio",
    name: /open studio/i,
    view: "studio",
  },
  {
    testid: "app-home-card-research",
    name: /explore research/i,
    view: "research",
  },
  {
    testid: "app-home-card-operations",
    name: /^operations/i,
    view: "operations",
  },
];

function renderHome(
  props: {
    onNavigate?: (view: View) => void;
    keysClient?: KeysClient;
    versionClient?: VersionClient;
    sessionPending?: boolean;
    sessionFailed?: boolean;
  } = {},
): KeysClient {
  const keysClient = props.keysClient ?? fakeKeysClient();
  render(
    <AppHome
      onNavigate={props.onNavigate ?? (() => {})}
      keysClient={keysClient}
      versionClient={props.versionClient ?? fakeVersionClient()}
      sessionPending={props.sessionPending}
      sessionFailed={props.sessionFailed}
    />,
  );
  return keysClient;
}

describe("AppHome — application overview", () => {
  it("renders a welcoming heading and a readable application purpose", async () => {
    renderHome();
    const region = screen.getByTestId("app-home");
    expect(region.tagName).toBe("SECTION");
    const heading = screen.getByRole("heading", {
      level: 1,
      name: /your workspace/i,
    });
    expect(region.contains(heading)).toBe(true);
    expect(
      screen.getByText(/A clear view of your strategies, paper bots/i),
    ).toBeDefined();
    expect(
      screen.getByText(/Build, inspect and paper-test/i),
    ).toBeDefined();
    await screen.findByTestId("keys-onboarding-kraken");
    await screen.findByTestId("keys-onboarding-coinbase");
  });

  it("offers a primary CTA into the paper workstation", () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    fireEvent.click(screen.getByTestId("app-home-cta-paper"));
    expect(onNavigate).toHaveBeenCalledWith("workstation");
  });

  it("keeps the local-preview / live-unavailable copy conspicuous", () => {
    renderHome();
    const availability = screen.getByTestId("app-home-availability");
    expect(availability.textContent).toMatch(/Local preview/i);
    expect(availability.textContent).toMatch(/Live trading unavailable/i);
  });

  it("renders the five feature cards as real in-app buttons, not anchors", () => {
    renderHome();
    expect(screen.queryByRole("link")).toBeNull();
    for (const { testid, name } of CARD_DESTINATIONS) {
      const card = screen.getByTestId(testid);
      expect(card.tagName).toBe("BUTTON");
      expect((card as HTMLButtonElement).type).toBe("button");
      expect(card.getAttribute("href")).toBeNull();
      expect(card.textContent).toMatch(name);
    }
  });

  it("navigates to each existing view when its card is activated", () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    for (const { testid, view } of CARD_DESTINATIONS) {
      fireEvent.click(screen.getByTestId(testid));
      expect(onNavigate).toHaveBeenLastCalledWith(view);
    }
    expect(onNavigate).toHaveBeenCalledTimes(CARD_DESTINATIONS.length);
  });

  it("activates cards with the keyboard (Enter and Space)", () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    // Native buttons are keyboard-activable by the platform (Enter and
    // Space both fire click); the guarantee under test is that every
    // card is a focusable button with no scripting barrier.
    const cards = CARD_DESTINATIONS.map(({ testid }) =>
      screen.getByTestId(testid),
    );
    for (const card of cards) {
      expect(card.tagName).toBe("BUTTON");
      expect((card as HTMLButtonElement).disabled).toBe(false);
      expect(card.getAttribute("tabindex")).toBeNull();
      (card as HTMLButtonElement).focus();
      expect(document.activeElement).toBe(card);
      fireEvent.click(card);
    }
    expect(onNavigate).toHaveBeenCalledTimes(CARD_DESTINATIONS.length);
    expect(onNavigate).toHaveBeenLastCalledWith("operations");
  });

  it("replaces the old not-connected copy with Kraken and Coinbase keys forms", async () => {
    renderHome();
    const works = screen.getByRole("region", { name: /what works here/i });
    expect(works.textContent).toMatch(/strategy/i);
    expect(works.textContent).toMatch(/research/i);
    expect(screen.queryByText(/No exchange is connected in this build/i)).toBeNull();
    const kraken = await screen.findByTestId("keys-onboarding-kraken");
    expect(kraken.textContent).toMatch(/Kraken exchange key/i);
    const coinbase = await screen.findByTestId("keys-onboarding-coinbase");
    expect(coinbase.textContent).toMatch(/Coinbase exchange key/i);
    expect(await screen.findByTestId("keys-form-kraken")).toBeTruthy();
    expect(await screen.findByTestId("keys-form-coinbase")).toBeTruthy();
    expect((await screen.findByTestId("keys-status-kraken")).textContent).toMatch(
      /no key stored/i,
    );
    expect((await screen.findByTestId("keys-status-coinbase")).textContent).toMatch(
      /no key stored/i,
    );
  });

  it("never fabricates live readiness, profit or sign-in marketing", async () => {
    const { container } = render(
      <AppHome
        onNavigate={() => {}}
        keysClient={fakeKeysClient()}
        versionClient={fakeVersionClient()}
      />,
    );
    await screen.findByTestId("keys-form-kraken");
    const html = container.innerHTML;
    for (const fabricated of [
      "live ready",
      "Live ready",
      "profitable",
      "Profit",
      "sign in",
      "Sign in",
      "checkout",
      "Checkout",
      "upgrade",
    ]) {
      expect(html.includes(fabricated)).toBe(false);
    }
  });

  it("does not fabricate financial or market data when no key is stored", async () => {
    const { container } = render(
      <AppHome
        onNavigate={() => {}}
        keysClient={fakeKeysClient()}
        versionClient={fakeVersionClient()}
      />,
    );
    await screen.findByTestId("keys-form-kraken");
    const html = container.innerHTML;
    for (const fabricated of [
      "$",
      "equity",
      "Equity",
      "latency",
      "returns",
      "Returns",
      "drawdown",
      "position open",
      "%",
    ]) {
      expect(html.includes(fabricated)).toBe(false);
    }
    expect(screen.queryByTestId("keys-balances-kraken")).toBeNull();
    expect(screen.queryByTestId("keys-balances-coinbase")).toBeNull();
  });

  it("surfaces the engine version and prerelease channel on About", async () => {
    renderHome();
    expect((await screen.findByTestId("app-home-about-version")).textContent).toBe(
      "v0.9.7",
    );
    expect(screen.getByTestId("app-home-about-channel").textContent).toBe(
      "Prerelease",
    );
    expect(screen.getByTestId("app-home-about-signing").textContent).toBe(
      "Unsigned artifacts",
    );
  });

  it("shows the session note only while the local session is starting", async () => {
    const keysClient = fakeKeysClient();
    const versionClient = fakeVersionClient();
    const { rerender } = render(
      <AppHome
        onNavigate={() => {}}
        keysClient={keysClient}
        versionClient={versionClient}
      />,
    );
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    rerender(
      <AppHome
        onNavigate={() => {}}
        keysClient={keysClient}
        versionClient={versionClient}
        sessionPending
      />,
    );
    expect(screen.getByTestId("app-home-session").textContent).toMatch(
      /starting the local session/i,
    );
    expect(screen.getByTestId("keys-waiting-session-kraken")).toBeTruthy();
    expect(screen.getByTestId("keys-waiting-session-coinbase")).toBeTruthy();
    rerender(
      <AppHome
        onNavigate={() => {}}
        keysClient={keysClient}
        versionClient={versionClient}
        sessionPending={false}
      />,
    );
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    await waitFor(() => {
      expect(keysClient.getStatus).toHaveBeenCalledWith("kraken");
      expect(keysClient.getStatus).toHaveBeenCalledWith("coinbase");
    });
  });
});
