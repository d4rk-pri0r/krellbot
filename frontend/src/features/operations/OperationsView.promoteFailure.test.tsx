import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type { CommandResult, OperationsClient, OperationsViewModel } from "./client";

afterEach(cleanup);

const model: OperationsViewModel = {
  schema_version: "1",
  live: {
    schema_version: "1", live_enabled: false, authorized: [],
    kill_switch: { engaged: false, reason: null, engaged_at: null },
    promotion_available: false, promotion_code: "live_promotion_owner_deferred",
  },
  deployments: ["SUIUSD", "BTCUSD"].map((pair) => ({
    venue: "kraken", pair, pack_id: "LOCAL_PROMOTE_TEST", pack_version: "1",
    mode: "paper", entries_paused: false,
    promotion: { available: false, code: "live_promotion_owner_deferred" },
  })),
  alerts: [],
};

// Controlled clients isolate thrown command outcomes and in-flight click races;
// the mounted component and its refresh hook are real.
function clientFor(promote: OperationsClient["promote"]): OperationsClient {
  return {
    getOperations: vi.fn().mockResolvedValue(model), promote,
    pauseEntries: vi.fn(), resumeEntries: vi.fn(), engageKill: vi.fn(),
    releaseKill: vi.fn(), ackAlert: vi.fn(),
  };
}
const buttonId = "ops-promote-kraken-SUIUSD";
const resultId = "ops-promote-result-kraken-SUIUSD";

describe("promotion failure honesty", () => {
  it.each([new Error("network unavailable"), "upstream 503"])(
    "keeps a thrown outcome unknown and refreshes, then clears error on retry: %s",
    async (error) => {
      const promote = vi.fn<OperationsClient["promote"]>()
        .mockRejectedValueOnce(error)
        .mockResolvedValue({ code: "live_promotion_owner_deferred", message: "owner approval required" });
      const client = clientFor(promote);
      render(<OperationsView client={client} />);
      fireEvent.click(await screen.findByTestId(buttonId));
      const failure = await screen.findByTestId("ops-promote-error");
      expect(failure.getAttribute("role")).toBe("alert");
      expect(failure.textContent).toBe(`Promote failed: ${error instanceof Error ? error.message : String(error)}`);
      expect(failure.closest("li")?.getAttribute("data-testid")).toBe("ops-deployment-kraken-SUIUSD");
      expect(screen.queryByTestId(resultId)).toBeNull();
      expect(screen.getAllByTestId("ops-promote-error")).toHaveLength(1);
      await waitFor(() => expect(client.getOperations).toHaveBeenCalledTimes(2));
      await waitFor(() => expect((screen.getByTestId(buttonId) as HTMLButtonElement).disabled).toBe(false));
      fireEvent.click(screen.getByTestId(buttonId));
      expect((await screen.findByTestId(resultId)).textContent).toBe("Refused: Live promotion owner deferred — owner approval required");
      await waitFor(() => expect(screen.queryByTestId("ops-promote-error")).toBeNull());
      expect(client.getOperations).toHaveBeenCalledTimes(3);
      expect(promote).toHaveBeenNthCalledWith(2, "kraken", "SUIUSD", "deployment");
    },
  );

  it("prevents duplicate sends while pending and preserves refresh failure visibility", async () => {
    let reject!: (error: Error) => void;
    const promote = vi.fn<OperationsClient["promote"]>(() => new Promise<CommandResult>((_, fail) => { reject = fail; }));
    const client = clientFor(promote);
    vi.mocked(client.getOperations).mockResolvedValueOnce(model).mockRejectedValue(new Error("refresh unavailable"));
    render(<OperationsView client={client} />);
    const button = await screen.findByTestId(buttonId) as HTMLButtonElement;
    fireEvent.click(button);
    fireEvent.click(button);
    expect(promote).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    expect((screen.getByTestId("ops-promote-kraken-BTCUSD") as HTMLButtonElement).disabled).toBe(false);
    reject(new Error("command unavailable"));
    expect((await screen.findByTestId("ops-promote-error")).textContent).toContain("command unavailable");
    expect((await screen.findByTestId("ops-stale-warning")).textContent).toContain("refresh unavailable");
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(screen.queryByTestId(resultId)).toBeNull();
  });
});
