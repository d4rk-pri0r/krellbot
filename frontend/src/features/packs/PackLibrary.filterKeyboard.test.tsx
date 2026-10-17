/**
 * Installed pack library — filter keyboard-shortcut announcements
 * (KRELL-SIGNAL-20261010, aria-keyshortcuts slice).
 *
 * A keyboard-only / screen-reader operator must hear the documented focus
 * shortcut for each filter control in the pack-library toolbar. These tests
 * mount the real component and pin the aria-keyshortcuts / aria-label
 * annotations without changing any visible text, testid, handler or gating:
 *
 *  - Search input announces "Control+F Meta+F";
 *  - Bucket select announces "Control+Alt+B Meta+Alt+B" — distinct from the
 *    Operations alerts ("Control+Alt+S"), last-runs venue ("Control+Alt+V")
 *    and last-runs status ("Control+Alt+T") chords;
 *  - the conditional Clear button announces "Escape" plus a descriptive
 *    accessible name while its visible literal, disabled gating and
 *    onClick={handleClearFilters} behavior stay byte-equal.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackLibrary, type PackLibraryClient, type PackRow } from "./PackLibrary";

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

function row(
  pack_id: string,
  bucket: PackRow["bucket"],
  extra: Partial<PackRow> = {},
): PackRow {
  return {
    bucket,
    pack_id,
    version: "1.0.0",
    permissions: [],
    rollback_ref: null,
    ...extra,
  };
}

const INVENTORY: PackRow[] = [
  row("krell.alpha.momentum", "deployed", { version: "2.4.1" }),
  row("krell.bravo.range", "installed", { version: "0.9.0" }),
];

/** Mounts the real component over a non-empty loaded inventory. */
async function mountedLibrary(
  client: PackLibraryClient = makeClient({
    listInstalled: vi.fn(async () => INVENTORY),
  }),
): Promise<void> {
  render(<PackLibrary client={client} />);
  await screen.findByTestId("pack-library-list");
}

describe("PackLibrary filter keyboard-shortcut announcements", () => {
  it("announces the documented focus shortcuts on the search and bucket controls", async () => {
    await mountedLibrary();

    const search = screen.getByTestId("pack-library-search");
    expect(search.getAttribute("id")).toBe("pack-library-search");
    expect(search.getAttribute("aria-keyshortcuts")).toBe("Control+F Meta+F");

    const bucket = screen.getByTestId("pack-library-bucket-select");
    expect(bucket.getAttribute("id")).toBe("pack-library-bucket");
    expect(bucket.getAttribute("aria-keyshortcuts")).toBe("Control+Alt+B Meta+Alt+B");
    // Distinct from the other toolbar chords already claimed elsewhere.
    expect(bucket.getAttribute("aria-keyshortcuts")).not.toContain("Alt+S");
    expect(bucket.getAttribute("aria-keyshortcuts")).not.toContain("Alt+V");
    expect(bucket.getAttribute("aria-keyshortcuts")).not.toContain("Alt+T");

    // The structural identity of both controls is untouched.
    expect(search.getAttribute("placeholder")).toBe("pack_id, version or permission");
    expect(search.getAttribute("value")).toBe("");
    expect(screen.getByText("Search packs")).toBeDefined();
    expect(screen.getByText("Filter by bucket")).toBeDefined();
    expect(screen.getByLabelText("Search packs")).toBe(search);
    expect(screen.getByLabelText("Filter by bucket")).toBe(bucket);
  });

  it("announces the Escape clear shortcut with an accessible name, keeping visible text and gating byte-equal", async () => {
    await mountedLibrary();

    const clear = screen.getByTestId("pack-library-clear-filters");
    expect(clear.getAttribute("aria-keyshortcuts")).toBe("Escape");
    expect(clear.getAttribute("aria-label")).toBe(
      "Clear pack-library search and bucket filter",
    );
    // Visible literal and disabled gating are unchanged.
    expect(clear.textContent).toBe("Clear search & filter");
    expect(clear.getAttribute("type")).toBe("button");
    expect(clear.hasAttribute("disabled")).toBe(true);
    expect(clear.getAttribute("aria-disabled")).toBe("true");

    // Activation restores the actual loaded inventory (existing callback).
    fireEvent.change(screen.getByTestId("pack-library-search"), {
      target: { value: "bravo" },
    });
    expect(screen.getByTestId("pack-library-count").textContent).toContain(
      "1 of 2 packs shown",
    );
    const armed = screen.getByTestId("pack-library-clear-filters");
    expect(armed.hasAttribute("disabled")).toBe(false);
    expect(armed.getAttribute("aria-disabled")).toBe("false");
    expect(armed.getAttribute("aria-keyshortcuts")).toBe("Escape");
    expect(armed.getAttribute("aria-label")).toBe(
      "Clear pack-library search and bucket filter",
    );
    fireEvent.click(armed);
    expect(screen.getByTestId("pack-library-search").getAttribute("value")).toBe("");
    expect(screen.getByTestId("pack-library-count").textContent).toContain(
      "2 of 2 packs shown",
    );
  });

  it("keeps the refresh affordance and structural testids unchanged by the announcements", async () => {
    await mountedLibrary();

    const refresh = screen.getByTestId("pack-library-refresh");
    expect(refresh.getAttribute("aria-busy")).not.toBe("true");
    const status = screen.getByTestId("pack-library-refresh-status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.getAttribute("role")).toBe("status");
    expect(refresh.textContent).toBe("Refresh");

    // The panel region and its visible heading stay structurally unchanged.
    const panel = screen.getByTestId("pack-library-panel");
    expect(panel.getAttribute("role")).toBe("region");
    expect(panel.getAttribute("aria-label")).toBe("Pack library");
    expect(screen.getByRole("heading", { name: "Pack library" })).toBeDefined();

    for (const testid of [
      "pack-library-refresh",
      "pack-library-refresh-status",
      "pack-library-search",
      "pack-library-bucket-select",
      "pack-library-clear-filters",
      "pack-library-count",
      "pack-library-list",
      "pack-library-row-krell.alpha.momentum",
      "pack-library-row-krell.bravo.range",
    ]) {
      expect(screen.getByTestId(testid)).toBeDefined();
    }
    expect(screen.queryByTestId("pack-library-no-matches")).toBeNull();
  });
});
