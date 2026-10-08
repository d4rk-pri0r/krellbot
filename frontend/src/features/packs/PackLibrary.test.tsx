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

describe("PackLibrary loading / empty / rows", () => {
  it("shows the loading state until the first list resolves", () => {
    const client = makeClient({
      listInstalled: vi.fn(() => new Promise<PackRow[]>(() => {})),
    });
    render(<PackLibrary client={client} />);
    expect(screen.getByTestId("pack-library-loading")).toBeDefined();
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
    expect(screen.queryByTestId("pack-library-empty")).toBeNull();
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });

  it("renders one row per pack with bucket, id, version, permissions, rollback_ref", async () => {
    const rows: PackRow[] = [
      row("alpha", "deployed", {
        version: "2.0.0",
        permissions: ["trade"],
        rollback_ref: { pack_id: "alpha", prior_revision_id: "0".repeat(64) },
      }),
      row("bravo", "configured"),
      row("charlie", "installed"),
      row("delta", "download_pending", { version: null }),
      row("echo", "purchased"),
    ];
    const client = makeClient({ listInstalled: vi.fn(async () => rows) });
    render(<PackLibrary client={client} />);

    const list = await screen.findByTestId("pack-library-list");
    for (const r of rows) {
      const item = within(list).getByTestId(`pack-library-row-${r.pack_id}`);
      expect(item.textContent ?? "").toContain(r.bucket);
      expect(item.textContent ?? "").toContain(r.pack_id);
      expect(
        within(item).getByTestId(`pack-library-version-${r.pack_id}`).textContent,
      ).toBe(r.version ?? "—");
    }
    const alpha = within(list).getByTestId("pack-library-row-alpha");
    expect(
      within(alpha).getByTestId("pack-library-permissions-alpha").textContent,
    ).toBe("trade");
    expect(
      within(alpha).getByTestId("pack-library-rollback-ref-alpha").textContent,
    ).toBe("0".repeat(64));
    const bravo = within(list).getByTestId("pack-library-row-bravo");
    expect(
      within(bravo).getByTestId("pack-library-permissions-bravo").textContent,
    ).toBe("no permissions");
    expect(
      within(bravo).getByTestId("pack-library-rollback-ref-bravo").textContent,
    ).toBe("—");
    expect(screen.queryByTestId("pack-library-loading")).toBeNull();
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });

  it("renders an empty-state message when no packs are returned", async () => {
    const client = makeClient({ listInstalled: vi.fn(async () => []) });
    render(<PackLibrary client={client} />);
    const empty = await screen.findByTestId("pack-library-empty");
    expect(empty.textContent ?? "").toMatch(/No packs/);
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });
});

describe("PackLibrary truthful error states", () => {
  it("surfaces an HTTP refusal code and never masks it as an empty library", async () => {
    const client = makeClient({
      listInstalled: vi.fn(async () => {
        throw new PackLibraryHttpError(403, "pack library failed: 403");
      }),
    });
    render(<PackLibrary client={client} />);
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/403/);
    expect(screen.queryByTestId("pack-library-empty")).toBeNull();
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
    expect(screen.queryByTestId("pack-library-loading")).toBeNull();
  });

  it("surfaces a non-HTTP failure without inventing a status code", async () => {
    const client = makeClient({
      listInstalled: vi.fn(async () => {
        throw new TypeError("network down");
      }),
    });
    render(<PackLibrary client={client} />);
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/Pack library failed/);
    expect(error.textContent ?? "").not.toMatch(/HTTP \d+/);
  });

  it("does not retry automatically after a failure", async () => {
    const listInstalled = vi.fn(async () => {
      throw new PackLibraryHttpError(500, "pack library failed: 500");
    });
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-error");
    await new Promise((resolve) => {
      setTimeout(resolve, 30);
    });
    expect(listInstalled).toHaveBeenCalledTimes(1);
  });
});

describe("PackLibrary Refresh", () => {
  it("refetches on demand and replaces the rows", async () => {
    let call = 0;
    const listInstalled = vi.fn(async (): Promise<PackRow[]> => {
      call += 1;
      return call === 1
        ? [row("alpha", "installed")]
        : [row("alpha", "installed"), row("bravo", "deployed")];
    });
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-row-alpha");
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    await screen.findByTestId("pack-library-row-bravo");
    expect(listInstalled).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });

  it("keeps the previous rows visible while a refresh is in flight", async () => {
    let release: (() => void) | null = null;
    const listInstalled = vi.fn(async (): Promise<PackRow[]> => {
      if (listInstalled.mock.calls.length === 1) {
        return [row("alpha", "installed")];
      }
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return [];
    });
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-row-alpha");
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    expect(screen.getByTestId("pack-library-row-alpha")).toBeDefined();
    expect(screen.getByTestId("pack-library-refresh").textContent).toMatch(/Refreshing/);
    await waitFor(() => {
      expect(release).not.toBeNull();
    });
    (release as () => void)();
    await waitFor(() => {
      expect(screen.queryByTestId("pack-library-row-alpha")).toBeNull();
    });
    expect(screen.getByTestId("pack-library-empty")).toBeDefined();
  });

  it("a failed refresh surfaces the new refusal code without clearing rows", async () => {
    let call = 0;
    const listInstalled = vi.fn(async (): Promise<PackRow[]> => {
      call += 1;
      if (call === 1) {
        return [row("alpha", "installed")];
      }
      throw new PackLibraryHttpError(403, "pack library failed: 403");
    });
    render(<PackLibrary client={makeClient({ listInstalled })} />);
    await screen.findByTestId("pack-library-row-alpha");
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/403/);
    // Stale rows stay: a failed refresh is not an empty library.
    expect(screen.getByTestId("pack-library-row-alpha")).toBeDefined();
  });
});

describe("PackLibrary click-to-copy pack_id", () => {
  it("copies the clicked row's pack_id and shows Copied feedback on that row", async () => {
    const written = stubClipboard();
    const rows = [row("alpha", "installed"), row("bravo", "deployed")];
    render(
      <PackLibrary client={makeClient({ listInstalled: vi.fn(async () => rows) })} />,
    );
    await screen.findByTestId("pack-library-list");

    fireEvent.click(screen.getByTestId("pack-library-copy-alpha"));
    await waitFor(() => {
      expect(written).toEqual(["alpha"]);
    });
    expect(
      screen.getByTestId("pack-library-copy-feedback-alpha").textContent,
    ).toBe("Copied");
    expect(
      screen.getByTestId("pack-library-copy-feedback-bravo").textContent,
    ).toBe("Copy");
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });

  it("does not claim a copy when the clipboard write is refused", async () => {
    stubClipboard([]);
    render(
      <PackLibrary
        client={makeClient({ listInstalled: vi.fn(async () => [row("alpha", "installed")]) })}
      />,
    );
    await screen.findByTestId("pack-library-row-alpha");
    fireEvent.click(screen.getByTestId("pack-library-copy-alpha"));
    await new Promise((resolve) => {
      setTimeout(resolve, 10);
    });
    expect(screen.getByTestId("pack-library-copy-feedback-alpha").textContent).toBe(
      "Copy",
    );
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });
});

describe("PackLibrary is read-only", () => {
  it("renders no install, catalog, entitlement, or rollback control", async () => {
    const rollback = vi.fn(async () => ({ ok: true }));
    const rows = [
      row("alpha", "deployed", {
        rollback_ref: { pack_id: "alpha", prior_revision_id: "0".repeat(64) },
      }),
      row("bravo", "installed"),
    ];
    render(
      <PackLibrary client={makeClient({ rollback, listInstalled: vi.fn(async () => rows) })} />,
    );
    await screen.findByTestId("pack-library-list");
    for (const r of rows) {
      const item = screen.getByTestId(`pack-library-row-${r.pack_id}`);
      const buttons = within(item).getAllByRole("button");
      expect(buttons).toHaveLength(1);
      expect(buttons[0].getAttribute("data-testid")).toBe(
        `pack-library-copy-${r.pack_id}`,
      );
    }
    expect(rollback).not.toHaveBeenCalled();
    const panelText =
      screen.getByTestId("pack-library-panel").textContent ?? "";
    expect(panelText).not.toMatch(/\b(install|catalog|entitle|rollback)\b/i);
  });
});
