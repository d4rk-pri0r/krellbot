import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient } from "./rehearsalClient";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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

function raiseStopOk(newStop: string): PaperCommandResult {
  // Byte-for-byte the shape paper.py returns on CODE_STOP_RAISED:
  // message "stop set: <venue> <pair> -> <new_stop>".
  return {
    schema_version: "1",
    code: "stop_raised",
    ok: true,
    message: `stop set: kraken SUIUSD -> ${newStop}`,
    effect: "changed",
    revision_before: "before",
    revision_after: "after",
  };
}

function rehearsalIdle(): RehearsalClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      label: "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
      status: "idle",
      cursor: 0,
      total_bars: 20,
      balances: { USD: "1000" },
      position: "0",
      resting_stop: null,
      recent_fills: [],
    }),
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    exit: vi.fn(),
    stop: vi.fn(),
  } as RehearsalClient;
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const client: PaperClient = {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    createRehearsalClient: () => rehearsalIdle(),
    ...overrides,
  };
  return client;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

/**
 * The /api/v1/commands response the real backend returns for a raise_stop
 * that lands above the resting stop. `inner` overrides the body.
 */
function commandResponse(inner: Record<string, unknown>): PaperCommandResult {
  return {
    schema_version: "1",
    code: "stop_raised",
    ok: true,
    message: "stop set: kraken SUIUSD -> 0.75",
    effect: "changed",
    revision_before: "before",
    revision_after: "after",
    ...inner,
  };
}

describe("StatusPanel raise-stop (paper armed surface)", () => {
  it("shows the input and Apply new stop button only in the armed paper branch, hidden when unarmed", async () => {
    const armed = makeClient();
    render(<StatusPanel client={armed} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-raise-stop-input")).toBeDefined();
    });
    expect(screen.getByTestId("paper-raise-stop-apply")).toBeDefined();
    expect(
      screen.getByRole("button", { name: /apply new stop/i }),
    ).toBeDefined();

    cleanup();
    const unarmed = makeClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: false,
      } satisfies PaperStatus),
    });
    render(<StatusPanel client={unarmed} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-empty")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-raise-stop")).toBeNull();
    expect(screen.queryByTestId("paper-raise-stop-input")).toBeNull();
    expect(screen.queryByTestId("paper-raise-stop-apply")).toBeNull();
  });

  it("POSTs paper.raise_stop, mirrors the backend success echo, and refreshes status without a manual refresh", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(commandResponse({ message: "stop set: kraken SUIUSD -> 0.75" })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
    });
    render(<StatusPanel client={client} />);

    fireEvent.change(await screen.findByTestId("paper-raise-stop-input"), {
      target: { value: "0.75" },
    });
    // A valid decimal clears the validation error and enables Apply.
    await waitFor(() => {
      expect(
        screen.getByTestId("paper-raise-stop-apply").getAttribute("disabled"),
      ).toBeNull();
    });
    fireEvent.click(screen.getByTestId("paper-raise-stop-apply"));

    // Exactly one command POST with the exact envelope the handler reads.
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/commands");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(String(init.body))).toEqual({
      schema_version: "1",
      command: "paper.raise_stop",
      payload: { venue: "kraken", pair: "SUIUSD", new_stop: "0.75" },
    });

    // The backend echo is mirrored in the visible sentence.
    const echo = await screen.findByTestId("paper-raise-stop-ok");
    expect(echo.textContent).toBe("raised stop to 0.75");

    // The follow-up read already landed: no manual refresh needed and the
    // panel never claims the new stop from the closed-shape status read.
    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByTestId("paper-raise-stop-ok").textContent).toBe(
      "raised stop to 0.75",
    );
  });

  it("propagates every backend refusal code to the standard refusal display, with no echo and no status refresh", async () => {
    const refusals: Array<{ code: string; message: string }> = [
      {
        code: "invalid_stop",
        message: "new stop must be strictly above the current stop",
      },
      { code: "not_armed", message: "not armed: kraken SUIUSD" },
      { code: "unknown_venue", message: "unknown venue: kraken" },
      {
        code: "stored_mode_not_paper",
        message: "stored mode is 'live'; paper service only mutates paper targets",
      },
    ];
    for (const refusal of refusals) {
      cleanup();
      const fetchMock = vi.fn().mockResolvedValue(
        jsonResponse(
          commandResponse({
            code: refusal.code,
            ok: false,
            message: refusal.message,
            effect: "refused",
          }),
        ),
      );
      vi.stubGlobal("fetch", fetchMock);
      const client = makeClient({
        getStatus: vi.fn().mockResolvedValue(armedStatus()),
      });
      render(<StatusPanel client={client} />);
      fireEvent.change(await screen.findByTestId("paper-raise-stop-input"), {
        target: { value: "0.10" },
      });
      fireEvent.click(screen.getByTestId("paper-raise-stop-apply"));

      // The same inline refusal surface disarm/pause/resume use.
      const error = await screen.findByTestId("paper-status-error");
      expect(error.textContent).toBe(refusal.message);
      // Refused: no success echo, and no follow-up reconciliation read.
      expect(screen.queryByTestId("paper-raise-stop-ok")).toBeNull();
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledTimes(1);
      });
      expect(client.getStatus).toHaveBeenCalledTimes(1);
      // The armed controls survive a refusal; Apply is usable again.
      expect(
        screen.getByTestId("paper-raise-stop-apply").getAttribute("disabled"),
      ).toBeNull();
      vi.unstubAllGlobals();
    }
  });

  it("rejects NaN, Infinity, empty and unparseable values: Apply disabled plus inline error, then accepts a valid decimal", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);
    const input = await screen.findByTestId("paper-raise-stop-input");
    const apply = screen.getByTestId("paper-raise-stop-apply");

    // Empty on mount is already invalid: the affordance is inert.
    expect(apply.getAttribute("disabled")).toBe("");
    expect(screen.getByTestId("paper-raise-stop-error")).toBeDefined();

    for (const bad of ["NaN", "Infinity", "abc", "1e3", ".5", "-1"]) {
      fireEvent.change(input, { target: { value: bad } });
      expect(apply.getAttribute("disabled")).toBe("");
      const error = screen.getByTestId("paper-raise-stop-error");
      expect(error.textContent).toMatch(/plain decimal/i);
    }

    // A parseable positive decimal unlocks Apply and clears the error.
    fireEvent.change(input, { target: { value: "1050.25" } });
    expect(apply.getAttribute("disabled")).toBeNull();
    expect(screen.queryByTestId("paper-raise-stop-error")).toBeNull();
  });
});
