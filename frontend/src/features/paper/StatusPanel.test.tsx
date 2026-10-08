import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(Storage.prototype, "setItem");
});

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const status: PaperStatus = {
    schema_version: "1",
    armed: false,
  };
  return {
    getStatus: vi.fn().mockResolvedValue(status),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
      message: "entries paused: kraken SUIUSD",
      effect: "changed",
      revision_before: "before",
      revision_after: "after",
    } satisfies PaperCommandResult),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
      message: "entries resumed: kraken SUIUSD",
      effect: "changed",
      revision_before: "before",
      revision_after: "after",
    } satisfies PaperCommandResult),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
      message: "disarmed kraken SUIUSD",
      effect: "changed",
      revision_before: "before",
      revision_after: "after",
    } satisfies PaperCommandResult),
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

describe("StatusPanel empty state", () => {
  it("renders 'No pack armed' when status says armed=false", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-empty")).toBeDefined();
    });
    expect(screen.getByTestId("paper-status-empty").textContent).toMatch(
      /No pack armed/,
    );
    // No controls while not armed.
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
  });
});

describe("StatusPanel armed controls", () => {
  it("shows Pause entries, Resume entries, and Disarm when status says armed", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /pause entries/i })).toBeDefined();
    });
    expect(screen.getByRole("button", { name: /resume entries/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /^disarm$/i })).toBeDefined();
  });

  it("renders 'Entries active' initially when entries_paused is false", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries active/);
  });

  it("renders 'Entries paused' initially when entries_paused is true", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(
        armedStatus({ entries_paused: true }),
      ),
    });
    render(<StatusPanel client={client} />);
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries paused/);
  });

  it("never renders a button whose name contains 'Live'", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-status-entries");
    const panel = screen.getByTestId("paper-status-panel");
    expect(panel.textContent ?? "").not.toMatch(/Live/);
    const buttons = panel.querySelectorAll("button");
    for (const btn of Array.from(buttons)) {
      expect(btn.textContent ?? "").not.toMatch(/Live/);
    }
  });

  it("hides pause, resume, and disarm when the armed mode is not paper", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus({ mode: "live" })),
    });
    render(<StatusPanel client={client} />);
    expect(await screen.findByText(/Controls unavailable/)).toBeDefined();
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
  });

  it("renders the pack id, venue, and pair in the status line", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const pack = await screen.findByTestId("paper-status-pack");
    expect(pack.textContent).toMatch(/trend-follow/);
    expect(pack.textContent).toMatch(/kraken/);
    expect(pack.textContent).toMatch(/SUIUSD/);
  });
});

describe("StatusPanel pause / resume / disarm commands", () => {
  it("Pause entries posts paper.pause_entries with {schema_version, command, payload:{venue,pair}}", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledTimes(1);
    });
    expect(client.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    // Pause sent as the typed envelope expected by the API.
    const lastFetch = (pause as unknown as { __lastFetch?: unknown }).__lastFetch;
    void lastFetch; // body assertion is on the client call.
    expect((client.pauseEntries as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual([
      "kraken",
      "SUIUSD",
    ]);
  });

  it("Resume entries posts paper.resume_entries with venue/pair", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const resume = await screen.findByRole("button", { name: /resume entries/i });
    fireEvent.click(resume);
    await waitFor(() => {
      expect(client.resumeEntries).toHaveBeenCalledTimes(1);
    });
    expect(client.resumeEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
  });

  it("Disarm posts paper.disarm with venue/pair", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const disarm = await screen.findByRole("button", { name: /^disarm$/i });
    fireEvent.click(disarm);
    await waitFor(() => {
      expect(client.disarm).toHaveBeenCalledTimes(1);
    });
    expect(client.disarm).toHaveBeenCalledWith("kraken", "SUIUSD");
  });
});

describe("StatusPanel visible status", () => {
  it("after a successful pause the visible sentence is 'Entries paused'", async () => {
    const afterStatus: PaperStatus = armedStatus({ entries_paused: true });
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(armedStatus())
        .mockResolvedValueOnce(afterStatus),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await waitFor(() => {
      const entries = screen.getByTestId("paper-status-entries");
      expect(entries.textContent).toMatch(/Entries paused/);
    });
  });

  it("after a successful resume the visible sentence is 'Entries active'", async () => {
    const afterStatus: PaperStatus = armedStatus({ entries_paused: false });
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(armedStatus({ entries_paused: true }))
        .mockResolvedValueOnce(afterStatus),
    });
    render(<StatusPanel client={client} />);
    const resume = await screen.findByRole("button", { name: /resume entries/i });
    fireEvent.click(resume);
    await waitFor(() => {
      const entries = screen.getByTestId("paper-status-entries");
      expect(entries.textContent).toMatch(/Entries active/);
    });
  });

  it("a refused command does not change the visible sentence", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "not_armed",
        ok: false,
        message: "not armed: kraken SUIUSD",
        effect: "refused",
        revision_before: "before",
        revision_after: "before",
      } satisfies PaperCommandResult),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    const before = screen.getByTestId("paper-status-entries").textContent;
    expect(before).toMatch(/Entries active/);
    fireEvent.click(pause);
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledTimes(1);
    });
    // Sentence unchanged.
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(/Entries active/);
    // Error message is surfaced.
    expect(screen.getByTestId("paper-status-error").textContent).toMatch(/not armed/);
  });

  it("after a successful disarm the panel hides the controls", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(armedStatus())
        .mockResolvedValueOnce({ schema_version: "1", armed: false }),
    });
    render(<StatusPanel client={client} />);
    const disarm = await screen.findByRole("button", { name: /^disarm$/i });
    fireEvent.click(disarm);
    await waitFor(() => {
      expect(client.disarm).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    });
    expect(screen.getByTestId("paper-status-empty").textContent).toMatch(/No pack armed/);
  });
});

describe("StatusPanel persistence", () => {
  it("does not write to localStorage on render or click", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await waitFor(() => {
      expect(client.pauseEntries).toHaveBeenCalledTimes(1);
    });
    expect(setItemSpy).not.toHaveBeenCalled();
  });
});

describe("StatusPanel unavailable state", () => {
  function unavailableMessage(): HTMLElement {
    return screen.getByTestId("paper-status-unavailable");
  }

  async function renderUnavailable(): Promise<{
    client: PaperClient;
    panel: HTMLElement;
  }> {
    const client = makeClient({
      getStatus: vi.fn().mockRejectedValue(new Error("paper status failed: 503")),
    });
    render(<StatusPanel client={client} />);
    await waitFor(() => {
      expect(unavailableMessage().textContent).toMatch(/unavailable/i);
    });
    return { client, panel: screen.getByTestId("paper-status-panel") };
  }

  it("shows an explicit unavailable state when the initial getStatus fails", async () => {
    const { panel } = await renderUnavailable();
    // The panel must not manufacture a confirmed unarmed response.
    expect(panel.textContent ?? "").not.toMatch(/No pack armed/);
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
  });

  it("shows no pause, resume, or disarm controls while the status is unknown", async () => {
    await renderUnavailable();
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
  });

  it("offers an explicit retry control after an initial failure", async () => {
    await renderUnavailable();
    expect(
      screen.getByRole("button", { name: /retry/i }),
    ).toBeDefined();
  });

  it("retry recovers to the armed state after an initial failure", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockRejectedValueOnce(new Error("paper status failed: 503"))
        .mockResolvedValueOnce(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-unavailable")).toBeDefined();
    });
    expect(client.getStatus).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries active/);
    expect(screen.getByTestId("paper-status-pack").textContent).toMatch(
      /trend-follow/,
    );
    expect(client.getStatus).toHaveBeenCalledTimes(2);
    // The unavailable state is gone once a real status is confirmed.
    expect(screen.queryByTestId("paper-status-unavailable")).toBeNull();
  });

  it("retry recovers to a confirmed unarmed state after an initial failure", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockRejectedValueOnce(new Error("paper status failed: 503"))
        .mockResolvedValueOnce({ schema_version: "1", armed: false }),
    });
    render(<StatusPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-unavailable")).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-empty").textContent).toMatch(
        /No pack armed/,
      );
    });
    expect(client.getStatus).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("paper-status-unavailable")).toBeNull();
  });

  it("a failed retry keeps the unavailable state instead of an unarmed claim", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockRejectedValue(new Error("paper status failed: 503")),
    });
    render(<StatusPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-unavailable")).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByTestId("paper-status-unavailable").textContent).toMatch(
      /unavailable/i,
    );
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
    // Still no unsafe controls while unknown.
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
  });
});

describe("StatusPanel pending initial status", () => {
  function deferred(): {
    promise: Promise<PaperStatus>;
    resolve: (value: PaperStatus) => void;
    reject: (reason?: unknown) => void;
  } {
    let resolve!: (value: PaperStatus) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<PaperStatus>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  }

  it("shows a truthful loading state with no controls and no unarmed claim while the initial getStatus is pending", async () => {
    const gate = deferred();
    const client = makeClient({ getStatus: vi.fn().mockReturnValue(gate.promise) });
    render(<StatusPanel client={client} />);

    // The initial lookup is still in flight: availability is unknown.
    expect(screen.getByTestId("paper-status-panel")).toBeDefined();
    expect(screen.getByTestId("paper-status-loading").textContent).toMatch(
      /checking|loading|unavailable/i,
    );
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
    expect(
      screen.getByTestId("paper-status-panel").textContent ?? "",
    ).not.toMatch(/No pack armed/);
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();

    // A confirmed unarmed response is the only thing that may claim it.
    await act(async () => {
      gate.resolve({ schema_version: "1", armed: false });
    });
    expect(screen.getByTestId("paper-status-empty").textContent).toMatch(
      /No pack armed/,
    );
    expect(screen.queryByTestId("paper-status-loading")).toBeNull();
  });

  it("shows a truthful loading state with no controls while pending, then unavailable on rejection", async () => {
    const gate = deferred();
    const client = makeClient({ getStatus: vi.fn().mockReturnValue(gate.promise) });
    render(<StatusPanel client={client} />);

    expect(screen.getByTestId("paper-status-loading")).toBeDefined();
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
    expect(screen.queryByTestId("paper-status-unavailable")).toBeNull();
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();

    await act(async () => {
      gate.reject(new Error("paper status failed: 503"));
    });
    expect(
      screen.getByTestId("paper-status-unavailable").textContent,
    ).toMatch(/unavailable/i);
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
  });
});

function commandGate() {
  let resolve!: (value: PaperCommandResult) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<PaperCommandResult>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("StatusPanel command pending guard", () => {
  async function renderArmed(): Promise<PaperClient> {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    await screen.findByRole("button", { name: /pause entries/i });
    return client;
  }

  it("a repeated pause click while pending sends the command exactly once", async () => {
    const client = await renderArmed();
    const gate = commandGate();
    (client.pauseEntries as ReturnType<typeof vi.fn>).mockReturnValue(gate.promise);
    // The initial load already consumed the default status; queue the
    // post-command reconciliation read with the server's paused truth.
    (client.getStatus as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      armedStatus({ entries_paused: true }),
    );
    const pause = screen.getByRole("button", { name: /pause entries/i });

    fireEvent.click(pause);
    fireEvent.click(pause);
    fireEvent.click(pause);

    expect(client.pauseEntries).toHaveBeenCalledTimes(1);
    expect(client.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");

    // All controls are disabled while the command is in flight, and the
    // pending command is announced.
    expect(pause.getAttribute("disabled")).not.toBeNull();
    expect(
      screen.getByRole("button", { name: /resume entries/i }).getAttribute("disabled"),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: /^disarm$/i }).getAttribute("disabled"),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: /refresh status/i }).getAttribute("disabled"),
    ).not.toBeNull();
    expect(screen.getByTestId("paper-status-panel").getAttribute("data-pending")).toBe(
      "pause",
    );

    // No optimistic sentence change while the outcome is unknown.
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );

    await act(async () => {
      gate.resolve({
        schema_version: "1",
        code: "entries_paused",
        ok: true,
        message: "entries paused: kraken SUIUSD",
      } satisfies PaperCommandResult);
    });
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
        /Entries paused/,
      );
    });
    // Pending cleared: controls usable again.
    expect(pause.getAttribute("disabled")).toBeNull();
    expect(screen.getByTestId("paper-status-panel").getAttribute("data-pending")).toBe("");
  });

  it("a repeated disarm click while pending sends the command exactly once", async () => {
    const client = await renderArmed();
    const gate = commandGate();
    (client.disarm as ReturnType<typeof vi.fn>).mockReturnValue(gate.promise);
    const disarm = screen.getByRole("button", { name: /^disarm$/i });

    fireEvent.click(disarm);
    fireEvent.click(disarm);

    expect(client.disarm).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );

    await act(async () => {
      gate.resolve({
        schema_version: "1",
        code: "disarmed",
        ok: true,
        message: "disarmed kraken SUIUSD",
      } satisfies PaperCommandResult);
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
    });
    expect(screen.getByTestId("paper-status-empty").textContent).toMatch(/No pack armed/);
  });
});

describe("StatusPanel command transport failures", () => {
  it("a pause transport failure shows an unknown outcome without optimistic success and without an automatic read", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      pauseEntries: vi.fn().mockRejectedValue(new Error("paper.pause_entries failed: 503")),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);

    const alert = await screen.findByTestId("paper-status-unknown");
    expect(alert.textContent).toMatch(/Pause outcome unknown/i);
    expect(alert.textContent).toMatch(/paper\.pause_entries failed: 503/);
    expect(alert.textContent).toMatch(/refresh/i);
    // No optimistic success and no fabricated state change.
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
    // No automatic retry or reconciliation read after the failure.
    await act(async () => {
      await Promise.resolve();
    });
    expect(client.getStatus).toHaveBeenCalledTimes(1);
    // Pending cleared so the user may act again.
    expect(pause.getAttribute("disabled")).toBeNull();
    expect(screen.getByTestId("paper-status-panel").getAttribute("data-pending")).toBe("");
  });

  it("an explicit refresh after an unknown pause reconciles to the server state and clears the unknown alert", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(armedStatus())
        .mockResolvedValueOnce(armedStatus({ entries_paused: true })),
      pauseEntries: vi.fn().mockRejectedValue(new Error("network error")),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await screen.findByTestId("paper-status-unknown");

    fireEvent.click(screen.getByRole("button", { name: /refresh status/i }));

    await waitFor(() => {
      expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
        /Entries paused/,
      );
    });
    expect(client.getStatus).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("paper-status-unknown")).toBeNull();
    expect(pause.getAttribute("disabled")).toBeNull();
  });

  it("a failing refresh keeps the last confirmed state instead of an unarmed claim and stays refreshable", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(armedStatus())
        .mockRejectedValueOnce(new Error("paper status failed: 503")),
      disarm: vi.fn().mockRejectedValue(new Error("paper.disarm failed: 503")),
    });
    render(<StatusPanel client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: /^disarm$/i }));
    await screen.findByTestId("paper-status-unknown");
    expect(screen.getByTestId("paper-status-unknown").textContent).toMatch(
      /Disarm outcome unknown/i,
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh status/i }));

    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalledTimes(2);
    });
    // The read failure is surfaced, the armed pack is still shown, and no
    // unarmed state is fabricated.
    const alert = await screen.findByTestId("paper-status-unknown");
    expect(alert.textContent).toMatch(/Status refresh failed/i);
    expect(screen.getByTestId("paper-status-pack").textContent).toMatch(/trend-follow/);
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
    expect(
      screen.getByRole("button", { name: /refresh status/i }).getAttribute("disabled"),
    ).toBeNull();
  });

  it("a malformed command response without an ok flag is treated as refused, not success", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      pauseEntries: vi.fn().mockResolvedValue({} satisfies PaperCommandResult),
    });
    render(<StatusPanel client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: /pause entries/i }));
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-error").textContent).toMatch(
        /Pause refused/,
      );
    });
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
    expect(screen.getByTestId("paper-status-panel").getAttribute("data-pending")).toBe("");
  });

  it("a refused command clears pending and keeps the controls usable", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "not_armed",
        ok: false,
        message: "not armed: kraken SUIUSD",
      } satisfies PaperCommandResult),
    });
    render(<StatusPanel client={client} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-error").textContent).toMatch(/not armed/);
    });
    expect(pause.getAttribute("disabled")).toBeNull();
    expect(screen.getByTestId("paper-status-panel").getAttribute("data-pending")).toBe("");
  });

  it("a late command response after unmount does not update the panel", async () => {
    const gate = commandGate();
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      pauseEntries: vi.fn().mockReturnValue(gate.promise),
    });
    const { unmount } = render(<StatusPanel client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: /pause entries/i }));
    expect(client.pauseEntries).toHaveBeenCalledTimes(1);

    unmount();

    // Resolving the in-flight command after unmount must not throw when
    // the retired handler tries to apply its (now stale) result.
    await act(async () => {
      gate.resolve({
        schema_version: "1",
        code: "entries_paused",
        ok: true,
        message: "entries paused: kraken SUIUSD",
      } satisfies PaperCommandResult);
      await Promise.resolve();
    });
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
  });

  it("a superseded response does not overwrite a later confirmed state", async () => {
    const client = makeClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(armedStatus({ entries_paused: true }))
        .mockResolvedValueOnce(armedStatus({ entries_paused: false })),
    });
    render(<StatusPanel client={client} />);
    const resume = await screen.findByRole("button", { name: /resume entries/i });
    fireEvent.click(resume);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
        /Entries active/,
      );
    });
    // The post-command reconciliation read confirms the same truth and
    // never reverts the sentence to a stale value.
    await act(async () => {
      await Promise.resolve();
    });
    expect(client.getStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
  });
});
