import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type { OperationsClient, OperationsViewModel } from "./client";

afterEach(cleanup);

// Client doubles isolate event ordering and command failures; the runtime
// verifier exercises the real client, server and Chromium separately.
function setup(engageKill = vi.fn<OperationsClient["engageKill"]>().mockResolvedValue({ ok: true })) {
  const view: OperationsViewModel = {
    schema_version: "1", deployments: [], alerts: [],
    live: { schema_version: "1", live_enabled: false, authorized: [],
      kill_switch: { engaged: false, reason: null, engaged_at: null },
      promotion_available: false, promotion_code: "live_disabled" },
  };
  const client: OperationsClient = {
    getOperations: vi.fn().mockResolvedValue(view), engageKill,
    releaseKill: vi.fn(), promote: vi.fn(), pauseEntries: vi.fn(),
    resumeEntries: vi.fn(), ackAlert: vi.fn(),
  };
  render(<OperationsView client={client} />);
  return client;
}

async function reason(value: string) {
  const input = await screen.findByTestId("ops-kill-reason");
  fireEvent.change(input, { target: { value } });
  return input;
}

describe("kill engagement safety", () => {
  it.each(["x", " a b c ", "   "])("refuses %j on Enter with an accessible inline reason", async value => {
    const client = setup();
    const input = await reason(value);
    fireEvent.keyDown(input, { key: "Enter" });
    const error = await screen.findByTestId("ops-kill-reason-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toContain("at least 4 non-whitespace characters");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toContain(error.id);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(client.engageKill).not.toHaveBeenCalled();
    expect(screen.queryByTestId("ops-kill-engage-confirm")).toBeNull();
  });

  it("refuses a short reason on click as well as Enter", async () => {
    const client = setup();
    await reason("x");
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    expect(await screen.findByTestId("ops-kill-reason-error")).toBeDefined();
    expect(client.engageKill).not.toHaveBeenCalled();
  });

  it("shows server refusal without claiming engagement", async () => {
    const client = setup(vi.fn<OperationsClient["engageKill"]>().mockResolvedValue({ ok: false, message: "local refusal" }));
    await reason("local safety check");
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    fireEvent.click(screen.getByTestId("ops-kill-engage-confirm-submit"));
    expect((await screen.findByTestId("ops-kill-engage-error")).textContent).toContain("local refusal");
    expect(screen.getByTestId("ops-kill-state").textContent).toBe("Kill switch: released");
    expect(client.getOperations).toHaveBeenCalledTimes(1);
  });

  it("confirms the exact trimmed reason before sending and refreshing", async () => {
    const client = setup();
    await reason("  a b c d  ");
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    expect(client.engageKill).not.toHaveBeenCalled();
    expect(screen.getByTestId("ops-kill-engage-confirm").textContent).toContain("a b c d");
    fireEvent.click(screen.getByTestId("ops-kill-engage-confirm-submit"));
    await waitFor(() => expect(client.engageKill).toHaveBeenCalledExactlyOnceWith("a b c d"));
    await waitFor(() => expect(client.getOperations).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("ops-kill-engage-confirm")).toBeNull();
  });

  it("cancels without sending and invalidates confirmation on edit", async () => {
    const client = setup();
    await reason("local safety check");
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    fireEvent.click(screen.getByTestId("ops-kill-engage-confirm-cancel"));
    expect(screen.queryByTestId("ops-kill-engage-confirm")).toBeNull();
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    await reason("different reason");
    expect(screen.queryByTestId("ops-kill-engage-confirm")).toBeNull();
    expect(client.engageKill).not.toHaveBeenCalled();
  });

  it("shows failure honestly and requires fresh confirmation to retry", async () => {
    const client = setup(vi.fn<OperationsClient["engageKill"]>().mockRejectedValue(new Error("session required")));
    await reason("local safety check");
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    fireEvent.click(screen.getByTestId("ops-kill-engage-confirm-submit"));
    const error = await screen.findByTestId("ops-kill-engage-error");
    expect(error.textContent).toContain("outcome unknown");
    expect(error.textContent).toContain("session required");
    expect(screen.queryByTestId("ops-kill-engage-confirm")).toBeNull();
    expect(client.engageKill).toHaveBeenCalledTimes(1);
  });

  it("prevents duplicate sends while confirmation is pending", async () => {
    let complete!: (result: { ok: boolean }) => void;
    const client = setup(vi.fn<OperationsClient["engageKill"]>().mockImplementation(() => new Promise(resolve => { complete = resolve; })));
    await reason("local safety check");
    fireEvent.click(screen.getByTestId("ops-kill-engage"));
    const submit = screen.getByTestId("ops-kill-engage-confirm-submit");
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(client.engageKill).toHaveBeenCalledTimes(1);
    complete({ ok: true });
    await waitFor(() => expect(screen.queryByTestId("ops-kill-engage-confirm")).toBeNull());
  });
});
