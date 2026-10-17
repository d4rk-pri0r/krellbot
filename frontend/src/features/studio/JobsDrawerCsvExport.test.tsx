import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobRow } from "../../shell/JobsDrawer";
import { JobsDrawerCsvExport } from "./JobsDrawerCsvExport";

afterEach(() => {
  cleanup();
});

const twoJobs: JobRow[] = [
  { id: "job-1", kind: "research.backtest", state: "succeeded" },
  { id: "job-2", kind: "housekeeping.compact", state: "hibernating" },
];

describe("JobsDrawerCsvExport", () => {
  it("renders a disabled export button when there are no jobs", () => {
    render(<JobsDrawerCsvExport jobs={[]} />);
    const button = screen.getByTestId(
      "jobs-drawer-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("renders an enabled export button labelled Export CSV when jobs exist", () => {
    render(<JobsDrawerCsvExport jobs={twoJobs} />);
    const button = screen.getByTestId(
      "jobs-drawer-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(button.textContent).toBe("Export CSV");
  });

  it("downloads the csv body as a text/csv blob, clicking the anchor exactly once and revoking the URL", async () => {
    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(
      () => "blob:jobs-csv",
    );
    const revokeObjectURL = vi.fn();
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    try {
      render(<JobsDrawerCsvExport jobs={twoJobs} />);
      fireEvent.click(screen.getByTestId("jobs-drawer-csv-export"));

      expect(createObjectURL).toHaveBeenCalledTimes(1);
      const passedBlob = createObjectURL.mock.calls[0]?.[0] as Blob | undefined;
      expect(passedBlob).toBeDefined();
      expect(passedBlob).toBeInstanceOf(Blob);
      expect(passedBlob!.type).toBe("text/csv;charset=utf-8");
      const text = await passedBlob!.text();
      expect(text).toBe(
        "id,kind,state\njob-1,research.backtest,succeeded\njob-2,housekeeping.compact,hibernating",
      );
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:jobs-csv");
    } finally {
      clickSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });

  it("stays disabled and downloads nothing when disabled is set with jobs present", () => {
    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(
      () => "blob:jobs-csv",
    );
    const originalCreate = URL.createObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    try {
      render(<JobsDrawerCsvExport jobs={twoJobs} disabled />);
      fireEvent.click(screen.getByTestId("jobs-drawer-csv-export"));
      expect(createObjectURL).not.toHaveBeenCalled();
    } finally {
      URL.createObjectURL = originalCreate;
    }
  });
});
