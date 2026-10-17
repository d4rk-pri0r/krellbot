/**
 * Editor Signal presentation slice — KRELL-SIGNAL-20261010.
 *
 * Pins the grouped presentation of the mounted strategy editor:
 * readable Signal groups (identity/readable rules, technical JSON/import
 * as a real disclosure, save/validation state, paper-run preparation and
 * risk-reduction controls) while preserving the editor's exact save,
 * validate, arm, import/export, revision/error and inline-stop behavior.
 *
 * The layout/disclosure assertions are RED on the flat pre-signal base;
 * the behavior guards prove the grouping changes presentation only.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import type { PaperClient, PaperStatus } from "../paper/client";

afterEach(cleanup);

const validPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

const validPackBytes = JSON.stringify(validPack, null, 2);

const unsupportedImportedPack = {
  schema_version: 1,
  id: "imported-nested",
  version: "1.0.0",
  label: "Imported nested pack",
  author: "someone else",
  timeframe: "4h",
  indicators: {
    fast: { fn: "ema", src: "close", len: 9 },
    slow: { fn: "ema", src: "close", len: 21 },
  },
  entry: { all: [["close", ">", "indicators.slow"]] },
  exit: [["close", "<", "indicators.fast"]],
  risk: { max_account_pct: 40, stop: { type: "pct", pct: 6.5 } },
  markets: [{ venue: "kraken", pair: "XXBTZUSD" }],
  origin: "imported",
};

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
      revision_id: "rev-create",
      state: "validated",
      pack: validPack,
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
}

function makePaperClient(overrides: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    ...overrides,
  };
}

function technicalSection(): HTMLElement {
  const section = screen.getByTestId("editor-technical-section");
  expect(section.tagName).toBe("DETAILS");
  return section as HTMLElement;
}

describe("Editor signal slice — grouped layout", () => {
  it("renders the four named Signal groups in a stable order", () => {
    render(<Editor client={makeClient()} />);
    const identity = screen.getByRole("region", {
      name: /strategy identity and readable rules/i,
    });
    const technical = screen.getByRole("region", {
      name: /technical json, import and export/i,
    });
    const save = screen.getByRole("region", {
      name: /save and validation/i,
    });
    const run = screen.getByRole("region", {
      name: /paper run and risk reduction/i,
    });
    expect(identity).toBeDefined();
    expect(technical).toBeDefined();
    expect(save).toBeDefined();
    expect(run).toBeDefined();

    const root = document.querySelector(".kbot-strategy-editor");
    expect(root).not.toBeNull();
    const order = [identity, technical, save, run].map((node) =>
      root!.compareDocumentPosition(node),
    );
    // All four groups are descendants of the editor root and appear in the
    // expected order (identity -> technical -> save -> paper run).
    for (const position of order) {
      expect(position & Node.DOCUMENT_POSITION_CONTAINED_BY).toBeTruthy();
    }
    expect(
      identity.compareDocumentPosition(technical) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      technical.compareDocumentPosition(save) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      save.compareDocumentPosition(run) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("keeps the technical JSON/import surface a real disclosure with summary semantics", () => {
    render(<Editor client={makeClient()} />);
    const details = technicalSection();
    const summary = details.querySelector(":scope > summary");
    expect(summary).not.toBeNull();
    expect(summary!.textContent).toMatch(/technical json, import and export/i);
    // The summary is keyboard-reachable as the disclosure control.
    expect(summary!.getAttribute("tabindex")).not.toBe("-1");
    // Raw JSON and the file import stay reachable inside the disclosure.
    expect(details.contains(screen.getByLabelText(/raw json/i))).toBe(true);
    expect(details.contains(screen.getByLabelText(/import pack file/i))).toBe(
      true,
    );
  });

  it("places import/export actions in the technical section and save/validate/arm in their own groups", () => {
    render(<Editor client={makeClient()} />);
    const details = technicalSection();
    const importButton = screen.getByRole("button", { name: /^import$/i });
    const exportButton = screen.getByRole("button", { name: /export pack/i });
    const csvButton = screen.getByRole("button", { name: /export csv/i });
    expect(details.contains(importButton)).toBe(true);
    expect(details.contains(exportButton)).toBe(true);
    expect(details.contains(csvButton)).toBe(true);

    const save = screen.getByRole("region", { name: /save and validation/i });
    expect(
      save.contains(screen.getByRole("button", { name: /^save$/i })),
    ).toBe(true);
    expect(
      save.contains(screen.getByRole("button", { name: /^validate$/i })),
    ).toBe(true);

    const run = screen.getByRole("region", {
      name: /paper run and risk reduction/i,
    });
    expect(run.contains(screen.getByRole("button", { name: /^arm$/i }))).toBe(
      true,
    );
    expect(run.contains(screen.getByLabelText(/venue/i))).toBe(true);
    expect(run.contains(screen.getByLabelText(/paper balance/i))).toBe(true);
  });

  it("keeps alert feedback outside the collapsed technical disclosure so it stays announced", async () => {
    render(<Editor client={makeClient()} />);
    const details = technicalSection();
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: "not json at all" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));
    const alert = await screen.findByTestId("editor-import-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/invalid json/i);
    expect(details.contains(alert)).toBe(false);
  });

  it("auto-expands the technical disclosure when an unsupported imported pack arrives", () => {
    render(<Editor client={makeClient()} />);
    const details = technicalSection();
    expect(details.hasAttribute("open")).toBe(false);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: {
        value: JSON.stringify(unsupportedImportedPack, null, 2),
      },
    });
    expect(screen.getByTestId("owned-strategy-form-unsupported")).toBeDefined();
    expect(details.hasAttribute("open")).toBe(true);
  });

  it("keeps a readable unsaved state instead of a blank save/validation group", () => {
    render(<Editor client={makeClient()} />);
    const save = screen.getByRole("region", { name: /save and validation/i });
    expect(save.textContent).toMatch(/no saved revision yet/i);
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
  });
});

describe("Editor signal slice — behavior preserved under grouping", () => {
  it("Save still creates a revision and Validate still runs on it", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(client.create).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
        /rev-create \(state: Draft\)/,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /^validate$/i }));
    await waitFor(() => expect(client.validate).toHaveBeenCalledWith("rev-create"));
    await waitFor(() =>
      expect(screen.getByTestId("editor-revision-id").textContent).toMatch(
        /rev-create \(state: Validated\)/,
      ),
    );
  });

  it("preserves the exact disabled semantics for Validate, Arm and CSV export", async () => {
    const client = makeClient();
    render(<Editor client={client} />);
    // Fresh draft: no revision yet.
    expect(
      (screen.getByRole("button", { name: /^validate$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /export csv/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: /^validate$/i }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    // Draft revision: Arm stays disabled until validated.
    expect(
      (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /^validate$/i }));
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });
    expect(
      (screen.getByRole("button", { name: /export csv/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("keeps imported unsupported pack bytes byte-for-byte with the form closed", () => {
    const client = makeClient();
    const importedBytes = JSON.stringify(unsupportedImportedPack, null, 2);
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

    // A label edit merges into the unsupported pack without stripping or
    // converting anything else.
    fireEvent.change(screen.getByLabelText(/^label$/i), {
      target: { value: "Renamed import" },
    });
    const after = JSON.parse(
      (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value,
    );
    expect(after.label).toBe("Renamed import");
    expect(after.indicators).toEqual(unsupportedImportedPack.indicators);
    expect(after.entry).toEqual(unsupportedImportedPack.entry);
    expect(after.risk).toEqual(unsupportedImportedPack.risk);
    expect(after.markets).toEqual(unsupportedImportedPack.markets);
    expect(after.origin).toBe(unsupportedImportedPack.origin);
  });

  it("exports the current textarea bytes through the technical export action", async () => {
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

    try {
      // The export action lives in the technical disclosure; reaching it
      // through the same labeled control proves the grouping did not
      // detach it from the editor's export behavior.
      fireEvent.click(screen.getByRole("button", { name: /^export pack$/i }));

      expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
      const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
      expect(await blob.text()).toBe(validPackBytes);

      const downloadAnchors = capturedAnchors.filter(
        (anchor) => anchor.download === "pack.json",
      );
      expect(downloadAnchors.length).toBeGreaterThan(0);
      expect(downloadAnchors[0].href).toBe("blob:test-url");
    } finally {
      clickSpy.mockRestore();
      createObjectURLSpy.mockRestore();
      revokeObjectURLSpy.mockRestore();
      createElementSpy.mockRestore();
    }
  });

  it("shows save outcome, validation errors and revision identity inside the save group", async () => {
    const client = makeClient({
      validate: vi.fn().mockResolvedValue({
        revision_id: "rev-create",
        state: "draft",
        pack: validPack,
        errors: [{ field: "entry", message: "operand is invalid" }],
      }),
      create: vi.fn().mockResolvedValue({
        revision_id: "rev-create",
        state: "draft",
        pack: validPack,
        errors: [],
        outcome: "created",
      }),
    });
    render(<Editor client={client} />);
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: { value: validPackBytes },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("editor-save-outcome").textContent).toMatch(
        /rev-create/,
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /^validate$/i }));
    const errorBlock = await screen.findByTestId("editor-error-entry");
    expect(errorBlock.getAttribute("role")).toBe("alert");
    const save = screen.getByRole("region", { name: /save and validation/i });
    expect(save.contains(errorBlock)).toBe(true);
    expect(
      save.contains(screen.getByTestId("editor-revision-id")),
    ).toBe(true);
  });

  it("arms through the paper-run group with the venue/balance inputs and refreshes the inline stop control", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce({ schema_version: "1", armed: false })
      .mockResolvedValue(armedStatus());
    const paperClient = makePaperClient({ getStatus });
    const client = makeClient();
    render(
      <Editor
        client={client}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: validPackBytes,
        }}
      />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(getStatus).toHaveBeenCalledTimes(1);
    // The risk-reduction control stays visible inside the paper-run group.
    const run = screen.getByRole("region", {
      name: /paper run and risk reduction/i,
    });
    expect(run.contains(screen.getByTestId("editor-inline-stop"))).toBe(true);

    fireEvent.change(screen.getByLabelText(/venue/i), {
      target: { value: "kraken" },
    });
    fireEvent.change(screen.getByLabelText(/paper balance/i), {
      target: { value: "1000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^arm$/i }));
    await waitFor(() =>
      expect(client.arm).toHaveBeenCalledWith("rev-1", "kraken", "1000"),
    );
    // armCounter bump forces the inline stop control to reconcile without
    // a manual Refresh status click.
    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(2));
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries active/);
  });

  it("keeps paper balance as a plain input default, not an account read", () => {
    render(<Editor client={makeClient()} />);
    const venue = screen.getByLabelText(/venue/i) as HTMLInputElement;
    const balance = screen.getByLabelText(/paper balance/i) as HTMLInputElement;
    expect(venue.value).toBe("kraken");
    expect(balance.value).toBe("1000");
    expect(screen.queryByText(/\$1,000/)).toBeNull();
    expect(screen.queryByText(/balance:/i)).toBeNull();
  });

  it("never auto-saves, auto-validates or auto-arms on mount", () => {
    const client = makeClient();
    render(<Editor client={client} />);
    expect(client.create).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
    expect(client.validate).not.toHaveBeenCalled();
    expect(client.arm).not.toHaveBeenCalled();
  });
});

describe("Editor signal slice — stylesheet contract", () => {
  const stylesDir = dirname(fileURLToPath(import.meta.url));
  let css = "";
  const readCss = (): string => {
    if (css === "") {
      css = readFileSync(join(stylesDir, "Editor.signal.css"), "utf8");
    }
    return css;
  };

  it("is root-scoped to the editor and consumes the approved named tokens", () => {
    const css = readCss();
    expect(css).toMatch(/^\.kbot-strategy-editor\b/m);
    for (const token of [
      "--navy",
      "--surface",
      "--panel",
      "--line",
      "--text",
      "--muted",
      "--seafoam",
      "--sage",
      "--coral",
    ]) {
      expect(css).toContain(`var(${token}`);
    }
  });

  it("does not reintroduce the retired neon palette or remote fonts", () => {
    const css = readCss();
    for (const legacy of ["#07090d", "#5ce1ff", "#c6ff3d"]) {
      expect(css.toLowerCase()).not.toContain(legacy);
    }
    expect(css).not.toMatch(/@import|https?:\/\//);
    expect(css).not.toMatch(/font-family:\s*ui-monospace/);
  });

  it("keeps narrow surfaces reachable with 44px controls and explicit internal scroll", () => {
    const css = readCss();
    const mediaIndex = css.indexOf("@media");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex);
    expect(narrow).toMatch(/min-height:\s*44px/);
    // Long JSON/revision content must not widen the page.
    expect(css).toMatch(/\.kbot-strategy-editor__textarea[\s\S]*?overflow-x:\s*auto/);
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
  });
});
