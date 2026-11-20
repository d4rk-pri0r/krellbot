/**
 * Post-wizard home first viewport (KRELL-SIGNAL-20261010).
 *
 * The shell only mounts after the wizard is done. Home keeps one sage CTA
 * and a pack text link without a squeezed settings sidebar, hotspot coach,
 * or activation checklist.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppHome } from "./AppHome";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderHome(): void {
  render(<AppHome onNavigate={() => {}} />);
}

describe("post-wizard home keeps clean first viewport without coach chrome or settings rail", () => {
  it("keeps brand, one headline, one supporting sentence, and one sage CTA", () => {
    renderHome();
    const first = screen.getByTestId("app-home-first-viewport");
    expect(first.querySelector(".kbot-brandmark")).not.toBeNull();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /paper trading on this computer/i,
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(/Start a free strategy with pretend money/i),
    ).toBeTruthy();
    expect(screen.getByTestId("app-home-cta-paper").textContent).toMatch(
      /Start with a free paper strategy/i,
    );
    expect(
      screen.getByTestId("app-home-cta-paper").hasAttribute("data-coach-anchor"),
    ).toBe(false);
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.queryByTestId("app-home-works")).toBeNull();
  });

  it("keeps I already have a pack as a text link, not a peer sage button", () => {
    renderHome();
    const packs = screen.getByTestId("app-home-cta-packs");
    expect(packs.tagName).toBe("BUTTON");
    expect(packs.classList.contains("app-home__cta-link")).toBe(true);
    expect(packs.classList.contains("app-home__cta")).toBe(false);
    expect(packs.textContent).toMatch(/I already have a pack/i);
    fireEvent.click(packs);
  });

  it("keeps Settings rails and duplicate destination cards off Workspace Home", () => {
    renderHome();
    expect(screen.queryByTestId("app-home-path")).toBeNull();
    expect(screen.queryByTestId("app-home-keys-rail")).toBeNull();
    expect(screen.queryByTestId("app-home-settings-trust")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.queryByTestId("app-home-works")).toBeNull();
    expect(document.querySelector("[data-coach-anchor]")).toBeNull();
  });
});
