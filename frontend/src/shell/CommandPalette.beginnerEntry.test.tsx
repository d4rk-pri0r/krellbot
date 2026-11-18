/**
 * Command palette beginner entry (M24.6): Start free paper strategy is first.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPalette, PALETTE_ACTIONS } from "./CommandPalette";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CommandPalette — Start free paper strategy first", () => {
  it("lists Start free paper strategy as the first palette action", () => {
    expect(PALETTE_ACTIONS[0]?.id).toBe("start-free-paper-strategy");
    expect(PALETTE_ACTIONS[0]?.label).toBe("Start free paper strategy");
    render(<CommandPalette open onClose={() => {}} onNavigate={() => {}} />);
    const results = screen.getByTestId("command-palette-results");
    const first = results.querySelector(
      '[data-testid^="command-palette-action-"]',
    );
    expect(first?.getAttribute("data-testid")).toBe(
      "command-palette-action-start-free-paper-strategy",
    );
    expect(first?.textContent).toMatch(/Start free paper strategy/);
  });

  it("navigates home (chooser entry) when Start free paper strategy runs", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette open onClose={onClose} onNavigate={onNavigate} />,
    );
    fireEvent.click(
      screen.getByTestId("command-palette-action-start-free-paper-strategy"),
    );
    expect(onNavigate).toHaveBeenCalledWith("home");
    expect(onClose).toHaveBeenCalled();
  });
});
