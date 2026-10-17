import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RevisionCompare } from "./RevisionCompare";
import type { LibraryClient, OwnedDraftSummary, OwnedRevisionBytes } from "./libraryClient";

afterEach(cleanup);

const rows: OwnedDraftSummary[] = ["one", "two", "three"].map((id) => ({
  revision_id: id, strategy_id: "fixture", parent_revision_id: id === "two" ? "one" : null,
  state: "draft", runnable: false, created_at: "2026-10-16", id: "fixture",
  label: "Selection race fixture", pair: "SUIUSD", timeframe: "1h",
}));
const bytes = (id: string): OwnedRevisionBytes => ({
  revision_id: id, state: "draft", bytes: JSON.stringify({ label: id }),
});
function deferred() {
  let resolve!: (value: OwnedRevisionBytes) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<OwnedRevisionBytes>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup() {
  // Deferred transport is confined to source regression tests; runtime uses the real API.
  const pending = deferred();
  const getJson = vi.fn((id: string) => Promise.resolve(bytes(id)))
    .mockImplementationOnce(() => pending.promise);
  const client: LibraryClient = { listOwned: vi.fn(), getJson };
  const props = { client, rows, row: rows[1] };
  return { ...render(<RevisionCompare {...props} />), pending, getJson, props };
}
function change(side: string, value: string) {
  fireEvent.change(screen.getByTestId(`revision-compare-${side}`), { target: { value } });
}
function run() { fireEvent.click(screen.getByTestId("revision-compare-run")); }
function idle() {
  for (const name of ["loading", "error", "identical", "changes", "summary", "caption"]) {
    expect(screen.queryByTestId(`revision-compare-${name}`)).toBeNull();
  }
}

describe("selection invalidates comparison, not just its labels", () => {
  for (const side of ["left", "right"]) {
    for (const outcome of ["success", "failure"]) {
      it(`ignores delayed ${outcome} after ${side} selection changes without Compare`, async () => {
        const { pending, getJson } = setup();
        run();
        expect(screen.getByTestId("revision-compare-loading")).toBeDefined();
        change(side, "three");
        idle();
        await act(async () => {
          if (outcome === "success") pending.resolve(bytes("one"));
          else pending.reject(new Error("old failure"));
        });
        idle();
        expect(getJson).toHaveBeenCalledTimes(2);
        run();
        await act(async () => {});
        expect(getJson).toHaveBeenCalledTimes(4);
        const body = screen.getByTestId("revision-compare-changes").textContent;
        expect(body).toContain("three");
        expect(body).toContain(side === "left" ? "two" : "one");
      });
    }
    it(`clears an identical result on ${side} change`, async () => {
      const { pending } = setup();
      run();
      await act(async () => pending.resolve(bytes("two")));
      expect(screen.getByTestId("revision-compare-identical")).toBeDefined();
      change(side, "three");
      idle();
    });
    it(`keeps fresh results when an older failure arrives after ${side} change`, async () => {
      const { pending } = setup();
      run();
      change(side, "three");
      run();
      await act(async () => {});
      const fresh = screen.getByTestId("revision-compare-changes").textContent;
      expect(fresh).toContain("three");
      await act(async () => pending.reject(new Error("superseded failure")));
      expect(screen.getByTestId("revision-compare-changes").textContent).toBe(fresh);
      expect(screen.queryByTestId("revision-compare-error")).toBeNull();
    });
    it(`clears a completed comparison on ${side} change`, async () => {
      const { pending, getJson } = setup();
      run();
      await act(async () => pending.resolve(bytes("one")));
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined();
      change(side, "three");
      idle();
      expect(getJson).toHaveBeenCalledTimes(2);
    });
    it(`clears a completed error on ${side} change and disables empty selection`, async () => {
      const { pending } = setup();
      run();
      await act(async () => pending.reject(new Error("actual failure")));
      expect(screen.getByTestId("revision-compare-error").textContent).toContain("actual failure");
      change(side, "");
      idle();
      expect((screen.getByTestId("revision-compare-run") as HTMLButtonElement).disabled).toBe(true);
    });
  }
  it("invalidates a pending request when the client changes", async () => {
    const { pending, props, rerender } = setup();
    run();
    rerender(<RevisionCompare {...props} client={{ ...props.client }} />);
    await act(async () => pending.resolve(bytes("one")));
    idle();
  });
  it("isolates an unmounted comparison from a newly mounted one", async () => {
    const { pending, props, unmount } = setup();
    run();
    unmount();
    render(<RevisionCompare {...props} />);
    await act(async () => pending.reject(new Error("closed request")));
    idle();
  });
});
