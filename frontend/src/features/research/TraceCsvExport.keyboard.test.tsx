import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";
import { TraceCsvExport } from "./TraceCsvExport";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// jsdom cannot download blob URLs; only the browser download boundary is stubbed.
function stubDownload() {
  const create = vi.fn(() => "blob:trace-csv");
  const revoke = vi.fn();
  class DownloadURL extends URL {
    static createObjectURL = create;
    static revokeObjectURL = revoke;
  }
  vi.stubGlobal("URL", DownloadURL);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  return { create, revoke, click };
}

function exportButton(): HTMLButtonElement {
  return screen.getByTestId("research-trace-csv-export") as HTMLButtonElement;
}

function expectEnabledLabel(button: HTMLButtonElement, label: string): void {
  expect(button.disabled).toBe(false);
  expect(screen.getByRole("button", { name: label })).toBe(button);
  expect(button.getAttribute("aria-label")).toBe(label);
  expect(button.getAttribute("aria-keyshortcuts")).toBe("Control+E Meta+E");
  expect(button.textContent).toBe("Export CSV");
}

function expectEmpty(button: HTMLButtonElement): void {
  expect(button.disabled).toBe(true);
  expect(button.getAttribute("aria-label")).toBe("Export trace CSV (no trace rows to export)");
  expect(button.getAttribute("aria-keyshortcuts")).toBe("Control+E Meta+E");
  const empty = screen.getByTestId("research-trace-csv-empty");
  expect(empty.getAttribute("role")).toBe("status");
  expect(empty.getAttribute("aria-live")).toBe("polite");
  expect(empty.getAttribute("aria-atomic")).toBe("true");
  expect(empty.textContent).toBe("No trace rows to export.");
}

describe("Trace CSV assistive-technology hooks", () => {
  it("names the loaded run and announces the empty flip on the same button", () => {
    const { rerender } = render(<TraceCsvExport trace={[{ a: 1 }]} jobId="job-abc" />);
    const button = exportButton();
    expectEnabledLabel(button, "Export trace CSV for run job-abc");
    expect(screen.queryByTestId("research-trace-csv-empty")).toBeNull();
    rerender(<TraceCsvExport trace={[]} jobId="job-abc" />);
    expect(exportButton()).toBe(button);
    expectEmpty(button);
    rerender(<TraceCsvExport trace={[{ a: 1 }]} jobId="job-next" />);
    expectEnabledLabel(button, "Export trace CSV for run job-next");
    expect(screen.queryByTestId("research-trace-csv-empty")).toBeNull();
  });

  it("uses the generic label only when enabled without a run id", () => {
    const { rerender } = render(<TraceCsvExport trace={[{ a: 1 }]} jobId={null} />);
    expectEnabledLabel(exportButton(), "Export trace CSV");
    rerender(<TraceCsvExport trace={[]} jobId={null} />);
    expectEmpty(exportButton());
  });

  it("includes a non-null empty run id in the enabled label", () => {
    render(<TraceCsvExport trace={[{ a: 1 }]} jobId="" />);
    expect(exportButton().getAttribute("aria-label")).toBe("Export trace CSV for run ");
  });

  it("clears busy on the next timer tick and can export again", () => {
    vi.useFakeTimers();
    const download = stubDownload();
    render(<TraceCsvExport trace={[{ a: 1 }]} jobId="job-abc" />);
    const button = exportButton();
    button.focus();
    expect(button.getAttribute("aria-busy")).toBe("false");
    for (let count = 1; count <= 2; count += 1) {
      fireEvent.click(button);
      expect(button.getAttribute("aria-busy")).toBe("true");
      expect(download.create).toHaveBeenCalledTimes(count);
      expect(download.click).toHaveBeenCalledTimes(count);
      expect(download.revoke).toHaveBeenLastCalledWith("blob:trace-csv");
      act(() => { vi.runOnlyPendingTimers(); });
      expect(button.getAttribute("aria-busy")).toBe("false");
      expect(document.activeElement).toBe(button);
    }
  });

  it("does not mark a disabled export busy or start a download", () => {
    const download = stubDownload();
    render(<TraceCsvExport trace={[]} jobId="job-abc" />);
    fireEvent.click(exportButton());
    expect(exportButton().getAttribute("aria-busy")).toBe("false");
    expect(download.create).not.toHaveBeenCalled();
    expect(download.click).not.toHaveBeenCalled();
  });

  it("exposes the hooks through the real ResearchView consumer and result refresh", async () => {
    let result: StoredResult = { legacy_receipt: { equity: 0 }, trace: [{ a: 1 }] };
    const client: ResearchClient = {
      submitRun: async () => ({ id: "job-abc", state: "succeeded" }),
      cancelJob: async () => {},
      getResult: async () => result,
      getJob: async () => ({ id: "job-abc", state: "succeeded" }),
      getResultDownload: async () => new Response("{}"),
    };
    render(<ResearchView client={client} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByTestId("research-trace-scroll");
    const button = exportButton();
    expect(screen.getByRole("region", { name: "Research" }).contains(button)).toBe(true);
    expectEnabledLabel(button, "Export trace CSV for run job-abc");
    result = { ...result, trace: [] };
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /load result/i }));
    });
    expect(exportButton()).toBe(button);
    expectEmpty(button);
  });
});
