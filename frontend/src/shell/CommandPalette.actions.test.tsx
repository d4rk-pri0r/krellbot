/**
 * CommandPalette — real navigable actions (M7.3).
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Pins that the palette is not an empty stub: it lists view navigation
 * and paper arm/disarm entry points (Workstation only — live arming is
 * not offered), filters by query, runs on click / Enter, and remains
 * keyboard-openable from the shell via Ctrl/Meta+K.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPalette, PALETTE_ACTIONS } from "./CommandPalette";
import { WorkstationShell } from "./WorkstationShell";
import { clickShellNav } from "./navTestUtils";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CommandPalette — navigable actions (M7.3)", () => {
  it("lists view destinations and paper arm/disarm entry points when open", () => {
    render(<CommandPalette open onClose={() => {}} onNavigate={() => {}} />);

    const results = screen.getByTestId("command-palette-results");
    expect(results.getAttribute("role")).toBe("listbox");

    for (const action of PALETTE_ACTIONS) {
      expect(
        screen.getByTestId(`command-palette-action-${action.id}`),
      ).toBeDefined();
    }

    expect(screen.getByTestId("command-palette-action-view-workstation")).toBeDefined();
    expect(screen.getByTestId("command-palette-action-paper-arm").textContent).toMatch(
      /Start paper run/,
    );
    expect(
      screen.getByTestId("command-palette-action-paper-disarm").textContent,
    ).toMatch(/Stop paper run/);
    expect(
      screen.getByTestId("command-palette-action-paper-arm").getAttribute(
        "data-palette-kind",
      ),
    ).toBe("paper-entry");
  });

  it("filters actions by query and shows an empty state when nothing matches", () => {
    render(<CommandPalette open onClose={() => {}} onNavigate={() => {}} />);

    const input = screen.getByRole("textbox", { name: "Command input" });
    fireEvent.change(input, { target: { value: "operations" } });

    expect(screen.getByTestId("command-palette-action-view-operations")).toBeDefined();
    expect(screen.queryByTestId("command-palette-action-view-home")).toBeNull();
    expect(screen.queryByTestId("command-palette-action-paper-arm")).toBeNull();

    fireEvent.change(input, { target: { value: "zzzz-no-match" } });
    expect(screen.getByTestId("command-palette-empty").textContent).toBe(
      "No matching actions.",
    );
  });

  it("navigates and closes when an action is activated by click or Enter", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette open onClose={onClose} onNavigate={onNavigate} />,
    );

    fireEvent.click(screen.getByTestId("command-palette-action-view-research"));
    expect(onNavigate).toHaveBeenCalledWith("research");
    expect(onClose).toHaveBeenCalled();

    onNavigate.mockClear();
    onClose.mockClear();
    cleanup();
    render(
      <CommandPalette open onClose={onClose} onNavigate={onNavigate} />,
    );

    const input = screen.getByRole("textbox", { name: "Command input" });
    fireEvent.change(input, { target: { value: "arm paper" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("workstation");
    expect(onClose).toHaveBeenCalled();
  });

  it("moves the active option with ArrowDown / ArrowUp before Enter", () => {
    const onNavigate = vi.fn();
    render(
      <CommandPalette open onClose={() => {}} onNavigate={onNavigate} />,
    );

    const input = screen.getByRole("textbox", { name: "Command input" });
    fireEvent.change(input, { target: { value: "Go to" } });

    const first = screen.getByTestId("command-palette-action-view-home");
    expect(first.getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    const second = screen.getByTestId("command-palette-action-view-workstation");
    expect(second.getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("workstation");
  });
});

describe("CommandPalette — keyboard open from shell (M7.3)", () => {
  it("opens via Control+K with the action list populated", async () => {
    render(<WorkstationShell />);
    await waitFor(() =>
      expect(screen.getByTestId("kbot-shell").getAttribute("data-bootstrap-done")).toBe(
        "1",
      ),
    );

    expect(screen.queryByTestId("command-palette")).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    const dialog = screen.getByTestId("command-palette");
    expect(dialog).toBeDefined();
    expect(screen.getByTestId("command-palette-results")).toBeDefined();
    expect(screen.getByTestId("command-palette-action-view-home")).toBeDefined();
    expect(screen.getByTestId("command-palette-action-paper-disarm")).toBeDefined();
    expect(document.activeElement).toBe(
      screen.getByRole("textbox", { name: "Command input" }),
    );
  });

  it("selecting a view action from the shell palette changes the active view", async () => {
    render(<WorkstationShell />);
    await waitFor(() =>
      expect(screen.getByTestId("kbot-shell").getAttribute("data-bootstrap-done")).toBe(
        "1",
      ),
    );

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.click(screen.getByTestId("command-palette-action-view-operations"));

    expect(screen.queryByTestId("command-palette")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Operations" }).getAttribute("aria-current"),
    ).toBe("page");
  });
});
