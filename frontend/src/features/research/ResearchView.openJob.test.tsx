import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ResearchView } from "./ResearchView";
import type { ResearchClient, StoredResult } from "./client";

afterEach(cleanup);
const result = (fee: number): StoredResult => ({ legacy_receipt: { fee_bps: fee }, trace: [] });
function client(): ResearchClient {
  return { submitRun: vi.fn(), cancelJob: vi.fn(), getJob: vi.fn(), getResultDownload: vi.fn(), getResult: vi.fn() };
}

it("opens stored evidence without submitting and ignores an older selection's late read", async () => {
  const api = client();
  let finishOld!: (value: StoredResult) => void;
  vi.mocked(api.getResult).mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; }))
    .mockResolvedValueOnce(result(17));
  const view = render(<ResearchView client={api} openedJob={{ id: "first" }} />);
  view.rerender(<ResearchView client={api} openedJob={{ id: "second" }} />);
  expect((await screen.findByTestId("research-result-fee-bps")).textContent).toBe("17");
  await act(async () => { finishOld(result(10)); });
  expect(screen.getByTestId("research-result-fee-bps").textContent).toBe("17");
  expect(screen.getByTestId("research-job-id").textContent).toContain("second");
  expect(api.submitRun).not.toHaveBeenCalled();
});

it("keeps the chosen job and exposes Load result after a failed stored read", async () => {
  const api = client();
  vi.mocked(api.getResult).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(result(10));
  render(<ResearchView client={api} openedJob={{ id: "saved" }} />);
  expect((await screen.findByTestId("research-job-error")).textContent).toContain("Load result");
  expect(screen.queryByTestId("research-result")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /^Load result$/ }));
  expect((await screen.findByTestId("research-result-fee-bps")).textContent).toBe("10");
  expect(api.getResult).toHaveBeenLastCalledWith("saved");
  expect(api.submitRun).not.toHaveBeenCalled();
});
