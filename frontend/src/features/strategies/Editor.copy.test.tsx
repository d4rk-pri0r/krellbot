import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";

afterEach(cleanup);

const ownedPack = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "local workstation",
  timeframe: "4h",
  indicators: { ma: { fn: "ema", src: "close", len: 36 } },
  entry: ["close", "crosses_above", "ma"],
  exit: ["close", "crosses_below", "ma"],
  risk: { max_account_pct: 40, stop: { type: "pct", pct: 6.5 } },
  markets: [{ venue: "kraken", pair: "XXBTZUSD" }],
};

const ownedPackBytes = JSON.stringify(ownedPack, null, 2);

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockImplementation(async (pack: Record<string, unknown>) => ({
      revision_id: "rev-copy-created",
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
    validate: vi.fn(),
    arm: vi.fn(),
    ...overrides,
  };
}

function copiedDraft() {
  return {
    bytes: ownedPackBytes,
    origin: {
      revision_id: "rev-owned-1",
      state: "validated" as const,
      label: "Trend follow",
    },
  };
}

describe("Editor — copiedDraft initialization", () => {
  it("seeds the copied raw bytes and a fresh draft identity, showing the origin revision", () => {
    render(
      <Editor client={makeClient()} copiedDraft={copiedDraft()} />,
    );
    expect((screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value).toBe(
      ownedPackBytes,
    );
    expect(screen.getByTestId("editor-copy-origin").textContent).toContain(
      "rev-owned-1",
    );
    // Fresh draft: no preloaded revision identity and no forged state.
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    expect(screen.queryByTestId("editor-save-outcome")).toBeNull();
    expect(screen.getByTestId("editor-copy-origin").textContent).toMatch(
      /unsaved/i,
    );
  });

  it("Save uses create (not edit) and preserves the copied settings exactly", async () => {
    const client = makeClient();
    const captured: Record<string, unknown>[] = [];
    (client.create as ReturnType<typeof vi.fn>).mockImplementation(
      async (pack: Record<string, unknown>) => {
        captured.push(pack);
        return {
          revision_id: "rev-copy-created",
          state: "draft",
          pack,
          errors: [],
          outcome: "created" as const,
        };
      },
    );
    render(<Editor client={client} copiedDraft={copiedDraft()} />);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(client.create).toHaveBeenCalledTimes(1));
    expect(client.edit).not.toHaveBeenCalled();
    const sent = captured[0];
    expect(sent.indicators).toEqual(ownedPack.indicators);
    expect(sent.entry).toEqual(ownedPack.entry);
    expect(sent.exit).toEqual(ownedPack.exit);
    expect(sent.risk).toEqual(ownedPack.risk);
    expect(sent.markets).toEqual(ownedPack.markets);
    expect(sent.timeframe).toBe("4h");
  });

  it("Save does not change the origin bytes string", async () => {
    const before = ownedPackBytes;
    const client = makeClient();
    render(<Editor client={client} copiedDraft={copiedDraft()} />);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(client.create).toHaveBeenCalledTimes(1));
    expect(before).toBe(ownedPackBytes);
    expect(client.create).toHaveBeenCalledTimes(1);
  });

  it("does not validate or arm anything on mount", () => {
    const client = makeClient();
    render(<Editor client={client} copiedDraft={copiedDraft()} />);
    expect(client.validate).not.toHaveBeenCalled();
    expect(client.arm).not.toHaveBeenCalled();
    expect(client.edit).not.toHaveBeenCalled();
    expect(client.create).not.toHaveBeenCalled();
    // The origin revision is not rendered as the editor's revision identity.
    expect(screen.queryByTestId("editor-revision-id")).toBeNull();
  });

  it("keeps a fresh draft identity after its own save renders the new revision", async () => {
    const client = makeClient();
    render(<Editor client={client} copiedDraft={copiedDraft()} />);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("editor-revision-id").textContent).toContain(
        "rev-copy-created",
      ),
    );
    expect(screen.getByTestId("editor-save-outcome").textContent).toContain(
      "rev-copy-created",
    );
    expect(screen.getByTestId("editor-copy-origin").textContent).toContain(
      "rev-owned-1",
    );
  });
});
