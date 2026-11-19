/**
 * M25.7 — home first viewport stays coach-friendly: one sage CTA, pack
 * path as a text link, Advanced stack and checklist hidden until coach
 * skip/complete (checklist **or** coach, never both).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../api/version";
import type { KeysClient } from "../features/keys/client";
import {
  FIRST_RUN_COACH_STORAGE_KEY,
  writeFirstRunCoachState,
} from "../features/onboarding/firstRunCoachPersistence";
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

function renderHome(
  props: {
    showHomeAdvanced?: boolean;
    suppressActivationChecklist?: boolean;
    coachSyncKey?: number;
  } = {},
): void {
  render(
    <AppHome
      onNavigate={() => {}}
      keysClient={absentKeysClient()}
      versionClient={previewVersionClient()}
      showHomeAdvanced={props.showHomeAdvanced}
      suppressActivationChecklist={props.suppressActivationChecklist}
      coachSyncKey={props.coachSyncKey}
    />,
  );
}

describe("home first viewport hides Advanced until coach is done", () => {
  it("keeps brand, one headline, one supporting sentence, and one sage CTA while coach is active", () => {
    writeFirstRunCoachState({ status: "idle", stepId: "welcome" });
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
    expect(screen.getByTestId("app-home").getAttribute("data-home-advanced")).toBe(
      "0",
    );
    expect(screen.queryByTestId("app-home-advanced-stack")).toBeNull();
    expect(screen.queryByTestId("app-home-path")).toBeNull();
    expect(screen.queryByTestId("app-home-keys-rail")).toBeNull();
    expect(screen.queryByTestId("app-home-works")).toBeNull();
  });

  it("keeps I already have a pack as a text link, not a peer sage button", () => {
    renderHome({ showHomeAdvanced: false });
    const packs = screen.getByTestId("app-home-cta-packs");
    expect(packs.tagName).toBe("BUTTON");
    expect(packs.classList.contains("app-home__cta-link")).toBe(true);
    expect(packs.classList.contains("app-home__cta")).toBe(false);
    expect(packs.textContent).toMatch(/I already have a pack/i);
    fireEvent.click(packs);
  });

  it("surfaces Advanced rails and the checklist only after coach skip or complete", () => {
    writeFirstRunCoachState({ status: "skipped", stepId: "choose_starter" });
    renderHome();
    expect(screen.getByTestId("app-home").getAttribute("data-home-advanced")).toBe(
      "1",
    );
    expect(screen.getByTestId("app-home-advanced-stack")).toBeTruthy();
    expect(screen.getByTestId("app-home-path").getAttribute("data-open")).toBe(
      "0",
    );
    expect(screen.getByTestId("app-home-keys-rail").getAttribute("data-open")).toBe(
      "0",
    );
    expect(screen.getByTestId("app-home-works")).toBeTruthy();
    expect(screen.getByTestId("activation-checklist")).toBeTruthy();
  });

  it("does not mount checklist chrome when Advanced is still locked for the coach", () => {
    writeFirstRunCoachState({ status: "active", stepId: "choose_starter" });
    renderHome({ showHomeAdvanced: false });
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.queryByTestId("app-home-works")).toBeNull();
  });

  it("honors an explicit showHomeAdvanced override from the shell", () => {
    writeFirstRunCoachState({ status: "idle", stepId: "welcome" });
    renderHome({ showHomeAdvanced: true });
    expect(screen.getByTestId("app-home").getAttribute("data-home-advanced")).toBe(
      "1",
    );
    expect(screen.getByTestId("app-home-path")).toBeTruthy();
  });
});

describe("home first viewport coach persistence key", () => {
  it("re-reads coach dismissal when coachSyncKey bumps", () => {
    writeFirstRunCoachState({ status: "idle", stepId: "welcome" });
    const { rerender } = render(
      <AppHome
        onNavigate={() => {}}
        keysClient={absentKeysClient()}
        versionClient={previewVersionClient()}
        coachSyncKey={0}
      />,
    );
    expect(screen.getByTestId("app-home").getAttribute("data-home-advanced")).toBe(
      "0",
    );
    writeFirstRunCoachState({ status: "completed", stepId: "win" });
    rerender(
      <AppHome
        onNavigate={() => {}}
        keysClient={absentKeysClient()}
        versionClient={previewVersionClient()}
        coachSyncKey={1}
      />,
    );
    expect(screen.getByTestId("app-home").getAttribute("data-home-advanced")).toBe(
      "1",
    );
    expect(window.localStorage.getItem(FIRST_RUN_COACH_STORAGE_KEY)).toMatch(
      /completed/,
    );
  });
});
