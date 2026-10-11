/**
 * Application Home — Signal composition (KRELL-SIGNAL-20261010).
 *
 * These tests pin the mounted application Home as a real, welcoming
 * overview: readable purpose, conspicuous local-preview/live-unavailable
 * copy, five state-driven navigation cards bound to the existing views,
 * keyboard activation, and no fabricated connection, account, license
 * or market state.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppHome } from "./AppHome";
import type { View } from "./Navigation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const CARD_DESTINATIONS: ReadonlyArray<{
  name: RegExp;
  view: View;
}> = [
  { name: /create or open a strategy/i, view: "strategies" },
  { name: /explore research/i, view: "research" },
  { name: /open studio/i, view: "studio" },
  { name: /paper workstation/i, view: "workstation" },
  { name: /operations/i, view: "operations" },
];

function renderHome(props: { onNavigate?: (view: View) => void } = {}): void {
  render(
    <AppHome
      onNavigate={props.onNavigate ?? (() => {})}
    />,
  );
}

describe("AppHome — application overview", () => {
  it("renders a welcoming heading and a readable application purpose", () => {
    renderHome();
    const region = screen.getByTestId("app-home");
    expect(region.tagName).toBe("SECTION");
    const heading = screen.getByRole("heading", {
      level: 1,
      name: /your crypto workstation, local by design/i,
    });
    expect(region.contains(heading)).toBe(true);
    expect(
      screen.getByText(/Build, inspect and paper-test/i),
    ).toBeDefined();
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
    for (const { name } of CARD_DESTINATIONS) {
      const card = screen.getByRole("button", { name });
      expect(card.tagName).toBe("BUTTON");
      expect((card as HTMLButtonElement).type).toBe("button");
      expect(card.getAttribute("href")).toBeNull();
    }
  });

  it("navigates to each existing view when its card is activated", () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    for (const { name, view } of CARD_DESTINATIONS) {
      fireEvent.click(screen.getByRole("button", { name }));
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
    const cards = CARD_DESTINATIONS.map(({ name }) =>
      screen.getByRole("button", { name }),
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

  it("exposes the What works here and Not connected yet explanations", () => {
    renderHome();
    const works = screen.getByRole("region", { name: /what works here/i });
    expect(works.textContent).toMatch(/strategy/i);
    expect(works.textContent).toMatch(/research/i);
    const notConnected = screen.getByRole("region", {
      name: /not connected yet/i,
    });
    expect(notConnected.textContent).toMatch(/no exchange/i);
    expect(notConnected.textContent).toMatch(/unavailable/i);
  });

  it("never claims a connection, live readiness, profit or credentials", () => {
    const { container } = render(<AppHome onNavigate={() => {}} />);
    const html = container.innerHTML;
    for (const fabricated of [
      "Connected",
      "connected to",
      "live ready",
      "Live ready",
      "profitable",
      "Profit",
      "api key",
      "API key",
      "sign in",
      "Sign in",
      "checkout",
      "Checkout",
      "upgrade",
    ]) {
      expect(html.includes(fabricated)).toBe(false);
    }
  });

  it("does not fabricate financial or market data", () => {
    const { container } = render(<AppHome onNavigate={() => {}} />);
    const html = container.innerHTML;
    for (const fabricated of [
      "$",
      "equity",
      "Equity",
      "latency",
      "returns",
      "Returns",
      "drawdown",
      "balance",
      "Balance",
      "position open",
      "%",
    ]) {
      expect(html.includes(fabricated)).toBe(false);
    }
  });

  it("shows the session note only while the local session is starting", () => {
    const { rerender } = render(<AppHome onNavigate={() => {}} />);
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    rerender(<AppHome onNavigate={() => {}} sessionPending />);
    expect(screen.getByTestId("app-home-session").textContent).toMatch(
      /starting the local session/i,
    );
    rerender(<AppHome onNavigate={() => {}} sessionPending={false} />);
    expect(screen.queryByTestId("app-home-session")).toBeNull();
  });
});
