import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type { PaperClient, PaperStatus } from "../paper/client";

afterEach(cleanup);

const validPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

function makeStrategyClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-edit",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
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

function disarmButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^disarm$/i,
  }) as HTMLButtonElement;
}

function armButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement;
}

describe("EditorInlineStopControl refreshSignal", () => {
  it("re-fetches status when the parent bumps refreshSignal, without a remount or manual refresh click", async () => {
    const unarmed: PaperStatus = { schema_version: "1", armed: false };
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmed)
      .mockResolvedValue(armedStatus());
    const paperClient = makePaperClient({ getStatus });

    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    // Initial fetch settles on the unarmed placeholder.
    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(disarmButton().disabled).toBe(true);
    expect(getStatus).toHaveBeenCalledTimes(1);

    const controlBefore = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );

    // Parent bumps the signal after its own Arm succeeds; the client now
    // reports the armed venue/pair. No click, no navigation, no remount.
    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    // Same mounted instance: the DOM node was reconciled in place.
    const controlAfter = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );
    expect(controlAfter).toBe(controlBefore);
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries active/);
  });

  it("Editor's own Arm success enables the inline controls without clicking Refresh status", async () => {
    const unarmed: PaperStatus = { schema_version: "1", armed: false };
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmed)
      .mockResolvedValue(armedStatus());
    const paperClient = makePaperClient({ getStatus });
    const client = makeStrategyClient();

    render(
      <Editor
        client={client}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(getStatus).toHaveBeenCalledTimes(1);

    expect(armButton().disabled).toBe(false);
    fireEvent.click(armButton());

    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    expect(client.arm).toHaveBeenCalledWith("rev-1", "kraken", "1000");

    // No Refresh-status click happens: the signal-driven re-fetch alone
    // must enable Disarm/Pause/Resume in the same mounted control.
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries active/);
  });

  it("an arm failure does NOT trigger the inline re-fetch (no bump on catch)", async () => {
    const unarmed: PaperStatus = { schema_version: "1", armed: false };
    const getStatus = vi.fn().mockResolvedValue(unarmed);
    const paperClient = makePaperClient({ getStatus });
    const client = makeStrategyClient({
      arm: vi.fn().mockRejectedValue(new Error("venue closed")),
    });

    render(
      <Editor
        client={client}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();

    fireEvent.click(armButton());
    const error = await screen.findByTestId("editor-arm-error");
    expect(error.textContent).toMatch(/Arm failed: venue closed/);

    // Only the mount fetch ever happened: a failed arm must never be
    // reported as an armed state.
    expect(getStatus).toHaveBeenCalledTimes(1);
    expect(disarmButton().disabled).toBe(true);
  });
});
