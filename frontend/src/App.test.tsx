import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App shell", () => {
  it("renders the paper workstation heading", () => {
    render(<App />);
    expect(screen.getByText("Paper workstation")).toBeDefined();
  });

  it("renders the live-orders unavailable status", () => {
    render(<App />);
    expect(screen.getByText("Live orders unavailable")).toBeDefined();
  });
});
