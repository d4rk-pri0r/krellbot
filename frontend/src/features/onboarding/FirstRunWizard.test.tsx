import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FirstRunWizard,
  FIRST_RUN_WIZARD_STORAGE_KEY,
  readFirstRunWizardState,
  writeFirstRunWizardState,
} from "./FirstRunWizard";
import { isFirstRunWizardDismissed } from "./firstRunWizardPersistence";

const STORAGE = FIRST_RUN_WIZARD_STORAGE_KEY;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("FirstRunWizard — welcome opens full-screen paper setup", () => {
  it("shows the welcome sentence, Let’s go, Krell visual, and no Skip yet", () => {
    render(<FirstRunWizard />);
    const wizard = screen.getByTestId("first-run-wizard");
    expect(wizard.getAttribute("data-wizard-step")).toBe("welcome");
    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "Let’s set up a pretend trading bot on this computer — no real money.",
    );
    expect(screen.getByTestId("first-run-wizard-primary").textContent).toBe(
      "Let’s go",
    );
    expect(
      screen.getByTestId("first-run-wizard-visual").getAttribute("data-wizard-visual"),
    ).toBe("krell-hero.webp");
    expect(screen.queryByTestId("first-run-wizard-skip")).toBeNull();
  });

  it("advances from Let’s go to choose and keeps Skip setup available", () => {
    render(<FirstRunWizard />);
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    const wizard = screen.getByTestId("first-run-wizard");
    expect(wizard.getAttribute("data-wizard-step")).toBe("choose");
    expect(wizard.getAttribute("data-wizard-status")).toBe("active");
    expect(screen.getByTestId("first-run-wizard-skip").textContent).toBe(
      "Skip setup",
    );
    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "Pick one free strategy to try.",
    );
    expect(readFirstRunWizardState(STORAGE)).toMatchObject({
      status: "active",
      stepId: "choose",
    });
  });
});

describe("FirstRunWizard — choose stubs three starter tiles", () => {
  it("renders Dual moving average, Mean reversion, and Range breakout Use tiles", () => {
    writeFirstRunWizardState(
      { status: "active", stepId: "choose", selectedStarterId: null },
      STORAGE,
    );
    render(<FirstRunWizard />);
    expect(screen.getByTestId("first-run-wizard-tiles")).toBeTruthy();
    expect(
      screen.getByTestId("first-run-wizard-use-starter-dual-ma-crossover")
        .textContent,
    ).toBe("Use");
    expect(
      screen.getByTestId("first-run-wizard-use-starter-mean-reversion-band")
        .textContent,
    ).toBe("Use");
    expect(
      screen.getByTestId("first-run-wizard-use-starter-range-breakout")
        .textContent,
    ).toBe("Use");
    expect(screen.getByText("Dual moving average")).toBeTruthy();
    expect(screen.getByText("Mean reversion")).toBeTruthy();
    expect(screen.getByText("Range breakout")).toBeTruthy();
    expect(screen.queryByTestId("first-run-wizard-primary")).toBeNull();
  });

  it("selecting Use advances to start_paper and stores the starter id", () => {
    writeFirstRunWizardState(
      { status: "active", stepId: "choose", selectedStarterId: null },
      STORAGE,
    );
    render(<FirstRunWizard />);
    fireEvent.click(
      screen.getByTestId("first-run-wizard-use-starter-dual-ma-crossover"),
    );
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("start_paper");
    expect(readFirstRunWizardState(STORAGE)).toEqual({
      status: "active",
      stepId: "start_paper",
      selectedStarterId: "starter-dual-ma-crossover",
    });
  });
});

describe("FirstRunWizard — skip persists and never re-traps", () => {
  it("persists Skip setup and hides the wizard on remount", () => {
    const onSkip = vi.fn();
    const { unmount } = render(<FirstRunWizard onSkip={onSkip} />);
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    fireEvent.click(screen.getByTestId("first-run-wizard-skip"));
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(readFirstRunWizardState(STORAGE).status).toBe("skipped");
    expect(isFirstRunWizardDismissed()).toBe(true);
    unmount();
    render(<FirstRunWizard />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
  });

  it("does not auto-show after completed either", () => {
    writeFirstRunWizardState(
      { status: "completed", stepId: "win", selectedStarterId: null },
      STORAGE,
    );
    render(<FirstRunWizard />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
  });
});

describe("FirstRunWizard — primary walks paper steps until win completes", () => {
  it("walks start_paper → status → win → completed with plan copy", () => {
    const onComplete = vi.fn();
    writeFirstRunWizardState(
      {
        status: "active",
        stepId: "start_paper",
        selectedStarterId: "starter-dual-ma-crossover",
      },
      STORAGE,
    );
    render(<FirstRunWizard onComplete={onComplete} />);

    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "Start it with pretend money so you can see how it behaves.",
    );
    expect(screen.getByTestId("first-run-wizard-primary").textContent).toBe(
      "Start paper run",
    );
    expect(
      screen.getByTestId("first-run-wizard-visual").getAttribute("data-wizard-visual"),
    ).toBe("krell_waistup.png");

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("status");
    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "It’s running on this computer (paper only — not live trading).",
    );
    expect(screen.getByTestId("first-run-wizard-primary").textContent).toBe(
      "Looks good",
    );
    expect(
      screen.getByTestId("first-run-wizard-visual").getAttribute("data-wizard-visual"),
    ).toBe("krell_chibi.png");

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("win");
    expect(screen.getByTestId("first-run-wizard-sentence").textContent).toBe(
      "You’re set. Here’s your workspace.",
    );
    expect(screen.getByTestId("first-run-wizard-primary").textContent).toBe(
      "Open Krellbot",
    );
    expect(
      screen.getByTestId("first-run-wizard-visual").getAttribute("data-wizard-visual"),
    ).toBe("krell_security.png");

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(readFirstRunWizardState(STORAGE)).toEqual({
      status: "completed",
      stepId: "win",
      selectedStarterId: "starter-dual-ma-crossover",
    });
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
  });

  it("keeps the step when onPrimaryAction returns false", () => {
    writeFirstRunWizardState(
      {
        status: "active",
        stepId: "start_paper",
        selectedStarterId: "starter-range-breakout",
      },
      STORAGE,
    );
    render(
      <FirstRunWizard
        onPrimaryAction={(stepId) =>
          stepId === "start_paper" ? false : undefined
        }
      />,
    );
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("start_paper");
  });

  it("keeps choose when onSelectStarter returns false", () => {
    writeFirstRunWizardState(
      { status: "active", stepId: "choose", selectedStarterId: null },
      STORAGE,
    );
    render(
      <FirstRunWizard onSelectStarter={() => false} />,
    );
    fireEvent.click(
      screen.getByTestId("first-run-wizard-use-starter-range-breakout"),
    );
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("choose");
  });
});

describe("FirstRunWizard — no cockpit chrome inside the shell", () => {
  it("does not render hotspot, checklist, or coach anchors", () => {
    render(<FirstRunWizard />);
    expect(document.querySelector("[data-coach-anchor]")).toBeNull();
    expect(document.querySelector(".kbot-first-run-coach")).toBeNull();
    expect(document.querySelector(".kbot-activation-checklist")).toBeNull();
    expect(screen.queryByTestId("first-run-coach-spotlight")).toBeNull();
  });
});
