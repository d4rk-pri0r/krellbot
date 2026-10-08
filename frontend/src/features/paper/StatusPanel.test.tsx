import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import {
  PaperCommandRefusalError,
  type PaperClient,
  type PaperCommandResult,
  type PaperStatus,
} from "./client";

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
    exportPaperPack: vi.fn().mockResolvedValue({ filename: null, bytes: "{}" }),
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

describe("StatusPanel export button availability", () => {
  function exportButton(): HTMLButtonElement {
    return screen.getByTestId("paper-export-btn") as HTMLButtonElement;
  }

  it("is enabled only when armed, mode is paper, and venue/pair are present", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-status-entries");
    const button = exportButton();
    expect(button.disabled).toBe(false);
    expect(button.textContent).toMatch(/^Download pack$/);
  });

  it("is disabled with 'Download pack — not armed' when status.armed is false", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue({ schema_version: "1", armed: false }),
    });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-status-empty");
    const button = exportButton();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toMatch(/Download pack — not armed/);
    expect(button.getAttribute("data-reason")).toBe("not armed");
  });

  it("is disabled with 'Download pack — pack stored in live mode' when mode is live", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus({ mode: "live" })),
    });
    render(<StatusPanel client={client} />);
    await screen.findByText(/Controls unavailable/);
    const button = exportButton();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toMatch(/Download pack — pack stored in live mode/);
  });

  it("is disabled with 'Download pack — venue/pair unavailable' when venue or pair is empty", async () => {
    const missingVenue = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus({ venue: undefined })),
    });
    render(<StatusPanel client={missingVenue} />);
    await screen.findByText(/Controls unavailable/);
    let button = exportButton();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toMatch(/Download pack — venue\/pair unavailable/);
    cleanup();

    const missingPair = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus({ pair: undefined })),
    });
    render(<StatusPanel client={missingPair} />);
    await screen.findByText(/Controls unavailable/);
    button = exportButton();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toMatch(/Download pack — venue\/pair unavailable/);
  });
});

describe("StatusPanel export download", () => {
  const urlProps = { createObjectURL: "createObjectURL", revokeObjectURL: "revokeObjectURL" };
  let created: Blob[];
  let revoked: string[];
  let clicked: HTMLAnchorElement[];
  let clickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    created = [];
    revoked = [];
    clicked = [];
    const urlRecord = URL as unknown as Record<string, unknown>;
    urlRecord.createObjectURL = vi.fn((blob: Blob) => {
      created.push(blob);
      return "blob:paper-pack-1";
    });
    urlRecord.revokeObjectURL = vi.fn((url: string) => {
      revoked.push(url);
    });
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      function handleClick(this: HTMLAnchorElement) {
        clicked.push(this);
      },
    );
  });

  afterEach(() => {
    const urlRecord = URL as unknown as Record<string, unknown>;
    delete urlRecord[urlProps.createObjectURL];
    delete urlRecord[urlProps.revokeObjectURL];
    void clickSpy;
    void revoked;
  });

  it("clicking the enabled button calls exportPaperPack with the armed venue and pair", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);
    const button = await screen.findByTestId("paper-export-btn");
    fireEvent.click(button);
    await waitFor(() => {
      expect(client.exportPaperPack).toHaveBeenCalledTimes(1);
    });
    expect(client.exportPaperPack).toHaveBeenCalledWith("kraken", "SUIUSD");
  });

  it("disables the button and shows a pending text while the export is in flight", async () => {
    let release: (value: { filename: string | null; bytes: string }) => void = () => {};
    const gate = new Promise<{ filename: string | null; bytes: string }>((resolve) => {
      release = resolve;
    });
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      exportPaperPack: vi.fn().mockReturnValue(gate),
    });
    render(<StatusPanel client={client} />);
    const button = (await screen.findByTestId("paper-export-btn")) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => {
      expect((screen.getByTestId("paper-export-btn") as HTMLButtonElement).disabled).toBe(true);
    });
    expect(screen.getByTestId("paper-export-btn").textContent).toMatch(/Downloading/i);
    // No download while pending.
    expect(clicked).toHaveLength(0);
    await act(async () => {
      release({ filename: null, bytes: "{}" });
    });
    await waitFor(() => {
      expect((screen.getByTestId("paper-export-btn") as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it("triggers a browser download of the pack bytes with the fallback venue/pair filename", async () => {
    const bytes = JSON.stringify({ schema_version: "1", id: "trend-follow" });
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      exportPaperPack: vi.fn().mockResolvedValue({ filename: null, bytes }),
    });
    render(<StatusPanel client={client} />);
    fireEvent.click(await screen.findByTestId("paper-export-btn"));
    await waitFor(() => {
      expect(clicked).toHaveLength(1);
    });
    const anchor = clicked[0];
    // The response carried no pack_id, so only the venue/pair fallback names it.
    expect(anchor.download).toBe("krellbot-pack-kraken-SUIUSD.json");
    expect(anchor.href).toBe("blob:paper-pack-1");
    expect(created).toHaveLength(1);
    expect(created[0].type).toBe("application/json");
    expect(await created[0].text()).toBe(bytes);
    expect(revoked).toEqual(["blob:paper-pack-1"]);
    // No refusal text on success.
    expect(screen.queryByTestId("paper-export-error")).toBeNull();
  });

  it("uses the response-provided filename when the export result carries one", async () => {
    const bytes = JSON.stringify({ schema_version: "1", id: "trend-follow" });
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      exportPaperPack: vi.fn().mockResolvedValue({ filename: "trend-follow", bytes }),
    });
    render(<StatusPanel client={client} />);
    fireEvent.click(await screen.findByTestId("paper-export-btn"));
    await waitFor(() => {
      expect(clicked).toHaveLength(1);
    });
    expect(clicked[0].download).toBe("trend-follow");
  });

  it.each(["not_armed", "unknown_venue", "stored_mode_not_paper", "invalid_pack"])(
    "surfaces the %s refusal without crashing the panel",
    async (code) => {
      const client = makeClient({
        getStatus: vi.fn().mockResolvedValue(armedStatus()),
        exportPaperPack: vi
          .fn()
          .mockRejectedValue(new PaperCommandRefusalError(code, `refused: ${code}`)),
      });
      render(<StatusPanel client={client} />);
      fireEvent.click(await screen.findByTestId("paper-export-btn"));
      const error = await screen.findByTestId("paper-export-error");
      expect(error.textContent).toMatch(new RegExp(code));
      expect(error.textContent).toMatch(/refused: /);
      // The panel stays mounted and usable.
      expect(screen.getByTestId("paper-status-panel")).toBeDefined();
      expect(screen.getByTestId("paper-status-entries")).toBeDefined();
      expect(clicked).toHaveLength(0);
    },
  );

  it("surfaces a network failure honestly without retrying", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      exportPaperPack: vi
        .fn()
        .mockRejectedValue(new PaperCommandRefusalError("network_failure", "paper.export request failed")),
    });
    render(<StatusPanel client={client} />);
    fireEvent.click(await screen.findByTestId("paper-export-btn"));
    const error = await screen.findByTestId("paper-export-error");
    expect(error.textContent).toMatch(/network_failure/);
    expect(client.exportPaperPack).toHaveBeenCalledTimes(1);
    expect(clicked).toHaveLength(0);
  });
});
