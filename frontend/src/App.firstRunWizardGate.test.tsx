/**
 * App cold-open gate — WorkstationShell unmounted until wizard complete/skip
 * (M26.4). Behavior-named pins for the girlfriend-test bar.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { writeFirstRunCoachState } from "./features/onboarding/firstRunCoachPersistence";
import {
  FIRST_RUN_WIZARD_STORAGE_KEY,
  writeFirstRunWizardState,
} from "./features/onboarding/FirstRunWizard";

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

beforeEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  document.head.innerHTML = "";
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  document.head.innerHTML = "";
  vi.restoreAllMocks();
});

vi.mock("./session", () => ({
  redeemBootstrap: (): Promise<void> => Promise.resolve(),
  recoverCsrf: (): Promise<boolean> => Promise.resolve(true),
  getCsrf: (): string => "test-csrf",
}));

function expectShellAbsent(): void {
  expect(screen.queryByTestId("kbot-shell")).toBeNull();
  expect(screen.queryByTestId("kbot-shell-brand")).toBeNull();
  expect(screen.queryByTestId("kbot-nav")).toBeNull();
  expect(screen.queryByTestId("app-home")).toBeNull();
  expect(screen.queryByTestId("command-palette")).toBeNull();
  expect(screen.queryByRole("dialog", { name: "Jobs" })).toBeNull();
  expect(screen.queryByRole("button", { name: /jobs/i })).toBeNull();
  expect(screen.queryByTestId("app-home-advanced-stack")).toBeNull();
  expect(screen.queryByTestId("first-run-coach")).toBeNull();
  expect(screen.queryByTestId("first-run-coach-spotlight")).toBeNull();
  expect(screen.queryByTestId("activation-checklist")).toBeNull();
}

describe("App cold open mounts only FirstRunWizard until complete", () => {
  it("mounts FirstRunWizard alone and leaves WorkstationShell unmounted", () => {
    render(<App />);
    expect(screen.getByTestId("first-run-wizard")).toBeDefined();
    expect(
      screen.getByTestId("first-run-wizard").getAttribute("data-wizard-step"),
    ).toBe("welcome");
    expectShellAbsent();
  });

  it("does not open command palette or Jobs while the wizard is active", () => {
    render(<App />);
    expectShellAbsent();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    expect(screen.queryByTestId("command-palette")).toBeNull();
    expect(screen.queryByRole("dialog", { name: "Jobs" })).toBeNull();
  });
});

describe("App mounts WorkstationShell after wizard skip", () => {
  it("persists skip and mounts shell chrome without re-trapping", () => {
    const { unmount } = render(<App />);
    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    fireEvent.click(screen.getByTestId("first-run-wizard-skip"));

    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(screen.getByTestId("kbot-nav")).toBeDefined();
    expect(screen.getByTestId("app-home")).toBeDefined();
    expect(screen.getByTestId("kbot-shell-brand")).toBeDefined();
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.getByRole("button", { name: "Settings" })).toBeDefined();
    expect(screen.queryByTestId("app-home-path")).toBeNull();

    const raw = window.localStorage.getItem(FIRST_RUN_WIZARD_STORAGE_KEY);
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).status).toBe("skipped");

    unmount();
    render(<App />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
  });
});

describe("App mounts WorkstationShell after wizard complete", () => {
  it("Open Krellbot dismisses the wizard and mounts the shell", () => {
    writeFirstRunWizardState({
      status: "active",
      stepId: "win",
      selectedStarterId: "starter-sma-cross",
    });
    render(<App />);
    expect(screen.getByTestId("first-run-wizard")).toBeDefined();
    expectShellAbsent();

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(screen.getByTestId("app-home")).toBeDefined();

    const raw = window.localStorage.getItem(FIRST_RUN_WIZARD_STORAGE_KEY);
    expect(JSON.parse(raw!).status).toBe("completed");
  });
});

describe("App deep link stays behind incomplete wizard", () => {
  it("keeps WorkstationShell unmounted for ?view=studio until skip", () => {
    window.history.pushState({}, "", "/?view=studio");
    render(<App />);
    expect(screen.getByTestId("first-run-wizard")).toBeDefined();
    expectShellAbsent();
    expect(window.location.search).toContain("view=studio");

    fireEvent.click(screen.getByTestId("first-run-wizard-primary"));
    fireEvent.click(screen.getByTestId("first-run-wizard-skip"));

    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(window.location.search).toContain("view=studio");
  });
});

describe("App adopts a prior coach skip or complete without re-trap", () => {
  it("mounts the shell when the hotspot coach was already skipped", () => {
    writeFirstRunCoachState({ status: "skipped", stepId: "choose_starter" });
    render(<App />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
    expect(screen.getByRole("button", { name: "Settings" })).toBeDefined();
    expect(screen.queryByTestId("app-home-path")).toBeNull();
    const raw = window.localStorage.getItem(FIRST_RUN_WIZARD_STORAGE_KEY);
    expect(JSON.parse(raw!).status).toBe("skipped");
  });

  it("mounts the shell when the hotspot coach was already completed", () => {
    writeFirstRunCoachState({ status: "completed", stepId: "win" });
    render(<App />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("app-home")).toBeDefined();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(
      JSON.parse(window.localStorage.getItem(FIRST_RUN_WIZARD_STORAGE_KEY)!).status,
    ).toBe("completed");
  });

  it("still shows the wizard when coach setup was left active", () => {
    writeFirstRunCoachState({ status: "active", stepId: "arm_paper" });
    render(<App />);
    expect(screen.getByTestId("first-run-wizard")).toBeDefined();
    expectShellAbsent();
  });
});

describe("App never re-traps after completed wizard", () => {
  it("mounts WorkstationShell when persistence already completed", () => {
    writeFirstRunWizardState({
      status: "completed",
      stepId: "win",
      selectedStarterId: null,
    });
    render(<App />);
    expect(screen.queryByTestId("first-run-wizard")).toBeNull();
    expect(screen.getByTestId("kbot-shell")).toBeDefined();
  });
});
