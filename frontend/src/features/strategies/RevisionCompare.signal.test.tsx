import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LibraryClient, OwnedRevisionBytes } from "./libraryClient";
import type { OwnedDraftSummary } from "./SavedStrategyLibrary";
import { RevisionCompare } from "./RevisionCompare";

/*
 * Signal presentation slice for RevisionCompare — KRELL-SIGNAL-20261010.
 *
 * These tests pin the scoped Signal vocabulary (`.kbot-shell__revision-*`)
 * layered onto the existing read-only compare surface. They are RED
 * against the inherited shell-styled component and GREEN once the scoped
 * vocabulary is mounted. The comparison itself stays untouched: every
 * value below comes from bytes served by the (fake) authenticated
 * library client, exactly as the real client would serve them.
 */

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
        return Promise.reject(new Error("library open failed: 404"));
      }
      return Promise.resolve(revision(revisionId, pack));
    }),
  };
}

const earlierPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  note: "old note",
  risk: { stop: { kind: "atr", multiple: 2 } },
};
const laterPack = {
  id: "trend-follow",
  label: "Trend follow tuned",
  timeframe: "4h",
  risk: { stop: { kind: "atr", multiple: 2 }, size: { risk_percent: 1 } },
  rules: { entry: 100 },
};

async function renderCompared(
  packs: Record<string, Record<string, unknown>> = {
    "rev-1": earlierPack,
    "rev-2": laterPack,
  },
) {
  const client = clientWith(packs);
  const rows = [
    summary({ revision_id: "rev-2", parent_revision_id: "rev-1", label: "Edited" }),
    summary(),
  ];
  render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
  fireEvent.click(screen.getByTestId("revision-compare-run"));
  await waitFor(() =>
    expect(screen.getByTestId("revision-compare-changes")).toBeDefined(),
  );
  return client;
}

function compareRow(path: string): HTMLTableRowElement {
  const found = screen
    .getAllByTestId("revision-compare-change")
    .find((element) => element.querySelector("code")?.textContent === path);
  if (!found) {
    throw new Error(`no compare row rendered for path ${path}`);
  }
  return found as HTMLTableRowElement;
}

describe("RevisionCompare — Signal scoped vocabulary", () => {
  it("retires the legacy unscoped wrapper class from the compare root", async () => {
    await renderCompared();
    const root = screen.getByTestId("revision-compare");
    expect(root.className).not.toContain("kbot-revision-compare");
  });

  it("mounts the scoped root, summary header, and kind chips", async () => {
    await renderCompared();
    const root = screen.getByTestId("revision-compare");
    expect(root.tagName).toBe("SECTION");
    expect(root.classList.contains("kbot-shell__revision-root")).toBe(true);

    const summary = screen.getByTestId("revision-compare-summary");
    expect(summary.classList.contains("kbot-shell__revision-summary")).toBe(true);

    const added = screen.getByTestId("revision-summary-added");
    expect(added.classList.contains("kbot-shell__revision-summary--added")).toBe(true);
    expect(added.textContent).toBe("2 added");
    const removed = screen.getByTestId("revision-summary-removed");
    expect(
      removed.classList.contains("kbot-shell__revision-summary--removed"),
    ).toBe(true);
    expect(removed.textContent).toBe("1 removed");
    const changed = screen.getByTestId("revision-summary-changed");
    expect(
      changed.classList.contains("kbot-shell__revision-summary--changed"),
    ).toBe(true);
    expect(changed.textContent).toBe("2 changed");
  });

  it("renders the identical-revisions empty state on the scoped vocabulary", async () => {
    // Identical packs never render the changes table; wait for the
    // empty state directly.
    const client = clientWith({
      "rev-1": earlierPack,
      "rev-2": earlierPack,
    });
    const rows = [
      summary({ revision_id: "rev-2", parent_revision_id: "rev-1" }),
      summary(),
    ];
    render(<RevisionCompare client={client} rows={rows} row={rows[0]} />);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-identical")).toBeDefined(),
    );
    const empty = screen.getByTestId("revision-compare-identical");
    expect(empty.classList.contains("kbot-shell__revision-empty")).toBe(true);
    expect(empty.textContent).toContain("No differences");
    expect(screen.getByTestId("revision-compare").contains(empty)).toBe(true);
  });

  it("marks an added key with the scoped added row and pill, showing the stored value verbatim", async () => {
    await renderCompared();
    const row = compareRow("rules");
    expect(row.getAttribute("data-kind")).toBe("added");
    expect(row.classList.contains("kbot-shell__revision-row")).toBe(true);
    expect(row.classList.contains("kbot-shell__revision-row--added")).toBe(true);

    const pill = row.querySelector(".kbot-shell__revision-row__kind");
    expect(pill?.classList.contains("kbot-shell__revision-row__kind--added")).toBe(
      true,
    );
    expect(pill?.textContent).toBe("added");

    // The later value is the stored object, serialized exactly as saved —
    // never synthesized or reformatted beyond JSON of the stored bytes.
    expect(row.cells[3].textContent).toBe('{"entry":100}');
  });

  it("marks a removed key with the scoped removed row and keeps the later slot empty", async () => {
    await renderCompared();
    const row = compareRow("note");
    expect(row.getAttribute("data-kind")).toBe("removed");
    expect(row.classList.contains("kbot-shell__revision-row--removed")).toBe(true);

    const pill = row.querySelector(".kbot-shell__revision-row__kind");
    expect(
      pill?.classList.contains("kbot-shell__revision-row__kind--removed"),
    ).toBe(true);
    expect(pill?.textContent).toBe("removed");

    // The earlier value is shown exactly as stored; the later slot carries
    // only the explicit absence marker — no value is invented for it.
    expect(row.cells[2].textContent).toBe("old note");
    expect(row.cells[3].textContent).toBe("— (not present)");
  });

  it("carries a read-only caption below the rows without replacing the summary header", async () => {
    await renderCompared();
    const caption = screen.getByTestId("revision-compare-caption");
    expect(caption.classList.contains("kbot-shell__revision-caption")).toBe(true);
    expect(caption.textContent).toBe(
      "Read-only comparison of revisions rev-1 and rev-2 · 5 differences",
    );
    expect(caption.textContent ?? "").not.toMatch(/armed|validated|saved/);
    // The caption supplements — never replaces — the summary header.
    expect(screen.getByTestId("revision-compare-summary")).toBeDefined();
    const summaryPosition = screen
      .getByTestId("revision-compare-summary")
      .compareDocumentPosition(caption);
    expect(summaryPosition & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps every diff row and value cell on the scoped vocabulary", async () => {
    await renderCompared();
    const rows = screen.getAllByTestId("revision-compare-change");
    expect(rows.length).toBe(5);
    for (const row of rows) {
      const kind = row.getAttribute("data-kind") ?? "";
      expect(row.classList.contains("kbot-shell__revision-row")).toBe(true);
      expect(
        row.classList.contains(`kbot-shell__revision-row--${kind}`),
      ).toBe(true);
      const pathCell = row.querySelector(".kbot-shell__revision-row__path");
      const previousCell = row.querySelector(
        ".kbot-shell__revision-row__previous",
      );
      const nextCell = row.querySelector(".kbot-shell__revision-row__next");
      expect(pathCell?.querySelector("code")).toBeDefined();
      expect(previousCell?.querySelector("code")).toBeDefined();
      expect(nextCell?.querySelector("code")).toBeDefined();
    }
  });
});
