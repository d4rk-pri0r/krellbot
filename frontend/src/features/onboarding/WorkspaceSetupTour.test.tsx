/**
 * Setup tour: persistence, viewport placement, and a non-blocking callout
 * that appears only after the intro wizard exits.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { Box } from "./workspaceSetupTourPlacement";
import { placeSetupTourCallout } from "./workspaceSetupTourPlacement";
import {
  clickPaperArmSubmit,
  findPaperArmSurface,
  prepareStarterRevision,
} from "./workspaceSetupTourLaunch";
import {
  armWorkspaceSetupTour,
  readWorkspaceSetupTourState,
  replayWorkspaceSetupTour,
  writeWorkspaceSetupTourState,
} from "./workspaceSetupTourPersistence";
import { WorkspaceSetupTour } from "./WorkspaceSetupTour";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "WorkspaceSetupTour.signal.css"), "utf8");

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

vi.mock("../../session", () => ({
  redeemBootstrap: (): Promise<void> => Promise.resolve(),
  recoverCsrf: (): Promise<boolean> => Promise.resolve(true),
  getCsrf: (): string => "test-csrf",
  issueReconnectToken: (): Promise<never> => Promise.reject(new Error("unused")),
  redeemReconnectToken: (): Promise<never> => Promise.reject(new Error("unused")),
}));

beforeEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

function inside(box: Box, viewport: { width: number; height: number }): boolean {
  return (
    box.top >= 11 &&
    box.left >= 11 &&
    box.top + box.height <= viewport.height - 11 &&
    box.left + box.width <= viewport.width - 11
  );
}

describe("setup tour persistence never re-traps after skip or complete", () => {
  it("stays idle until the wizard exit arms it, then ignores a second arm", () => {
    expect(readWorkspaceSetupTourState()).toEqual({
      status: "idle",
      stepId: "workspace",
    });
    expect(armWorkspaceSetupTour()).toEqual({
      status: "active",
      stepId: "workspace",
    });
    writeWorkspaceSetupTourState({ status: "active", stepId: "keys" });
    expect(armWorkspaceSetupTour().stepId).toBe("keys");
    writeWorkspaceSetupTourState({ status: "skipped", stepId: "strategy" });
    expect(armWorkspaceSetupTour().status).toBe("skipped");
    writeWorkspaceSetupTourState({ status: "completed", stepId: "run" });
    expect(armWorkspaceSetupTour().status).toBe("completed");
    expect(replayWorkspaceSetupTour()).toEqual({
      status: "active",
      stepId: "workspace",
    });
    window.localStorage.setItem("krellbot.home.setupTour", "{");
    expect(readWorkspaceSetupTourState().status).toBe("idle");
  });
});

describe("setup tour callout stays inside the viewport and off protected controls", () => {
  it("places a desktop card below a workspace chip without covering nav or the paper CTA", () => {
    const viewport = { width: 1440, height: 900 };
    const placed = placeSetupTourCallout({
      viewport,
      target: { top: 168, left: 48, width: 280, height: 64 },
      card: { width: 360, height: 220 },
      avoid: [
        { top: 0, left: 280, width: 640, height: 56 },
        { top: 120, left: 1080, width: 220, height: 44 },
      ],
    });
    expect(inside(placed.card, viewport)).toBe(true);
    expect(placed.arrow).not.toBeNull();
    expect(placed.spotlight).not.toBeNull();
    const arrow = placed.arrow!;
    for (const value of [arrow.x1, arrow.x2]) {
      expect(value).toBeGreaterThanOrEqual(2);
      expect(value).toBeLessThanOrEqual(viewport.width - 2);
    }
    for (const value of [arrow.y1, arrow.y2]) {
      expect(value).toBeGreaterThanOrEqual(2);
      expect(value).toBeLessThanOrEqual(viewport.height - 2);
    }
    const card = placed.card;
    const overlapsCta =
      card.left < 1300 &&
      card.left + card.width > 1080 &&
      card.top < 164 &&
      card.top + card.height > 120;
    expect(overlapsCta).toBe(false);
    const overlapsNav =
      card.top < 56 && card.left < 920 && card.left + card.width > 280;
    expect(overlapsNav).toBe(false);
    expect(card.top).toBeGreaterThanOrEqual(168 + 64 + 8);
  });

  it("sits above a bottom toast without covering the paper controls", () => {
    const viewport = { width: 1440, height: 900 };
    const placed = placeSetupTourCallout({
      viewport,
      target: { top: 120, left: 40, width: 900, height: 48 },
      card: { width: 360, height: 220 },
      avoid: [
        { top: 280, left: 40, width: 900, height: 80 },
        { top: 700, left: 510, width: 420, height: 176 },
      ],
    });
    expect(inside(placed.card, viewport)).toBe(true);
    const card = placed.card;
    const overlapsButtons =
      card.top < 360 && card.top + card.height > 280 && card.left < 940;
    const overlapsToast =
      card.top < 876 &&
      card.top + card.height > 700 &&
      card.left < 930 &&
      card.left + card.width > 510;
    expect(overlapsButtons).toBe(false);
    expect(overlapsToast).toBe(false);
    expect(placed.arrow).not.toBeNull();
  });

  it("keeps a phone card inside 390×844 and clear of the stacked paper CTA", () => {
    const viewport = { width: 390, height: 844 };
    const placed = placeSetupTourCallout({
      viewport,
      target: { top: 210, left: 16, width: 340, height: 72 },
      card: { width: 360, height: 240 },
      avoid: [
        { top: 0, left: 0, width: 390, height: 140 },
        { top: 320, left: 16, width: 340, height: 48 },
      ],
    });
    expect(inside(placed.card, viewport)).toBe(true);
    expect(placed.card.top + placed.card.height).toBeLessThanOrEqual(844 - 11);
    expect(placed.card.left + placed.card.width).toBeLessThanOrEqual(390 - 11);
    const card = placed.card;
    const overlapsCta =
      card.top < 368 && card.top + card.height > 320 && card.left < 356;
    expect(overlapsCta).toBe(false);
    expect(card.top).toBeGreaterThanOrEqual(210 + 72 + 8);
    expect(placed.arrow).not.toBeNull();
    expect(placed.arrow!.x2).toBeLessThanOrEqual(388);
    expect(placed.arrow!.y2).toBeLessThanOrEqual(842);
  });

  it("parks the card inside the viewport when the target is missing", () => {
    const viewport = { width: 390, height: 844 };
    const placed = placeSetupTourCallout({
      viewport,
      target: null,
      card: { width: 360, height: 200 },
    });
    expect(placed.arrow).toBeNull();
    expect(placed.spotlight).toBeNull();
    expect(inside(placed.card, viewport)).toBe(true);
  });
});

describe("setup tour Signal CSS leaves the cockpit clickable", () => {
  it("uses Signal tokens, a sage primary, and pointer-events only on the card", () => {
    expect(css).toMatch(/KRELL-SIGNAL-20261010/);
    expect(css).toMatch(/--sage|--action-primary-bg/);
    expect(css).toMatch(/--seafoam|--focus-ring/);
    expect(css).toMatch(/--danger-text/);
    expect(css).toMatch(/\.kbot-setup-tour\s*\{[^}]*pointer-events:\s*none/);
    expect(css).toMatch(/\.kbot-setup-tour__card\s*\{[^}]*pointer-events:\s*auto/);
    expect(css).toMatch(/\.kbot-setup-tour__spotlight\s*\{[^}]*pointer-events:\s*none/);
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/animation:\s*none/);
  });
});

describe("setup tour callout steps", () => {
  function renderTour(
    props: Partial<ComponentProps<typeof WorkspaceSetupTour>> = {},
  ) {
    const onBack = vi.fn();
    const onNext = vi.fn();
    const onStartPaper = vi.fn();
    const onComplete = vi.fn();
    const onDismiss = vi.fn();
    render(
      <WorkspaceSetupTour
        stepId="workspace"
        paperArmed={false}
        onBack={onBack}
        onNext={onNext}
        onStartPaper={onStartPaper}
        onComplete={onComplete}
        onDismiss={onDismiss}
        {...props}
      />,
    );
    return { onBack, onNext, onStartPaper, onComplete, onDismiss };
  }

  it("shows step 1 of 4 and advances, goes back, and skips", () => {
    const handlers = renderTour();
    expect(screen.getByTestId("workspace-setup-tour").getAttribute("data-setup-step")).toBe(
      "workspace",
    );
    expect(screen.getByTestId("workspace-setup-tour-progress").textContent).toBe(
      "1 of 4",
    );
    expect(screen.getByTestId("workspace-setup-tour-title").textContent).toMatch(
      /Paper mode/i,
    );
    expect(
      (screen.getByTestId("workspace-setup-tour-back") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByTestId("workspace-setup-tour-next"));
    expect(handlers.onNext).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("workspace-setup-tour-skip"));
    expect(handlers.onDismiss).toHaveBeenCalledTimes(1);
  });

  it("dismisses on Escape and offers a real paper start only when no run is showing", () => {
    const skipped = renderTour();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(skipped.onDismiss).toHaveBeenCalledTimes(1);
    cleanup();

    const start = renderTour({ stepId: "run", paperArmed: false });
    expect(screen.getByTestId("workspace-setup-tour-next").textContent).toBe(
      "Start paper simulation",
    );
    fireEvent.click(screen.getByTestId("workspace-setup-tour-next"));
    expect(start.onStartPaper).toHaveBeenCalledTimes(1);
    expect(start.onComplete).not.toHaveBeenCalled();
    cleanup();

    const done = renderTour({ stepId: "run", paperArmed: true });
    expect(screen.getByTestId("workspace-setup-tour-next").textContent).toBe("Done");
    fireEvent.click(screen.getByTestId("workspace-setup-tour-next"));
    expect(done.onComplete).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("workspace-setup-tour-back"));
    expect(done.onBack).toHaveBeenCalledTimes(1);
  });
});

describe("setup tour paper launch helpers", () => {
  it("prepares a validated starter revision and clicks an enabled arm control", async () => {
    const strategy = {
      create: vi.fn().mockResolvedValue({
        revision_id: "rev-tour-1",
        state: "draft",
        pack: {},
        errors: [],
      }),
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-tour-1",
        state: "validated",
        pack: {},
        errors: [],
      }),
    };
    const revision = await prepareStarterRevision(strategy, async () => ({
      schema_version: "1",
      catalogue_version: "1",
      examples: [
        {
          id: "starter-dual-ma-crossover",
          label: "Dual moving average",
          description: "A free starter",
          pack: { id: "starter-dual-ma-crossover" },
        },
      ],
    }));
    expect(revision).toBe("rev-tour-1");
    expect(findPaperArmSurface()).toBe("pending");
    const button = document.createElement("button");
    button.dataset.testid = "paper-arm-submit";
    button.disabled = true;
    document.body.appendChild(button);
    expect(findPaperArmSurface()).toBe("pending");
    expect(clickPaperArmSubmit()).toBe(false);
    button.disabled = false;
    expect(findPaperArmSurface()).toBe("ready");
    const clicked = vi.fn();
    button.addEventListener("click", clicked);
    expect(clickPaperArmSubmit()).toBe(true);
    expect(clicked).toHaveBeenCalledTimes(1);
    button.remove();
    const entries = document.createElement("p");
    entries.dataset.testid = "paper-status-entries";
    entries.textContent = "Entries active";
    document.body.appendChild(entries);
    expect(findPaperArmSurface()).toBe("running");
    entries.remove();
  });
});

describe("setup tour stays unmounted during the intro wizard", () => {
  it("appears after skip and does not steal a studio deep link", () => {
    window.history.pushState({}, "", "/?view=studio");
    render(<App />);
    expect(screen.getByTestId("first-run-wizard")).toBeDefined();
    expect(screen.queryByTestId("workspace-setup-tour")).toBeNull();
    expect(screen.queryByTestId("kbot-shell")).toBeNull();

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    fireEvent.click(screen.getByTestId("first-run-wizard-skip"));

    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(screen.getByTestId("workspace-setup-tour").getAttribute("data-setup-step")).toBe(
      "workspace",
    );
    expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
    expect(window.location.search).toContain("view=studio");
    expect(readWorkspaceSetupTourState().status).toBe("active");

    fireEvent.click(screen.getByTestId("workspace-setup-tour-skip"));
    expect(screen.queryByTestId("workspace-setup-tour")).toBeNull();
    expect(readWorkspaceSetupTourState().status).toBe("skipped");
    expect(window.location.search).toContain("view=studio");
  });
});
