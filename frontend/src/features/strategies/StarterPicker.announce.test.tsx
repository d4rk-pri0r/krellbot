import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StarterPicker } from "./StarterPicker";
import type { StarterCatalogue } from "./StarterPicker.client";

// jsdom has no viewport: control only visibility and loader completion here.
class ControlledObserver {
  static instances: ControlledObserver[] = [];
  constructor(private callback: IntersectionObserverCallback) {
    ControlledObserver.instances.push(this);
  }
  observe(): void {}
  disconnect = vi.fn();
  intersect(isIntersecting: boolean): void {
    this.callback(
      [{ isIntersecting } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
}

function intersect(isIntersecting = true): void {
  act(() => ControlledObserver.instances.at(-1)!.intersect(isIntersecting));
}

function expectSilent(): void {
  expect(screen.queryByTestId("starter-picker-error")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(document.querySelector("[aria-live]")).toBeNull();
}

const loaded: StarterCatalogue = {
  schema_version: "1",
  catalogue_version: "1",
  examples: [{
    id: "example", label: "Example", description: "Educational example",
    pack: { id: "example" },
  }],
};

beforeEach(() => {
  ControlledObserver.instances = [];
  vi.stubGlobal("IntersectionObserver", ControlledObserver);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("starter failure announcements", () => {
  it.each([
    "Failed to fetch", "starter catalogue unavailable: 404",
    "starter catalogue unavailable: 503", "unexpected exception",
  ])("announces the unchanged error paragraph and cause: %s", async (message) => {
    render(<StarterPicker onPick={() => {}} loadStarters={() => Promise.reject(new Error(message))} />);
    intersect();
    const error = await screen.findByTestId("starter-picker-error");
    expect(error.tagName).toBe("P");
    expect(error.textContent).toBe(`Could not load starter examples: ${message}`);
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.getAttribute("aria-live")).toBe("polite");
    expect(screen.getAllByRole("alert")).toEqual([error]);
  });

  it.each<[string, StarterCatalogue, string]>([
    ["success", loaded, "starter-picker-item-example"],
    ["empty", { ...loaded, examples: [] }, "starter-picker-empty"],
    ["version zero", { ...loaded, catalogue_version: "0" }, "starter-picker-empty"],
  ])("clears the announcement on a subsequent %s load", async (_name, catalogue, testId) => {
    const { rerender } = render(<StarterPicker onPick={() => {}} loadStarters={() => Promise.reject(new Error("offline"))} />);
    intersect();
    const error = await screen.findByTestId("starter-picker-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.getAttribute("aria-live")).toBe("polite");
    rerender(<StarterPicker onPick={() => {}} loadStarters={() => Promise.resolve(catalogue)} />);
    intersect();
    await screen.findByTestId(testId);
    expectSilent();
  });

  it("is silent before intersection, in flight, and after a successful initial load", async () => {
    let resolve!: (catalogue: StarterCatalogue) => void;
    const load = vi.fn(() => new Promise<StarterCatalogue>((done) => { resolve = done; }));
    render(<StarterPicker onPick={() => {}} loadStarters={load} />);
    intersect(false);
    expect(load).not.toHaveBeenCalled();
    expectSilent();
    intersect();
    expect(load).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
    expectSilent();
    await act(async () => resolve(loaded));
    expect(screen.getByTestId("starter-picker-item-example")).toBeDefined();
    expectSilent();
  });

  it("does not retain an old announcement when reopened idle after failure", async () => {
    const first = render(<StarterPicker onPick={() => {}} loadStarters={() => Promise.reject(new Error("offline"))} />);
    intersect();
    await screen.findByTestId("starter-picker-error");
    first.unmount();
    const load = vi.fn(() => Promise.resolve(loaded));
    render(<StarterPicker onPick={() => {}} loadStarters={load} />);
    expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
    expect(load).not.toHaveBeenCalled();
    expectSilent();
  });
});
