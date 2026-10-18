import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackLibrary, type PackLibraryClient, type PackRow } from "./PackLibrary";
import { PackLibraryHttpError } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeClient(overrides: Partial<PackLibraryClient> = {}): PackLibraryClient {
  return {
    listInstalled: vi.fn(async () => [] as PackRow[]),
    rollback: vi.fn(async () => ({ ok: true })),
    ...overrides,
  };
}

function row(pack_id: string, bucket: PackRow["bucket"]): PackRow {
  return { bucket, pack_id, version: "1.0.0", permissions: [], rollback_ref: null };
}

/** A listInstalled promise whose settlement the test controls. */
function deferred() {
  let resolve!: (rows: PackRow[]) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<PackRow[]>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

const refreshButton = () => screen.getByTestId("pack-library-refresh");
const statusRegion = () => screen.getByTestId("pack-library-refresh-status");
/** "true" while the read is in flight; absent or "false" once settled. */
const busy = () => refreshButton().getAttribute("aria-busy");

describe("PackLibrary refresh aria-busy and polite status", () => {
  it("marks the button busy and announces the in-flight read until it resolves", async () => {
    const pending = deferred();
    const listInstalled = vi.fn();
    listInstalled.mockResolvedValueOnce([row("alpha", "installed")]);
    listInstalled.mockImplementationOnce(() => pending.promise);
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-list");

    expect(busy()).not.toBe("true");
    expect(statusRegion().getAttribute("aria-live")).toBe("polite");
    expect(statusRegion().getAttribute("role")).toBe("status");
    expect(statusRegion().textContent).toBe("");

    fireEvent.click(refreshButton());
    expect(busy()).toBe("true");
    expect(refreshButton().textContent).toBe("Refreshing\u2026");
    expect(statusRegion().textContent).toBe("Reading installed packs\u2026");
    // The panel stays usable while the read is in flight.
    fireEvent.change(screen.getByTestId("pack-library-search"), {
      target: { value: "alpha" },
    });
    expect(screen.getByTestId("pack-library-count").textContent).toContain(
      "1 of 1 packs shown",
    );

    await act(async () => {
      pending.resolve([row("alpha", "installed"), row("bravo", "deployed")]);
    });
    await waitFor(() => {
      expect(busy()).not.toBe("true");
    });
    expect(refreshButton().textContent).toBe("Refresh");
    expect(statusRegion().textContent).toBe("");
    expect(listInstalled).toHaveBeenCalledTimes(2);
  });

  it("clears the affordance after a rejected read and keeps the refusal visible", async () => {
    const pending = deferred();
    const listInstalled = vi.fn();
    listInstalled.mockResolvedValueOnce([]);
    listInstalled.mockImplementationOnce(() => pending.promise);
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-empty");

    fireEvent.click(refreshButton());
    expect(busy()).toBe("true");
    expect(statusRegion().textContent).toBe("Reading installed packs\u2026");

    await act(async () => {
      pending.reject(new PackLibraryHttpError(403, "pack library failed: 403"));
    });
    await waitFor(() => {
      expect(busy()).not.toBe("true");
    });
    expect(refreshButton().textContent).toBe("Refresh");
    expect(statusRegion().textContent).toBe("");
    // The existing alert paragraph carries the existing failureMessage(err).
    expect(screen.getByTestId("pack-library-error").getAttribute("role")).toBe("alert");
    expect(screen.getByTestId("pack-library-error").textContent).toBe(
      "Pack library failed (HTTP 403)",
    );
  });

  it("stays busy while an earlier mount read settles stale; the refresh read wins", async () => {
    // A slow or hung loopback read is in flight when the operator clicks
    // Refresh: two listInstalled reads overlap and the later one must win.
    const mountRead = deferred();
    const refreshRead = deferred();
    const listInstalled = vi.fn();
    listInstalled.mockImplementationOnce(() => mountRead.promise);
    listInstalled.mockImplementationOnce(() => refreshRead.promise);
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    expect(screen.getByTestId("pack-library-loading")).toBeDefined();
    expect(busy()).not.toBe("true");

    fireEvent.click(refreshButton());
    expect(listInstalled).toHaveBeenCalledTimes(2);
    expect(busy()).toBe("true");
    expect(refreshButton().textContent).toBe("Refreshing\u2026");
    expect(statusRegion().textContent).toBe("Reading installed packs\u2026");

    // The earlier mount read settles stale: its rows never land and the
    // affordance keeps describing the read that is still in flight.
    await act(async () => {
      mountRead.resolve([row("alpha", "installed")]);
    });
    expect(busy()).toBe("true");
    expect(refreshButton().textContent).toBe("Refreshing\u2026");
    expect(statusRegion().textContent).toBe("Reading installed packs\u2026");
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
    expect(screen.getByTestId("pack-library-loading")).toBeDefined();

    await act(async () => {
      refreshRead.resolve([row("bravo", "deployed")]);
    });
    await waitFor(() => {
      expect(busy()).not.toBe("true");
    });
    expect(refreshButton().textContent).toBe("Refresh");
    expect(statusRegion().textContent).toBe("");
    expect(screen.getByTestId("pack-library-row-bravo")).toBeDefined();
    expect(screen.queryByTestId("pack-library-row-alpha")).toBeNull();
  });
});
