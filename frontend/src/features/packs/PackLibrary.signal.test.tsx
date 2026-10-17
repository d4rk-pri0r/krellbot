/**
 * Installed pack library — local discovery/query surface (KRELL-SIGNAL-20261010).
 *
 * These tests pin the scoped presentation upgrade:
 *
 *  - a local query box that matches the real pack_id / version / permission
 *    fields of the already-loaded records (no fetching, no record mutation);
 *  - an accessible bucket selector that filters the loaded records;
 *  - a clear affordance that restores the actual loaded inventory;
 *  - "no matches" distinct from a server-empty library and from load errors;
 *  - exact pack_id copy still works after filtering, with truthful feedback;
 *  - no rollback (or any other mutating client call) is ever made.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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

function stubClipboard(allow: string[] | null = null): string[] {
  const written: string[] = [];
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi.fn(async (value: string) => {
        written.push(value);
        if (allow !== null && !allow.includes(value)) {
          throw new DOMException("write denied", "NotAllowedError");
        }
      }),
    },
  });
  return written;
}

const INVENTORY: PackRow[] = [
  row("krell.alpha.momentum", "deployed", {
    version: "2.4.1",
    permissions: ["trade", "read"],
    rollback_ref: {
      pack_id: "krell.alpha.momentum",
      prior_revision_id: "a".repeat(64),
    },
  }),
  row("krell.bravo.range", "installed", {
    version: "1.9.0",
    permissions: ["read"],
    rollback_ref: null,
  }),
  row("krell.charlie.connector", "purchased", {
    version: null,
    permissions: ["connect"],
    rollback_ref: null,
  }),
];

describe("PackLibrary local query", () => {
  it("offers an accessible search box and bucket filter over the loaded records", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);

    await screen.findByTestId("pack-library-list");
    expect(screen.getByLabelText(/Search packs/i)).toBeDefined();
    expect(screen.getByLabelText(/Filter by bucket/i)).toBeDefined();

    const bucketSelect = screen.getByLabelText(/Filter by bucket/i) as HTMLSelectElement;
    const options = within(bucketSelect)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "");
    // Only buckets that actually occur in the loaded records, plus "All".
    expect(options).toEqual(
      expect.arrayContaining(["All buckets", "deployed", "installed", "purchased"]),
    );
    expect(options).toHaveLength(4);
  });

  it("matches the query against pack_id, version and permission fields", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    const search = screen.getByLabelText(/Search packs/i);
    fireEvent.change(search, { target: { value: "momentum" } });
    expect(screen.getByTestId("pack-library-row-krell.alpha.momentum")).toBeDefined();
    expect(
      screen.queryByTestId("pack-library-row-krell.bravo.range"),
    ).toBeNull();
    expect(
      screen.queryByTestId("pack-library-row-krell.charlie.connector"),
    ).toBeNull();

    fireEvent.change(search, { target: { value: "1.9.0" } });
    expect(screen.getByTestId("pack-library-row-krell.bravo.range")).toBeDefined();
    expect(
      screen.queryByTestId("pack-library-row-krell.alpha.momentum"),
    ).toBeNull();

    fireEvent.change(search, { target: { value: "connect" } });
    expect(
      screen.getByTestId("pack-library-row-krell.charlie.connector"),
    ).toBeDefined();
    expect(
      screen.queryByTestId("pack-library-row-krell.alpha.momentum"),
    ).toBeNull();
  });

  it("filters locally without fetching or mutating records", async () => {
    const listInstalled = vi.fn(async () => INVENTORY);
    const rollback = vi.fn(async () => ({ ok: true }));
    render(
      <PackLibrary client={makeClient({ listInstalled, rollback })} />,
    );
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByLabelText(/Search packs/i), {
      target: { value: "bravo" },
    });
    const bucketSelect = screen.getByLabelText(/Filter by bucket/i);
    fireEvent.change(bucketSelect, { target: { value: "installed" } });

    expect(listInstalled).toHaveBeenCalledTimes(1);
    expect(rollback).not.toHaveBeenCalled();
  });
});

describe("PackLibrary bucket filter and clear", () => {
  it("filters by bucket with an accessible selector", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByLabelText(/Filter by bucket/i), {
      target: { value: "deployed" },
    });
    expect(
      screen.getByTestId("pack-library-row-krell.alpha.momentum"),
    ).toBeDefined();
    expect(
      screen.queryByTestId("pack-library-row-krell.bravo.range"),
    ).toBeNull();

    fireEvent.change(screen.getByLabelText(/Filter by bucket/i), {
      target: { value: "installed" },
    });
    expect(
      screen.getByTestId("pack-library-row-krell.bravo.range"),
    ).toBeDefined();
    expect(
      screen.queryByTestId("pack-library-row-krell.alpha.momentum"),
    ).toBeNull();
  });

  it("combines query and bucket filter, then clear restores the loaded inventory", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByLabelText(/Search packs/i), {
      target: { value: "krell" },
    });
    fireEvent.change(screen.getByLabelText(/Filter by bucket/i), {
      target: { value: "purchased" },
    });
    expect(
      screen.getByTestId("pack-library-row-krell.charlie.connector"),
    ).toBeDefined();
    expect(
      screen.queryByTestId("pack-library-row-krell.alpha.momentum"),
    ).toBeNull();

    fireEvent.click(screen.getByTestId("pack-library-clear-filters"));

    for (const r of INVENTORY) {
      expect(screen.getByTestId(`pack-library-row-${r.pack_id}`)).toBeDefined();
    }
    const search = screen.getByLabelText(/Search packs/i) as HTMLInputElement;
    expect(search.value).toBe("");
    const bucketSelect = screen.getByLabelText(
      /Filter by bucket/i,
    ) as HTMLSelectElement;
    expect(bucketSelect.value).toBe("all");
  });

  it("keeps prior revision context visible and honest for each row", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    const list = await screen.findByTestId("pack-library-list");

    const alpha = within(list).getByTestId("pack-library-row-krell.alpha.momentum");
    expect(
      within(alpha).getByTestId("pack-library-rollback-ref-krell.alpha.momentum")
        .textContent,
    ).toBe("a".repeat(64));
    expect(
      within(alpha).getByTestId("pack-library-permissions-krell.alpha.momentum")
        .textContent,
    ).toBe("trade, read");
    expect(
      within(alpha).getByTestId("pack-library-version-krell.alpha.momentum")
        .textContent,
    ).toBe("2.4.1");

    const bravo = within(list).getByTestId("pack-library-row-krell.bravo.range");
    expect(
      within(bravo).getByTestId("pack-library-rollback-ref-krell.bravo.range")
        .textContent,
    ).toBe("—");
    expect(
      within(bravo).getByTestId("pack-library-permissions-krell.bravo.range")
        .textContent,
    ).toBe("read");
  });
});

describe("PackLibrary no-matches vs empty vs error", () => {
  it("shows a distinct no-matches state when filters exclude every loaded record", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByLabelText(/Search packs/i), {
      target: { value: "does-not-exist-anywhere",
      },
    });

    const noMatches = await screen.findByTestId("pack-library-no-matches");
    expect(noMatches.textContent ?? "").toMatch(/No packs match/i);
    // Distinct from a genuinely empty library and from a load failure.
    expect(screen.queryByTestId("pack-library-empty")).toBeNull();
    expect(screen.queryByTestId("pack-library-failed")).toBeNull();
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
    // Clearing restores the real inventory, not an invented one.
    fireEvent.click(screen.getByTestId("pack-library-clear-filters"));
    expect(screen.getByTestId("pack-library-list")).toBeDefined();
  });

  it("reports a server-empty library without offering a no-matches claim", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => []) });
    render(<PackLibrary client={client} />);
    const empty = await screen.findByTestId("pack-library-empty");
    expect(empty.textContent ?? "").toMatch(/No packs/);
    expect(screen.queryByTestId("pack-library-no-matches")).toBeNull();
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
  });

  it("keeps the toolbar filters from acting on data that never loaded", async () => {
    const client = makeClient({
      listInstalled: vi.fn(async () => {
        throw new PackLibraryHttpError(403, "pack library failed: 403");
      }),
    });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-error");
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
    expect(screen.queryByLabelText(/Search packs/i)).toBeNull();
    expect(screen.queryByLabelText(/Filter by bucket/i)).toBeNull();
    expect(screen.queryByTestId("pack-library-no-matches")).toBeNull();
  });

  it("keeps a failed refresh explicit even when older rows stay visible", async () => {
    let call = 0;
    const listInstalled = vi.fn(async (): Promise<PackRow[]> => {
      call += 1;
      if (call === 1) {
        return INVENTORY;
      }
      throw new PackLibraryHttpError(500, "pack library failed: 500");
    });
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/500/);
    // Older rows remain visible and still usable.
    expect(
      screen.getByTestId("pack-library-row-krell.alpha.momentum"),
    ).toBeDefined();
  });
});

describe("PackLibrary copy after filtering", () => {
  it("copies the exact pack_id of a filtered row with truthful feedback", async () => {
    const written = stubClipboard();
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByLabelText(/Search packs/i), {
      target: { value: "charlie" },
    });
    expect(
      screen.getByTestId("pack-library-row-krell.charlie.connector"),
    ).toBeDefined();

    fireEvent.click(
      screen.getByTestId("pack-library-copy-krell.charlie.connector"),
    );
    await waitFor(() => {
      expect(written).toEqual(["krell.charlie.connector"]);
    });
    expect(
      screen.getByTestId("pack-library-copy-feedback-krell.charlie.connector")
        .textContent,
    ).toBe("Copied");
    // No other row claims a copy.
    expect(
      screen.queryByTestId("pack-library-copy-feedback-krell.alpha.momentum"),
    ).toBeNull();
  });

  it("does not claim a copy when the clipboard write is refused", async () => {
    stubClipboard([]);
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.click(screen.getByTestId("pack-library-copy-krell.bravo.range"));
    await new Promise((resolve) => {
      setTimeout(resolve, 10);
    });
    expect(
      screen.getByTestId("pack-library-copy-feedback-krell.bravo.range")
        .textContent,
    ).toBe("Copy");
  });
});

describe("PackLibrary read-only discovery", () => {
  it("never calls rollback while searching, filtering or clearing", async () => {
    const rollback = vi.fn(async () => ({ ok: true }));
    const client = makeClient({
      rollback,
      listInstalled: vi.fn(async () => INVENTORY),
    });
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByLabelText(/Search packs/i), {
      target: { value: "alpha" },
    });
    fireEvent.change(screen.getByLabelText(/Filter by bucket/i), {
      target: { value: "deployed" },
    });
    fireEvent.click(screen.getByTestId("pack-library-clear-filters"));
    fireEvent.click(screen.getByTestId("pack-library-copy-krell.alpha.momentum"));

    expect(rollback).not.toHaveBeenCalled();
    const panelText =
      screen.getByTestId("pack-library-panel").textContent ?? "";
    expect(panelText).not.toMatch(/\b(install|catalog|entitle|rollback)\b/i);
  });

  it("reports how many loaded records the current view shows", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => INVENTORY) });
    render(<PackLibrary client={client} />);
    const count = await screen.findByTestId("pack-library-count");
    expect(count.textContent ?? "").toMatch(/3 of 3/i);

    fireEvent.change(screen.getByLabelText(/Filter by bucket/i), {
      target: { value: "deployed" },
    });
    expect(count.textContent ?? "").toMatch(/1 of 3/i);

    fireEvent.click(screen.getByTestId("pack-library-clear-filters"));
    expect(count.textContent ?? "").toMatch(/3 of 3/i);
  });
});
