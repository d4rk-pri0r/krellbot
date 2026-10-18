import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type { OperationsClient, OperationsViewModel } from "./client";
import { OPERATIONS_READ_TIMEOUT_MS } from "./useOperationsRefresh";

const VIEW: OperationsViewModel = {
  schema_version: "1",
  live: {
    schema_version: "1",
    live_enabled: false,
    authorized: [],
    kill_switch: { engaged: false, reason: null, engaged_at: null },
    promotion_available: false,
    promotion_code: "live_promotion_owner_deferred",
  },
  deployments: [],
  alerts: [],
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Operations manual refresh busy affordance", () => {
  it.each(["resolve", "reject", "timeout"] as const)(
    "blocks overlapping clicks and returns to idle after %s",
    async (outcome) => {
      let resolveRead!: (value: OperationsViewModel) => void;
      let rejectRead!: (reason: Error) => void;
      const pendingRead = new Promise<OperationsViewModel>((resolve, reject) => {
        resolveRead = resolve;
        rejectRead = reject;
      });
      let reads = 0;
      const unexpectedCommand = async (): Promise<never> => {
        throw new Error("refresh must not send commands");
      };
      const client: OperationsClient = {
        getOperations: () => {
          reads += 1;
          return reads === 1 ? Promise.resolve(VIEW) : pendingRead;
        },
        promote: unexpectedCommand,
        pauseEntries: unexpectedCommand,
        resumeEntries: unexpectedCommand,
        engageKill: unexpectedCommand,
        releaseKill: unexpectedCommand,
        ackAlert: unexpectedCommand,
      };
      render(<OperationsView client={client} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      const button = screen.getByTestId("ops-refresh") as HTMLButtonElement;
      expect(button.className).toBe("kbot-ops__refresh");
      expect(button.textContent).toBe("Refresh now");
      expect(button.hasAttribute("aria-busy")).toBe(false);
      expect(button.disabled).toBe(false);

      fireEvent.click(button);
      expect(reads).toBe(2);
      expect(button.getAttribute("aria-busy")).toBe("true");
      expect(button.disabled).toBe(true);
      expect(button.textContent).toBe("Refreshing…");
      fireEvent.click(button);
      expect(reads).toBe(2);
      expect(screen.queryByTestId("ops-stale-warning")).toBeNull();

      await act(async () => {
        if (outcome === "resolve") resolveRead(VIEW);
        if (outcome === "reject") rejectRead(new Error("local read failed"));
        await vi.advanceTimersByTimeAsync(
          outcome === "timeout" ? OPERATIONS_READ_TIMEOUT_MS : 0,
        );
      });
      expect(button.hasAttribute("aria-busy")).toBe(false);
      expect(button.disabled).toBe(false);
      expect(button.textContent).toBe("Refresh now");
      expect(reads).toBe(2);
      if (outcome === "resolve") {
        expect(screen.queryByTestId("ops-stale-warning")).toBeNull();
      } else {
        expect(screen.getByTestId("ops-stale-warning").textContent).toContain(
          outcome === "reject" ? "local read failed" : "timed out",
        );
      }
    },
  );
});
