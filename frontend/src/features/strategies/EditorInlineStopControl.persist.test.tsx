import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";

afterEach(cleanup);

function armedStatus(): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
  };
}

function raiseOk(newStop: string): PaperCommandResult {
  return {
    schema_version: "1",
    code: "stop_raised",
    ok: true,
    message: `stop set: kraken SUIUSD -> ${newStop}`,
    effect: "changed",
  };
}

function disarmOk(): PaperCommandResult {
  return {
    schema_version: "1",
    code: "disarmed",
    ok: true,
    effect: "changed",
  };
}

// Hand-rolled fake: only the command surface the inline control touches. No
// network, no fetchStarters; status reads are sequenced through the
// refreshSignal prop.
function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ ok: true }),
    disarm: vi.fn().mockResolvedValue(disarmOk()),
    raiseStop: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  };
}

function stopInput(): HTMLInputElement {
  return screen.getByTestId(
    "editor-inline-stop-new-stop",
  ) as HTMLInputElement;
}

function applyButton(): HTMLButtonElement {
  return screen.getByTestId("editor-inline-stop-apply") as HTMLButtonElement;
}

function disarmButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^disarm$/i,
  }) as HTMLButtonElement;
}

async function raiseTo(value: string): Promise<void> {
  // Wait for the armed raise block to mount before typing: the mount status
  // read resolves asynchronously.
  const input = (await screen.findByTestId(
    "editor-inline-stop-new-stop",
  )) as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  await waitFor(() => {
    expect(applyButton().disabled).toBe(false);
  });
  fireEvent.click(applyButton());
  await waitFor(() => {
    expect(screen.getByTestId("editor-inline-stop-at").textContent).toBe(
      `stop at ${value}`,
    );
  });
}

async function disarmConfirmed(): Promise<void> {
  fireEvent.click(disarmButton());
  await waitFor(() => {
    expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
      /No pack armed/,
    );
  });
}

describe("EditorInlineStopControl stop persistence across disarm + re-arm", () => {
  it("(a) renders no stop-at text on mount when status.armed is false", async () => {
    const paperClient = makePaperClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: false,
      }),
    });
    render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();
    expect(screen.queryByText(/stop at/)).toBeNull();
  });

  it("(b) renders stop at 6.25 after a confirmed raise_stop success", async () => {
    const raiseStop = vi.fn().mockResolvedValue(raiseOk("6.25"));
    const paperClient = makePaperClient({ raiseStop });
    render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    await raiseTo("6.25");
    expect(raiseStop).toHaveBeenCalledTimes(1);
    expect(raiseStop).toHaveBeenCalledWith("kraken", "SUIUSD", "6.25");
  });

  it("(c) still renders stop at 6.25 after Disarm + re-arm via a refreshSignal bump, with no re-raise", async () => {
    const raiseStop = vi.fn().mockResolvedValue(raiseOk("6.25"));
    const paperClient = makePaperClient({ raiseStop });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    await raiseTo("6.25");
    await disarmConfirmed();
    // Disarm removes the armed surface, so the remembered value is invisible.
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();

    // Parent bumps the signal after its own Arm succeeds: the same mounted
    // control re-reads status and re-displays the remembered stop verbatim.
    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );

    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 6.25");
    expect(disarmButton().disabled).toBe(false);
    // The remembered value came from memory, not a second raise.
    expect(raiseStop).toHaveBeenCalledTimes(1);
  });

  it("(d) a second confirmed raise_stop overwrites the remembered value with stop at 7.0", async () => {
    const raiseStop = vi
      .fn()
      .mockResolvedValueOnce(raiseOk("6.25"))
      .mockResolvedValueOnce(raiseOk("7.0"));
    const paperClient = makePaperClient({ raiseStop });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    await raiseTo("6.25");
    await disarmConfirmed();
    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("editor-inline-stop-at").textContent).toBe(
        "stop at 6.25",
      );
    });

    fireEvent.change(stopInput(), { target: { value: "7.0" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());
    await waitFor(() => {
      expect(screen.getByTestId("editor-inline-stop-at").textContent).toBe(
        "stop at 7.0",
      );
    });
    expect(raiseStop).toHaveBeenCalledTimes(2);
  });

  it("(e) shows no stop-at after Disarm + a new Arm when no raise_stop ever happened", async () => {
    const raiseStop = vi.fn();
    const paperClient = makePaperClient({ raiseStop });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();

    await disarmConfirmed();
    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();
    expect(screen.queryByText(/stop at/)).toBeNull();
    expect(raiseStop).not.toHaveBeenCalled();
  });
});
