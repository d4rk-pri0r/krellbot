import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LibraryClient, OwnedRevisionBytes } from "./libraryClient";
import type { OwnedDraftSummary } from "./SavedStrategyLibrary";
import { RevisionCompare } from "./RevisionCompare";

afterEach(cleanup);

function summary(overrides: Partial<OwnedDraftSummary> = {}): OwnedDraftSummary {
  return {
    revision_id: "rev-1",
    strategy_id: "trend-follow",
    parent_revision_id: null,
    state: "draft",
    runnable: false,
    created_at: "2026-10-07T10:00:00Z",
    id: "trend-follow",
    label: "Trend follow",
    pair: "SUIUSD",
    timeframe: "1h",
    ...overrides,
  };
}

function revision(
  revisionId: string,
  pack: Record<string, unknown>,
): OwnedRevisionBytes {
  return {
    revision_id: revisionId,
    state: "draft",
    bytes: JSON.stringify(pack),
  };
}

function clientWith(
  packs: Record<string, Record<string, unknown>>,
): LibraryClient & { getJson: ReturnType<typeof vi.fn> } {
  return {
    listOwned: vi.fn(),
    getJson: vi.fn((revisionId: string): Promise<OwnedRevisionBytes> => {
      const pack = packs[revisionId];
      if (!pack) {
        return Promise.reject(new Error(`library open failed: 404`));
      }
      return Promise.resolve(revision(revisionId, pack));
    }),
  };
}

describe("RevisionCompare — mounting and selection", () => {
  it("defaults to the parent and the clicked revision when the parent is listed", async () => {
    const rows = [
      summary({
        revision_id: "rev-2",
        parent_revision_id: "rev-1",
        label: "Edited",
        created_at: "2026-10-07T12:00:00Z",
      }),
      summary(),
    ];
    render(
      <RevisionCompare client={clientWith({})} rows={rows} row={rows[0]} />,
    );
    const left = screen.getByTestId("revision-compare-left") as HTMLSelectElement;
    const right = screen.getByTestId(
      "revision-compare-right",
    ) as HTMLSelectElement;
    expect(left.value).toBe("rev-1");
    expect(right.value).toBe("rev-2");
  });

  it("leaves the later slot unchosen when no parent is listed", async () => {
    const rows = [summary()];
    render(
      <RevisionCompare client={clientWith({})} rows={rows} row={rows[0]} />,
    );
    const left = screen.getByTestId("revision-compare-left") as HTMLSelectElement;
    const right = screen.getByTestId(
      "revision-compare-right",
    ) as HTMLSelectElement;
    expect(left.value).toBe("rev-1");
    expect(right.value).toBe("");
    expect(
      (screen.getByTestId("revision-compare-run") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("offers every listed revision in both selectors", () => {
    const rows = [
      summary({
        revision_id: "rev-3",
        parent_revision_id: "rev-2",
      }),
      summary({
        revision_id: "rev-2",
        parent_revision_id: "rev-1",
      }),
      summary(),
    ];
    render(
      <RevisionCompare client={clientWith({})} rows={rows} row={rows[0]} />,
    );
    for (const testId of [
      "revision-compare-left",
      "revision-compare-right",
    ] as const) {
      const select = screen.getByTestId(testId) as HTMLSelectElement;
      const values = Array.from(select.options).map((option) => option.value);
      expect(values).toEqual(["", "rev-3", "rev-2", "rev-1"]);
    }
  });
});

describe("RevisionCompare — real fetch and diff", () => {
  const earlierPack = {
    id: "trend-follow",
    label: "Trend follow",
    timeframe: "1h",
    indicators: [
      { name: "sma", period: 20, source: "close" },
      { name: "atr", period: 14 },
    ],
    risk: { stop: { kind: "atr", multiple: 2 }, size: { risk_percent: 1 } },
    rules: { entry: { operator: ">", left: "close", right: 100 } },
  };
  const laterPack = {
    id: "trend-follow",
    label: "Trend follow tuned",
    timeframe: "4h",
    indicators: [
      { name: "sma", period: 50, source: "close" },
      { name: "ema", period: 21, source: "close" },
    ],
    risk: { stop: { kind: "percent", multiple: 2 }, size: { risk_percent: 1 } },
    rules: { entry: { operator: ">", left: "close", right: 100 }, exit: null },
  };

  it("fetches both actual revisions and lists exact paths with values", async () => {
    const client = clientWith({
      "rev-1": earlierPack,
      "rev-2": laterPack,
    });
    const rows = [
      summary({
        revision_id: "rev-2",
        parent_revision_id: "rev-1",
        label: "Edited",
      }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
    );
    expect(client.getJson).toHaveBeenCalledWith("rev-1");
    expect(client.getJson).toHaveBeenCalledWith("rev-2");
    const rowsOut = screen.getAllByTestId("revision-compare-change");
    const byPath = new Map(
      rowsOut.map((element) => [
        element.querySelector("code")?.textContent ?? "",
        element.getAttribute("data-kind") ?? "",
      ]),
    );
    expect(byPath.get("label")).toBe("changed");
    expect(byPath.get("timeframe")).toBe("changed");
    expect(byPath.get("indicators[0].period")).toBe("changed");
    expect(byPath.get("indicators[1].name")).toBe("changed");
    expect(byPath.get("risk.stop.kind")).toBe("changed");
    expect(byPath.get("rules.exit")).toBe("added");
    expect(byPath.get("timeframe")).toBe("changed");
    const body = screen.getByTestId("revision-compare-changes").textContent ?? "";
    expect(body).toContain("1h");
    expect(body).toContain("4h");
    expect(body).toContain("Trend follow tuned");
    const surface = screen.getByTestId("revision-compare").textContent ?? "";
    expect(surface).toContain("rev-1");
    expect(surface).toContain("rev-2");
    expect(screen.queryByTestId("revision-compare-error")).toBeNull();
  });

  it("reports no changes for identical revisions", async () => {
    const client = clientWith({
      "rev-1": earlierPack,
      "rev-2": earlierPack,
    });
    const rows = [
      summary({
        revision_id: "rev-2",
        parent_revision_id: "rev-1",
      }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-identical")).toBeDefined(),
    );
    expect(screen.queryByTestId("revision-compare-changes")).toBeNull();
  });

  it("shows a loading state while the fetches are pending", () => {
    const client: LibraryClient = {
      listOwned: vi.fn(),
      getJson: vi.fn(
        () => new Promise<OwnedRevisionBytes>(() => {}),
      ),
    };
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    expect(screen.getByTestId("revision-compare-loading")).toBeDefined();
    expect(screen.queryByTestId("revision-compare-changes")).toBeNull();
  });

  it("surfaces fetch failures honestly and keeps the list usable", async () => {
    const client = clientWith({ "rev-1": earlierPack });
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-error").textContent).toContain(
        "library open failed: 404",
      ),
    );
    expect(screen.queryByTestId("revision-compare-changes")).toBeNull();
  });

  it("surfaces unreadable JSON as an error without fabricating a diff", async () => {
    const client: LibraryClient = {
      listOwned: vi.fn(),
      getJson: vi.fn((revisionId: string): Promise<OwnedRevisionBytes> =>
        revisionId === "rev-1"
          ? Promise.resolve({
              revision_id: "rev-1",
              state: "draft",
              bytes: "{not json",
            })
          : Promise.resolve(revision("rev-2", laterPack)),
      ),
    };
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-error").textContent).toContain(
        "not readable JSON",
      ),
    );
    expect(screen.queryByTestId("revision-compare-changes")).toBeNull();
  });

  it("ignores a superseded comparison response", async () => {
    let releaseStale: ((bytes: OwnedRevisionBytes) => void) | undefined;
    const stale = new Promise<OwnedRevisionBytes>((resolve) => {
      releaseStale = resolve;
    });
    let rev2Calls = 0;
    const client: LibraryClient = {
      listOwned: vi.fn(),
      getJson: vi.fn((revisionId: string) => {
        if (revisionId === "rev-2") {
          rev2Calls += 1;
          // Only the first rev-2 fetch hangs; the superseding one resolves.
          return rev2Calls === 1 ? stale : Promise.resolve(revision("rev-2", laterPack));
        }
        return Promise.resolve(
          revision(revisionId, revisionId === "rev-3" ? laterPack : earlierPack),
        );
      }),
    };
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary({ revision_id: "rev-3", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    expect(screen.getByTestId("revision-compare-loading")).toBeDefined();
    // Re-select and re-run while the first compare is still pending.
    fireEvent.change(screen.getByTestId("revision-compare-right"), {
      target: { value: "rev-3" },
    });
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.queryByTestId("revision-compare-loading")).toBeNull(),
    );
    expect(screen.getByTestId("revision-compare-changes")).toBeDefined();
    // Releasing the stale first response must not re-render anything.
    releaseStale?.(revision("rev-2", earlierPack));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByTestId("revision-compare-loading")).toBeNull();
    expect(screen.queryByTestId("revision-compare-error")).toBeNull();
    expect(screen.getByTestId("revision-compare-summary").textContent).toContain(
      "rev-3",
    );
  });
});

describe("RevisionCompare — read-only guarantees", () => {
  const earlierPack = { label: "Trend follow", rules: { entry: { period: 20 } } };
  const laterPack = { label: "Tuned", rules: { entry: { period: 50 } } };

  it("never calls listOwned and only reads through getJson", async () => {
    const client = clientWith({
      "rev-1": earlierPack,
      "rev-2": laterPack,
    });
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
    );
    expect(client.listOwned).not.toHaveBeenCalled();
    const calls = (client.getJson as unknown as { mock: { calls: string[][] } })
      .mock.calls;
    expect(calls.map((call) => call[0]).sort()).toEqual(["rev-1", "rev-2"]);
  });

  it("renders hostile stored values as text, not markup", async () => {
    const hostile = {
      label: '<img src=x onerror="alert(1)">Trend',
      note: "<script>alert(2)</script>",
    };
    const client = clientWith({
      "rev-1": { label: "plain", note: "plain" },
      "rev-2": hostile,
    });
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
    );
    const html = screen.getByTestId("revision-compare").innerHTML;
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script");
    expect(screen.getByTestId("revision-compare-changes").textContent).toContain(
      '<img src=x onerror="alert(1)">Trend',
    );
  });

  it("supports arbitrary pack structures safely, including nested unknowns", async () => {
    const client = clientWith({
      "rev-1": { custom: { deep: [1, "two", { three: true }] }, nulled: null },
      "rev-2": { custom: { deep: [1, "two", { three: false }] } },
    });
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
    );
    const body = screen.getByTestId("revision-compare-changes").textContent ?? "";
    expect(body).toContain("custom.deep[2].three");
    expect(body).toContain("true");
    expect(body).toContain("false");
    expect(body).toContain("nulled");
  });

  it("offers no arm, validate, save, or other write control", () => {
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(
      <RevisionCompare client={clientWith({})} rows={rows} row={rows[0]} />,
    );
    const controls = screen
      .getAllByRole("button")
      .map((button) => button.textContent ?? "");
    expect(controls.length).toBe(1);
    expect(controls[0]).toBe("Compare revisions");
  });

  it("closes through the host without touching the client", () => {
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    const onClose = vi.fn();
    const client = clientWith({});
    render(
      <RevisionCompare
        client={client}
        rows={rows}
        row={rows[0]}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("revision-compare-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(client.getJson).not.toHaveBeenCalled();
  });
});
