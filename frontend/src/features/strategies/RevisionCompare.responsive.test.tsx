import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { LibraryClient, OwnedRevisionBytes } from "./libraryClient";
import type { OwnedDraftSummary } from "./SavedStrategyLibrary";
import { RevisionCompare } from "./RevisionCompare";

/*
 * RevisionCompare — viewport containment regression (issue129).
 *
 * On base, an ordinary GUI probe on the real guarded workstation at a
 * 390px viewport produced a document scrollWidth of ~757-762px once
 * Compare opened: the compare root's implicit `auto` grid track sized
 * itself to the <select> intrinsic min-content (the widest option
 * label carries a full 64-char revision id, ~704px), so every child —
 * header, note, picks, summary, table, caption — stretched past the
 * viewport at 390 and 640px. The fix is structural:
 *
 *   1. one explicit root track `minmax(0, 1fr)` so panel content can
 *      never size the panel past its container, and
 *   2. `overflow-wrap: anywhere` (not break-word) so 64-char ids wrap
 *      mid-token and contribute ~1ch of min-content inside the flex
 *      summary/empty lines, plus
 *   3. a <=720px block restoring the KRELL-SIGNAL-20261010 44px touch
 *      targets the scoped 34px rules otherwise override.
 *
 * jsdom does not run layout, so these unit tests pin the stylesheet
 * contract and the DOM preservation of full identifiers; the
 * geometric RED->GREEN proof at 390/640/1440px is recorded from
 * production Chromium driving the real guarded workstation (see
 * .operator/evidence for the probe logs). Data is never truncated,
 * dropped, or replaced: every value below comes from bytes served by
 * the fake authenticated library client exactly as stored.
 */

const LONG_ID_A =
  "8d4f0f61b3bedda41722440ce92d89fd8cbadbad32fb340dc8e038215f439883";
const LONG_ID_B =
  "c45b1e92a7f0c3d6285a1f7e9b0d4c8a3f6e2d1b9c8a7f6e5d4c3b2a1f0e9d8c";

afterEach(cleanup);

function summary(overrides: Partial<OwnedDraftSummary> = {}): OwnedDraftSummary {
  return {
    revision_id: LONG_ID_A,
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

describe("RevisionCompare — viewport containment stylesheet contract", () => {
  const stylesDir = dirname(fileURLToPath(import.meta.url));
  const css = readFileSync(join(stylesDir, "RevisionCompare.signal.css"), "utf8");

  it("clamps the root grid track to minmax(0, 1fr) so intrinsic select content cannot widen the panel", () => {
    // The defect: an implicit auto track sized to the widest <option>
    // (64-char revision id + label + date) blew the panel to ~704px of
    // content inside a 390px viewport. An explicit min-0 track keeps
    // the panel exactly as wide as its container at every breakpoint.
    expect(css).toMatch(
      /\.kbot-shell__revision-root\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
  });

  it("breaks long revision identifiers anywhere so flex summary/empty lines contain their min-content", () => {
    // overflow-wrap: break-word does not reduce a word's contribution
    // to min-content; `anywhere` does, which is what lets the 64-char
    // ids inside the flex summary and identical-empty lines wrap.
    expect(css).toMatch(
      /\.kbot-shell__revision-root\s*\{[^}]*overflow-wrap:\s*anywhere/,
    );
  });

  it("keeps diff values wrapped and internally scrollable instead of widening the page", () => {
    expect(css).toMatch(
      /\.kbot-revision-compare__scroll\s*\{[^}]*overflow-x:\s*auto/,
    );
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
  });

  it("restores 44px touch targets for the close/run controls and selectors on narrow screens", () => {
    // The scoped 34px rules out-specify the shell's narrow
    // `.kbot-shell button { min-height: 44px }`; the <=720px block
    // (the host library surface's own narrow breakpoint) must restore
    // the KRELL-SIGNAL-20261010 touch-target contract.
    const mediaIndex = css.indexOf("@media (max-width: 720px)");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex, css.indexOf("}", css.indexOf("select", mediaIndex)) + 1);
    for (const control of [
      "kbot-revision-compare__close",
      "kbot-revision-compare__run",
      "kbot-revision-compare__picks select",
    ]) {
      expect(narrow).toContain(control);
    }
    expect(narrow.match(/min-height:\s*44px/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("contains the panel without forbidden page-level or fixed-width mechanisms", () => {
    // No global page clip, no sr-only hacks on the compare surface,
    // no arbitrary fixed widths: containment must come from the
    // clamped track + anywhere wrapping above. Media-query
    // breakpoints are viewport conditions, not element widths.
    const declarations = css.replace(/@media[^{]+\{/g, "");
    expect(css).not.toMatch(/overflow\s*:\s*hidden/);
    expect(declarations).not.toMatch(/(?:min-|max-)?width\s*:\s*\d+px/);
    expect(css).not.toMatch(/(^|[\s,])(html|body)\s*[,{]/);
  });
});

describe("RevisionCompare — long identifiers stay whole in the DOM", () => {
  it("renders both selectors with the full 64-char revision ids as stored option values", async () => {
    const client = clientWith({
      [LONG_ID_A]: { id: "trend-follow", label: "Trend follow" },
      [LONG_ID_B]: { id: "trend-follow", label: "Trend follow tuned" },
    });
    const rows = [
      summary({
        revision_id: LONG_ID_B,
        parent_revision_id: LONG_ID_A,
        label: "Edited",
      }),
      summary(),
    ];
    render(
      <RevisionCompare client={client} rows={rows} row={rows[0]} />,
    );
    for (const testid of ["revision-compare-left", "revision-compare-right"]) {
      const select = screen.getByTestId(testid) as HTMLSelectElement;
      const values = Array.from(select.options).map((option) => option.value);
      expect(values).toContain(LONG_ID_A);
      expect(values).toContain(LONG_ID_B);
      const labelled = Array.from(select.options)
        .map((option) => option.textContent ?? "")
        .find((text) => text.includes(LONG_ID_A));
      expect(labelled).toBeDefined();
    }
  });

  it("carries the full 64-char ids verbatim through the summary and caption after comparing", async () => {
    const client = clientWith({
      [LONG_ID_A]: { id: "trend-follow", label: "Trend follow" },
      [LONG_ID_B]: { id: "trend-follow", label: "Trend follow tuned" },
    });
    const rows = [
      summary({
        revision_id: LONG_ID_B,
        parent_revision_id: LONG_ID_A,
        label: "Edited",
      }),
      summary(),
    ];
    render(
      <RevisionCompare client={client} rows={rows} row={rows[0]} />,
    );
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-summary")).toBeDefined(),
    );
    expect(screen.getByTestId("revision-compare-summary").textContent).toContain(
      LONG_ID_A,
    );
    expect(screen.getByTestId("revision-compare-summary").textContent).toContain(
      LONG_ID_B,
    );
    expect(screen.getByTestId("revision-compare-caption").textContent).toContain(
      LONG_ID_A,
    );
    expect(screen.getByTestId("revision-compare-caption").textContent).toContain(
      LONG_ID_B,
    );
  });

  it("keeps the read-only selection state and stored diff values unchanged by presentation", async () => {
    const client = clientWith({
      [LONG_ID_A]: { id: "trend-follow", label: "Trend follow", risk: { stop: { pct: 25 } } },
      [LONG_ID_B]: { id: "trend-follow", label: "Trend follow tuned", risk: { stop: { pct: 33 } } },
    });
    const rows = [
      summary({
        revision_id: LONG_ID_B,
        parent_revision_id: LONG_ID_A,
        label: "Edited",
      }),
      summary(),
    ];
    render(
      <RevisionCompare client={client} rows={rows} row={rows[0]} />,
    );
    const left = screen.getByTestId("revision-compare-left") as HTMLSelectElement;
    expect(left.value).toBe(LONG_ID_A);
    fireEvent.click(screen.getByTestId("revision-compare-run"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-compare-changes").children.length).toBe(
        2,
      ),
    );
    const stops = screen
      .getAllByTestId("revision-compare-change")
      .find(
        (row) => row.querySelector("code")?.textContent === "risk.stop.pct",
      ) as HTMLTableRowElement | undefined;
    expect(stops?.cells[2].textContent).toBe("25");
    expect(stops?.cells[3].textContent).toBe("33");
    expect(client.getJson).toHaveBeenCalledWith(LONG_ID_A);
    expect(client.getJson).toHaveBeenCalledWith(LONG_ID_B);
  });
});
