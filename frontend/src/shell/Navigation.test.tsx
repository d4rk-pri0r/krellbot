import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Navigation } from "./Navigation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Navigation — workstation views", () => {
  it("renders the Home tab first alongside the five core nav tabs", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    const labels = Array.from(
      nav.querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
    ).map((button) => button.textContent?.trim());
    expect(labels[0]).toBe("Home");
    for (const label of [
      "Home",
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("marks Home with aria-current when active and clears the others", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    expect(
      screen.getByRole("button", { name: "Home" }).getAttribute("aria-current"),
    ).toBe("page");
    for (const label of [
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ]) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute("aria-current"),
      ).toBeNull();
    }
  });

  it("reports the Home selection through onChange", () => {
    const onChange = vi.fn();
    render(<Navigation active="workstation" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    expect(onChange).toHaveBeenCalledWith("home");
  });

  it("renders the five core nav tabs with their labels", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    for (const label of [
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("renders the Deploy nav tab so users can reach the live preflight dry-run", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Deploy" })).toBeDefined();
  });

  it("marks only the active tab with aria-current", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    const activeButton = screen.getByRole("button", {
      name: "Workstation",
    });
    expect(activeButton.getAttribute("aria-current")).toBe("page");
    const otherLabels = [
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ];
    for (const label of otherLabels) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute("aria-current"),
      ).toBeNull();
    }
  });
});
