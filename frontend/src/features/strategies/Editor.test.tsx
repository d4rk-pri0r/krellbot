import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";

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