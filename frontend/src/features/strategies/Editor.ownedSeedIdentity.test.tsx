import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type DraftSummary, type LoadedRevision, type StrategyClient } from "./Editor";
import { seedOwnedStrategyPack } from "./ownedStrategy";

// Component-level JSDOM witness for the fresh-owned-seed draft lifecycle:
// the explicit "Create new owned strategy" action must start an unsaved
// fresh draft, drop the replaced draft's revision/state/save/validation/arm
// surfaces, and invalidate its pending Save/Validate continuations.
//
// Every StrategyClient response below (including the deferred ones) is an
// explicitly SYNTHETIC test double: this file proves Editor.tsx source
// behavior only — it is NOT a real-backend or Chromium acceptance claim.
// The real guarded loopback backend independently refuses this journey's
// broken shape with 409 strategy_id_mismatch (edit of the old parent with
// a newly generated pack id), which is why Save after a fresh-owned seed
// must go through create.
afterEach(cleanup);

const parentPack = seedOwnedStrategyPack("Reopened parent plan");
const parentBytes = JSON.stringify(parentPack, null, 2);

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
      revision_id: "rev-owned-created",
      state: "draft",
      pack,
      errors: [],
      outcome: "created",
    })),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Record<string, unknown>) => ({
        revision_id: "rev-owned-edited",
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
    revision_id: "rev-owned-edited",
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

function startOwnedButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /create new owned strategy/i,
  }) as HTMLButtonElement;
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

function rawJson(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

function statusText(): string {
  return screen.getByTestId("editor-save-status").textContent ?? "";
}

function callsOf(mock: unknown): unknown[][] {
  return (mock as ReturnType<typeof vi.fn>).mock.calls;
}

/** Click "Create new owned strategy" and return the seeded pack it wrote. */
function startOwnedSeed(): Record<string, unknown> {
  fireEvent.click(startOwnedButton());
  const seeded = JSON.parse(rawJson().value) as Record<string, unknown>;
  return seeded;
}

describe("Editor fresh-owned seed after a reopened saved revision", () => {
  it("seeding a fresh owned strategy makes Save create with the actual fresh pack, never edit the reopened parent", async () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedParent()} />);

    const seeded = startOwnedSeed();
    expect(seeded.id).not.toBe(parentPack.id);
    expect(rawJson().value).not.toBe(parentBytes);

    fireEvent.click(saveButton());

    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(callsOf(client.create)[0][0]).toEqual(seeded);
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("seeding drops the reopened revision's identity so the truthful surface says no saved revision yet", () => {
    const client = makeClient();
    render(<Editor client={client} initial={loadedParent("validated")} />);

    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-parent/,
    );
    fireEvent.click(startOwnedButton());

    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(
      screen.getByText(/no saved revision yet — save creates one\./i),
    ).toBeDefined();
    expect(validateButton().disabled).toBe(true);
    expect(armButton().disabled).toBe(true);
  });

  it("seeding clears the prior draft's save outcome, validate error and arm error surfaces without further actions", async () => {
    const client = makeClient({
      validate: vi.fn().mockRejectedValue(new Error("stale revision gone")),
      arm: vi.fn().mockRejectedValue(new Error("arm refused")),
    });
    render(<Editor client={client} initial={loadedParent("validated")} />);

    // Produce real stale surfaces from the loaded revision first.
    fireEvent.click(validateButton());
    expect(await screen.findByTestId("editor-validate-error")).toBeDefined();
    fireEvent.click(armButton());
    expect(await screen.findByTestId("editor-arm-error")).toBeDefined();
    fireEvent.click(saveButton());
    expect(await screen.findByTestId("editor-save-outcome")).toBeDefined();

    fireEvent.click(startOwnedButton());

    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(screen.queryByTestId("editor-arm-error")).toBeNull();
    expect(screen.queryByTestId("editor-save-error")).toBeNull();
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    // Nothing saves, validates or arms by itself after the seed.
    expect(callsOf(client.create)).toHaveLength(0);
    expect(callsOf(client.edit)).toHaveLength(1);
    expect(callsOf(client.validate)).toHaveLength(1);
    expect(callsOf(client.arm)).toHaveLength(1);
  });
});

describe("Editor fresh-owned seed after an already-saved draft", () => {
  it("seeding after this session's own create drops that revision so the next Save creates again, not edits it", async () => {
    const client = makeClient();
    render(<Editor client={client} />);

    fireEvent.click(startOwnedButton());
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-owned-created/,
    );

    const seeded = startOwnedSeed();
    const firstSent = callsOf(client.create)[0][0] as Record<string, unknown>;
    expect(seeded.id).not.toBe(firstSent.id);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(
      screen.getByText(/no saved revision yet — save creates one\./i),
    ).toBeDefined();

    fireEvent.click(saveButton());

    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(2);
    });
    expect(callsOf(client.create)[1][0]).toEqual(seeded);
    expect(client.edit).not.toHaveBeenCalled();
  });
});

describe("Editor async Save lifetime vs a fresh-owned seed", () => {
  it("a late Save success after the seed does not republish the old revision, outcome, error or callback, and the next Save creates", async () => {
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

    const seeded = startOwnedSeed();
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    // The fresh bytes remain; the old parent stays detached.
    expect(JSON.parse(rawJson().value)).toEqual(seeded);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(screen.queryByTestId("editor-save-error")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(statusText()).toBe("");

    // The single-flight lock was released: the next explicit Save creates.
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(callsOf(client.create)[0][0]).toEqual(seeded);
    expect(client.edit).toHaveBeenCalledTimes(1);
  });

  it("a late Save failure after the seed does not display the obsolete error and Save is still possible", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(saveButton());
    const seeded = startOwnedSeed();

    await act(async () => {
      late.reject(new Error("strategy_id_mismatch: 409 parent refused"));
    });

    expect(screen.queryByTestId("editor-save-error")).toBeNull();
    expect(statusText()).toBe("");
    expect(JSON.parse(rawJson().value)).toEqual(seeded);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();

    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.edit).toHaveBeenCalledTimes(1);
  });
});

describe("Editor async Validate lifetime vs a fresh-owned seed", () => {
  it("a late Validate success after the seed does not reattach the old revision, invoke the callback, or imply fresh validation or arming", async () => {
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

    const seeded = startOwnedSeed();

    await act(async () => {
      late.resolve(validatedSummary("rev-parent"));
    });

    // The fresh, unsaved draft must not inherit the old revision's
    // validated identity or enable Arm off the replaced draft.
    expect(JSON.parse(rawJson().value)).toEqual(seeded);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(validateButton().disabled).toBe(true);
    expect(armButton().disabled).toBe(true);
  });

  it("a late Validate failure after the seed does not display the obsolete error", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      validate: vi.fn().mockReturnValueOnce(late.promise),
    });
    render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );

    fireEvent.click(validateButton());
    const seeded = startOwnedSeed();

    await act(async () => {
      late.reject(new Error("old revision unreachable"));
    });

    expect(screen.queryByTestId("editor-validate-error")).toBeNull();
    expect(JSON.parse(rawJson().value)).toEqual(seeded);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(onRevision).not.toHaveBeenCalled();
    expect(armButton().disabled).toBe(true);
  });
});

describe("Editor fresh-owned draft ordinary controls", () => {
  it("after the seeded draft is saved, same-draft form edits edit the new revision and Validate targets it", async () => {
    const client = makeClient();
    render(<Editor client={client} />);

    fireEvent.click(startOwnedButton());
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-owned-created/,
    );

    // Ordinary same-draft edits keep normal parent semantics.
    fireEvent.change(screen.getByLabelText(/protective stop percent/i), {
      target: { value: "7" },
    });
    fireEvent.click(saveButton());
    await waitFor(() => {
      expect(client.edit).toHaveBeenCalledTimes(1);
    });
    expect(callsOf(client.edit)[0][0]).toBe("rev-owned-created");
    const [, editedPack] = callsOf(client.edit)[0] as unknown as [
      string,
      Record<string, unknown>,
    ];
    expect((editedPack.risk as { stop: { pct: number } }).stop.pct).toBe(7);
    expect(client.create).toHaveBeenCalledTimes(1);

    // Validate is an explicit control on the revision the edit produced.
    expect(validateButton().disabled).toBe(false);
    fireEvent.click(validateButton());
    await waitFor(() => {
      expect(client.validate).toHaveBeenCalledTimes(1);
    });
    expect(client.validate).toHaveBeenCalledWith("rev-owned-edited");
    expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
      /rev-owned-edited/,
    );
  });
});

describe("Editor fresh-owned seed stale callback and unmount safety", () => {
  it("a Save completing after a fresh seed and unmount applies nothing and never invokes the stale onRevision callback", async () => {
    const onRevision = vi.fn();
    const late = deferred<DraftSummary>();
    const client = makeClient({
      edit: vi.fn().mockReturnValueOnce(late.promise),
    });
    const view = render(
      <Editor client={client} initial={loadedParent()} onRevision={onRevision} />,
    );
    fireEvent.click(saveButton());
    fireEvent.click(startOwnedButton());
    view.unmount();

    await act(async () => {
      late.resolve(editedSummary("rev-parent"));
    });

    expect(onRevision).not.toHaveBeenCalled();
  });
});
