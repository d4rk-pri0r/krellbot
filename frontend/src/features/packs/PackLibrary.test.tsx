import { cleanup, render, screen, within } from "@testing-library/react";
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

describe("PackLibrary bucket rendering", () => {
  it("renders one row per pack with its bucket label", async () => {
    const rows: PackRow[] = [
      row("alpha", "deployed"),
      row("bravo", "configured"),
      row("charlie", "installed"),
      row("delta", "download_pending"),
      row("echo", "purchased"),
    ];
    const client = makeClient({ listInstalled: vi.fn(async () => rows) });
    render(<PackLibrary client={client} />);

    const panel = await screen.findByTestId("pack-library-panel");
    expect(panel).toBeDefined();
    const list = screen.getByTestId("pack-library-list");
    for (const r of rows) {
      const item = within(list).getByTestId(`pack-library-row-${r.pack_id}`);
      expect(item).toBeDefined();
      expect(item.textContent ?? "").toContain(r.bucket);
      expect(item.textContent ?? "").toContain(r.pack_id);
    }
  });

  it("renders an empty-state message when no packs are returned", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => []) });
    render(<PackLibrary client={client} />);
    const empty = await screen.findByTestId("pack-library-empty");
    expect(empty.textContent ?? "").toMatch(/No packs/);
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
  });
});

describe("PackLibrary Rollback button", () => {
  it("renders the Rollback button when rollback_ref is set", async () => {
    const rows: PackRow[] = [
      row("foxtrot", "deployed", {
        rollback_ref: { pack_id: "foxtrot", prior_revision_id: "0".repeat(64) },
      }),
    ];
    const client = makeClient({ listInstalled: vi.fn(async () => rows) });
    render(<PackLibrary client={client} />);
    const item = await screen.findByTestId("pack-library-row-foxtrot");
    const rollback = within(item).getByRole("button", { name: /^rollback$/i });
    expect(rollback).toBeDefined();
    expect((rollback as HTMLButtonElement).disabled).toBe(false);
  });

  it("renders the Rollback button DISABLED when rollback_ref is null", async () => {
    const rows: PackRow[] = [
      row("golf", "deployed", { rollback_ref: null }),
    ];
    const client = makeClient({ listInstalled: vi.fn(async () => rows) });
    render(<PackLibrary client={client} />);
    const item = await screen.findByTestId("pack-library-row-golf");
    const rollback = within(item).getByRole("button", { name: /^rollback$/i });
    expect(rollback).toBeDefined();
    expect((rollback as HTMLButtonElement).disabled).toBe(true);
  });

  it("does not render the Rollback button for non-deployed buckets", async () => {
    const rows: PackRow[] = [
      row("hotel", "installed"),
      row("india", "configured"),
      row("juliet", "download_pending"),
      row("kilo", "purchased"),
    ];
    const client = makeClient({ listInstalled: vi.fn(async () => rows) });
    render(<PackLibrary client={client} />);
    for (const r of rows) {
      const item = await screen.findByTestId(`pack-library-row-${r.pack_id}`);
      expect(within(item).queryByRole("button", { name: /^rollback$/i })).toBeNull();
    }
  });
});
