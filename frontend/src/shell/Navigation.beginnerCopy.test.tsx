/**
 * Pins shell honesty strings for the beginner vocabulary pass (M24.5):
 * Live trading unavailable stays visible in the nav note.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Navigation } from "./Navigation";

afterEach(() => {
  cleanup();
});

describe("Navigation beginner copy honesty", () => {
  it("keeps Live trading unavailable in the local-preview note", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    expect(screen.getByText("Live trading unavailable")).toBeDefined();
  });
});
