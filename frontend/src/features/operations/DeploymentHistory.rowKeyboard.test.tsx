import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(cleanup);

const record: DeploymentRecordRow = {
  deployment_id: "LOCAL-KEYBOARD-1", venue: "kraken", pair: "SUIUSD",
  created_at_ms: 1_700_000_000_000, state: "paper", config: { mode: "paper" },
  schedule: { timeframe: "1h" }, last_execution_summary: "Local keyboard fixture",
};

// Client fakes isolate event dispatch; the runtime verifier exercises the real API.
function mount(getDeploymentRecord = vi.fn().mockResolvedValue(record)) {
  const client: OperationsClient = {
    getOperations: vi.fn(), promote: vi.fn(), pauseEntries: vi.fn(), resumeEntries: vi.fn(),
    engageKill: vi.fn(), releaseKill: vi.fn(), ackAlert: vi.fn(),
    listDeploymentRecords: vi.fn().mockResolvedValue([record]), getDeploymentRecord,
  };
  render(<DeploymentHistory client={client} />);
  return getDeploymentRecord;
}

const rowId = "ops-history-row-LOCAL-KEYBOARD-1";
const detailId = "ops-history-detail-LOCAL-KEYBOARD-1";

describe("deployment history row keyboard disclosure", () => {
  it("keeps the table row, exposing a focusable button named by deployment and state", async () => {
    mount();
    const row = await screen.findByTestId(rowId);
    expect(row.tagName).toBe("TR");
    expect(row.closest("tbody")?.closest("table")?.dataset.testid).toBe("ops-history-table");
    expect(row.getAttribute("role")).toBe("button");
    expect(row.tabIndex).toBe(0);
    expect(screen.getByRole("button", { name: "Deployment LOCAL-KEYBOARD-1, paper" })).toBe(row);
    expect(row.getAttribute("aria-expanded")).toBe("false");
  });

  it.each(["Enter", " "])("%j mirrors click expansion and collapse without refetch, preserving focus", async (key) => {
    const getDetail = mount();
    const row = await screen.findByTestId(rowId);
    row.focus();
    expect(fireEvent.keyDown(row, { key })).toBe(false);
    await screen.findByTestId("ops-history-detail-config");
    expect(row.getAttribute("aria-expanded")).toBe("true");
    expect(getDetail).toHaveBeenCalledExactlyOnceWith(record.deployment_id);
    expect(screen.getByTestId(detailId).textContent).toContain("Local keyboard fixture");
    expect(fireEvent.keyDown(row, { key })).toBe(false);
    expect(screen.queryByTestId(detailId)).toBeNull();
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(row);
    expect(getDetail).toHaveBeenCalledTimes(1);
    fireEvent.click(row);
    await screen.findByTestId("ops-history-detail-config");
    expect(getDetail).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(row, { key });
    expect(screen.queryByTestId(detailId)).toBeNull();
  });

  it("ignores repeats, composition, arrows and unrelated keys", async () => {
    const getDetail = mount();
    const row = await screen.findByTestId(rowId);
    row.focus();
    for (const key of ["Enter", " "]) {
      expect(fireEvent.keyDown(row, { key, repeat: true })).toBe(true);
      expect(fireEvent.keyDown(row, { key, isComposing: true })).toBe(true);
    }
    for (const key of ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Escape", "a"]) {
      expect(fireEvent.keyDown(row, { key })).toBe(true);
    }
    expect(getDetail).not.toHaveBeenCalled();
    expect(screen.queryByTestId(detailId)).toBeNull();
    expect(document.activeElement).toBe(row);
  });

  it("uses the same pending and error panel on keyboard activation", async () => {
    let rejectDetail: (reason: Error) => void = () => {};
    mount(vi.fn().mockImplementation(() => new Promise<DeploymentRecordRow>((_, reject) => {
      rejectDetail = reject;
    })));
    const row = await screen.findByTestId(rowId);
    fireEvent.keyDown(row, { key: "Enter" });
    expect(await screen.findByTestId("ops-history-detail-loading")).toBeTruthy();
    rejectDetail(new Error("deployment history failed: 403 session required"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("403 session required"));
    fireEvent.keyDown(row, { key: " " });
    expect(screen.queryByTestId(detailId)).toBeNull();
  });
});
