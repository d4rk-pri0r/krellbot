import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { fetchStarters, type StarterExample } from "./StarterPicker.client";
import type { Pack } from "./client";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);

const fetchStartersMock = vi.mocked(fetchStarters);

// Every test gets a valid empty catalogue by default so mounting the
// picker never depends on a test-specific mock; starter tests override
// it with a real example row.
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

/**
 * Minimal IntersectionObserver stand-in (same shape as StarterPicker's
 * tests): report the picker visible as soon as it is observed so the
 * catalogue loads through the (mocked) production fetch path.
 */
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

const filePack = seedOwnedStrategyPack("File plan");
const fileBytes = JSON.stringify(filePack, null, 2);

const secondFilePack = seedOwnedStrategyPack("Second file plan");
const secondFileBytes = JSON.stringify(secondFilePack, null, 2);

const editedPack = seedOwnedStrategyPack("Edited plan");
const editedBytes = JSON.stringify(editedPack, null, 2);

const malformedBytes = '{"label": "broken", ';

const parentPack = seedOwnedStrategyPack("Parent plan");
const parentBytes = JSON.stringify(parentPack, null, 2);

const starterPack: Pack = {
  schema_version: 1,
  id: "starter-file-resistant",
  label: "File-resistant starter",
  timeframe: "1h",
};
const starterBytes = JSON.stringify(starterPack, null, 2);

const examples: StarterExample[] = [
  {
    id: "starter-file-resistant",
    label: "File-resistant starter",
    description: "Educational example used by the stale-file tests.",
    pack: starterPack,
  },
];

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack: Record<string, unknown>) => ({
      revision_id: "rev-file-created",
      state: "draft",
      pack,
      errors: [],
      outcome: "created",
    })),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Record<string, unknown>) => ({
        revision_id: "rev-file-edited",
        parent_revision_id: parentRevisionId,
        state: "draft",
        pack,
        errors: [],
        outcome: "created",
      }),
    ),
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

/** Wraps the real readAsText while counting how many reads were started. */
function spyReadAsText(): { count: () => number; restore: () => void } {
  const original = FileReader.prototype.readAsText;
  const spy = vi.fn(function (this: FileReader, file: Blob): void {
    return original.call(this, file);
  });
  FileReader.prototype.readAsText = spy as unknown as typeof FileReader.prototype.readAsText;
  return {
    count: () => spy.mock.calls.length,
    restore: () => {
      FileReader.prototype.readAsText = original;
    },
  };
}

type GatedRead = {
  calls: () => number;
  dispatched: () => number;
  release: () => void;
  restore: () => void;
};

/**
 * Holds every readAsText until release(); each released read resolves
 * with `text` and fires the real "load" event, so onload handlers run
 * exactly as they would for a slow asynchronous file read.
 */
function gateReadAsText(text: string): GatedRead {
  const original = FileReader.prototype.readAsText;
  let releaseRead!: () => void;
  const gate = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  let calls = 0;
  let dispatched = 0;
  const spy = vi.fn(async function (this: FileReader): Promise<void> {
    calls += 1;
    Object.defineProperty(this, "result", { value: text, configurable: true });
    await gate;
    this.dispatchEvent(new Event("load"));
    dispatched += 1;
  });
  FileReader.prototype.readAsText = spy as unknown as typeof FileReader.prototype.readAsText;
  return {
    calls: () => calls,
    dispatched: () => dispatched,
    release: () => releaseRead(),
    restore: () => {
      FileReader.prototype.readAsText = original;
    },
  };
}

/**
 * Records every write to the file input's value. The PRODUCT must clear
 * the picker after each completed read (including refusals) so a real
 * browser treats re-picking the same file as a new change event; these
 * tests never clear the input on the product's behalf.
 */
function trackPickerValueWrites(
  input: HTMLInputElement,
): { writes: () => string[]; stop: () => void } {
  const descriptor = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!;
  const seen: string[] = [];
  Object.defineProperty(input, "value", {
    get() {
      return descriptor.get!.call(input) as string;
    },
    set(next: string) {
      seen.push(next);
      descriptor.set!.call(input, next);
    },
    configurable: true,
  });
  return {
    writes: () => seen,
    stop: () => {
      Reflect.deleteProperty(input, "value");
    },
  };
}

describe("Editor Import never re-reads the chosen file", () => {
  it("after a valid file import, textarea edits survive Import and the file is never read again", async () => {
    const read = spyReadAsText();
    try {
      const client = makeClient();
      render(<Editor client={client} />);

      chooseFile(fileBytes);
      await waitFor(() => {
        expect(rawJson().value).toBe(fileBytes);
      });

      fireEvent.change(rawJson(), { target: { value: editedBytes } });
      fireEvent.click(importButton());

      expect(read.count()).toBe(1);
      expect(rawJson().value).toBe(editedBytes);
      expect(screen.queryByTestId("editor-import-error")).toBeNull();
      expect(client.create).not.toHaveBeenCalled();
      expect(client.edit).not.toHaveBeenCalled();
    } finally {
      read.restore();
    }
  });

  it("after a valid file import and Save, edit, Import, Save updates the same revision with the edit", async () => {
    const read = spyReadAsText();
    try {
      const client = makeClient();
      render(
        <Editor
          client={client}
          initial={{
            revision_id: "rev-parent",
            state: "draft",
            bytes: parentBytes,
          }}
        />,
      );

      chooseFile(fileBytes);
      await waitFor(() => {
        expect(rawJson().value).toBe(fileBytes);
      });

      fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
      await waitFor(() => {
        expect(client.create).toHaveBeenCalledTimes(1);
      });

      fireEvent.change(rawJson(), { target: { value: editedBytes } });
      fireEvent.click(importButton());
      expect(screen.queryByTestId("editor-import-error")).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
      await waitFor(() => {
        expect(client.edit).toHaveBeenCalledTimes(1);
      });
      expect(client.create).toHaveBeenCalledTimes(1);
      const [parentId, pack] = (client.edit as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, Record<string, unknown>];
      expect(parentId).toBe("rev-file-created");
      expect(pack).toEqual(editedPack);
      // Import never queued a re-read, and the edit persists after any
      // pending read would have settled.
      expect(read.count()).toBe(1);
      await waitFor(() => {
        expect(rawJson().value).toBe(editedBytes);
      });
    } finally {
      read.restore();
    }
  });

  it("a pending file read cannot overwrite a later textarea edit, and Import then validates the edited box", async () => {
    const gate = gateReadAsText(fileBytes);
    try {
      const client = makeClient();
      render(
        <Editor
          client={client}
          initial={{
            revision_id: "rev-parent",
            state: "draft",
            bytes: parentBytes,
          }}
        />,
      );

      chooseFile(fileBytes);
      fireEvent.change(rawJson(), { target: { value: editedBytes } });

      gate.release();
      await waitFor(() => {
        expect(gate.dispatched()).toBe(1);
      });
      await waitFor(() => {
        expect(rawJson().value).toBe(editedBytes);
      });

      fireEvent.click(importButton());
      expect(gate.calls()).toBe(1);
      expect(screen.queryByTestId("editor-import-error")).toBeNull();
      expect(rawJson().value).toBe(editedBytes);
    } finally {
      gate.restore();
    }
  });

  it("a pending file read cannot overwrite a later starter pick", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    const gate = gateReadAsText(fileBytes);
    try {
      render(<Editor client={makeClient()} />);
      const useStarter = await screen.findByRole("button", {
        name: "Use File-resistant starter",
      });

      chooseFile(fileBytes);
      fireEvent.click(useStarter);
      expect(rawJson().value).toBe(starterBytes);

      gate.release();
      await waitFor(() => {
        expect(gate.dispatched()).toBe(1);
      });
      await waitFor(() => {
        expect(rawJson().value).toBe(starterBytes);
      });
      expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    } finally {
      gate.restore();
    }
  });

  it("after a completed file import, picking a starter and pressing Import checks the box, never the earlier file", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    const read = spyReadAsText();
    try {
      const client = makeClient();
      render(<Editor client={client} />);

      chooseFile(fileBytes);
      await waitFor(() => {
        expect(rawJson().value).toBe(fileBytes);
      });

      fireEvent.click(
        await screen.findByRole("button", {
          name: "Use File-resistant starter",
        }),
      );
      await waitFor(() => {
        expect(rawJson().value).toBe(starterBytes);
      });

      fireEvent.click(importButton());
      expect(read.count()).toBe(1);
      expect(rawJson().value).toBe(starterBytes);
      expect(screen.queryByTestId("editor-import-error")).toBeNull();
      expect(client.create).not.toHaveBeenCalled();
      expect(client.edit).not.toHaveBeenCalled();
    } finally {
      read.restore();
    }
  });

  it("reopening a saved revision is not overwritten by a pending read from the previous editor instance", async () => {
    const gate = gateReadAsText(fileBytes);
    try {
      const first = render(<Editor client={makeClient()} />);
      chooseFile(fileBytes);
      first.unmount();

      const reopenedBytes = JSON.stringify(
        seedOwnedStrategyPack("Reopened plan"),
        null,
        2,
      );
      render(
        <Editor
          client={makeClient()}
          initial={{
            revision_id: "rev-reopened",
            state: "draft",
            bytes: reopenedBytes,
          }}
        />,
      );

      gate.release();
      await waitFor(() => {
        expect(gate.dispatched()).toBe(1);
      });
      await waitFor(() => {
        expect(rawJson().value).toBe(reopenedBytes);
      });
      expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
        /rev-reopened/,
      );
    } finally {
      gate.restore();
    }
  });

  it("choosing the same file twice reads it both times because the product resets the picker after each completed read", async () => {
    const read = spyReadAsText();
    let stopTracking: (() => void) | null = null;
    try {
      render(<Editor client={makeClient()} />);
      const tracker = trackPickerValueWrites(fileInput());
      stopTracking = tracker.stop;

      chooseFile(fileBytes);
      await waitFor(() => {
        expect(rawJson().value).toBe(fileBytes);
      });
      // The product (not the test) cleared the picker, so a real browser
      // fires change again for the same file name.
      expect(tracker.writes()).toEqual([""]);

      chooseFile(secondFileBytes);
      await waitFor(() => {
        expect(rawJson().value).toBe(secondFileBytes);
      });
      expect(read.count()).toBe(2);

      // A refused (malformed) read also resets the picker: one product
      // clear per completed read — three reads, three clears.
      chooseFile(malformedBytes);
      expect(await screen.findByTestId("editor-import-error")).toBeDefined();
      expect(tracker.writes()).toEqual(["", "", ""]);
      expect(read.count()).toBe(3);
    } finally {
      read.restore();
      stopTracking?.();
    }
  });

  it("editing the raw JSON clears a file refusal, and Import then validates the box", async () => {
    const client = makeClient();
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-parent",
          state: "draft",
          bytes: parentBytes,
        }}
      />,
    );

    chooseFile(malformedBytes);
    expect(await screen.findByTestId("editor-import-error")).toBeDefined();

    fireEvent.change(rawJson(), { target: { value: editedBytes } });
    await waitFor(() => {
      expect(screen.queryByTestId("editor-import-error")).toBeNull();
    });

    fireEvent.click(importButton());
    expect(screen.queryByTestId("editor-import-error")).toBeNull();
    expect(rawJson().value).toBe(editedBytes);
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();

    // Import now checks the box, so malformed box bytes refuse again.
    fireEvent.change(rawJson(), { target: { value: malformedBytes } });
    fireEvent.click(importButton());
    expect(screen.getByTestId("editor-import-error").textContent).toContain(
      "Invalid JSON",
    );
  });

  it("with no file chosen, Import on a valid box stays a plain validation that never reads a file", async () => {
    const read = spyReadAsText();
    try {
      const client = makeClient();
      render(<Editor client={client} />);

      fireEvent.change(rawJson(), { target: { value: fileBytes } });
      fireEvent.click(importButton());

      expect(screen.queryByTestId("editor-import-error")).toBeNull();
      expect(read.count()).toBe(0);
      expect(client.create).not.toHaveBeenCalled();
      expect(client.edit).not.toHaveBeenCalled();
    } finally {
      read.restore();
    }
  });
});
