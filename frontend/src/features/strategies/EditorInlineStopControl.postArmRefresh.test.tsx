import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";

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

function disarmOk(): PaperCommandResult {
  return {
    schema_version: "1",
    code: "disarmed",
    ok: true,
    effect: "changed",
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

function makePaperClient(overrides: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ ok: true }),
    disarm: vi.fn().mockResolvedValue(disarmOk()),
    raiseStop: vi.fn().mockResolvedValue(raiseOk("6.25")),
    ...overrides,
  };
}

function armButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^arm$/i }) as HTMLButtonElement;
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

function renderEditor(paperClient: PaperClient, client: StrategyClient) {
  return render(
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
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("EditorInlineStopControl post-Arm automatic status refresh", () => {
  it("(a) on Arm success fires exactly one automatic getStatus() and mirrors the armed status, without Refresh, Paper-tab navigation or a remount", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmedStatus)
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const paperClient = makePaperClient({ getStatus });
    const client = makeStrategyClient();
    const view = renderEditor(paperClient, client);

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(getStatus).toHaveBeenCalledTimes(1);

    const controlBefore = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );

    fireEvent.click(armButton());
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });

    // Exactly ONE automatic read after the confirmed Arm: no polling, no
    // manual Refresh click, no remount of the inline control.
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
    const client = makeStrategyClient();
    renderEditor(paperClient, client);

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(getStatus).toHaveBeenCalledTimes(1);

    fireEvent.click(armButton());
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    // The post-Arm read is in flight (held on the deferred) and has not
    // been joined by any second automatic request.
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    expect(disarmButton().disabled).toBe(true);

    second.resolve(armedStatus());
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });

    // Give any hypothetical poller ample time to fire: none may.
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
    const client = makeStrategyClient();
    renderEditor(paperClient, client);

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();

    fireEvent.click(armButton());
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });

    // The automatic path already reconciled: armed controls are live.
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    // Option, not requirement: the Refresh button still exists and still
    // issues exactly one further read when the user chooses it.
    expect(refreshButton().disabled).toBe(false);
    fireEvent.click(refreshButton());
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(3);
    });

    // Option, not requirement: a remount still performs its mount read.
    cleanup();
    const remount = renderEditor(
      makePaperClient({
        getStatus: vi.fn().mockResolvedValue(armedStatus()),
      }),
      client,
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
    const client = makeStrategyClient();
    renderEditor(paperClient, client);

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();

    fireEvent.click(armButton());
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });

    const unknown = await screen.findByTestId("editor-inline-stop-unknown");
    expect(unknown.getAttribute("role")).toBe("alert");
    expect(unknown.textContent).toMatch(
      /Status refresh failed: boom: connection reset/,
    );
    // The last confirmed (unarmed) state is kept; exactly one automatic
    // attempt, no auto-retry, no manufactured armed state.
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
    const client = makeStrategyClient();
    renderEditor(paperClient, client);

    // First Arm: post-Arm read #2 mirrors the armed state.
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

    // Disarm: the remembered stop leaves view but survives in memory.
    fireEvent.click(disarmButton());
    await waitFor(() => {
      expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
        /No pack armed/,
      );
    });
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();

    // Second Arm in the same Editor (the first client.arm call in this
    // scenario): the post-Arm read re-displays the resting stop without any
    // re-raise.
    fireEvent.click(armButton());
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 6.25");
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(raiseStop).toHaveBeenCalledTimes(1);
  });
});
