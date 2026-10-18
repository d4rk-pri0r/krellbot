import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type DraftSummary, type StrategyClient } from "./Editor";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);
const pack = seedOwnedStrategyPack("Keyboard plan");
const bytes = JSON.stringify(pack);
const summary: DraftSummary = {
  revision_id: "rev-keyboard", state: "draft", pack, errors: [], outcome: "created",
};

// The injected API boundary is controlled; all editor parsing/form/save paths are real.
function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue(summary),
    edit: vi.fn().mockResolvedValue(summary),
    validate: vi.fn(), arm: vi.fn(), ...overrides,
  };
}
function seedJson(value = bytes): void {
  fireEvent.change(screen.getByLabelText(/raw json/i), { target: { value } });
}
function saveButton(): HTMLElement {
  return screen.getByRole("button", { name: /^save$/i });
}
function shortcut(target = saveButton(), options = {}): boolean {
  target.focus();
  return fireEvent.keyDown(target, { key: "s", ctrlKey: true, ...options });
}
function status(): HTMLElement {
  return screen.getByTestId("editor-save-status");
}

describe("Editor keyboard Save", () => {
  it.each([
    ["Control", { ctrlKey: true, metaKey: false, key: "s" }],
    ["Meta", { ctrlKey: false, metaKey: true, key: "S" }],
  ])("%s+S saves once through create and prevents browser navigation", async (_, keys) => {
    const client = makeClient();
    const onRevision = vi.fn();
    render(<Editor client={client} onRevision={onRevision} />);
    seedJson();
    const nativeDefault = shortcut(saveButton(), keys);
    expect(client.create).toHaveBeenCalledExactlyOnceWith(pack);
    expect(nativeDefault).toBe(false);
    expect((await screen.findByTestId("editor-save-outcome")).textContent)
      .toBe("saved new revision rev-keyboard");
    expect(client.create).toHaveBeenCalledExactlyOnceWith(pack);
    expect(client.edit).not.toHaveBeenCalled();
    expect(onRevision).toHaveBeenCalledExactlyOnceWith(summary, bytes);
    expect(status().textContent).toBe("Saved");
  });

  it("loaded revision uses edit and preserves the click path's unchanged outcome", async () => {
    const client = makeClient({ edit: vi.fn().mockResolvedValue({ ...summary, outcome: "unchanged" }) });
    const onRevision = vi.fn();
    render(<Editor client={client} onRevision={onRevision}
      initial={{ revision_id: "rev-parent", state: "validated", bytes }} />);
    shortcut();
    expect((await screen.findByTestId("editor-save-outcome")).textContent)
      .toBe("no change: revision rev-keyboard kept");
    expect(client.edit).toHaveBeenCalledExactlyOnceWith("rev-parent", pack);
    expect(client.create).not.toHaveBeenCalled();
    expect(onRevision).not.toHaveBeenCalled();
    expect(status().textContent).toBe("Saved");
  });

  it.each(["not json {", "[]", "null", "42", ""])("blocks invalid Pack %j with the existing error", (value) => {
    const client = makeClient();
    render(<Editor client={client} />);
    seedJson(value);
    expect(shortcut()).toBe(false);
    expect(screen.getByTestId("editor-import-error").textContent).toBe("Invalid JSON");
    expect(status().textContent).toBe("Invalid JSON; save blocked");
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
    expect(screen.getByTestId("editor-technical-section").hasAttribute("open")).toBe(true);
  });

  it("leaves both native shortcuts in the raw JSON textarea alone", () => {
    const client = makeClient();
    render(<Editor client={client} />);
    seedJson();
    const raw = screen.getByLabelText(/raw json/i);
    expect(shortcut(raw)).toBe(true);
    expect(shortcut(raw, { ctrlKey: false, metaKey: true })).toBe(true);
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
    expect(status().textContent).toBe("");
  });

  it("leaves owned-form inputs' native semantics alone, including invalid form edits", () => {
    const client = makeClient();
    render(<Editor client={client} initial={{ revision_id: "rev-parent", state: "draft", bytes }} />);
    fireEvent.change(screen.getByLabelText(/average length \(bars\)/i), { target: { value: "600" } });
    const inputs = screen.getByTestId("owned-strategy-form").querySelectorAll("input");
    expect(inputs.length).toBeGreaterThan(0);
    for (const input of inputs) {
      expect(shortcut(input)).toBe(true);
      expect(shortcut(input, { ctrlKey: false, metaKey: true })).toBe(true);
    }
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });

  it.each(["Label", "Venue", "Paper balance"])("saves from the editor's %s input after an edit", async (label) => {
    const client = makeClient();
    render(<Editor client={client} />);
    seedJson();
    const input = screen.getByLabelText(label);
    const value = label === "Label" ? "Renamed" : label === "Venue" ? "coinbase" : "2500";
    fireEvent.change(input, { target: { value } });
    expect(shortcut(input)).toBe(false);
    await screen.findByTestId("editor-save-outcome");
    expect(client.create).toHaveBeenCalledExactlyOnceWith(label === "Label" ? { ...pack, label: value } : pack);
    expect(client.arm).not.toHaveBeenCalled();
  });

  it("imported file saves a fresh draft instead of editing the loaded revision", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={{ revision_id: "rev-parent", state: "draft", bytes }} />);
    const input = screen.getByLabelText(/import pack file/i);
    fireEvent.change(input, { target: { files: [new File([bytes], "pack.json", { type: "application/json" })] } });
    await waitFor(() => expect(screen.queryByTestId("editor-revision-id")).toBeNull());
    expect(shortcut(input)).toBe(false);
    await screen.findByTestId("editor-save-outcome");
    expect(client.create).toHaveBeenCalledExactlyOnceWith(pack);
    expect(client.edit).not.toHaveBeenCalled();
  });

  it.each(["keyboard", "click"])("announces pending %s save, guards reentry, announces failure, then allows retry", async (origin) => {
    let reject!: (error: Error) => void;
    const pending = new Promise<DraftSummary>((_, fail) => { reject = fail; });
    const client = makeClient({ create: vi.fn().mockReturnValueOnce(pending).mockResolvedValue(summary) });
    render(<Editor client={client} />);
    seedJson();
    expect(status().getAttribute("aria-live")).toBe("polite");
    expect(status().getAttribute("aria-atomic")).toBe("true");
    if (origin === "click") fireEvent.click(saveButton());
    else shortcut();
    expect(status().textContent).toBe("Saving…");
    shortcut();
    shortcut(saveButton(), { ctrlKey: false, metaKey: true });
    fireEvent.click(saveButton());
    expect(client.create).toHaveBeenCalledTimes(1);
    await act(async () => reject(new Error("network down")));
    expect(screen.getByTestId("editor-save-error").textContent).toBe("network down");
    expect(status().textContent).toBe("Save failed: network down");
    shortcut();
    await waitFor(() => expect(status().textContent).toBe("Saved"));
    expect(client.create).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("editor-save-error")).toBeNull();
  });

  it("keeps the Save click path and advertises its keyboard equivalent", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    seedJson();
    expect(saveButton().getAttribute("aria-keyshortcuts")).toBe("Control+S Meta+S");
    fireEvent.click(saveButton());
    expect((await screen.findByTestId("editor-save-outcome")).textContent)
      .toBe("saved new revision rev-keyboard");
    expect(status().textContent).toBe("Saved");
    expect(client.create).toHaveBeenCalledExactlyOnceWith(pack);
  });

  it("ignores unmodified keys, other chords, repeats, and non-editor surfaces", () => {
    const client = makeClient();
    render(<><Editor client={client} /><button>Outside</button></>);
    seedJson();
    expect(shortcut(saveButton(), { ctrlKey: false })).toBe(true);
    expect(shortcut(saveButton(), { key: "x" })).toBe(true);
    shortcut(saveButton(), { repeat: true });
    expect(shortcut(screen.getByRole("button", { name: "Outside" }))).toBe(true);
    expect(client.create).not.toHaveBeenCalled();
  });
});
