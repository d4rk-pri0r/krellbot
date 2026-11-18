import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ActivationChecklist,
  ACTIVATION_CHECKLIST_STORAGE_KEY,
  deriveActivationChecklistItems,
  markActivationPaperRunStarted,
  markActivationPaperStatusVisible,
  markActivationStarterChosen,
  readActivationChecklistState,
  writeActivationChecklistState,
} from "./ActivationChecklist";

const STORAGE = ACTIVATION_CHECKLIST_STORAGE_KEY;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("activation checklist — installed locally is pre-checked", () => {
  it("shows Installed locally done on a fresh install with unfinished items open", () => {
    render(<ActivationChecklist />);
    const installed = screen.getByTestId("activation-checklist-item-installed");
    expect(installed.getAttribute("data-done")).toBe("1");
    expect(installed.textContent).toMatch(/Installed locally/);
    expect(
      screen.getByTestId("activation-checklist-item-chose_starter").getAttribute(
        "data-done",
      ),
    ).toBe("0");
    expect(
      screen.getByTestId("activation-checklist-item-paper_run").getAttribute(
        "data-done",
      ),
    ).toBe("0");
    expect(screen.getByTestId("activation-checklist").getAttribute("data-complete")).toBe(
      "0",
    );
  });
});

describe("activation checklist — persists starter and paper-run progress", () => {
  it("checks chose a free paper strategy after starter is recorded and keeps it on remount", () => {
    render(<ActivationChecklist />);
    act(() => {
      markActivationStarterChosen({
        revisionId: "rev-starter-1",
        label: "Dual moving average",
      });
    });
    expect(
      screen.getByTestId("activation-checklist-item-chose_starter").getAttribute(
        "data-done",
      ),
    ).toBe("1");
    expect(readActivationChecklistState(STORAGE)).toMatchObject({
      starterChosen: true,
      starterRevisionId: "rev-starter-1",
      starterLabel: "Dual moving average",
    });
    cleanup();
    render(<ActivationChecklist />);
    expect(
      screen.getByTestId("activation-checklist-item-chose_starter").getAttribute(
        "data-done",
      ),
    ).toBe("1");
  });

  it("checks started a paper run when armed status is noted", () => {
    render(<ActivationChecklist />);
    act(() => {
      markActivationPaperStatusVisible(false);
    });
    expect(
      screen.getByTestId("activation-checklist-item-paper_run").getAttribute(
        "data-done",
      ),
    ).toBe("0");
    act(() => {
      markActivationPaperStatusVisible(true);
    });
    expect(
      screen.getByTestId("activation-checklist-item-paper_run").getAttribute(
        "data-done",
      ),
    ).toBe("1");
    expect(readActivationChecklistState(STORAGE).paperRunStarted).toBe(true);
  });

  it("marks complete only when starter and paper run are both done", () => {
    act(() => {
      markActivationStarterChosen({ revisionId: "rev-2", label: "Mean reversion" });
      markActivationPaperRunStarted();
    });
    render(<ActivationChecklist />);
    expect(screen.getByTestId("activation-checklist").getAttribute("data-complete")).toBe(
      "1",
    );
    const items = deriveActivationChecklistItems({}, STORAGE);
    expect(items.every((item) => item.done)).toBe(true);
  });
});

describe("activation checklist — live facts override without fighting persistence", () => {
  it("treats paperArmed fact as started even before a write", () => {
    render(<ActivationChecklist facts={{ paperArmed: true }} />);
    expect(
      screen.getByTestId("activation-checklist-item-paper_run").getAttribute(
        "data-done",
      ),
    ).toBe("1");
  });

  it("treats starterChosen fact as done", () => {
    render(<ActivationChecklist facts={{ starterChosen: true }} />);
    expect(
      screen.getByTestId("activation-checklist-item-chose_starter").getAttribute(
        "data-done",
      ),
    ).toBe("1");
  });
});

describe("activation checklist — coach coexistence and resume", () => {
  it("renders nothing when suppressed for an active coach step", () => {
    render(<ActivationChecklist suppressed />);
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
  });

  it("offers Resume setup only while incomplete and a handler is provided", () => {
    const onResumeSetup = vi.fn();
    const { rerender } = render(
      <ActivationChecklist onResumeSetup={onResumeSetup} />,
    );
    fireEvent.click(screen.getByTestId("activation-checklist-resume"));
    expect(onResumeSetup).toHaveBeenCalledTimes(1);

    act(() => {
      writeActivationChecklistState(
        {
          starterChosen: true,
          paperRunStarted: true,
        },
        STORAGE,
      );
      markActivationPaperRunStarted();
    });
    rerender(<ActivationChecklist onResumeSetup={onResumeSetup} />);
    expect(screen.queryByTestId("activation-checklist-resume")).toBeNull();
  });
});

describe("activation checklist — compact copy stays lean", () => {
  it("names the three activation items without a lecture wall", () => {
    render(<ActivationChecklist />);
    const region = screen.getByRole("region", { name: /your next steps/i });
    expect(region.textContent).toMatch(/Installed locally/);
    expect(region.textContent).toMatch(/free paper strategy/i);
    expect(region.textContent).toMatch(/paper run/i);
    expect(region.textContent).not.toMatch(/Beginner|Power mode/i);
    expect((region.textContent ?? "").length).toBeLessThan(280);
  });
});
