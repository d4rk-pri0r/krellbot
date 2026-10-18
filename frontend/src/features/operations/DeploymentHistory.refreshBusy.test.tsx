import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(cleanup);

// Deferred client I/O keeps the real component's pending window deterministic.
function client(listDeploymentRecords: NonNullable<OperationsClient["listDeploymentRecords"]>): OperationsClient {
  return {
    getOperations: vi.fn(), promote: vi.fn(), pauseEntries: vi.fn(), resumeEntries: vi.fn(),
    engageKill: vi.fn(), releaseKill: vi.fn(), ackAlert: vi.fn(), listDeploymentRecords,
  };
}

const BUSY = "Refreshing history…";

describe("Deployment history toolbar refresh busy feedback", () => {
  it.each([false, true])("announces pending and settled refresh, including failure=%s", async (fail) => {
    let release!: (rows: DeploymentRecordRow[]) => void;
    let reject!: (error: Error) => void;
    const pending = new Promise<DeploymentRecordRow[]>((resolve, refuse) => {
      release = resolve;
      reject = refuse;
    });
    const list = vi.fn<() => Promise<DeploymentRecordRow[]>>()
      .mockResolvedValueOnce([]).mockReturnValueOnce(pending);
    render(<DeploymentHistory client={client(list)} />);
    await screen.findByTestId("ops-history-empty");
    const button = screen.getByTestId("ops-history-refresh") as HTMLButtonElement;
    expect(button.textContent).toBe("Refresh");
    expect(button.hasAttribute("aria-busy")).toBe(false);
    expect(screen.queryByTestId("ops-history-refresh-status")).toBeNull();
    button.focus();
    fireEvent.click(button);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.disabled).toBe(true);
    expect(button.textContent).toBe(BUSY);
    expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
    expect(document.activeElement).toBe(button);
    const status = screen.getByTestId("ops-history-refresh-status");
    expect(status.tagName).toBe("P");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.hasAttribute("role")).toBe(false);
    expect(status.textContent).toBe(BUSY);
    expect(status.parentElement).toBe(button.closest(".kbot-ops__history-toolbar"));
    fireEvent.click(button);
    fireEvent.keyDown(button, { key: "Enter", repeat: true });
    expect(list).toHaveBeenCalledTimes(2);
    await act(async () => { if (fail) reject(new Error("local refusal")); else release([]); });
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(button.hasAttribute("aria-busy")).toBe(false);
    expect(button.textContent).toBe("Refresh");
    expect(status.textContent).toBe("Refresh complete");
    expect(list).toHaveBeenCalledTimes(2);
    if (fail) expect(screen.getByTestId("ops-history-error").textContent).toContain("local refusal");
  });

  it("preserves the toolbar class and refresh onClick chain", () => {
    const source = readFileSync(resolve(__dirname, "DeploymentHistory.tsx"), "utf8");
    expect(source).toContain('<div className="kbot-ops__history-toolbar">');
    expect(source).toContain(`onClick={() => {
            setExpandedId(null);
            setDetail(null);
            setDetailError(null);
            void loadRows();
          }}`);
  });
});
