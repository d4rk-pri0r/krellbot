import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type LoadedRevision, type StrategyClient } from "./Editor";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);

// A pack that is exactly the supported single-average subset, so the
// readable form can be derived from the imported bytes.
const supportedImportedPack = {
  schema_version: 1,
  id: "imported-plan",
  version: "1.0.0",
  label: "Imported plan",
  author: "local workstation",
  timeframe: "4h",
  indicators: { ma: { fn: "ema", src: "close", len: 36 } },
  entry: ["close", "crosses_above", "ma"],
  exit: ["close", "crosses_below", "ma"],
  risk: { max_account_pct: 40, stop: { type: "pct", pct: 6.5 } },
  markets: [{ venue: "kraken", pair: "XXBTZUSD" }],
};

const supportedImportedBytes = JSON.stringify(supportedImportedPack, null, 2);

// Nested conditions and an atr stop: outside the supported subset, so the
// form must never be invented for it and the bytes stay untouched.
const unsupportedImportedPack = {
  schema_version: 1,
  id: "imported-mix",
  version: "1.2.0",
  label: "Imported mixed pack",
  author: "someone else",
  origin: "Imported from a file. Ownership not verified.",
  timeframe: "4h",
  indicators: {
    fast: { fn: "ema", src: "close", len: 12 },
    slow: { fn: "sma", src: "close", len: 40 },
  },
  entry: { all: [["close", "crosses_above", "fast"], ["close", ">", "slow"]] },
  exit: ["close", "<", "slow"],
  risk: { max_account_pct: 10, stop: { type: "atr", len: 14, mult: 2 } },
  markets: [
    { venue: "kraken", pair: "XXBTZUSD" },
    { venue: "coinbase", pair: "BTC-USD" },
  ],
};

const unsupportedImportedBytes = JSON.stringify(unsupportedImportedPack, null, 2);

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack: Record<string, unknown>) => ({
      revision_id: "rev-import-created",
      state: "draft",
      pack,
      errors: [],
      outcome: "created",
    })),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Record<string, unknown>) => ({
        revision_id: "rev-edit",
        parent_revision_id: parentRevisionId,
        state: "draft",
        pack,
        errors: [],
        outcome: "created",
      }),
    ),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-validated",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function loadedRevision(
  bytes: string,
  state: LoadedRevision["state"] = "validated",
): LoadedRevision {
  return { revision_id: "rev-parent", state, bytes };
}

function jsonFile(text: string): File {
  return new File([text], "pack.json", { type: "application/json" });
}

async function importFile(text: string): Promise<void> {
  const fileInput = screen.getByLabelText(/import pack file/i) as HTMLInputElement;
  fireEvent.change(fileInput, { target: { files: [jsonFile(text)] } });
  await waitFor(() => {
    expect((screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value).toBe(
      text,
    );
  });
}

const parentBytes = JSON.stringify(seedOwnedStrategyPack("Trend plan"), null, 2);

describe("Editor import → Save reset (previously-saved revision)", () => {
  it("importing a pack file makes the next Save call create, never edit on the loaded revision", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    await importFile(supportedImportedBytes);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.edit).not.toHaveBeenCalled();
    const pack = (client.create as ReturnType<typeof vi.fn>).mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(pack.id).toBe("imported-plan");
    expect(pack.label).toBe("Imported plan");
  });

  it("the rendered Save outcome reflects the revision the create returned", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    await importFile(supportedImportedBytes);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    const outcome = await screen.findByTestId("editor-save-outcome");
    expect(outcome.textContent).toMatch(/saved new revision rev-import-created/);
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-import-created/,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).not.toMatch(
      /rev-parent/,
    );
  });

  it("a second Save after the imported create edits the newly created revision", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    await importFile(supportedImportedBytes);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await screen.findByTestId("editor-save-outcome");

    fireEvent.change(screen.getByLabelText(/^label$/i), {
      target: { value: "Renamed import" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    const [parentId, pack] = (client.edit as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Record<string, unknown>];
    expect(parentId).toBe("rev-import-created");
    expect(pack.label).toBe("Renamed import");
  });

  it("importing clears the prior revision's outcome, validate error, arm error and identity", async () => {
    const client = makeClient({
      validate: vi.fn().mockRejectedValue(new Error("stale revision gone")),
      arm: vi.fn().mockRejectedValue(new Error("arm refused")),
    });
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    // Produce real stale surfaces from the loaded revision first.
    fireEvent.click(screen.getByRole("button", { name: /^validate$/i }));
    expect(await screen.findByTestId("editor-validate-error")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /^arm$/i }));
    expect(await screen.findByTestId("editor-arm-error")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByTestId("editor-save-outcome")).toBeDefined();

    await importFile(supportedImportedBytes);

    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(screen.queryByTestId("editor-arm-error")).toBeNull();
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(
      screen.getByText(/no saved revision yet — save creates one\./i),
    ).toBeDefined();
    expect(
      (screen.getByRole("button", { name: /^validate$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(client.arm).toHaveBeenCalledTimes(1);
  });

  it("derives the readable form from the imported bytes without inventing form state", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    await importFile(supportedImportedBytes);

    expect(screen.getByTestId("owned-strategy-form")).toBeDefined();
    expect(
      (screen.getByLabelText(/strategy name/i) as HTMLInputElement).value,
    ).toBe("Imported plan");
    expect(
      (screen.getByLabelText(/average length \(bars\)/i) as HTMLInputElement).value,
    ).toBe("36");
    expect(screen.queryByTestId("owned-strategy-form-unsupported")).toBeNull();
  });

  it("an unsupported imported pack stays unsupported and its Save still goes through create", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    await importFile(unsupportedImportedBytes);

    expect(screen.getByTestId("owned-strategy-form-unsupported")).toBeDefined();
    expect(screen.queryByTestId("owned-strategy-form")).toBeNull();
    expect(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    ).toBe(unsupportedImportedBytes);

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.edit).not.toHaveBeenCalled();
    const pack = (client.create as ReturnType<typeof vi.fn>).mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(pack.entry).toEqual(unsupportedImportedPack.entry);
  });
});

describe("Editor import → Save reset (no previous revision)", () => {
  it("importing with no loaded revision keeps Save on the create path", async () => {
    const client = makeClient();
    render(<Editor client={client} />);

    await importFile(supportedImportedBytes);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("a failed import keeps the previously-loaded revision identity so Save still edits it", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedRevision(parentBytes)} />);

    const fileInput = screen.getByLabelText(/import pack file/i) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [jsonFile("not-json")] } });
    expect(await screen.findByTestId("editor-import-error")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    const [parentId] = (client.edit as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
    ];
    expect(parentId).toBe("rev-parent");
    expect(client.create).not.toHaveBeenCalled();
  });
});
