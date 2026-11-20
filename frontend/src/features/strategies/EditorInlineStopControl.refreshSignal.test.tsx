import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type { PaperClient, PaperStatus } from "../paper/client";

afterEach(cleanup);

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

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(disarmButton().disabled).toBe(true);
    expect(getStatus).toHaveBeenCalledTimes(1);

    const controlBefore = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    const controlAfter = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );
    expect(controlAfter).toBe(controlBefore);
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries active/);
  });

  it("does NOT trigger an inline re-fetch when refreshSignal stays unchanged", async () => {
    const unarmed: PaperStatus = { schema_version: "1", armed: false };
    const getStatus = vi.fn().mockResolvedValue(unarmed);
    const paperClient = makePaperClient({ getStatus });

    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );
    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );
    expect(getStatus).toHaveBeenCalledTimes(1);
    expect(disarmButton().disabled).toBe(true);
  });

  it("a refreshSignal bump after Arm success triggers the same one-shot automatic getStatus() (post_arm_refresh slot, no polling)", async () => {
    const unarmed: PaperStatus = { schema_version: "1", armed: false };
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmed)
      .mockResolvedValue(armedStatus());
    const paperClient = makePaperClient({ getStatus });

    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );
    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(getStatus).toHaveBeenCalledTimes(1);

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    await new Promise((resolve) => {
      setTimeout(resolve, 150);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries active/);

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );
    expect(getStatus).toHaveBeenCalledTimes(2);
  });
});
