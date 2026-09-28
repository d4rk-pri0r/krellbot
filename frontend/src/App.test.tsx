import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";

afterEach(cleanup);

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

describe("App status strip", () => {
  it("exposes the Paper mode badge inside the status strip", () => {
    render(<App />);
    const strip = screen.getByRole("region", { name: /status/i });
    expect(strip.textContent).toMatch(/Paper/);
  });

  it("exposes the live-orders sentence inside the status strip", () => {
    render(<App />);
    const strip = screen.getByRole("region", { name: /status/i });
    expect(strip.textContent).toMatch(/Live orders unavailable/);
  });
});

describe("App navigation", () => {
  it("renders in-app controls for Workstation, Strategies, and Research", () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: /workstation navigation/i });
    expect(nav.querySelector("a")).toBeNull();
    const buttons = nav.querySelectorAll("button");
    const labels = Array.from(buttons).map((b) => b.textContent?.trim());
    expect(labels).toEqual(
      expect.arrayContaining(["Workstation", "Strategies", "Research"]),
    );
  });
});

describe("App inspector", () => {
  it("renders an inspector region whose empty state reads 'Nothing selected'", () => {
    render(<App />);
    const inspector = screen.getByRole("region", { name: "Inspector" });
    expect(inspector.textContent).toMatch(/Nothing selected/);
  });
});

describe("App jobs drawer", () => {
  it("opens a drawer labelled 'Jobs' with the 'No jobs' empty state", () => {
    render(<App />);
    expect(screen.queryByRole("dialog", { name: "Jobs" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
    const drawer = screen.getByRole("dialog", { name: "Jobs" });
    expect(drawer.textContent).toMatch(/No jobs/);
  });
});

describe("App command palette", () => {
  it("opens on Control+K, focuses its input, and does not submit a command", () => {
    render(<App />);
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    const input = dialog.querySelector("input");
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("opens on Meta+K and focuses its input", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    const input = dialog.querySelector("input");
    expect(document.activeElement).toBe(input);
  });

  it("closes on Escape and returns focus to the previously focused element", () => {
    render(<App />);
    const trigger = screen.getByRole("button", { name: /jobs/i });
    trigger.focus();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen
      .getByRole("dialog", { name: /command palette/i })
      .querySelector("input");
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input as HTMLInputElement, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("App view routing", () => {
  it("starts on Workstation and renders the inspector", () => {
    render(<App />);
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(
      screen.getByRole("region", { name: "Inspector" }),
    ).toBeDefined();
  });

  it("does not render the strategy editor before Strategies is selected", () => {
    render(<App />);
    expect(
      screen.queryByRole("region", { name: /strategy editor/i }),
    ).toBeNull();
  });

  it("choosing Strategies shows the strategy editor and hides the workstation heading", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    const editor = screen.getByRole("region", { name: /strategy editor/i });
    expect(editor).toBeDefined();
    expect(editor.textContent).toMatch(/Label/);
    expect(editor.textContent).toMatch(/Raw JSON/);
    expect(screen.queryByText("Paper workstation")).toBeNull();
    expect(screen.queryByRole("region", { name: "Inspector" })).toBeNull();
  });

  it("choosing Workstation after Strategies shows the paper workstation again", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(
      screen.getByRole("region", { name: /strategy editor/i }),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(
      screen.queryByRole("region", { name: /strategy editor/i }),
    ).toBeNull();
  });
});
