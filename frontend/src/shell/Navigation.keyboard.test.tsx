/**
 * Navigation — roving-tabindex keyboard behavior for the tiered strip.
 *
 * Tab lands on the active view once; ArrowLeft/ArrowRight move across
 * primary tabs, the More toggle, and (when expanded) More destinations.
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

function viewTabIndexes(): number[] {
  const nav = screen.getByTestId("kbot-nav");
  return Array.from(
    nav.querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
  ).map((button) => button.tabIndex);
}

describe("Navigation — roving tabindex", () => {
  it("keeps only the active view button in the tab order among view items", () => {
    const { rerender } = render(<Navigation active="home" onChange={() => {}} />);
    // More destinations stay mounted while collapsed (`hidden`), so nine
    // view buttons remain in the tree; only the active page is tabbable.
    expect(viewTabIndexes()).toEqual([0, -1, -1, -1, -1, -1, -1, -1, -1]);
    rerender(<Navigation active="deployments" onChange={() => {}} />);
    expect(viewTabIndexes()).toEqual([-1, -1, -1, -1, -1, -1, -1, -1, 0]);
  });
});

describe("Navigation — arrow key navigation", () => {
  it("moves focus and activates the next primary view on ArrowRight", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="home" onChange={onChange} />,
    );
    tab("Workspace").focus();
    fireEvent.keyDown(tab("Workspace"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("workstation");
    rerender(<Navigation active="workstation" onChange={onChange} />);
    expect(focusedLabel()).toBe("Run");

    fireEvent.keyDown(tab("Run"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("strategies");
    rerender(<Navigation active="strategies" onChange={onChange} />);
    expect(focusedLabel()).toBe("Strategies");
  });

  it("opens More from the last primary tab and continues into Research", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="settings" onChange={onChange} />,
    );
    tab("Settings").focus();
    fireEvent.keyDown(tab("Settings"), { key: "ArrowRight" });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("More");
    rerender(<Navigation active="settings" onChange={onChange} />);
    fireEvent.keyDown(tab("More"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("research");
    rerender(<Navigation active="research" onChange={onChange} />);
    expect(focusedLabel()).toBe("Research");
  });

  it("moves focus and activates the previous view on ArrowLeft", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="research" onChange={onChange} />,
    );
    tab("Research").focus();
    fireEvent.keyDown(tab("Research"), { key: "ArrowLeft" });
    // Left of Research is the More toggle (not a view change).
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("More");
    fireEvent.keyDown(tab("More"), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenCalledWith("settings");
    rerender(<Navigation active="settings" onChange={onChange} />);
    expect(focusedLabel()).toBe("Settings");
  });

  it("clamps instead of wrapping at the row ends", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="home" onChange={onChange} />,
    );
    tab("Workspace").focus();
    fireEvent.keyDown(tab("Workspace"), { key: "ArrowLeft" });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("Workspace");
    rerender(<Navigation active="deployments" onChange={onChange} />);
    tab("Deploy").focus();
    fireEvent.keyDown(tab("Deploy"), { key: "ArrowRight" });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("Deploy");
  });

  it("focuses the first view on Home and the last More destination on End", () => {
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
    expect(focusedLabel()).toBe("Workspace");
  });

  it("steps from Workspace through primary tabs into Research", () => {
    const onChange = vi.fn();
    let active: View = "home";
    const controller = (next: View): void => {
      onChange(next);
      active = next;
    };
    const { rerender } = render(
      <Navigation active={active} onChange={controller} />,
    );
    tab("Workspace").focus();
    for (const step of ["Run", "Strategies", "Packs", "Settings"]) {
      fireEvent.keyDown(tab(focusedLabel() as string), { key: "ArrowRight" });
      rerender(<Navigation active={active} onChange={controller} />);
      expect(focusedLabel()).toBe(step);
    }
    fireEvent.keyDown(tab("Settings"), { key: "ArrowRight" });
    rerender(<Navigation active={active} onChange={controller} />);
    expect(focusedLabel()).toBe("More");
    fireEvent.keyDown(tab("More"), { key: "ArrowRight" });
    rerender(<Navigation active={active} onChange={controller} />);
    expect(focusedLabel()).toBe("Research");
    expect(onChange).toHaveBeenLastCalledWith("research");
  });

  it("leaves untouched keys to the native button behavior", () => {
    const onChange = vi.fn();
    render(<Navigation active="home" onChange={onChange} />);
    const home = tab("Workspace");
    home.focus();
    fireEvent.keyDown(home, { key: "ArrowUp" });
    fireEvent.keyDown(home, { key: "PageDown" });
    fireEvent.keyDown(home, { key: "Enter", shiftKey: true });
    expect(onChange).not.toHaveBeenCalled();
    expect(focusedLabel()).toBe("Workspace");
  });
});
