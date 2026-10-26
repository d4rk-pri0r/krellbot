import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
  type OwnedRevisionBytes,
} from "./SavedStrategyLibrary";

afterEach(cleanup);

/**
 * Compare-target ownership regressions for the ordinary SavedStrategyLibrary
 * flow: click Compare on one row's child, then click Compare on a different
 * row's child without closing the panel. The newly selected row must own the
 * surface — its parent/child (or parentless) defaults replace the old row's
 * picks, the old row's results/error/loading are discarded, and a still-pending
 * comparison of the old row can no longer surface after the switch. The row
 * switch itself never fetches: only an explicit Compare revisions click reads.
 *
 * Only the authenticated read boundary (LibraryClient) is faked with
 * deterministic deferred reads; the real mounted library, keyboard handler and
 * RevisionCompare surface all run.
 */

const rows: OwnedDraftSummary[] = [
  {
    revision_id: "rev-a2",
    strategy_id: "alpha",
    parent_revision_id: "rev-a1",
    state: "draft",
    runnable: false,
    created_at: "2026-10-26T10:00:00Z",
    id: "alpha",
    label: "Alpha edited",
    pair: "SUIUSD",
    timeframe: "1h",
  },
  {
    revision_id: "rev-a1",
    strategy_id: "alpha",
    parent_revision_id: null,
    state: "validated",
    runnable: true,
    created_at: "2026-10-26T09:00:00Z",
    id: "alpha",
    label: "Alpha base",
    pair: "SUIUSD",
    timeframe: "1h",
  },
  {
    revision_id: "rev-b2",
    strategy_id: "bravo",
    parent_revision_id: "rev-b1",
    state: "draft",
    runnable: false,
    created_at: "2026-10-26T12:00:00Z",
    id: "bravo",
    label: "Bravo edited",
    pair: "ETHUSD",
    timeframe: "4h",
  },
  {
    revision_id: "rev-b1",
    strategy_id: "bravo",
    parent_revision_id: null,
    state: "draft",
    runnable: false,
    created_at: "2026-10-26T11:00:00Z",
    id: "bravo",
    label: "Bravo base",
    pair: "ETHUSD",
    timeframe: "4h",
  },
  {
    revision_id: "rev-solo",
    strategy_id: "solo",
    parent_revision_id: null,
    state: "draft",
    runnable: false,
    created_at: "2026-10-26T13:00:00Z",
    id: "solo",
    label: "Solo parentless",
    pair: "SUIUSD",
    timeframe: "1h",
  },
  {
    revision_id: "rev-orphan",
    strategy_id: "orphan",
    parent_revision_id: "rev-gone",
    state: "draft",
    runnable: false,
    created_at: "2026-10-26T14:00:00Z",
    id: "orphan",
    label: "Orphan parentless",
    pair: "SUIUSD",
    timeframe: "1h",
  },
];

type ReadGate = {
  promise: Promise<OwnedRevisionBytes>;
  resolve: (value: OwnedRevisionBytes) => void;
  reject: (reason: Error) => void;
};

function deferredRead(): ReadGate {
  let resolve!: (value: OwnedRevisionBytes) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<OwnedRevisionBytes>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

/** Every client.getJson call hands back its own deferred gate, recorded in
 * order, so a test can settle exactly the read it wants. */
function gatedClient(): {
  client: LibraryClient;
  getJson: ReturnType<typeof vi.fn>;
  reads: ReadGate[];
} {
  const reads: ReadGate[] = [];
  const getJson = vi.fn((): Promise<OwnedRevisionBytes> => {
    const gate = deferredRead();
    reads.push(gate);
    return gate.promise;
  });
  const client: LibraryClient = {
    listOwned: vi.fn().mockResolvedValue(rows),
    getJson,
  };
  return { client, getJson, reads };
}

/** The actual stored bytes for a revision: any two ids differ, so a completed
 * comparison of two distinct revisions always lists a real difference. */
function storedBytes(revisionId: string): string {
  return JSON.stringify({ id: "compare-target", revision: revisionId });
}

function settleRead(gate: ReadGate, revisionId: string): void {
  gate.resolve({
    revision_id: revisionId,
    state: "draft",
    bytes: storedBytes(revisionId),
  });
}

async function mountLibrary(client: LibraryClient) {
  const view = render(
    <SavedStrategyLibrary client={client} onReopen={vi.fn()} />,
  );
  await screen.findAllByTestId("library-row");
  return view;
}

function compareButtonFor(revisionId: string): HTMLButtonElement {
  const row = screen
    .getAllByTestId("library-row")
    .find((element) => element.getAttribute("data-revision-id") === revisionId);
  if (!row) {
    throw new Error(`no library row rendered for ${revisionId}`);
  }
  return within(row).getByTestId<HTMLButtonElement>("library-row-compare");
}

function openCompare(revisionId: string): void {
  fireEvent.click(compareButtonFor(revisionId));
}

function picks(): { left: string; right: string } {
  return {
    left: (screen.getByTestId("revision-compare-left") as HTMLSelectElement)
      .value,
    right: (screen.getByTestId("revision-compare-right") as HTMLSelectElement)
      .value,
  };
}

function runCompare(): void {
  fireEvent.click(screen.getByTestId("revision-compare-run"));
}

/** The surface is back to its untouched state: no old loading, error or diff. */
function expectIdleSurface(): void {
  for (const name of [
    "loading",
    "error",
    "identical",
    "changes",
    "summary",
    "caption",
    "scroll",
  ]) {
    expect(screen.queryByTestId(`revision-compare-${name}`)).toBeNull();
  }
}

async function runAndSettle(reads: ReadGate[], left: string, right: string) {
  runCompare();
  const start = reads.length - 2;
  await act(async () => {
    settleRead(reads[start], left);
    settleRead(reads[start + 1], right);
  });
  expect(screen.getByTestId("revision-compare-changes")).toBeDefined();
}

describe("SavedStrategyLibrary — a different row owns the compare target", () => {
  it("replaces a child row's parent/child defaults with the newly clicked row's", async () => {
    const { client } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    expect(picks()).toEqual({ left: "rev-a1", right: "rev-a2" });
    openCompare("rev-b2");
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
    expect(
      (screen.getByTestId("revision-compare-run") as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("replaces parentless defaults with the newly clicked row's own", async () => {
    const { client } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a1");
    expect(picks()).toEqual({ left: "rev-a1", right: "" });
    openCompare("rev-solo");
    expect(picks()).toEqual({ left: "rev-solo", right: "" });
    openCompare("rev-orphan");
    expect(picks()).toEqual({ left: "rev-orphan", right: "" });
    expect(
      (screen.getByTestId("revision-compare-run") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("discards a completed comparison when another row takes the surface", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    await runAndSettle(reads, "rev-a1", "rev-a2");
    expect(screen.getByTestId("revision-compare-summary").textContent).toContain(
      "rev-a1",
    );
    openCompare("rev-b2");
    expectIdleSurface();
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
    expect(client.getJson).toHaveBeenCalledTimes(2);
  });
});

describe("SavedStrategyLibrary — pending old-row reads cannot surface after the switch", () => {
  it("drops a pending success, then serves B's explicit compare with B's own ids", async () => {
    const { client, getJson, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    runCompare();
    expect(screen.getByTestId("revision-compare-loading")).toBeDefined();
    openCompare("rev-b2");
    expectIdleSurface();
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
    // The row switch itself must not fetch, re-list or compare anything.
    expect(getJson).toHaveBeenCalledTimes(2);
    expect(client.listOwned).toHaveBeenCalledTimes(1);
    await act(async () => {
      settleRead(reads[0], "rev-a1");
      settleRead(reads[1], "rev-a2");
    });
    expectIdleSurface();
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
    await runAndSettle(reads, "rev-b1", "rev-b2");
    const calls = getJson.mock.calls.map((call) => call[0]);
    expect(calls).toEqual(["rev-a1", "rev-a2", "rev-b1", "rev-b2"]);
    expect(screen.getByTestId("revision-compare-summary").textContent).toContain(
      "rev-b1",
    );
  });

  it("drops a pending refused read (getJson rejection) after the switch", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    runCompare();
    openCompare("rev-b2");
    await act(async () => {
      reads[0].reject(new Error("library open failed: 503"));
    });
    expectIdleSurface();
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
    await runAndSettle(reads, "rev-b1", "rev-b2");
  });

  it("drops a pending malformed-JSON read after the switch", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    runCompare();
    openCompare("rev-b2");
    await act(async () => {
      reads[0].resolve({
        revision_id: "rev-a1",
        state: "draft",
        bytes: "{not json",
      });
      settleRead(reads[1], "rev-a2");
    });
    expectIdleSurface();
    expect(screen.getByTestId("revision-compare").textContent).not.toContain(
      "not readable JSON",
    );
    await runAndSettle(reads, "rev-b1", "rev-b2");
  });

  it("keeps B's completed comparison when A's late outcomes settle", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    runCompare();
    openCompare("rev-b2");
    await runAndSettle(reads, "rev-b1", "rev-b2");
    const before = screen.getByTestId("revision-compare-changes").textContent;
    await act(async () => {
      settleRead(reads[0], "rev-a1");
      reads[1].reject(new Error("library open failed: 500"));
    });
    expect(screen.getByTestId("revision-compare-changes").textContent).toBe(
      before,
    );
    expect(screen.queryByTestId("revision-compare-error")).toBeNull();
    expect(screen.queryByTestId("revision-compare-loading")).toBeNull();
  });
});

describe("SavedStrategyLibrary — same-row and unrelated renders keep the user's comparison", () => {
  it("keeps manual selections, results and repeat reads on a same-row Compare click", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    fireEvent.change(screen.getByTestId("revision-compare-left"), {
      target: { value: "rev-b1" },
    });
    await runAndSettle(reads, "rev-b1", "rev-a2");
    const before = screen.getByTestId("revision-compare-changes").textContent;
    openCompare("rev-a2");
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-a2" });
    expect(screen.getByTestId("revision-compare-changes").textContent).toBe(
      before,
    );
    await runAndSettle(reads, "rev-b1", "rev-a2");
    expect(client.getJson).toHaveBeenCalledTimes(4);
  });

  it("keeps manual selections and results across an unrelated rerender", async () => {
    const { client, reads } = gatedClient();
    const view = await mountLibrary(client);
    openCompare("rev-a2");
    fireEvent.change(screen.getByTestId("revision-compare-left"), {
      target: { value: "rev-b1" },
    });
    await runAndSettle(reads, "rev-b1", "rev-a2");
    const before = screen.getByTestId("revision-compare-changes").textContent;
    view.rerender(
      <SavedStrategyLibrary client={client} onReopen={vi.fn()} />,
    );
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-a2" });
    expect(screen.getByTestId("revision-compare-changes").textContent).toBe(
      before,
    );
  });
});

describe("SavedStrategyLibrary — close, reopen and unmount reown the surface", () => {
  it("reopens after Close with the new row's defaults and no old results", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-a2");
    await runAndSettle(reads, "rev-a1", "rev-a2");
    fireEvent.click(screen.getByTestId("revision-compare-close"));
    expect(screen.queryByTestId("revision-compare")).toBeNull();
    openCompare("rev-b2");
    expectIdleSurface();
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
  });

  it("drops pending reads when the library unmounts", async () => {
    const { client, getJson, reads } = gatedClient();
    const view = await mountLibrary(client);
    openCompare("rev-b2");
    runCompare();
    expect(getJson).toHaveBeenCalledTimes(2);
    view.unmount();
    await act(async () => {
      settleRead(reads[0], "rev-b1");
      reads[1].reject(new Error("library open failed: 503"));
    });
    expect(view.container.innerHTML).toBe("");
    expect(getJson).toHaveBeenCalledTimes(2);
  });
});

describe("SavedStrategyLibrary — keyboard Compare switch and honest current errors", () => {
  it("reowns defaults when Control+Alt+C opens a different row", async () => {
    const { client } = gatedClient();
    await mountLibrary(client);
    const first = compareButtonFor("rev-a2");
    first.focus();
    fireEvent.keyDown(first, { key: "c", ctrlKey: true, altKey: true });
    expect(screen.getByTestId("revision-compare")).toBeDefined();
    expect(picks()).toEqual({ left: "rev-a1", right: "rev-a2" });
    const second = compareButtonFor("rev-b2");
    second.focus();
    fireEvent.keyDown(second, { key: "c", ctrlKey: true, altKey: true });
    expectIdleSurface();
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
  });

  it("still surfaces the current row's own refusal and retries honestly", async () => {
    const { client, reads } = gatedClient();
    await mountLibrary(client);
    openCompare("rev-b2");
    runCompare();
    await act(async () => {
      reads[0].reject(new Error("library open failed: 404"));
    });
    expect(screen.getByTestId("revision-compare-error").textContent).toContain(
      "library open failed: 404",
    );
    expect(picks()).toEqual({ left: "rev-b1", right: "rev-b2" });
    await runAndSettle(reads, "rev-b1", "rev-b2");
    expect(screen.queryByTestId("revision-compare-error")).toBeNull();
  });
});
