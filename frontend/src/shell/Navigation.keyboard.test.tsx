/**
 * Navigation — roving-tabindex keyboard behavior for the view tab strip.
 *
 * A keyboard-only user Tab-stops onto the row once (the active tab is the
 * only tabbable button) and then moves between views with ArrowLeft /
 * ArrowRight (clamped at the ends, no wrapping) and Home / End. Each of
 * those keys drives the exact same onChange(view.id) path a click uses,
 * and focus follows the newly active button.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Navigation, type View } from "./Navigation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function tab(label: string): HTMLElement {
  return screen.getByRole("button", { name: label });
}

function focusedLabel(): string | null {
  const element = document.activeElement;
  return element ? element.textContent?.trim() ?? null : null;
}

function tabIndexes(): number[] {
  const nav = screen.getByTestId("kbot-nav");
  return Array.from(
    nav.querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
  ).map((button) => button.tabIndex);
}

describe("Navigation — roving tabindex", () => {
  it("keeps only the active tab in the tab order", () => {
    const { rerender } = render(<Navigation active="home" onChange={() => {}} />);
    expect(tabIndexes()).toEqual([0, -1, -1, -1, -1, -1, -1]);
    rerender(<Navigation active="deployments" onChange={() => {}} />);
    expect(tabIndexes()).toEqual([-1, -1, -1, -1, -1, -1, 0]);
  });
});

describe("Navigation — arrow key navigation", () => {
  it("moves focus and activates the next view on ArrowRight", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="home" onChange={onChange} />,
    );
    tab("Home").focus();
    fireEvent.keyDown(tab("Home"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("workstation");
    rerender(<Navigation active="workstation" onChange={onChange} />);
    expect(focusedLabel()).toBe("Workstation");

    fireEvent.keyDown(tab("Workstation"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("strategies");
    rerender(<Navigation active="strategies" onChange={onChange} />);
    expect(focusedLabel()).toBe("Strategies");
  });

  it("moves focus and activates the previous view on ArrowLeft", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="research" onChange={onChange} />,
    );
    tab("Research").focus();
    fireEvent.keyDown(tab("Research"), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenCalledWith("strategies");
    rerender(<Navigation active="strategies" onChange={onChange} />);
    expect(focusedLabel()).toBe("Strategies");
  });

  it("clamps instead of wrapping at the row ends", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="home" onChange={onChange} />,
    );
    tab("Home").focus();
    fireEvent.keyDown(tab("Home"), { key: "ArrowLeft" });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("Home");
    rerender(<Navigation active="deployments" onChange={onChange} />);
    tab("Deploy").focus();
    fireEvent.keyDown(tab("Deploy"), { key: "ArrowRight" });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("Deploy");
  });

  it("focuses the first view on Home and the last view on End", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="research" onChange={onChange} />,
    );
    tab("Research").focus();
    fireEvent.keyDown(tab("Research"), { key: "End" });
    expect(onChange).toHaveBeenCalledWith("deployments");
    rerender(<Navigation active="deployments" onChange={onChange} />);
    expect(focusedLabel()).toBe("Deploy");

    fireEvent.keyDown(tab("Deploy"), { key: "Home" });
    expect(onChange).toHaveBeenCalledWith("home");
    rerender(<Navigation active="home" onChange={onChange} />);
    expect(focusedLabel()).toBe("Home");
  });

  it("steps from Home to Research with three ArrowRight presses", () => {
    const onChange = vi.fn();
    let active: View = "home";
    const controller = (next: View): void => {
      onChange(next);
      active = next;
    };
    const { rerender } = render(
      <Navigation active={active} onChange={controller} />,
    );
    tab("Home").focus();
    for (const step of ["Workstation", "Strategies", "Research"]) {
      fireEvent.keyDown(tab(focusedLabel() as string), { key: "ArrowRight" });
      rerender(<Navigation active={active} onChange={controller} />);
      expect(focusedLabel()).toBe(step);
    }
    expect(onChange).toHaveBeenLastCalledWith("research");
    fireEvent.keyDown(tab("Research"), { key: "Home" });
    rerender(<Navigation active={active} onChange={controller} />);
    expect(onChange).toHaveBeenLastCalledWith("home");
    expect(focusedLabel()).toBe("Home");
    fireEvent.keyDown(tab("Home"), { key: "End" });
    rerender(<Navigation active={active} onChange={controller} />);
    expect(onChange).toHaveBeenLastCalledWith("deployments");
    expect(focusedLabel()).toBe("Deploy");
  });

  it("leaves untouched keys to the native button behavior", () => {
    const onChange = vi.fn();
    render(<Navigation active="home" onChange={onChange} />);
    const home = tab("Home");
    home.focus();
    fireEvent.keyDown(home, { key: "ArrowUp" });
    fireEvent.keyDown(home, { key: "PageDown" });
    fireEvent.keyDown(home, { key: "Enter", shiftKey: true });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("Home");
  });
});
