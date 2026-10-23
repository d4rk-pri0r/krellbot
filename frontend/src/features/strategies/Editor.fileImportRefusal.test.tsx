import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack: Record<string, unknown>) => ({
      revision_id: "rev-file-created",
      state: "draft",
      pack,
      errors: [],
      outcome: "created",
    })),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-file-edit",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-file-validated",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const malformedBytes = '{"label": "broken", ';

const validFilePack = seedOwnedStrategyPack("Recovered plan");
const validFileBytes = JSON.stringify(validFilePack, null, 2);

const parentBytes = JSON.stringify(seedOwnedStrategyPack("Parent plan"), null, 2);

function fileInput(): HTMLInputElement {
  return screen.getByLabelText(/import pack file/i) as HTMLInputElement;
}

function rawJson(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

function importButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^import$/i }) as HTMLButtonElement;
}

function chooseFile(text: string): void {
  fireEvent.change(fileInput(), {
    target: { files: [new File([text], "pack.json", { type: "application/json" })] },
  });
}

describe("Editor file-import refusal is not cleared by the adjacent Import button", () => {
  it("keeps the malformed-file refusal visible after the adjacent Import is clicked, without importing or saving", async () => {
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{ revision_id: "rev-parent", state: "draft", bytes: parentBytes }}
      />,
    );

    chooseFile(malformedBytes);
    const refusal = await screen.findByTestId("editor-import-error");
    expect(refusal.textContent).toContain("Invalid JSON");
    expect(refusal.getAttribute("role")).toBe("alert");
    expect(rawJson().value).toBe(parentBytes);

    // The Import button acts on the chosen (still malformed) file, so the
    // refusal stays instead of being cleared by the valid textarea bytes.
    fireEvent.click(importButton());

    expect(screen.getByTestId("editor-import-error").textContent).toContain(
      "Invalid JSON",
    );
    expect(rawJson().value).toBe(parentBytes);
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(/rev-parent/);
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("keeps the refusal when Import is clicked while the file read is still in flight, and the unrelated textarea is never imported", async () => {
    const client = makeClient();
    render(<Editor client={client} />);

    let releaseRead!: () => void;
    const gate = new Promise<void>((resolve) => {
      releaseRead = resolve;
    });
    const originalReadAsText = FileReader.prototype.readAsText;
    const readAsText = vi.fn(async function (this: FileReader) {
      await gate;
      this.dispatchEvent(new Event("load"));
    });
    FileReader.prototype.readAsText = readAsText;
    try {
      chooseFile(malformedBytes);

      // Import while the asynchronous read has not completed: it must not
      // fall back to the unrelated (still-empty) textarea. Import only
      // validates the raw JSON box and never reads the file, so no second
      // read is queued behind the still-pending one.
      fireEvent.click(importButton());
      expect(readAsText).toHaveBeenCalledTimes(1);

      releaseRead();
      const refusal = await screen.findByTestId("editor-import-error");
      expect(refusal.textContent).toContain("Invalid JSON");
      expect(rawJson().value).toBe("");
      expect(client.create).not.toHaveBeenCalled();
      expect(client.edit).not.toHaveBeenCalled();
    } finally {
      FileReader.prototype.readAsText = originalReadAsText;
    }
  });

  it("recovers when a valid pack file is chosen afterwards, and Save imports it as a fresh revision", async () => {
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{ revision_id: "rev-parent", state: "draft", bytes: parentBytes }}
      />,
    );

    chooseFile(malformedBytes);
    expect(await screen.findByTestId("editor-import-error")).toBeDefined();

    chooseFile(validFileBytes);
    await waitFor(() => {
      expect(screen.queryByTestId("editor-import-error")).toBeNull();
    });
    expect(rawJson().value).toBe(validFileBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.edit).not.toHaveBeenCalled();
    const pack = (client.create as ReturnType<typeof vi.fn>).mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(pack).toEqual(validFilePack);
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-file-created/,
    );
  });

  it("a textarea-driven Import still validates the raw JSON as before", () => {
    const client = makeClient();
    render(<Editor client={client} />);

    fireEvent.change(rawJson(), { target: { value: malformedBytes } });
    fireEvent.click(importButton());
    expect(screen.getByTestId("editor-import-error").textContent).toContain("Invalid JSON");
    expect(client.create).not.toHaveBeenCalled();

    fireEvent.change(rawJson(), { target: { value: validFileBytes } });
    expect(screen.queryByTestId("editor-import-error")).toBeNull();
    expect(rawJson().value).toBe(validFileBytes);
  });

  it("a valid pack file still imports and saves normally", async () => {
    const client = makeClient();
    render(<Editor client={client} />);

    chooseFile(validFileBytes);
    await waitFor(() => {
      expect(rawJson().value).toBe(validFileBytes);
    });
    expect(screen.queryByTestId("editor-import-error")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const pack = (client.create as ReturnType<typeof vi.fn>).mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(pack).toEqual(validFilePack);
  });
});
