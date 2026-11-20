import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";

afterEach(cleanup);

const unarmedStatus: PaperStatus = { schema_version: "1", armed: false };

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

function raiseOk(stop: string): PaperCommandResult {
  return {
    schema_version: "1",
    code: "stop_raised",
    ok: true,
    message: `stop set: kraken SUIUSD -> ${stop}`,
    effect: "changed",
  };
}

function disarmOk(): PaperCommandResult {
  return {
    schema_version: "1",
    code: "disarmed",
    ok: true,
    message: "disarmed: kraken SUIUSD",
    effect: "changed",
  };
}

function makePaperClient(overrides: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ ok: true }),
    disarm: vi.fn().mockResolvedValue(disarmOk()),
    raiseStop: vi.fn().mockResolvedValue(raiseOk("2.5")),
    ...overrides,
  };
}

function disarmButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^disarm$/i,
  }) as HTMLButtonElement;
}

function refreshButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /refresh status/i,
  }) as HTMLButtonElement;
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("EditorInlineStopControl post-Arm automatic status refresh", () => {
  it("(a) on refreshSignal bump fires exactly one automatic getStatus() and mirrors the armed status, without Refresh or a remount", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmedStatus)
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const paperClient = makePaperClient({ getStatus });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
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
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries paused/);

    const controlAfter = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );
    expect(controlAfter).toBe(controlBefore);
  });

  it("(b) resolves zero automatic polls after the post-Arm read settles", async () => {
    const second = deferred<PaperStatus>();
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmedStatus)
      .mockReturnValueOnce(second.promise)
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
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    expect(disarmButton().disabled).toBe(true);

    second.resolve(armedStatus());
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });

    await new Promise((resolve) => {
      setTimeout(resolve, 150);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);
  });

  it("(c) Refresh status and remount remain available options but are NOT required to see the armed controls", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmedStatus)
      .mockResolvedValue(armedStatus());
    const paperClient = makePaperClient({ getStatus });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    expect(refreshButton().disabled).toBe(false);
    fireEvent.click(refreshButton());
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(3);
    });

    cleanup();
    const remount = render(
      <EditorInlineStopControl
        paperClient={makePaperClient({
          getStatus: vi.fn().mockResolvedValue(armedStatus()),
        })}
        refreshSignal={0}
      />,
    );
    expect(remount).toBeDefined();
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
  });

  it("(d) a failed post-Arm getStatus surfaces the same unknown-outcome path as disarm/raise_stop and never auto-retries", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmedStatus)
      .mockRejectedValueOnce(new Error("boom: connection reset"))
      .mockResolvedValue(armedStatus());
    const paperClient = makePaperClient({ getStatus });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );

    const unknown = await screen.findByTestId("editor-inline-stop-unknown");
    expect(unknown.getAttribute("role")).toBe("alert");
    expect(unknown.textContent).toMatch(
      /Status refresh failed: boom: connection reset/,
    );
    expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
      /No pack armed/,
    );
    expect(disarmButton().disabled).toBe(true);

    await new Promise((resolve) => {
      setTimeout(resolve, 150);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);
  });

  it("(e) the persisted stopAt from the disarm + re-arm slice re-displays after the post-Arm read returns armed=true", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValue(armedStatus());
    const raiseStop = vi.fn().mockResolvedValue(raiseOk("6.25"));
    const disarm = vi.fn().mockResolvedValue(disarmOk());
    const paperClient = makePaperClient({ getStatus, raiseStop, disarm });
    const view = render(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={0} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    const input = (await screen.findByTestId(
      "editor-inline-stop-new-stop",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "6.25" } });
    fireEvent.click(
      screen.getByTestId("editor-inline-stop-apply") as HTMLButtonElement,
    );
    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 6.25");

    fireEvent.click(disarmButton());
    await waitFor(() => {
      expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
        /No pack armed/,
      );
    });
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();

    view.rerender(
      <EditorInlineStopControl paperClient={paperClient} refreshSignal={1} />,
    );
    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 6.25");
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(raiseStop).toHaveBeenCalledTimes(1);
  });
});
