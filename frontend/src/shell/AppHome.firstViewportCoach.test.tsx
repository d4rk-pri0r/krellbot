/**
 * Post-wizard home first viewport (M24 IA / M26.6).
 *
 * The shell only mounts after the wizard is done. Home keeps one sage CTA
 * and a pack text link, with Advanced rails mounted and collapsed. No
 * hotspot coach and no activation checklist.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../api/version";
import type { KeysClient } from "../features/keys/client";
import { AppHome } from "./AppHome";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function absentKeysClient(): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      venue: "kraken",
      present: false,
      corrupt: false,
      message: "no key stored",
      backend_label: null,
      balances: null,
      balances_available: false,
    }),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
  };
}

function previewVersionClient(): VersionClient {
  return {
    getVersion: vi.fn().mockResolvedValue({
      schema_version: "1",
      version: "0.9.7",
      channel: "prerelease",
      artifacts_signed: false,
    }),
  };
}

function renderHome(): void {
  render(
    <AppHome
      onNavigate={() => {}}
      keysClient={absentKeysClient()}
      versionClient={previewVersionClient()}
    />,
  );
}

describe("post-wizard home keeps M24 first viewport without coach chrome", () => {
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
    expect(screen.getByTestId("app-home-cta-paper").hasAttribute("data-coach-anchor")).toBe(
      false,
    );
    expect(screen.getByTestId("app-home").getAttribute("data-home-advanced")).toBe(
      "1",
    );
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

  it("mounts collapsed Advanced rails and does not mount the activation checklist", () => {
    renderHome();
    expect(screen.getByTestId("app-home-advanced-stack")).toBeTruthy();
    expect(screen.getByTestId("app-home-path").getAttribute("data-open")).toBe(
      "0",
    );
    expect(screen.getByTestId("app-home-keys-rail").getAttribute("data-open")).toBe(
      "0",
    );
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.queryByTestId("app-home-works")).toBeNull();
    expect(document.querySelector("[data-coach-anchor]")).toBeNull();
  });
});
