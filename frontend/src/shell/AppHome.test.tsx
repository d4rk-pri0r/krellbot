/**
 * Application Home — Signal workspace composition (KRELL-SIGNAL-20261010).
 *
 * Workspace Home has one focused job: start or open a paper run. Exchange keys,
 * disclosures, live-ready wizard, reconnect invite, demo fixture, and About
 * live in the dedicated Settings view.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppHome } from "./AppHome";
import type { View } from "./Navigation";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

function renderHome(
  props: {
    onNavigate?: (view: View) => void;
    sessionPending?: boolean;
    sessionFailed?: boolean;
    onReplaySetupTour?: () => void;
  } = {},
) {
  return render(
    <AppHome
      onNavigate={props.onNavigate ?? (() => {})}
      sessionPending={props.sessionPending}
      sessionFailed={props.sessionFailed}
      onReplaySetupTour={props.onReplaySetupTour}
    />,
  );
}

describe("AppHome — focused workspace front door", () => {
  it("renders a welcoming heading, readable purpose, and no embedded Settings rail", () => {
    const { container } = renderHome();
    const region = screen.getByTestId("app-home");
    expect(region.tagName).toBe("SECTION");
    const heading = screen.getByRole("heading", {
      level: 1,
      name: /paper trading on this computer/i,
    });
    expect(region.contains(heading)).toBe(true);
    expect(
      screen.getByText(/Start a free strategy with pretend money/i),
    ).toBeDefined();
    expect(heading.closest(".app-home__hero-copy")?.textContent).toMatch(
      /Live trading stays off/i,
    );
    expect(screen.queryByTestId("app-home-path")).toBeNull();
    expect(screen.queryByTestId("app-home-settings-trust")).toBeNull();
    expect(screen.queryByTestId("keys-onboarding-kraken")).toBeNull();
    expect(screen.queryByTestId("keys-onboarding-coinbase")).toBeNull();
    expect(container.textContent).not.toMatch(/No separate Settings view/i);
  });

  it("offers a primary CTA that opens the home starter chooser", () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    expect(screen.getByTestId("app-home-cta-paper").textContent).toMatch(
      /Start with a free paper strategy/i,
    );
    fireEvent.click(screen.getByTestId("app-home-cta-paper"));
    expect(screen.getByTestId("paper-starter-chooser")).toBeDefined();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("offers a secondary text action for operators who already have a pack", () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    fireEvent.click(screen.getByTestId("app-home-cta-packs"));
    expect(onNavigate).toHaveBeenCalledWith("packs");
  });

  it("renders a quiet setup tour replay link in the hero when wired", () => {
    const onReplaySetupTour = vi.fn();
    renderHome({ onReplaySetupTour });
    const replay = screen.getByTestId("workspace-setup-tour-replay");
    expect(replay.textContent).toMatch(/Take setup tour/i);
    fireEvent.click(replay);
    expect(onReplaySetupTour).toHaveBeenCalledTimes(1);
  });

  it("keeps the local-preview / live-unavailable copy conspicuous", () => {
    renderHome();
    const availability = screen.getByTestId("app-home-availability");
    expect(availability.textContent).toMatch(/Local preview/i);
    expect(availability.textContent).toMatch(/Live trading unavailable/i);
  });

  it("never fabricates live readiness, profit, financial metrics, or sign-in marketing", () => {
    const { container } = renderHome();
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
