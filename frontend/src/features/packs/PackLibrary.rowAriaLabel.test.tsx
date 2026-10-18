import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackLibrary, type PackLibraryClient, type PackRow } from "./PackLibrary";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeClient(rows: PackRow[]): PackLibraryClient {
  return {
    listInstalled: vi.fn(async () => rows),
    rollback: vi.fn(async () => ({ ok: true })),
  };
}

function fullRow(): PackRow {
  return {
    bucket: "download_pending",
    pack_id: "alpha-pack",
    version: "2.3.1",
    permissions: ["read:keys", "write:notes"],
    rollback_ref: { pack_id: "alpha-pack", prior_revision_id: "rev-009" },
  };
}

describe("PackLibrary row aria-label summary", () => {
  it("labels each row <li> with one concise summary of its whole state", async () => {
    render(<PackLibrary client={makeClient([fullRow()])} />);
    await screen.findByTestId("pack-library-list");

    const row = screen.getByTestId("pack-library-row-alpha-pack");
    expect(row.tagName).toBe("LI");
    expect(row.getAttribute("aria-label")).toBe(
      "Pack alpha-pack, bucket Download pending, version 2.3.1, " +
        "permissions read:keys, write:notes, prior revision rev-009",
    );
  });

  it("speaks humanized fallbacks for missing version, permissions and prior revision", async () => {
    const sparse: PackRow = {
      bucket: "installed",
      pack_id: "bravo-pack",
      version: null,
      permissions: [],
      rollback_ref: null,
    };
    render(<PackLibrary client={makeClient([sparse])} />);
    await screen.findByTestId("pack-library-list");

    expect(screen.getByTestId("pack-library-row-bravo-pack").getAttribute("aria-label")).toBe(
      "Pack bravo-pack, bucket Installed, version unspecified, " +
        "permissions none, prior revision —",
    );
  });

  it("keeps every existing child testid, visible text and copy-button label queryable", async () => {
    const row = fullRow();
    render(<PackLibrary client={makeClient([row])} />);
    await screen.findByTestId("pack-library-list");

    const id = "alpha-pack";
    expect(screen.getByTestId(`pack-library-bucket-${id}`).textContent).toBe(
      "download_pending (Download pending)",
    );
    expect(screen.getByTestId(`pack-library-id-${id}`).textContent).toBe(id);
    const copy = screen.getByTestId(`pack-library-copy-${id}`);
    expect(copy.getAttribute("aria-label")).toBe(`Copy pack_id ${id}`);
    expect(screen.getByTestId(`pack-library-copy-feedback-${id}`).textContent).toBe("Copy");
    expect(screen.getByTestId(`pack-library-version-${id}`).textContent).toBe("2.3.1");
    expect(screen.getByTestId(`pack-library-permissions-${id}`).textContent).toBe(
      "read:keys, write:notes",
    );
    expect(screen.getByTestId(`pack-library-rollback-ref-${id}`).textContent).toBe("rev-009");
    // The <li> keeps its listitem semantics and styling; only the label is new.
    const li = screen.getByTestId(`pack-library-row-${id}`);
    expect(li.getAttribute("role")).toBeNull();
    expect(li.className).toBe("kbot-pack-library__row");
  });

  it("labels every visible row independently under bucket filtering", async () => {
    render(
      <PackLibrary
        client={makeClient([
          { ...fullRow(), bucket: "deployed", pack_id: "alpha-pack" },
          { bucket: "purchased", pack_id: "charlie-pack", version: "0.1.0", permissions: [], rollback_ref: null },
        ])}
      />,
    );
    await screen.findByTestId("pack-library-list");

    fireEvent.change(screen.getByTestId("pack-library-bucket-select"), {
      target: { value: "purchased" },
    });
    expect(screen.queryByTestId("pack-library-row-alpha-pack")).toBeNull();
    expect(screen.getByTestId("pack-library-row-charlie-pack").getAttribute("aria-label")).toBe(
      "Pack charlie-pack, bucket Purchased, version 0.1.0, permissions none, prior revision —",
    );
  });
});
