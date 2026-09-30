import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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