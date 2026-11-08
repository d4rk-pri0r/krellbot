import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type { CommandResult, OperationsClient, OperationsViewModel } from "./client";

afterEach(cleanup);

function model(engaged: boolean): OperationsViewModel {
  return {
    schema_version: "1",
    live: {
      schema_version: "1", live_enabled: false, authorized: [],
      kill_switch: { engaged, reason: engaged ? "synthetic prior reason" : null, engaged_at: null },
      promotion_available: false, promotion_code: "live_promotion_owner_deferred",
    },
    deployments: [{ venue: "kraken", pair: "SUIUSD", pack_id: "synthetic", pack_version: "1",
      mode: "paper", entries_paused: false, promotion: { available: false, code: "live_promotion_owner_deferred" } }],
    alerts: [],
  };
}

function clientFor(action: "engage" | "release", command: () => Promise<CommandResult>): OperationsClient {
  return {
    getOperations: vi.fn().mockResolvedValue(model(action === "release")),
    promote: vi.fn(), pauseEntries: vi.fn(), resumeEntries: vi.fn(), ackAlert: vi.fn(),
    engageKill: action === "engage" ? command : vi.fn(),
    releaseKill: action === "release" ? command : vi.fn(),
  };
}

async function mount(action: "engage" | "release", client: OperationsClient) {
  render(<OperationsView client={client} />);
  const reason = await screen.findByTestId("ops-kill-reason") as HTMLInputElement;
  fireEvent.change(reason, { target: { value: "  synthetic operator reason  " } });
  return { reason, button: screen.getByTestId(`ops-kill-${action}`) as HTMLButtonElement };
}

describe.each(["engage", "release"] as const)("kill %s command feedback", (action) => {
  it("preserves the reason and renders a confirmed refusal without inventing state", async () => {
    const command = vi.fn().mockResolvedValue({ ok: false, code: "bad_input", message: "synthetic refusal reason" });
    const client = clientFor(action, command);
    const { reason, button } = await mount(action, client);
    fireEvent.click(button);
    const feedback = await screen.findByTestId("ops-kill-command-feedback");
    expect(feedback.getAttribute("role")).toBe("alert");
    expect(feedback.textContent).toMatch(/refused/i);
    expect(feedback.textContent).toContain("bad_input");
    expect(feedback.textContent).toContain("synthetic refusal reason");
    expect(reason.value).toBe("  synthetic operator reason  ");
    expect(screen.getByTestId("ops-kill-state").textContent).toContain(action === "engage" ? "released" : "engaged");
    expect(command).toHaveBeenCalledTimes(1);
  });

  it.each([{}, { ok: "true" }, null])("does not treat malformed success as confirmation: %j", async (result) => {
    const command = vi.fn().mockResolvedValue(result);
    const { reason, button } = await mount(action, clientFor(action, command));
    fireEvent.click(button);
    expect((await screen.findByTestId("ops-kill-command-feedback")).textContent).toContain("outcome unknown");
    expect(reason.value).toBe("  synthetic operator reason  ");
    expect(command).toHaveBeenCalledTimes(1);
  });

  it("catches transport failure, preserves input, and allows explicit state reconciliation without retry", async () => {
    const command = vi.fn().mockRejectedValue(new Error("synthetic transport loss"));
    const client = clientFor(action, command);
    const { reason, button } = await mount(action, client);
    fireEvent.click(button);
    const feedback = await screen.findByTestId("ops-kill-command-feedback");
    expect(feedback.textContent).toContain("outcome unknown");
    expect(feedback.textContent).toContain("check state before retrying");
    expect(reason.value).toBe("  synthetic operator reason  ");
    vi.mocked(client.getOperations).mockResolvedValue(model(action === "engage"));
    fireEvent.click(screen.getByTestId("ops-refresh"));
    await waitFor(() => expect(screen.getByTestId("ops-kill-state").textContent).toContain(action === "engage" ? "engaged" : "released"));
    expect(command).toHaveBeenCalledTimes(1);
  });

  it("blocks duplicate pending sends while leaving refresh and other safety controls available", async () => {
    let finish!: (result: CommandResult) => void;
    const command = vi.fn(() => new Promise<CommandResult>((resolve) => { finish = resolve; }));
    const client = clientFor(action, command);
    const { reason, button } = await mount(action, client);
    act(() => { button.click(); button.click(); });
    expect(command).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect((screen.getByTestId("ops-refresh") as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByTestId("ops-pause-kraken-SUIUSD") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(reason, { target: { value: "newer unsent reason" } });
    await act(async () => { finish({ ok: true }); });
    expect(reason.value).toBe("newer unsent reason");
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it("clears an engage reason only after explicit ok:true and refreshes real state", async () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    const client = clientFor(action, command);
    const { reason, button } = await mount(action, client);
    vi.mocked(client.getOperations).mockResolvedValue(model(action === "engage"));
    fireEvent.click(button);
    await waitFor(() => expect(client.getOperations).toHaveBeenCalledTimes(2));
    expect(reason.value).toBe(action === "engage" ? "" : "  synthetic operator reason  ");
    expect(screen.queryByTestId("ops-kill-command-feedback")).toBeNull();
  });
});
