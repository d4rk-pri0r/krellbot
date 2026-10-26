import {
  cleanup,
  fireEvent,
  render,
  screen,
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

function row(pack_id: string, bucket: PackRow["bucket"]): PackRow {
  return { bucket, pack_id, version: "1.0.0", permissions: [], rollback_ref: null };
}

/**
 * Controllable synthetic client: `listInstalled` walks a scripted sequence of
 * settled reads (rows or a thrown failure), one entry per call, so each test
 * states exactly what the guarded backend returned for the ordinary load and
 * every later Refresh. Mutating methods stay instrumented and unused.
 */
type ReadStep =
  | { kind: "rows"; rows: PackRow[] }
  | { kind: "fail"; error: unknown };

function scriptClient(steps: ReadStep[]): {
  client: PackLibraryClient;
  listInstalled: ReturnType<typeof vi.fn>;
  rollback: ReturnType<typeof vi.fn>;
} {
  let call = 0;
  const listInstalled = vi.fn(async (): Promise<PackRow[]> => {
    const step = steps[Math.min(call, steps.length - 1)];
    call += 1;
    if (step.kind === "fail") {
      throw step.error;
    }
    return step.rows;
  });
  const rollback = vi.fn(async () => ({ ok: true }));
  return { client: makeClient({ listInstalled, rollback }), listInstalled, rollback };
}

function bucketSelect(): HTMLSelectElement {
  return screen.getByTestId("pack-library-bucket-select") as HTMLSelectElement;
}

function optionValues(select: HTMLSelectElement): string[] {
  return [...select.options].map((option) => option.value);
}

function optionByValue(
  select: HTMLSelectElement,
  value: string,
): HTMLOptionElement {
  const matches = [...select.options].filter((option) => option.value === value);
  expect(matches).toHaveLength(1);
  return matches[0];
}

describe("PackLibrary refresh keeps the selected bucket filter truthful", () => {
  it("keeps the selected bucket as an explicit option and filters truthfully when Refresh drops it from inventory", async () => {
    const { client } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      {
        kind: "rows",
        rows: [row("charlie", "deployed"), row("delta", "deployed")],
      },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(bucketSelect(), { target: { value: "installed" } });
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "1 of 2 packs shown",
    );

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    await screen.findByTestId("pack-library-no-matches");

    // The hidden state still filters by "installed": the control must keep an
    // explicit option for it, with the bucket's existing wording, so the DOM
    // selector agrees with the count instead of silently showing "all".
    const select = bucketSelect();
    expect(optionValues(select)).toEqual(
      expect.arrayContaining(["all", "deployed", "installed"]),
    );
    expect(optionValues(select)).toHaveLength(3);
    expect(select.value).toBe("installed");
    expect(optionByValue(select, "installed").textContent).toBe("installed");
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "0 of 2 packs shown",
    );
    expect(screen.queryByTestId("pack-library-list")).toBeNull();
    expect(screen.queryByTestId("pack-library-error")).toBeNull();
  });

  it("Clear search & filter reveals all refreshed rows without touching the search query's refresh behavior", async () => {
    const { client } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      {
        kind: "rows",
        rows: [row("charlie", "deployed"), row("delta", "deployed")],
      },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(bucketSelect(), { target: { value: "installed" } });
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    await screen.findByTestId("pack-library-no-matches");

    fireEvent.click(screen.getByTestId("pack-library-clear-filters"));
    const list = await screen.findByTestId("pack-library-list");
    expect(bucketSelect().value).toBe("all");
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "2 of 2 packs shown",
    );
    for (const pack_id of ["charlie", "delta"]) {
      expect(within(list).getByTestId(`pack-library-row-${pack_id}`)).toBeDefined();
    }
    expect(screen.queryByTestId("pack-library-no-matches")).toBeNull();
  });

  it("shows the returning bucket exactly once when a later Refresh brings it back", async () => {
    const { client } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      {
        kind: "rows",
        rows: [row("charlie", "deployed"), row("delta", "deployed")],
      },
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("charlie", "deployed")],
      },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(bucketSelect(), { target: { value: "installed" } });
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    await screen.findByTestId("pack-library-no-matches");

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const list = await screen.findByTestId("pack-library-list");

    const select = bucketSelect();
    expect(optionValues(select)).toEqual(
      expect.arrayContaining(["all", "deployed", "installed"]),
    );
    expect(optionValues(select)).toHaveLength(3);
    expect(select.value).toBe("installed");
    expect(within(list).getByTestId("pack-library-row-alpha")).toBeDefined();
    expect(screen.queryByTestId("pack-library-row-charlie")).toBeNull();
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "1 of 2 packs shown",
    );
  });

  it("preserves the search query across a Refresh that changes inventory", async () => {
    const { client } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      {
        kind: "rows",
        rows: [row("bravo", "deployed"), row("charlie", "deployed")],
      },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(screen.getByTestId("pack-library-search"), {
      target: { value: "bravo" },
    });

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const list = await screen.findByTestId("pack-library-list");

    expect(screen.getByTestId("pack-library-search")).toHaveProperty(
      "value",
      "bravo",
    );
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "1 of 2 packs shown",
    );
    expect(within(list).getByTestId("pack-library-row-bravo")).toBeDefined();
    expect(screen.queryByTestId("pack-library-row-charlie")).toBeNull();
  });

  it("keeps the prior inventory, selected filter option and surfaces the error when Refresh fails", async () => {
    const { client } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      { kind: "fail", error: new PackLibraryHttpError(403, "pack library failed: 403") },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(bucketSelect(), { target: { value: "installed" } });

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const error = await screen.findByTestId("pack-library-error");
    expect(error.textContent ?? "").toMatch(/403/);

    const select = bucketSelect();
    expect(select.value).toBe("installed");
    expect(optionValues(select)).toEqual(
      expect.arrayContaining(["all", "deployed", "installed"]),
    );
    expect(optionValues(select)).toHaveLength(3);
    expect(screen.getByTestId("pack-library-row-alpha")).toBeDefined();
    expect(screen.queryByTestId("pack-library-row-bravo")).toBeNull();
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "1 of 2 packs shown",
    );
  });

  it("recovers from an empty inventory to a nonempty one with the selection intact", async () => {
    const { client } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      { kind: "rows", rows: [] },
      { kind: "rows", rows: [row("alpha", "installed")] },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(bucketSelect(), { target: { value: "installed" } });

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const empty = await screen.findByTestId("pack-library-empty");
    expect(empty.textContent ?? "").toMatch(/No packs/);
    expect(screen.queryByTestId("pack-library-error")).toBeNull();

    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    const list = await screen.findByTestId("pack-library-list");
    const select = bucketSelect();
    expect(select.value).toBe("installed");
    expect(optionValues(select)).toEqual(
      expect.arrayContaining(["all", "installed"]),
    );
    expect(optionValues(select)).toHaveLength(2);
    expect(within(list).getByTestId("pack-library-row-alpha")).toBeDefined();
    expect(screen.getByTestId("pack-library-count").textContent).toBe(
      "1 of 1 packs shown",
    );
  });

  it("only ever reads: no rollback or other mutating client call in these flows", async () => {
    const { client, listInstalled, rollback } = scriptClient([
      {
        kind: "rows",
        rows: [row("alpha", "installed"), row("bravo", "deployed")],
      },
      {
        kind: "rows",
        rows: [row("charlie", "deployed"), row("delta", "deployed")],
      },
      { kind: "fail", error: new PackLibraryHttpError(500, "pack library failed: 500") },
    ]);
    render(<PackLibrary client={client} />);
    await screen.findByTestId("pack-library-list");
    fireEvent.change(bucketSelect(), { target: { value: "installed" } });
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    await screen.findByTestId("pack-library-no-matches");
    fireEvent.click(screen.getByTestId("pack-library-refresh"));
    await screen.findByTestId("pack-library-error");

    expect(listInstalled).toHaveBeenCalledTimes(3);
    expect(rollback).not.toHaveBeenCalled();
  });
});
