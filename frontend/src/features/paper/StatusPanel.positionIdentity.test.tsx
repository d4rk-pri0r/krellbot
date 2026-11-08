import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperPosition, PaperStatus } from "./client";

afterEach(cleanup);
const status: PaperStatus = { schema_version: "1", armed: true, venue: "kraken", pair: "SUIUSD", mode: "paper", entries_paused: false, pack_id: "synthetic" };
const position: PaperPosition = { schema_version: "1", armed: true, venue: "kraken", pair: "SUIUSD", mode: "paper", holdings: [{ symbol: "SUI", qty: "2.5000" }], free_cash: "748.123400", as_of_run: "synthetic" };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
function client(): PaperClient {
  return { getStatus: vi.fn().mockImplementation(async () => ({ ...status })), getPosition: vi.fn().mockResolvedValue(position),
    pauseEntries: vi.fn(), resumeEntries: vi.fn(), disarm: vi.fn(),
    createRehearsalClient: () => ({ getStatus: vi.fn().mockResolvedValue({ schema_version: "1", label: "SYNTHETIC", status: "idle", cursor: 0, total_bars: 0, balances: {}, position: "0", resting_stop: null, recent_fills: [] }), start: vi.fn(), pause: vi.fn(), resume: vi.fn(), exit: vi.fn(), stop: vi.fn() }),
  } as PaperClient;
}

describe("paper position identity", () => {
  it.each([{ pair: "ETHUSD" }, { venue: "coinbase" }])("drops cached holdings while a changed market position is pending: %j", async (change) => {
    const api = client();
    render(<StatusPanel client={api} />);
    await screen.findByTestId("paper-position");
    const next = deferred<PaperPosition>();
    vi.mocked(api.getStatus).mockResolvedValue({ ...status, ...change });
    vi.mocked(api.getPosition!).mockReturnValue(next.promise);
    fireEvent.click(screen.getAllByRole("button", { name: "Refresh status" }).find((button) => button.classList.contains("kbot-paper-status__action"))!);
    await waitFor(() => expect(api.getPosition).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("paper-position")).toBeNull();
    expect(screen.getByTestId("paper-position-pending")).toBeDefined();
    await act(async () => { next.resolve({ ...position, ...change, holdings: [], free_cash: "123.4500" }); });
    expect((await screen.findByTestId("paper-position")).textContent).toContain("123.4500");
    expect(screen.getByTestId("paper-position").textContent).not.toContain("2.5000");
  });

  it.each([{ pair: "ETHUSD" }, { venue: "coinbase" }, { mode: "live" }, { armed: false }])("rejects an independently returned mismatched position and recovers: %j", async (change) => {
    const api = client();
    vi.mocked(api.getPosition!).mockResolvedValue({ ...position, ...change });
    render(<StatusPanel client={api} />);
    expect((await screen.findByTestId("paper-position-unavailable")).textContent).toMatch(/identity|market/i);
    expect(screen.queryByTestId("paper-position")).toBeNull();
    vi.mocked(api.getPosition!).mockResolvedValue(position);
    fireEvent.click(screen.getAllByRole("button", { name: "Refresh status" }).find((button) => button.classList.contains("kbot-paper-status__action"))!);
    expect((await screen.findByTestId("paper-position")).textContent).toBe("Owned position: 2.5000 SUI — free cash 748.123400 USD");
  });

  it("clears an old position error on market change", async () => {
    const api = client();
    vi.mocked(api.getPosition!).mockRejectedValueOnce(new Error("synthetic old market read failure"));
    render(<StatusPanel client={api} />);
    await screen.findByTestId("paper-position-unavailable");
    vi.mocked(api.getStatus).mockResolvedValue({ ...status, pair: "ETHUSD" });
    vi.mocked(api.getPosition!).mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getAllByRole("button", { name: "Refresh status" }).find((button) => button.classList.contains("kbot-paper-status__action"))!);
    await waitFor(() => expect(api.getPosition).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("paper-position-unavailable")).toBeNull();
    expect(screen.getByTestId("paper-position-pending")).toBeDefined();
  });

  it("preserves matching decimal strings during a same-identity refresh", async () => {
    const api = client();
    render(<StatusPanel client={api} />);
    const shown = await screen.findByTestId("paper-position");
    vi.mocked(api.getStatus).mockResolvedValue({ ...status });
    vi.mocked(api.getPosition!).mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getAllByRole("button", { name: "Refresh status" }).find((button) => button.classList.contains("kbot-paper-status__action"))!);
    await waitFor(() => expect(api.getPosition).toHaveBeenCalledTimes(2));
    expect(shown.textContent).toBe("Owned position: 2.5000 SUI — free cash 748.123400 USD");
  });
});
