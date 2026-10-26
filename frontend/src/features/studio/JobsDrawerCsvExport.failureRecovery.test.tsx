import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobRow } from "../../shell/JobsDrawer";
import { JobsDrawerCsvExport } from "./JobsDrawerCsvExport";

/*
 * Failure-recovery regression coverage for the Jobs drawer CSV export.
 *
 * Fault injection below replaces URL.createObjectURL,
 * URL.revokeObjectURL, HTMLAnchorElement.prototype.click and
 * document.body.removeChild inside JSDOM. That is SYNTHETIC fault
 * injection, not real-browser evidence: it exercises the component's
 * containment and cleanup logic only, and passing here says nothing
 * about OS-level file persistence in a real browser.
 */

const escapingJobs: JobRow[] = [
  { id: "job-1", kind: "research.backtest", state: "succeeded" },
  {
    id: 'job,"2"',
    kind: "housekeeping,compact",
    state: "failed\nmid-run",
  },
];

let uncaught: string[];

function trackUncaught(): void {
  uncaught = [];
  window.addEventListener("error", onError);
}

const onError = (event: ErrorEvent): void => {
  uncaught.push(event.message);
  event.preventDefault();
};

/** Click that also records a synchronous escape as an uncaught error. */
function ordinaryClick(): void {
  try {
    fireEvent.click(screen.getByTestId("jobs-drawer-csv-export"));
  } catch (error) {
    uncaught.push(String(error));
  }
}

function failureStatusText(): string {
  return screen.getByRole("status").textContent ?? "";
}

function installUrlMocks(
  faults?: Partial<{
    createObjectURL: (input: Blob | MediaSource) => string;
    revokeObjectURL: (url: string) => void;
  }>,
): {
  createObjectURL: ReturnType<typeof vi.fn>;
  revokeObjectURL: ReturnType<typeof vi.fn>;
} {
  const createObjectURL = vi.fn(
    faults?.createObjectURL ??
      (() => "blob:jobs-csv"),
  );
  const revokeObjectURL = vi.fn(faults?.revokeObjectURL ?? (() => {}));
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}

afterEach(() => {
  window.removeEventListener("error", onError);
  document.querySelectorAll("a[download]").forEach((a) => a.remove());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  cleanup();
});

describe("JobsDrawerCsvExport failure recovery", () => {
  it("contains a URL allocation failure, reports a generic accessible status, and the next ordinary click succeeds without remount", () => {
    trackUncaught();
    const { createObjectURL, revokeObjectURL } = installUrlMocks({
      createObjectURL: () => {
        throw new Error("synthetic allocation denial");
      },
    });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    render(<JobsDrawerCsvExport jobs={escapingJobs} />);
    ordinaryClick();

    expect(uncaught).toEqual([]);
    expect(clickSpy).not.toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    const status = failureStatusText();
    expect(status).toMatch(/failed|unable|could not/i);
    expect(status).not.toMatch(/synthetic|allocation|denial/i);

    // Next ordinary click on the same mounted control recovers.
    createObjectURL.mockImplementation(() => "blob:jobs-csv");
    ordinaryClick();

    expect(uncaught).toEqual([]);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:jobs-csv");
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(failureStatusText()).not.toMatch(/failed|unable|could not/i);
  });

  it("cleans the attached anchor and object URL when anchor activation throws, then the next ordinary click succeeds without remount", () => {
    trackUncaught();
    const { revokeObjectURL } = installUrlMocks();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementationOnce(() => {
        throw new Error("synthetic click denial");
      })
      .mockImplementation(() => {});

    render(<JobsDrawerCsvExport jobs={escapingJobs} />);
    ordinaryClick();

    expect(uncaught).toEqual([]);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:jobs-csv");
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    const status = failureStatusText();
    expect(status).toMatch(/failed|unable|could not/i);
    expect(status).not.toMatch(/synthetic|click|denial/i);

    ordinaryClick();

    expect(uncaught).toEqual([]);
    expect(clickSpy).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(failureStatusText()).not.toMatch(/failed|unable|could not/i);
  });

  it("keeps the exact CSV bytes, MIME, filename and disabled/empty behaviour of the ordinary export", async () => {
    trackUncaught();
    const { createObjectURL } = installUrlMocks();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    const { unmount } = render(<JobsDrawerCsvExport jobs={escapingJobs} />);
    const button = screen.getByTestId(
      "jobs-drawer-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(button.textContent).toBe("Export CSV");
    ordinaryClick();

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("text/csv;charset=utf-8");
    expect(await blob.text()).toBe(
      'id,kind,state\njob-1,research.backtest,succeeded\n"job,""2""","housekeeping,compact","failed\nmid-run"',
    );
    const anchor = clickSpy.mock.instances[0] as HTMLAnchorElement;
    expect(anchor.download).toMatch(/^krellbot-jobs-\d{8}T\d{6}Z\.csv$/);
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    unmount();

    const { createObjectURL: emptyCreate } = installUrlMocks();
    render(<JobsDrawerCsvExport jobs={[]} />);
    const emptyButton = screen.getByTestId(
      "jobs-drawer-csv-export",
    ) as HTMLButtonElement;
    expect(emptyButton.disabled).toBe(true);
    fireEvent.click(emptyButton);
    expect(emptyCreate).not.toHaveBeenCalled();
    expect(uncaught).toEqual([]);
  });

  it("stays inert when disabled with jobs present and keeps any prior status from enabling a click", () => {
    trackUncaught();
    const { createObjectURL } = installUrlMocks();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<JobsDrawerCsvExport jobs={escapingJobs} disabled />);
    const button = screen.getByTestId(
      "jobs-drawer-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(uncaught).toEqual([]);
  });

  it("contains cleanup failures defensively: anchor removal throwing still revokes the URL, and a revoke throw never escapes", () => {
    trackUncaught();
    const { revokeObjectURL } = installUrlMocks();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementationOnce(() => {
        throw new Error("synthetic click denial");
      })
      .mockImplementation(() => {});
    const realRemoveChild = document.body.removeChild.bind(document.body);
    vi.spyOn(document.body, "removeChild")
      .mockImplementationOnce(() => {
        throw new Error("synthetic anchor detach denial");
      })
      .mockImplementation((child: Node) => realRemoveChild(child));

    render(<JobsDrawerCsvExport jobs={escapingJobs} />);
    ordinaryClick();

    expect(uncaught).toEqual([]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:jobs-csv");
    expect(failureStatusText()).toMatch(/failed|unable|could not/i);
    expect(failureStatusText()).not.toMatch(/detach|denial/i);

    // A revoke failure after a successful activation must not escape or
    // retain a failure status; browser initiation is not a persistence claim.
    revokeObjectURL.mockImplementation(() => {
      throw new Error("synthetic revoke denial");
    });
    ordinaryClick();

    expect(uncaught).toEqual([]);
    expect(clickSpy).toHaveBeenCalledTimes(2);
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(failureStatusText()).not.toMatch(/failed|unable|could not/i);
  });
});
