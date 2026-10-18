import { readFileSync } from "node:fs";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RehearsalPanel } from "./RehearsalPanel";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";

afterEach(cleanup);
const status = (lifecycle = "idle"): RehearsalStatus => ({
  schema_version: "1", label: "Synthetic test fixture", status: lifecycle,
  cursor: 0, total_bars: 20, balances: { USD: "1000" }, position: "0",
  resting_stop: null, recent_fills: [],
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
// Only the transport is deferred; the mounted component and reducer are real.
function clientWith(overrides: Partial<RehearsalClient> = {}): RehearsalClient {
  return {
    getStatus: vi.fn().mockResolvedValue(status()),
    start: vi.fn(), pause: vi.fn(), resume: vi.fn(), exit: vi.fn(), stop: vi.fn(),
    ...overrides,
  };
}
const commands = [
  ["start", "idle", "Start rehearsal", "Starting…", "Starting rehearsal…"],
  ["pause", "running", "Pause rehearsal", "Pausing…", "Pause requested…"],
  ["resume", "paused", "Resume rehearsal", "Resuming…", "Resume requested…"],
  ["exit", "running", "Exit rehearsal", "Exiting…", "Exit requested…"],
  ["stop", "running", "Stop rehearsal", "Stopping…", "Stop requested…"],
] as const;
const button = (name: string) => screen.getByTestId(`rehearsal-command-${name}`) as HTMLButtonElement;
const live = () => screen.getByTestId("rehearsal-commands-busy-status");
function expectBusy(name: string, label: string, announcement: string) {
  expect(button(name).getAttribute("aria-busy")).toBe("true");
  expect(button(name).disabled).toBe(true);
  expect(button(name).textContent).toBe(label);
  expect(live().textContent).toBe(announcement);
  expect(live().getAttribute("aria-live")).toBe("polite");
  expect(live().getAttribute("role")).toBeNull();
  expect(live().parentElement).toBe(screen.getByTestId("rehearsal-commands-panel"));
  expect(live().previousElementSibling?.className).toBe("kbot-rehearsal__actions");
  fireEvent.mouseDown(button(name));
  fireEvent.keyDown(button(name), { key: "Enter", repeat: true });
  fireEvent.click(button(name));
}
function expectSettled(name: string, label: string) {
  expect(button(name).hasAttribute("aria-busy")).toBe(false);
  expect(button(name).textContent).toBe(label);
  expect(live().textContent).toBe("Settled");
}

describe("rehearsal-commands-busy", () => {
  it("exposes six idle shortcuts and preserves action classes", async () => {
    render(<RehearsalPanel client={clientWith()} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    const buttons = within(screen.getByTestId("rehearsal-commands-panel")).getAllByRole("button");
    expect(buttons).toHaveLength(6);
    for (const action of buttons) {
      expect(action.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
      expect(action.hasAttribute("aria-busy")).toBe(false);
      expect(action.className).toBe(action === button("start")
        ? "kbot-rehearsal__action kbot-rehearsal__action--primary" : "kbot-rehearsal__action");
    }
  });

  it.each(commands)("signals %s through settlement and permits later activation", async (name, lifecycle, idle, active, announcement) => {
    const response = deferred<RehearsalCommandResult>();
    const nextResponse = deferred<RehearsalCommandResult>();
    const action = vi.fn().mockImplementationOnce(() => response.promise).mockImplementationOnce(() => nextResponse.promise);
    render(<RehearsalPanel client={clientWith({ getStatus: vi.fn().mockResolvedValue(status(lifecycle)), [name]: action })} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    button(name).focus();
    expect(document.activeElement).toBe(button(name));
    fireEvent.click(button(name));
    expectBusy(name, active, announcement);
    expect(action).toHaveBeenCalledTimes(1);
    await act(async () => response.resolve({ ok: true, status: status(lifecycle) }));
    expectSettled(name, idle);
    expect(button(name).disabled).toBe(false);
    fireEvent.click(button(name));
    expectBusy(name, active, announcement);
    expect(action).toHaveBeenCalledTimes(2);
    await act(async () => nextResponse.resolve({ ok: true, status: status(lifecycle) }));
    expectSettled(name, idle);
  });

  it("guards synchronous clicks before React commits disabled attributes", async () => {
    const response = deferred<RehearsalCommandResult>();
    const start = vi.fn(() => response.promise);
    render(<RehearsalPanel client={clientWith({ start })} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    act(() => {
      button("start").click();
      button("start").click();
    });
    expectBusy("start", "Starting…", "Starting rehearsal…");
    expect(start).toHaveBeenCalledTimes(1);
    expect(button("stop").disabled).toBe(true);
    expect(button("refresh").disabled).toBe(true);
    await act(async () => response.resolve({ ok: true, status: status() }));
    expectSettled("start", "Start rehearsal");
  });

  it.each(["refusal", "rejection"])("settles %s on the existing error surface", async (failure) => {
    const response = deferred<RehearsalCommandResult>();
    const start = vi.fn(() => response.promise);
    render(<RehearsalPanel client={clientWith({ start })} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    fireEvent.click(button("start"));
    expectBusy("start", "Starting…", "Starting rehearsal…");
    await act(async () => {
      if (failure === "refusal") response.resolve({ ok: false, message: "refused fixture" });
      else response.reject(new Error("transport fixture"));
    });
    expectSettled("start", "Start rehearsal");
    const error = screen.getByTestId(failure === "refusal" ? "rehearsal-error" : "rehearsal-unknown");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toContain(failure === "refusal" ? "refused fixture" : "transport fixture");
    if (failure === "refusal") expect(error.className).toBe("kbot-rehearsal__error");
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("keeps start busy after pending clears until reconciliation settles", async () => {
    const followUp = deferred<RehearsalStatus>();
    const start = vi.fn().mockResolvedValue({ ok: true });
    render(<RehearsalPanel client={clientWith({ start, getStatus: vi.fn().mockResolvedValueOnce(status()).mockImplementation(() => followUp.promise) })} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    await act(async () => fireEvent.click(button("start")));
    expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-pending")).toBe("");
    expectBusy("start", "Starting…", "Starting rehearsal…");
    expect(start).toHaveBeenCalledTimes(1);
    await act(async () => followUp.resolve(status()));
    expectSettled("start", "Start rehearsal");
    expect(button("start").disabled).toBe(false);
  });

  it.each([false, true])("signals refresh until settlement (rejected=%s)", async (failure) => {
    const response = deferred<RehearsalStatus>();
    const getStatus = vi.fn().mockResolvedValueOnce(status()).mockImplementation(() => response.promise);
    render(<RehearsalPanel client={clientWith({ getStatus })} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    fireEvent.click(button("refresh"));
    expectBusy("refresh", "Refreshing status…", "Refreshing status…");
    expect(getStatus).toHaveBeenCalledTimes(2);
    await act(async () => { if (failure) response.reject(new Error("refresh fixture")); else response.resolve(status()); });
    expectSettled("refresh", "Refresh status");
    expect(button("refresh").disabled).toBe(false);
  });

  it("calls each command once during a lifecycle journey on one mount", async () => {
    const client = clientWith();
    for (const [name, next] of [["start", "running"], ["pause", "paused"], ["resume", "running"], ["exit", "exited"], ["stop", "stopped"]] as const) {
      vi.mocked(client[name]).mockResolvedValue({ ok: true, status: status(next) });
    }
    // Exit disables stop; a readback makes stop reachable without another command.
    vi.mocked(client.getStatus).mockResolvedValueOnce(status()).mockResolvedValue(status("running"));
    render(<RehearsalPanel client={client} />);
    await screen.findByTestId("rehearsal-holdings-panel");
    for (const name of ["start", "pause", "resume", "exit", "refresh", "stop"]) {
      await act(async () => fireEvent.click(button(name)));
    }
    for (const [name] of commands) expect(client[name]).toHaveBeenCalledTimes(1);
    expect(client.getStatus).toHaveBeenCalledTimes(2);
  });

  it("preserves every existing conditional testid verbatim", () => {
    const source = readFileSync("src/features/paper/RehearsalPanel.tsx", "utf8");
    for (const id of ["commands-panel", "error", "state-chip", "loading", "sentence", "holdings-panel", "cursor", "position", "stop", "balance", "fills-panel", "fills-empty", "fill", "eyebrow", "label", "load-failed", "panel", "unavailable", "unknown"]) {
      expect(source).toContain(`data-testid="rehearsal-${id}"`);
    }
  });
});
