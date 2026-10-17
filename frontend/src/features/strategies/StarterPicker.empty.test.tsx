import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Editor } from "./Editor";
import { fetchStarters } from "./StarterPicker.client";
import { StarterPicker } from "./StarterPicker";

afterEach(cleanup);

class VisibleIntersectionObserver {
  constructor(callback: IntersectionObserverCallback) {
    queueMicrotask(() => {
      callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      );
    });
  }
  observe(): void {}
  disconnect(): void {}
  unobserve(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

beforeAll(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    VisibleIntersectionObserver as unknown as typeof IntersectionObserver,
  );
});

afterAll(() => {
  vi.unstubAllGlobals();
});

const fetchStartersMock = vi.mocked(fetchStarters);

vi.mock("./StarterPicker.client", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("./StarterPicker.client")>();
  return {
    ...original,
    fetchStarters: vi.fn(),
  };
});

describe("StarterPicker empty and error states", () => {
  it("stays idle (loading state, no fetch) without IntersectionObserver", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    try {
      render(<StarterPicker onPick={() => {}} />);
      expect(screen.getByTestId("starter-picker-loading")).toBeDefined();
      expect(fetchStartersMock).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
      vi.stubGlobal(
        "IntersectionObserver",
        VisibleIntersectionObserver as unknown as typeof IntersectionObserver,
      );
    }
  });

  it("shows the explicit empty state when the catalogue ships no examples", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples: [],
    });
    render(<StarterPicker onPick={() => {}} />);
    expect(
      await screen.findByTestId("starter-picker-empty"),
    ).toBeDefined();
    expect(screen.getByText("No starter examples available")).toBeDefined();
    expect(screen.queryByRole("button", { name: /^Use / })).toBeNull();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
  });

  it("shows the explicit empty state for catalogue_version 0", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "0",
      examples: [
        {
          id: "starter-dual-ma-crossover",
          label: "Dual moving-average crossover",
          description: "Should not render for a version-0 catalogue.",
          pack: { id: "starter-dual-ma-crossover" },
        },
      ],
    });
    render(<StarterPicker onPick={() => {}} />);
    expect(
      await screen.findByTestId("starter-picker-empty"),
    ).toBeDefined();
    expect(screen.queryByText("Dual moving-average crossover")).toBeNull();
    expect(screen.queryByTestId("starter-picker-error")).toBeNull();
  });

  it("shows an explicit inline error when the fetch rejects", async () => {
    fetchStartersMock.mockRejectedValue(new Error("network down"));
    render(<StarterPicker onPick={() => {}} />);
    const alert = await screen.findByTestId("starter-picker-error");
    expect(alert.textContent).toContain("Could not load starter examples");
    expect(alert.textContent).toContain("network down");
    expect(screen.queryByTestId("starter-picker-empty")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Use / })).toBeNull();
  });

  it("shows an explicit inline error when the fetch fails with a non-2xx", async () => {
    fetchStartersMock.mockRejectedValue(
      new Error("starter catalogue unavailable: 500"),
    );
    render(<StarterPicker onPick={() => {}} />);
    const alert = await screen.findByTestId("starter-picker-error");
    expect(alert.textContent).toContain("starter catalogue unavailable: 500");
  });

  it("never renders mock rows when the real fetch fails", async () => {
    fetchStartersMock.mockRejectedValue(new Error("boom"));
    const onPick = vi.fn();
    render(<StarterPicker onPick={onPick} />);
    await screen.findByTestId("starter-picker-error");
    expect(screen.queryByTestId("starter-picker-item-starter-dual-ma-crossover")).toBeNull();
    expect(onPick).not.toHaveBeenCalled();
  });

  it("keeps the editor shell usable when the catalogue fails", async () => {
    fetchStartersMock.mockRejectedValue(new Error("network down"));
    render(<Editor client={makeClient()} />);
    await screen.findByTestId("starter-picker-error");
    expect(screen.getByLabelText(/raw json/i)).toBeDefined();
    expect(screen.getByRole("button", { name: "Save" })).toBeDefined();
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: JSON.stringify({ id: "x", label: "X" }, null, 2) },
    });
    expect((screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value).toContain(
      '"X"',
    );
  });
});

function makeClient() {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: {},
      errors: [],
      outcome: "created",
    }),
    edit: vi.fn(),
    validate: vi.fn(),
    arm: vi.fn(),
  };
}
