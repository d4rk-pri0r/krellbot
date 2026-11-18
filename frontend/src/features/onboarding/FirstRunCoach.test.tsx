import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FirstRunCoach,
  FIRST_RUN_COACH_STORAGE_KEY,
  readFirstRunCoachState,
  writeFirstRunCoachState,
} from "./FirstRunCoach";
import {
  isFirstRunCoachDismissed,
  resumeFirstRunCoachState,
} from "./firstRunCoachPersistence";

const STORAGE = FIRST_RUN_COACH_STORAGE_KEY;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("FirstRunCoach — welcome opens into guided steps", () => {
  it("shows the welcome strip with Start and no Skip guide yet", () => {
    render(<FirstRunCoach />);
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "welcome",
    );
    expect(screen.getByTestId("first-run-coach-primary").textContent).toBe("Start");
    expect(screen.queryByTestId("first-run-coach-skip")).toBeNull();
  });

  it("advances from Start to choose_starter and keeps Skip guide available", () => {
    render(<FirstRunCoach />);
    fireEvent.click(screen.getByTestId("first-run-coach-primary"));
    const coach = screen.getByTestId("first-run-coach");
    expect(coach.getAttribute("data-coach-step")).toBe("choose_starter");
    expect(coach.getAttribute("data-coach-status")).toBe("active");
    expect(screen.getByTestId("first-run-coach-skip").textContent).toBe("Skip guide");
    expect(readFirstRunCoachState(STORAGE)).toEqual({
      status: "active",
      stepId: "choose_starter",
    });
  });
});

describe("FirstRunCoach — skip persists and never re-traps", () => {
  it("persists Skip guide and hides the coach on remount", () => {
    const onSkip = vi.fn();
    const { unmount } = render(<FirstRunCoach onSkip={onSkip} />);
    fireEvent.click(screen.getByTestId("first-run-coach-primary"));
    fireEvent.click(screen.getByTestId("first-run-coach-skip"));
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(readFirstRunCoachState(STORAGE).status).toBe("skipped");
    expect(isFirstRunCoachDismissed()).toBe(true);
    unmount();
    render(<FirstRunCoach />);
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
  });

  it("does not auto-show after completed either", () => {
    writeFirstRunCoachState({ status: "completed", stepId: "win" }, STORAGE);
    render(<FirstRunCoach />);
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
  });
});

describe("FirstRunCoach — spotlight tracks coach anchors", () => {
  it("spotlights the matching data-coach-anchor target", () => {
    render(
      <div>
        <button type="button" data-coach-anchor="choose_starter">
          Start with a free paper strategy
        </button>
        <FirstRunCoach />
      </div>,
    );
    fireEvent.click(screen.getByTestId("first-run-coach-primary"));
    expect(screen.getByTestId("first-run-coach-spotlight")).toBeTruthy();
  });
});

describe("FirstRunCoach — primary advances steps until win completes", () => {
  it("walks choose_starter → arm_paper → status → win → completed", () => {
    const onComplete = vi.fn();
    render(<FirstRunCoach onComplete={onComplete} />);
    fireEvent.click(screen.getByTestId("first-run-coach-primary")); // welcome → choose
    fireEvent.click(screen.getByTestId("first-run-coach-primary")); // → arm
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "arm_paper",
    );
    fireEvent.click(screen.getByTestId("first-run-coach-primary")); // → status
    fireEvent.click(screen.getByTestId("first-run-coach-primary")); // → win
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "win",
    );
    fireEvent.click(screen.getByTestId("first-run-coach-primary")); // Done
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(readFirstRunCoachState(STORAGE)).toEqual({
      status: "completed",
      stepId: "win",
    });
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
  });

  it("keeps the step when onPrimaryAction returns false", () => {
    render(
      <FirstRunCoach
        onPrimaryAction={(stepId) => (stepId === "choose_starter" ? false : undefined)}
      />,
    );
    fireEvent.click(screen.getByTestId("first-run-coach-primary"));
    fireEvent.click(screen.getByTestId("first-run-coach-primary"));
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "choose_starter",
    );
  });
});

describe("FirstRunCoach — resume helper for incomplete setup", () => {
  it("reopens a skipped coach into an active guided step", () => {
    writeFirstRunCoachState(
      { status: "skipped", stepId: "arm_paper" },
      STORAGE,
    );
    const resumed = resumeFirstRunCoachState(STORAGE);
    expect(resumed).toEqual({ status: "active", stepId: "arm_paper" });
    render(<FirstRunCoach />);
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "arm_paper",
    );
  });

  it("does not resume after completed", () => {
    writeFirstRunCoachState({ status: "completed", stepId: "win" }, STORAGE);
    expect(resumeFirstRunCoachState(STORAGE).status).toBe("completed");
  });
});
