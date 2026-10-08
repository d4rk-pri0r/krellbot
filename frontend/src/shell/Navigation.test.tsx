import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Navigation } from "./Navigation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Navigation — workstation views", () => {
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
