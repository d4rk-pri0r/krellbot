import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);

const validPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

const validPackBytes = JSON.stringify(validPack, null, 2);

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Record<string, unknown>) => ({
        revision_id: "rev-edit",
        parent_revision_id: parentRevisionId,
        state: "draft",
        pack,
        errors: [],
      }),
    ),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-validate",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("Editor form/JSON sync", () => {
  it("renders a label field and a raw JSON textarea", () => {
    render(<Editor client={makeClient()} />);
    expect(screen.getByLabelText(/label/i)).toBeDefined();
    expect(screen.getByLabelText(/raw json/i)).toBeDefined();
  });

  it("changing the label updates the raw JSON view", () => {
    render(<Editor client={makeClient()} />);
    const textarea = screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: validPackBytes } });
    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: "Edited label" },
    });
    const parsed = JSON.parse(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    );
    expect(parsed.label).toBe("Edited label");
  });

  it("changing the raw JSON view updates the label field", () => {
    render(<Editor client={makeClient()} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });
    expect((screen.getByLabelText(/label/i) as HTMLInputElement).value).toBe(
      "Trend follow",
    );
  });

  it("a round-trip preserves id, label, timeframe, entry, and exit", () => {
    render(<Editor client={makeClient()} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });

    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: "Edited label" },
    });
    const afterLabel = JSON.parse(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    );
    expect(afterLabel.id).toBe("trend-follow");
    expect(afterLabel.label).toBe("Edited label");
    expect(afterLabel.timeframe).toBe("1h");
    expect(afterLabel.entry).toEqual(["close", ">", "sma20"]);
    expect(afterLabel.exit).toEqual(["close", "<", "sma20"]);

    const rewritten = JSON.stringify(
      { ...afterLabel, indicator: "sma" },
      null,
      2,
    );
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: rewritten },
    });
    const parsed = JSON.parse(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    );
    expect(parsed.id).toBe("trend-follow");
    expect(parsed.label).toBe("Edited label");
    expect(parsed.timeframe).toBe("1h");
    expect(parsed.entry).toEqual(["close", ">", "sma20"]);
    expect(parsed.exit).toEqual(["close", "<", "sma20"]);
  });
});

describe("Editor save", () => {
  it("Save calls client.create and does not write localStorage", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const calledWith = (client.create as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(calledWith.id).toBe("trend-follow");
    expect(calledWith.label).toBe("Trend follow");
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });

  it("Save does not mutate a deployedBytes string passed into the editor", async () => {
    const deployedBytes = validPackBytes;
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "deployed",
          bytes: deployedBytes,
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: "Edited label" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    expect(deployedBytes).toBe(validPackBytes);
  });

  it("when initial state is deployed, Save calls edit and renders the new revision_id", async () => {
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "deployed",
          bytes: validPackBytes,
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: "Edited label" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    const [parent, pack] = (client.edit as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Record<string, unknown>];
    expect(parent).toBe("rev-parent");
    expect(pack.label).toBe("Edited label");
    expect(
      screen.getByTestId("editor-revision-id").textContent,
    ).toMatch(/rev-edit/);
  });

  it("when initial state is not deployed, Save also calls edit", async () => {
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "draft",
          bytes: validPackBytes,
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    expect(client.create).not.toHaveBeenCalled();
  });
});

describe("Editor M2-WRITE save outcomes", () => {
  it("unchanged save renders 'No change: revision <id> kept' and does not call onRevision", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      edit: vi.fn().mockResolvedValue({
        revision_id: "rev-parent",
        parent_revision_id: null,
        state: "validated",
        pack: validPack,
        errors: [],
        outcome: "unchanged",
      }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "validated",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const outcome = await screen.findByTestId("editor-save-outcome");
    expect(outcome.textContent).toMatch(/No change: revision rev-parent kept/);
    expect(onRevision).not.toHaveBeenCalled();
  });

  it("created save renders 'Saved new revision <id>' and surfaces the outcome", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      edit: vi.fn().mockResolvedValue({
        revision_id: "rev-new",
        parent_revision_id: "rev-parent",
        state: "draft",
        pack: validPack,
        errors: [],
        outcome: "created",
      }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "draft",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const outcome = await screen.findByTestId("editor-save-outcome");
    expect(outcome.textContent).toMatch(/Saved new revision rev-new/);
    expect(onRevision).toHaveBeenCalledTimes(1);
  });

  it("strategy id mismatch error renders an alert and surfaces strategy_id_mismatch", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      edit: vi.fn().mockRejectedValue(
        new Error("request failed: 409 strategy_id_mismatch"),
      ),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "draft",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/strategy_id_mismatch/);
  });

  it("save with a missing server outcome renders 'Saved revision <id>' and never 'Saved new revision' (W3)", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      edit: vi.fn().mockResolvedValue({
        revision_id: "rev-no-outcome",
        parent_revision_id: "rev-parent",
        state: "draft",
        pack: validPack,
        errors: [],
      }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "draft",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const outcome = await screen.findByTestId("editor-save-outcome");
    expect(outcome.textContent).toMatch(/Saved revision rev-no-outcome/);
    expect(outcome.textContent).not.toMatch(/Saved new revision/);
  });
});

describe("Editor validation", () => {
  it("renders validation errors with field text next to the message", async () => {
    const client = makeClient({
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-validate",
        state: "draft",
        pack: validPack,
        errors: [{ field: "entry", message: "operand is invalid" }],
      }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes: validPackBytes,
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    expect(await screen.findByText(/entry/)).toBeDefined();
    expect(await screen.findByText(/operand is invalid/)).toBeDefined();
    const errorBlock = screen.getByTestId("editor-error-entry");
    expect(errorBlock.textContent).toMatch(/entry/);
    expect(errorBlock.textContent).toMatch(/operand is invalid/);
  });

  it("Arm control is disabled when state is draft", () => {
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes: validPackBytes,
        }}
      />,
    );
    const arm = screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement;
    expect(arm.disabled).toBe(true);
  });

  it("Arm control is enabled when state is validated", async () => {
    const client = makeClient({
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-1",
        state: "validated",
        pack: validPack,
        errors: [],
      }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes: validPackBytes,
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });
  });

  it("a rejected validate call shows a validation error alert, keeps the last known revision/state, and does not imply success", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      validate: vi.fn().mockRejectedValueOnce(new Error("network down")),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));

    const error = await screen.findByTestId("editor-validate-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(/network down/);
    expect(error.textContent).toMatch(/validat/i);

    // Last known revision/state is retained, not invented or promoted.
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-1 \(state: draft\)/,
    );
    expect(onRevision).not.toHaveBeenCalled();
    expect(
      (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("an explicit retry that succeeds replaces the validation error and updates the real revision/state", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      validate: vi
        .fn()
        .mockRejectedValueOnce(new Error("network down"))
        .mockResolvedValueOnce({
          revision_id: "rev-validated",
          state: "validated",
          pack: validPack,
          errors: [],
        }),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "draft",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    expect(await screen.findByTestId("editor-validate-error")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
        /rev-validated \(state: validated\)/,
      );
    });
    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(client.validate).toHaveBeenCalledTimes(2);
    expect(onRevision).toHaveBeenCalledTimes(1);
    expect(onRevision.mock.calls[0][0].revision_id).toBe("rev-validated");
    expect(onRevision.mock.calls[0][0].state).toBe("validated");
  });
});

describe("Editor arm", () => {
  it("a pending arm request refuses a second click, and its rejection shows an arm failure alert without fabricating or retrying", async () => {
    const onRevision = vi.fn();
    const rejections: Array<(reason?: unknown) => void> = [];
    const client = makeClient({
      arm: vi.fn().mockImplementation(
        () =>
          new Promise<void>((_, reject) => {
            rejections.push(reject);
          }),
      ),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );

    const arm = screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement;
    fireEvent.click(arm);
    fireEvent.click(arm);
    expect(client.arm).toHaveBeenCalledTimes(1);

    rejections[0](new Error("venue unreachable"));

    const error = await screen.findByTestId("editor-arm-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(/arm/i);
    expect(error.textContent).toMatch(/venue unreachable/);

    // Validated revision/state is preserved; nothing is invented or promoted.
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-1 \(state: validated\)/,
    );
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();

    // Give any automatic retry a chance to happen, then prove it never did.
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(client.arm).toHaveBeenCalledTimes(1);
    expect(arm.disabled).toBe(false);
  });

  it("an explicit retry after a rejected arm issues exactly a second call, clears the error, and does not claim a deployment", async () => {
    const onRevision = vi.fn();
    const client = makeClient({
      arm: vi
        .fn()
        .mockRejectedValueOnce(new Error("venue unreachable"))
        .mockResolvedValueOnce(undefined),
    });
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: validPackBytes,
        }}
        onRevision={onRevision}
      />,
    );

    const arm = screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement;
    fireEvent.click(arm);
    expect(await screen.findByTestId("editor-arm-error")).toBeDefined();

    fireEvent.click(arm);
    await waitFor(() => {
      expect(screen.queryByTestId("editor-arm-error")).toBeNull();
    });
    expect(client.arm).toHaveBeenCalledTimes(2);
    expect((client.arm as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual([
      "rev-1",
      "kraken",
      "1000",
    ]);
    expect((client.arm as ReturnType<typeof vi.fn>).mock.calls[1]).toEqual([
      "rev-1",
      "kraken",
      "1000",
    ]);

    // Controls are restored without implying a deployment from stale local state.
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-1 \(state: validated\)/,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).not.toMatch(
      /deployed/,
    );
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(arm.disabled).toBe(false);
  });
});

describe("Editor import", () => {
  it("Import with valid JSON leaves the editor without saving", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("Importing JSON that fails JSON.parse shows 'Invalid JSON' and does not call save", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: "not json {" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));
    expect(await screen.findByText(/invalid json/i)).toBeDefined();
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("Save with invalid JSON shows 'Invalid JSON' and does not call save", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: "not json {" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByText(/invalid json/i)).toBeDefined();
    expect(client.create).not.toHaveBeenCalled();
  });

  it("Importing a pack file with valid JSON fills the textarea and does not call save", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    const file = new File(['{"label":"from-file"}'], "pack.json", {
      type: "application/json",
    });
    const fileInput = screen.getByLabelText(/import pack file/i) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
      ).toBe('{"label":"from-file"}');
    });
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("Importing a pack file with invalid JSON shows 'Invalid JSON' and does not call save", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    const file = new File(["not-json"], "pack.json", {
      type: "application/json",
    });
    const fileInput = screen.getByLabelText(/import pack file/i) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    expect(await screen.findByText(/invalid json/i)).toBeDefined();
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });
});

describe("Editor export", () => {
  it("Export pack creates an object URL from the current textarea text and an anchor with download 'pack.json'", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    const textarea = screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: validPackBytes } });

    const originalCreateElement = document.createElement.bind(document);
    const createObjectURLSpy = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test-url");
    const revokeObjectURLSpy = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const createElementSpy = vi.spyOn(document, "createElement");
    const capturedAnchors: HTMLAnchorElement[] = [];
    createElementSpy.mockImplementation(((tag: string) => {
      const element = originalCreateElement(tag);
      if (tag === "a" && element instanceof HTMLAnchorElement) {
        capturedAnchors.push(element);
      }
      return element;
    }) as typeof document.createElement);

    fireEvent.click(screen.getByRole("button", { name: /^export pack$/i }));

    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(await blob.text()).toBe(validPackBytes);

    const downloadAnchors = capturedAnchors.filter(
      (a) => a.download === "pack.json",
    );
    expect(downloadAnchors.length).toBeGreaterThan(0);
    expect(downloadAnchors[0].download).toBe("pack.json");

    clickSpy.mockRestore();
    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
    createElementSpy.mockRestore();
  });
});

const ownedUnsupportedImportedPack = {
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
  risk: {
    max_account_pct: 10,
    stop: { type: "atr", len: 14, mult: 2 },
  },
  markets: [
    { venue: "kraken", pair: "XXBTZUSD" },
    { venue: "coinbase", pair: "BTC-USD" },
  ],
};

describe("Editor owned-strategy form: no-JSON creation", () => {
  it("Create new owned strategy seeds a full valid pack and Save sends it to client.create", async () => {
    const client = makeClient();
    render(<Editor client={client} />);

    expect(screen.queryByTestId("owned-strategy-form")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: /create new owned strategy/i }),
    );
    expect(screen.getByTestId("owned-strategy-form")).toBeDefined();

    fireEvent.change(screen.getByLabelText(/strategy name/i), {
      target: { value: "My trend plan" },
    });
    const seededJson = (
      screen.getByLabelText(/raw json/i) as HTMLTextAreaElement
    ).value;
    expect(seededJson).not.toBe("");
    const seeded = JSON.parse(seededJson);
    expect(seeded.schema_version).toBe(1);
    expect(seeded.indicators).toEqual({
      ma: { fn: "sma", src: "close", len: 20 },
    });
    expect(seeded.entry).toEqual(["close", ">", "ma"]);

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const pack = (client.create as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(pack.label).toBe("My trend plan");
    expect(pack.entry).toEqual(["close", ">", "ma"]);
    expect(pack.risk).toEqual({
      max_account_pct: 25,
      stop: { type: "pct", pct: 5 },
    });
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("changing form parameters reaches the client payload, not just form state", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.click(
      screen.getByRole("button", { name: /create new owned strategy/i }),
    );

    fireEvent.change(screen.getByLabelText(/average length \(bars\)/i), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByLabelText(/enter when/i), {
      target: { value: "crosses_above" },
    });
    fireEvent.change(screen.getByLabelText(/exit when/i), {
      target: { value: "crosses_below" },
    });
    fireEvent.change(screen.getByLabelText(/max account percent/i), {
      target: { value: "40" },
    });
    fireEvent.change(screen.getByLabelText(/protective stop percent/i), {
      target: { value: "2.5" },
    });
    fireEvent.change(screen.getByLabelText(/kraken pair/i), {
      target: { value: "XETHZUSD" },
    });
    fireEvent.change(screen.getByLabelText(/average type/i), {
      target: { value: "ema" },
    });
    fireEvent.change(screen.getByLabelText(/timeframe/i), {
      target: { value: "4h" },
    });

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const pack = (client.create as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(pack.indicators).toEqual({
      ma: { fn: "ema", src: "close", len: 50 },
    });
    expect(pack.entry).toEqual(["close", "crosses_above", "ma"]);
    expect(pack.exit).toEqual(["close", "crosses_below", "ma"]);
    expect(pack.timeframe).toBe("4h");
    expect(pack.risk).toEqual({
      max_account_pct: 40,
      stop: { type: "pct", pct: 2.5 },
    });
    expect(pack.markets).toEqual([{ venue: "kraken", pair: "XETHZUSD" }]);
  });

  it("an invalid value refuses to generate a pack and keeps the last good payload for Save", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.click(
      screen.getByRole("button", { name: /create new owned strategy/i }),
    );
    const goodJson = (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement)
      .value;
    expect(goodJson).not.toBe("");

    fireEvent.change(screen.getByLabelText(/average length \(bars\)/i), {
      target: { value: "600" },
    });
    const problems = await screen.findByTestId("owned-strategy-form-problems");
    expect(problems.textContent).toMatch(/between 2 and 599/);
    expect((screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value).toBe(
      goodJson,
    );

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const pack = (client.create as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(pack.indicators).toEqual({
      ma: { fn: "sma", src: "close", len: 20 },
    });
  });

  it("Save after a form edit of a loaded supported revision uses the immutable parentId flow", async () => {
    const client = makeClient();
    const seeded = seedOwnedStrategyPack("Trend plan");
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "validated",
          bytes: JSON.stringify(seeded, null, 2),
        }}
      />,
    );
    expect(screen.getByTestId("owned-strategy-form")).toBeDefined();
    fireEvent.change(screen.getByLabelText(/protective stop percent/i), {
      target: { value: "7" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    const [parentId, pack] = (client.edit as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Record<string, unknown>];
    expect(parentId).toBe("rev-parent");
    expect(pack.risk).toEqual({
      max_account_pct: 25,
      stop: { type: "pct", pct: 7 },
    });
    expect(client.create).not.toHaveBeenCalled();
    expect(seeded.risk).toEqual({
      max_account_pct: 25,
      stop: { type: "pct", pct: 5 },
    });
  });

  it("an unsupported imported pack is not rewritten or stripped and the JSON round-trips byte for byte", () => {
    const client = makeClient();
    const importedBytes = JSON.stringify(ownedUnsupportedImportedPack, null, 2);
    render(<Editor client={client} />);

    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: importedBytes },
    });
    const notice = screen.getByTestId("owned-strategy-form-unsupported");
    expect(notice.textContent).toMatch(/not supported by the form/i);
    expect(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    ).toBe(importedBytes);
    expect(screen.queryByTestId("owned-strategy-form")).toBeNull();

    fireEvent.change(screen.getByLabelText(/^label$/i), {
      target: { value: "Renamed import" },
    });
    const after = JSON.parse(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    );
    expect(after.label).toBe("Renamed import");
    expect(after.entry).toEqual(ownedUnsupportedImportedPack.entry);
    expect(after.indicators).toEqual(ownedUnsupportedImportedPack.indicators);
    expect(after.risk).toEqual(ownedUnsupportedImportedPack.risk);
    expect(after.markets).toEqual(ownedUnsupportedImportedPack.markets);
    expect(after.origin).toBe(ownedUnsupportedImportedPack.origin);
  });

  it("Create new owned strategy after an unsupported import replaces the editor contents by explicit action", () => {
    const client = makeClient();
    const importedBytes = JSON.stringify(ownedUnsupportedImportedPack, null, 2);
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: importedBytes },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /create new owned strategy/i }),
    );
    const seeded = JSON.parse(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    );
    expect(seeded.indicators).not.toEqual(ownedUnsupportedImportedPack.indicators);
    expect(seeded.entry).toEqual(["close", ">", "ma"]);
    expect(screen.queryByTestId("owned-strategy-form-unsupported")).toBeNull();
  });

  it("the form is seeded from a loaded supported revision with its real values", () => {
    const client = makeClient();
    const seeded = seedOwnedStrategyPack("Trend plan");
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "draft",
          bytes: JSON.stringify(seeded, null, 2),
        }}
      />,
    );
    expect(screen.getByTestId("owned-strategy-form")).toBeDefined();
    expect(
      (screen.getByLabelText(/strategy name/i) as HTMLInputElement).value,
    ).toBe("Trend plan");
  });

  it("creating a form-seeded strategy does not auto-arm and leaves Arm disabled", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.click(
      screen.getByRole("button", { name: /create new owned strategy/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.arm).not.toHaveBeenCalled();
    expect(
      (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});