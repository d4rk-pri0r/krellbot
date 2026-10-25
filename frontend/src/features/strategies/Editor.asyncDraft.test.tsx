import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor, type DraftSummary, type LoadedRevision, type StrategyClient } from "./Editor";
import { fetchStarters, type StarterExample } from "./StarterPicker.client";
import type { Pack } from "./client";
import { seedOwnedStrategyPack } from "./ownedStrategy";

// Component-level JSDOM/FileReader witness for asynchronous Save/Validate
// completion lifetime. Every deferred StrategyClient response below is an
// explicitly SYNTHETIC test double: this file proves Editor.tsx source
// behavior only — it is NOT a real-backend or Chromium acceptance claim.
afterEach(cleanup);

const fetchStartersMock = vi.mocked(fetchStarters);

// Every test gets a valid empty catalogue by default so mounting the
// picker never depends on a test-specific mock; starter tests override it.
beforeEach(() => {
  fetchStartersMock.mockReset();
  fetchStartersMock.mockResolvedValue({
    schema_version: "1",
    catalogue_version: "0",
    examples: [],
  });
});

vi.mock("./StarterPicker.client", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("./StarterPicker.client")>();
  return {
    ...original,
    fetchStarters: vi.fn(),
  };
});

/** Minimal IntersectionObserver stand-in: report the picker visible. */
class VisibleIntersectionObserver {
  callback: IntersectionObserverCallback;
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
  }
  observe(target: Element): void {
    this.callback(
      [{ isIntersecting: true, target } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
  disconnect(): void {}
  unobserve(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

beforeAll(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    VisibleIntersectionObserver as unknown as typeof IntersectionObserver,
  );
});

afterAll(() => {
  vi.unstubAllGlobals();
});

const parentPack = seedOwnedStrategyPack("Async parent plan");
const parentBytes = JSON.stringify(parentPack, null, 2);

const importedPack = seedOwnedStrategyPack("Imported newer plan");
const importedBytes = JSON.stringify(importedPack, null, 2);

const starterPack: Pack = {
  schema_version: 1,
  id: "starter-async",
  label: "Async starter",
  timeframe: "1h",
};
const starterBytes = JSON.stringify(starterPack, null, 2);

const examples: StarterExample[] = [
  {
    id: "starter-async",
    label: "Async starter",
    description: "Educational example used by the async-draft tests.",
    pack: starterPack,
  },
];

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack: Record<string, unknown>) => ({
      revision_id: "rev-async-created",
      state: "draft",
      pack,
      errors: [],
      outcome: "created",
    })),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Record<string, unknown>) => ({
        revision_id: "rev-async-edited",
        parent_revision_id: parentRevisionId,
        state: "draft",
        pack,
        errors: [],
        outcome: "created",
      }),
    ),
    validate: vi.fn().mockImplementation(async (revisionId: string) => ({
      revision_id: revisionId,
      state: "validated",
      pack: {},
      errors: [],
    })),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function editedSummary(parentId: string): DraftSummary {
  return {
    revision_id: "rev-async-edited",
    parent_revision_id: parentId,
    state: "draft",
    pack: parentPack,
    errors: [],
    outcome: "created",
  };
}

function validatedSummary(revisionId: string): DraftSummary {
  return {
    revision_id: revisionId,
    state: "validated",
    pack: parentPack,
    errors: [],
  };
}

function loadedParent(state: LoadedRevision["state"] = "draft"): LoadedRevision {
  return { revision_id: "rev-parent", state, bytes: parentBytes };
}

function rawJson(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

function fileInput(): HTMLInputElement {
  return screen.getByLabelText(/import pack file/i) as HTMLInputElement;
}

function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
}

function validateButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^validate$/i }) as HTMLButtonElement;
}

function armButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement;
}

function statusText(): string {
  return screen.getByTestId("editor-save-status").textContent ?? "";
}

function chooseFile(text: string): void {
  fireEvent.change(fileInput(), {
    target: { files: [new File([text], "pack.json", { type: "application/json" })] },
  });
}

async function importFile(text: string): Promise<void> {
  chooseFile(text);
  await waitFor(() => {
    expect(rawJson().value).toBe(text);
  });
}

function callsOf(mock: unknown): unknown[][] {
  return (mock as ReturnType<typeof vi.fn>).mock.calls;
}

describe("Editor async Save lifetime vs a newer fresh draft", () => {
  it("a late Save success after a newer file import does not republish the old revision, callback, outcome or fresh-create identity", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(saveButton());
    expect(client.edit).toHaveBeenCalledTimes(1);

    await importFile(importedBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    // The newer imported bytes remain; the old revision stays detached.
    expect(rawJson().value).toBe(importedBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(
      screen.getByText(/no saved revision yet — save creates one\./i),
    ).toBeDefined();
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(screen.queryByTestId("editor-save-error")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(validateButton().disabled).toBe(true);
    expect(armButton().disabled).toBe(true);
    expect(statusText()).toBe("");

    // The next explicit Save creates from the imported draft instead of
    // editing the replaced parent.
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const [sentPack] = callsOf(client.create)[0] as [Record<string, unknown>];
    expect(sentPack.id).toBe(importedPack.id);
    expect(sentPack.label).toBe("Imported newer plan");
    expect(client.edit).toHaveBeenCalledTimes(1);
  });

  it("a late Save failure after a newer file import does not display the obsolete error", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(saveButton());
    await importFile(importedBytes);

    await act(async () => {
      late.reject(new Error("parent revision gone"));
    });

    expect(screen.queryByTestId("editor-save-error")).toBeNull();
    expect(statusText()).toBe("");
    expect(rawJson().value).toBe(importedBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();

    // Saving the imported draft is still possible and uses create.
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.edit).toHaveBeenCalledTimes(1);
  });

  it("a late Save success after a starter replacement is dropped and the next Save creates", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(saveButton());
    fireEvent.click(
      await screen.findByRole("button", { name: "Use Async starter" }),
    );
    await waitFor(() => {
      expect(rawJson().value).toBe(starterBytes);
    });

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(rawJson().value).toBe(starterBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(screen.queryByTestId("editor-save-error")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();

    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    const [sentPack] = callsOf(client.create)[0] as [Record<string, unknown>];
    expect(sentPack.id).toBe("starter-async");
    expect(client.edit).toHaveBeenCalledTimes(1);
  });
});

describe("Editor async Validate lifetime vs a newer fresh draft", () => {
  it("a late Validate success after a newer file import does not reattach the old revision or invoke the stale callback", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(validateButton());
    expect(client.validate).toHaveBeenCalledTimes(1);
    expect(client.validate).toHaveBeenCalledWith("rev-parent");

    await importFile(importedBytes);

    await act(async () => {
      late.resolve(validatedSummary("rev-parent"));
    });

    expect(rawJson().value).toBe(importedBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(armButton().disabled).toBe(true);
    expect(validateButton().disabled).toBe(true);
    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
  });

  it("a late Validate failure after a newer file import does not display the obsolete error", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(validateButton());
    await importFile(importedBytes);

    await act(async () => {
      late.reject(new Error("old revision unreachable"));
    });

    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(rawJson().value).toBe(importedBytes);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(armButton().disabled).toBe(true);
  });
});

describe("Editor async reverse resolve order", () => {
  it("a newer Save's result survives an older Validate resolving afterwards", async () => {
    const onRevision = vi.fn();
    const oldValidate = deferred<DraftSummary>();
    const newCreate = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi.fn().mockReturnValueOnce(oldValidate.promise),
      create: vi.fn().mockReturnValueOnce(newCreate.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(validateButton());
    await importFile(importedBytes);
    fireEvent.click(saveButton());
    await act(async () => {
      newCreate.resolve({
        revision_id: "rev-async-created",
        state: "draft",
        pack: importedPack,
        errors: [],
        outcome: "created",
      });
    });
    expect(await screen.findByTestId("editor-save-outcome")).toBeDefined();
    expect(onRevision).toHaveBeenCalledTimes(1);

    await act(async () => {
      oldValidate.resolve(validatedSummary("rev-parent"));
    });

    expect(screen.getByTestId("editor-revision-id")?.textContent).toMatch(
      /rev-async-created/,
    );
    expect(screen.getByTestId("editor-revision-id")?.textContent).not.toMatch(
      /rev-parent/,
    );
    expect(onRevision).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(screen.getByTestId("editor-save-outcome").textContent).toMatch(
      /rev-async-created/,
    );
    expect(armButton().disabled).toBe(true);
  });

  it("an older Validate failure resolving after a newer Validate succeeded does not republish the obsolete error", async () => {
    const first = deferred<DraftSummary>();
    const second = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi
        .fn()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise),
    });
    render(<Editor client={client} initial={loadedParent()} />);

    fireEvent.click(validateButton());
    fireEvent.click(validateButton());

    await act(async () => {
      second.resolve(validatedSummary("rev-parent"));
    });
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-parent \(state: Validated\)/,
    );

    await act(async () => {
      first.reject(new Error("first attempt unreachable"));
    });

    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-parent \(state: Validated\)/,
    );
  });
});

describe("Editor async component and client lifetime honesty", () => {
  it("a Save completing after unmount applies nothing and never invokes the stale onRevision callback", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    const view = render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );
    fireEvent.click(saveButton());
    view.unmount();

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(onRevision).not.toHaveBeenCalled();
  });

  it("a Save from a replaced client does not reattach its revision into the editor bound to the new client", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const oldClient = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    const newClient = makeClient();
    const view = render(
      <Editor
        client={oldClient}
        initial={loadedParent()}
        onRevision={onRevision}
      />,
    );
    fireEvent.click(saveButton());
    view.rerender(
      <Editor
        client={newClient}
        initial={loadedParent()}
        onRevision={onRevision}
      />,
    );

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(onRevision).not.toHaveBeenCalled();
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-parent/,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).not.toMatch(
      /rev-async-edited/,
    );
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();

    // The editor's current draft identity is still the loaded parent, so
    // the explicit Save goes through the new client against rev-parent.
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(newClient.edit).toHaveBeenCalledTimes(1);
    });
    expect(callsOf(newClient.edit)[0]).toEqual(["rev-parent", parentPack]);
    expect(callsOf(oldClient.edit)).toHaveLength(1);
  });
});

describe("Editor async no-replacement controls", () => {
  it("control: without a replacement the deferred Save success still applies outcome, revision and captured bytes", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );
    fireEvent.click(saveButton());

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(screen.getByTestId("editor-save-outcome").textContent).toMatch(
      /saved new revision rev-async-edited/,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-async-edited/,
    );
    expect(onRevision).toHaveBeenCalledTimes(1);
    expect(onRevision.mock.calls[0][1]).toBe(parentBytes);
    expect(statusText()).toBe("Saved");

    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(2);
    });
    expect(callsOf(client.edit)[1][0]).toBe("rev-async-edited");
  });

  it("control: without a replacement the deferred Validate success still applies and enables Arm", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );
    fireEvent.click(validateButton());

    await act(async () => {
      late.resolve(validatedSummary("rev-parent"));
    });

    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-parent \(state: Validated\)/,
    );
    expect(onRevision).toHaveBeenCalledTimes(1);
    expect(onRevision.mock.calls[0][1]).toBe(parentBytes);
    expect(armButton().disabled).toBe(false);
  });

  it("control: without a replacement a deferred Save failure still surfaces its real error", async () => {
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(<Editor client={client} initial={loadedParent()} />);
    fireEvent.click(saveButton());

    await act(async () => {
      late.reject(new Error("disk full"));
    });

    expect(screen.getByTestId("editor-save-error").textContent).toBe("disk full");
    expect(statusText()).toBe("Save failed: disk full");
  });

  it("control: without a replacement a deferred Validate failure still surfaces its real error", async () => {
    const late = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(<Editor client={client} initial={loadedParent()} />);
    fireEvent.click(validateButton());

    await act(async () => {
      late.reject(new Error("engine busy"));
    });

    expect(screen.getByTestId("editor-validate-error").textContent).toMatch(
      /engine busy/,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-parent \(state: Draft\)/,
    );
  });

  it("control: a second Save click while the deferred Save is pending stays single-flight", async () => {
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi
        .fn()
        .mockReturnValueOnce(late.promise)
        .mockResolvedValueOnce(editedSummary("rev-parent")),
    });
    render(<Editor client={client} initial={loadedParent()} />);
    fireEvent.click(saveButton());
    fireEvent.click(saveButton());
    expect(client.edit).toHaveBeenCalledTimes(1);

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(client.edit).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("editor-save-outcome").textContent).toMatch(
      /rev-async-edited/,
    );
  });

  it("control: editing the raw JSON during a pending Save does not drop its completion (text edits are not draft replacements)", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );
    fireEvent.click(saveButton());
    const edited = JSON.stringify(
      { ...parentPack, label: "Renamed while saving" },
      null,
      2,
    );
    fireEvent.change(rawJson(), { target: { value: edited } });

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-async-edited/,
    );
    expect(onRevision).toHaveBeenCalledTimes(1);
    // onRevision carries the bytes captured at Save start (existing policy).
    expect(onRevision.mock.calls[0][1]).toBe(parentBytes);
  });
});
