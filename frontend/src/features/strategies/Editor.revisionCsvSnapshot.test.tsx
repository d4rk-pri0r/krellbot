import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import type { DraftSummary, Pack } from "./client";

// Component-level JSDOM witness for the saved-revision CSV snapshot
// contract. Every StrategyClient below is an explicitly SYNTHETIC test
// double and the download is captured from the Blob handed to
// URL.createObjectURL: this file proves Editor.tsx source behavior only —
// it is NOT a real-backend or real-browser CSV download acceptance claim.

afterEach(cleanup);

const savedPack: Pack = {
  schema_version: 1,
  id: "saved-plan",
  version: "1.0.0",
  label: "Saved plan",
  author: "local workstation",
  timeframe: "4h",
  indicators: { ma: { fn: "ema", src: "close", len: 36 } },
  entry: ["close", "crosses_above", "ma"],
  exit: ["close", "crosses_below", "ma"],
  risk: { max_account_pct: 40, stop: { type: "pct", pct: 6.5 } },
  markets: [{ venue: "kraken", pair: "XXBTZUSD" }],
};

const savedPackBytes = JSON.stringify(savedPack, null, 2);

const CSV_HEADER =
  "revision_id,state,error_count,label,parameter_count,kind_count";

// Top-level keys excluding `label`: 5 scalars (schema_version, id, version,
// author, timeframe) and 5 structured values (indicators, entry, exit,
// risk, markets).
const SAVED_ROW = "rev-saved,validated,0,Saved plan,5,5";

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
    create: vi.fn(),
    edit: vi.fn(),
    validate: vi.fn(),
    arm: vi.fn(),
    ...overrides,
  };
}

function editEchoClient(
  edit: StrategyClient["edit"],
): StrategyClient {
  return makeClient({ edit });
}

function mountLoadedEditor(client: StrategyClient): void {
  render(
    <Editor
      client={client}
      initial={{
        revision_id: "rev-saved",
        state: "validated",
        bytes: savedPackBytes,
      }}
    />,
  );
}

function csvExportButton(): HTMLButtonElement {
  return screen.getByTestId(
    "strategies-editor-csv-export",
  ) as HTMLButtonElement;
}

function labelInput(): HTMLInputElement {
  return screen.getByLabelText(/^label$/i) as HTMLInputElement;
}

function rawJsonBox(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

/** Captures the Blob the export hands to URL.createObjectURL and the
 * generated anchor download names, with the navigation stubbed out. */
function captureCsvDownload(): {
  blobs: () => Blob[];
  downloadNames: () => string[];
  restore: () => void;
} {
  const createObjectURL = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:csv-snapshot-test");
  const revokeObjectURL = vi
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => {});
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const originalCreateElement = document.createElement.bind(document);
  const anchors: HTMLAnchorElement[] = [];
  const createElement = vi.spyOn(document, "createElement");
  createElement.mockImplementation(((tag: string) => {
    const element = originalCreateElement(tag);
    if (tag === "a" && element instanceof HTMLAnchorElement) {
      anchors.push(element);
    }
    return element;
  }) as typeof document.createElement);
  return {
    blobs: () => createObjectURL.mock.calls.map((call) => call[0] as Blob),
    downloadNames: () => anchors.map((anchor) => anchor.download),
    restore: () => {
      click.mockRestore();
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
      createElement.mockRestore();
    },
  };
}

async function exportCsvLines(): Promise<{
  lines: string[];
  downloadNames: string[];
}> {
  const capture = captureCsvDownload();
  try {
    fireEvent.click(csvExportButton());
    const blobs = capture.blobs();
    expect(blobs.length).toBe(1);
    const csv = await blobs[0].text();
    const lines = csv.split("\n");
    expect(lines.length).toBe(2);
    expect(lines[0]).toBe(CSV_HEADER);
    expect(csv).not.toContain("\r");
    return { lines, downloadNames: capture.downloadNames() };
  } finally {
    capture.restore();
  }
}

async function exportCsvRow(): Promise<string> {
  const { lines } = await exportCsvLines();
  return lines[1];
}

describe("Editor revision CSV snapshot identity", () => {
  it("control: a loaded validated revision exports its own saved row unchanged", async () => {
    mountLoadedEditor(makeClient());
    expect(csvExportButton().disabled).toBe(false);
    expect(await exportCsvRow()).toBe(SAVED_ROW);
  });

  it("an unsaved Label edit never contaminates the exported saved row", async () => {
    const client = makeClient();
    mountLoadedEditor(client);

    fireEvent.change(labelInput(), { target: { value: "Unsaved label edit" } });
    expect(JSON.parse(rawJsonBox().value).label).toBe("Unsaved label edit");

    expect(await exportCsvRow()).toBe(SAVED_ROW);

    // The draft edit survives the export and nothing saved, validated or armed.
    expect(JSON.parse(rawJsonBox().value).label).toBe("Unsaved label edit");
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
    expect(client.validate).not.toHaveBeenCalled();
    expect(client.arm).not.toHaveBeenCalled();
  });

  it("an unsaved raw-JSON shape edit never adds parameter counts under the saved identity", async () => {
    const client = makeClient();
    mountLoadedEditor(client);

    const reshaped = JSON.stringify(
      { ...savedPack, notes: "unsaved raw tweak" },
      null,
      2,
    );
    fireEvent.change(rawJsonBox(), { target: { value: reshaped } });

    expect(await exportCsvRow()).toBe(SAVED_ROW);
    expect(JSON.parse(rawJsonBox().value).notes).toBe("unsaved raw tweak");
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("an unsaved owned-form edit never contaminates the exported saved row", async () => {
    const client = makeClient();
    mountLoadedEditor(client);

    expect(screen.getByTestId("owned-strategy-form")).toBeDefined();
    fireEvent.change(screen.getByLabelText(/strategy name/i), {
      target: { value: "Unsaved form name" },
    });
    expect(JSON.parse(rawJsonBox().value).label).toBe("Unsaved form name");

    expect(await exportCsvRow()).toBe(SAVED_ROW);
    expect(JSON.parse(rawJsonBox().value).label).toBe("Unsaved form name");
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("a successful explicit Save promotes the returned snapshot even after further unsaved edits", async () => {
    const client = editEchoClient(
      vi.fn().mockImplementation(
        async (parentId: string, pack: Pack): Promise<DraftSummary> => ({
          revision_id: "rev-2",
          parent_revision_id: parentId,
          state: "draft",
          pack,
          errors: [],
          outcome: "created",
        }),
      ),
    );
    mountLoadedEditor(client);

    fireEvent.change(labelInput(), { target: { value: "Saved in rev-2" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByTestId("editor-save-outcome")).toBeDefined();

    fireEvent.change(labelInput(), {
      target: { value: "Unsaved after save" },
    });

    const { lines, downloadNames } = await exportCsvLines();
    expect(lines[1]).toBe("rev-2,draft,0,Saved in rev-2,5,5");
    expect(
      downloadNames.filter((name) =>
        /^krellbot-revision-rev-2-\d{14}\.csv$/.test(name),
      ).length,
    ).toBe(1);
  });

  it("edits made while a Save is pending never become part of the saved revision", async () => {
    const late = deferred<DraftSummary>();
    const client = editEchoClient(
      vi.fn().mockReturnValueOnce(late.promise),
    );
    mountLoadedEditor(client);

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(client.edit).toHaveBeenCalledWith("rev-saved", savedPack);

    fireEvent.change(labelInput(), {
      target: { value: "Edited while pending" },
    });

    await act(async () => {
      late.resolve({
        revision_id: "rev-2",
        parent_revision_id: "rev-saved",
        state: "draft",
        pack: savedPack,
        errors: [],
        outcome: "created",
      });
    });

    expect(await exportCsvRow()).toBe("rev-2,draft,0,Saved plan,5,5");
    // The pending-time edit stays an editable draft, never part of rev-2.
    expect(JSON.parse(rawJsonBox().value).label).toBe("Edited while pending");
  });

  it("a failed Save preserves the previous saved snapshot", async () => {
    const client = editEchoClient(
      vi.fn().mockRejectedValue(new Error("backend refused")),
    );
    mountLoadedEditor(client);

    fireEvent.change(labelInput(), { target: { value: "Unsaved label edit" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const error = await screen.findByTestId("editor-save-error");
    expect(error.textContent).toMatch(/backend refused/);

    expect(await exportCsvRow()).toBe(SAVED_ROW);
    expect(JSON.parse(rawJsonBox().value).label).toBe("Unsaved label edit");
  });

  it("control: an unsaved fresh draft keeps the CSV export disabled with no blob", async () => {
    render(<Editor client={makeClient()} />);

    fireEvent.change(rawJsonBox(), { target: { value: savedPackBytes } });

    const button = csvExportButton();
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId("strategies-editor-csv-empty").textContent).toBe(
      "Save revision first.",
    );

    const capture = captureCsvDownload();
    try {
      fireEvent.click(button);
      expect(capture.blobs().length).toBe(0);
    } finally {
      capture.restore();
    }
  });
});
