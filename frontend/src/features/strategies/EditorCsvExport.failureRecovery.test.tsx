import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DraftSummary, Pack } from "./client";
import { EditorCsvExport } from "./EditorCsvExport";

// Synthetic JSDOM fault-injection recovery regressions (A29). These are NOT
// real-browser or OS-persistence evidence: anchor.click() activation is only
// the handoff to the browser download machinery, and nothing here claims the
// file reached disk.

const validatedPack: Pack = {
  id: "trend-follow",
  label: "Alpha",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { stop: "2%" },
};

function makeSummary(overrides: Partial<DraftSummary> = {}): DraftSummary {
  return {
    revision_id: "rev-1",
    state: "validated",
    pack: validatedPack,
    errors: [],
    ...overrides,
  };
}

function installCapture() {
  const originalCreateElement = document.createElement.bind(document);
  const createObjectURL = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:recovery-test");
  const revokeObjectURL = vi
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => {});
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const createElement = vi.spyOn(document, "createElement");
  const anchors: HTMLAnchorElement[] = [];
  createElement.mockImplementation(((tag: string) => {
    const element = originalCreateElement(tag);
    if (tag === "a" && element instanceof HTMLAnchorElement) {
      anchors.push(element);
    }
    return element;
  }) as typeof document.createElement);
  return {
    anchors,
    blobs: () => createObjectURL.mock.calls.map((call) => call[0] as Blob),
    createObjectURL,
    revokeObjectURL,
    click,
    restore: () => {
      click.mockRestore();
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
      createElement.mockRestore();
    },
  };
}

describe("EditorCsvExport browser-failure recovery", () => {
  let windowErrors: string[];
  const captureWindowError = (event: ErrorEvent): void => {
    windowErrors.push(event.message);
    event.preventDefault();
  };

  beforeEach(() => {
    windowErrors = [];
    window.addEventListener("error", captureWindowError);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.querySelectorAll("a[download]").forEach((anchor) => anchor.remove());
    window.removeEventListener("error", captureWindowError);
  });

  it("normal click keeps exact bytes, MIME, filename, counts and cleanup", async () => {
    const summary = makeSummary({
      errors: [{ field: "entry", message: "bad" }],
    });
    render(<EditorCsvExport lastSummary={summary} currentPack={validatedPack} />);
    const capture = installCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const blobs = capture.blobs();
      expect(blobs.length).toBe(1);
      expect(blobs[0].type).toBe("text/csv");
      const csv = await blobs[0].text();
      expect(csv).toBe(
        "revision_id,state,error_count,label,parameter_count,kind_count\n" +
          "rev-1,validated,1,Alpha,2,3",
      );
      expect(csv).not.toContain("\r");
      expect(capture.anchors.length).toBe(1);
      expect(capture.anchors[0].download).toMatch(
        /^krellbot-revision-rev-1-\d{14}\.csv$/,
      );
      expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
      expect(document.querySelectorAll("a[download]")).toHaveLength(0);
      expect(windowErrors).toEqual([]);
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      capture.restore();
    }
  });

  it("contains a caller preparation failure, reports accessibly, and retries on the same mount", () => {
    const summary = makeSummary();
    let preparationDenials = 0;
    Object.defineProperty(summary, "state", {
      configurable: true,
      get() {
        preparationDenials += 1;
        if (preparationDenials === 1) {
          throw new Error("synthetic preparation denial");
        }
        return "validated";
      },
    });
    render(<EditorCsvExport lastSummary={summary} currentPack={validatedPack} />);
    const capture = installCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(windowErrors).toEqual([]);
      const status = screen.getByRole("status");
      expect(status.textContent ?? "").toMatch(/failed|unable|could not/i);
      expect(status.textContent ?? "").not.toContain("synthetic preparation denial");
      expect(capture.createObjectURL).not.toHaveBeenCalled();
      expect(capture.anchors).toHaveLength(0);

      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(capture.click).toHaveBeenCalledTimes(1);
      expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
      expect(screen.queryByRole("status")).toBeNull();
      expect(windowErrors).toEqual([]);
    } finally {
      capture.restore();
    }
  });

  it("contains a Blob construction failure before any allocation and retries on the same mount", async () => {
    const RealBlob = globalThis.Blob;
    let blobDenials = 0;
    class FlakyBlob {
      constructor(parts: BlobPart[], init?: BlobPropertyBag) {
        blobDenials += 1;
        if (blobDenials === 1) {
          throw new Error("synthetic blob denial");
        }
        return new RealBlob(parts, init);
      }
    }
    vi.stubGlobal("Blob", FlakyBlob);
    render(<EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />);
    const capture = installCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(windowErrors).toEqual([]);
      expect(screen.getByRole("status").textContent ?? "").toMatch(
        /failed|unable|could not/i,
      );
      expect(screen.getByRole("status").textContent ?? "").not.toContain(
        "synthetic blob denial",
      );
      expect(capture.createObjectURL).not.toHaveBeenCalled();
      expect(capture.anchors).toHaveLength(0);

      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(capture.blobs().length).toBe(1);
      expect((await capture.blobs()[0].text()).split("\n")[1]).toBe(
        "rev-1,validated,0,Alpha,2,3",
      );
      expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
      expect(screen.queryByRole("status")).toBeNull();
      expect(windowErrors).toEqual([]);
    } finally {
      capture.restore();
    }
  });

  it("contains an objectURL allocation failure and retries on the same mount", () => {
    render(<EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />);
    const capture = installCapture();
    try {
      capture.createObjectURL.mockImplementationOnce(() => {
        throw new Error("synthetic allocation denial");
      });
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(windowErrors).toEqual([]);
      const status = screen.getByRole("status");
      expect(status.textContent ?? "").toMatch(/failed|unable|could not/i);
      expect(status.textContent ?? "").not.toContain("synthetic allocation denial");
      expect(document.querySelectorAll("a[download]")).toHaveLength(0);
      expect(capture.revokeObjectURL).not.toHaveBeenCalled();

      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(capture.click).toHaveBeenCalledTimes(1);
      expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
      expect(screen.queryByRole("status")).toBeNull();
      expect(windowErrors).toEqual([]);
    } finally {
      capture.restore();
    }
  });

  it("contains an attachment failure, still revokes the allocated objectURL, and retries on the same mount", () => {
    render(<EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />);
    const capture = installCapture();
    const appendChild = vi
      .spyOn(document.body, "appendChild")
      .mockImplementationOnce(() => {
        throw new Error("synthetic attach denial");
      });
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(windowErrors).toEqual([]);
      expect(screen.getByRole("status").textContent ?? "").toMatch(
        /failed|unable|could not/i,
      );
      expect(document.querySelectorAll("a[download]")).toHaveLength(0);
      expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");

      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(capture.click).toHaveBeenCalledTimes(1);
      expect(document.querySelectorAll("a[download]")).toHaveLength(0);
      expect(screen.queryByRole("status")).toBeNull();
      expect(windowErrors).toEqual([]);
    } finally {
      appendChild.mockRestore();
      capture.restore();
    }
  });

  it("cleans the attached anchor and objectURL after an activation failure and retries on the same mount", () => {
    render(<EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />);
    const capture = installCapture();
    try {
      capture.click.mockImplementationOnce(() => {
        throw new Error("synthetic click denial");
      });
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(windowErrors).toEqual([]);
      const status = screen.getByRole("status");
      expect(status.textContent ?? "").toMatch(/failed|unable|could not/i);
      expect(status.textContent ?? "").not.toContain("synthetic click denial");
      expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
      expect(document.querySelectorAll("a[download]")).toHaveLength(0);

      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(capture.click).toHaveBeenCalledTimes(2);
      expect(capture.revokeObjectURL).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole("status")).toBeNull();
      expect(windowErrors).toEqual([]);
    } finally {
      capture.restore();
    }
  });

  it("shows one stable generic message across different failure causes without error detail", () => {
    const { rerender } = render(
      <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
    );
    const capture = installCapture();
    try {
      capture.createObjectURL.mockImplementationOnce(() => {
        throw new Error("synthetic allocation denial");
      });
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const allocationMessage = screen.getByRole("status").textContent ?? "";

      capture.click.mockImplementationOnce(() => {
        throw new Error("synthetic click denial");
      });
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const activationMessage = screen.getByRole("status").textContent ?? "";

      expect(activationMessage).toBe(allocationMessage);
      expect(activationMessage).not.toContain("synthetic allocation denial");
      expect(activationMessage).not.toContain("synthetic click denial");
      expect(windowErrors).toEqual([]);

      rerender(
        <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
      );
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      capture.restore();
    }
  });

  describe("independent cleanup", () => {
    it("still revokes the objectURL and keeps the delivery when anchor removal refuses", () => {
      render(
        <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
      );
      const capture = installCapture();
      const removeChild = vi
        .spyOn(document.body, "removeChild")
        .mockImplementation(() => {
          throw new Error("synthetic remove refusal");
        });
      try {
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(capture.click).toHaveBeenCalledTimes(1);
        expect(windowErrors).toEqual([]);
        expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
        expect(screen.queryByRole("status")).toBeNull();
      } finally {
        removeChild.mockRestore();
        capture.restore();
      }
    });

    it("still removes the anchor when objectURL revocation refuses", () => {
      render(
        <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
      );
      const capture = installCapture();
      capture.revokeObjectURL.mockImplementation(() => {
        throw new Error("synthetic revoke refusal");
      });
      try {
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(capture.click).toHaveBeenCalledTimes(1);
        expect(windowErrors).toEqual([]);
        expect(document.querySelectorAll("a[download]")).toHaveLength(0);
        expect(screen.queryByRole("status")).toBeNull();
      } finally {
        capture.restore();
      }
    });

    it("contains both cleanups refusing after a delivered activation without retracting it", () => {
      render(
        <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
      );
      const capture = installCapture();
      const removeChild = vi
        .spyOn(document.body, "removeChild")
        .mockImplementation(() => {
          throw new Error("synthetic remove refusal");
        });
      capture.revokeObjectURL.mockImplementation(() => {
        throw new Error("synthetic revoke refusal");
      });
      try {
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(capture.click).toHaveBeenCalledTimes(1);
        expect(windowErrors).toEqual([]);
        expect(screen.queryByRole("status")).toBeNull();
        expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");
      } finally {
        removeChild.mockRestore();
        capture.restore();
      }
    });

    it("still reports the preactivation failure when every cleanup refuses, then recovers on the same mount", () => {
      render(
        <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
      );
      const capture = installCapture();
      const removeChild = vi
        .spyOn(document.body, "removeChild")
        .mockImplementationOnce(() => {
          throw new Error("synthetic remove refusal");
        });
      capture.revokeObjectURL.mockImplementationOnce(() => {
        throw new Error("synthetic revoke refusal");
      });
      capture.click.mockImplementationOnce(() => {
        throw new Error("synthetic click denial");
      });
      try {
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(windowErrors).toEqual([]);
        expect(screen.getByRole("status").textContent ?? "").toMatch(
          /failed|unable|could not/i,
        );
        expect(capture.revokeObjectURL).toHaveBeenCalledWith("blob:recovery-test");

        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(capture.click).toHaveBeenCalledTimes(2);
        expect(document.querySelectorAll("a[download]")).toHaveLength(1);
        expect(screen.queryByRole("status")).toBeNull();
        expect(windowErrors).toEqual([]);
      } finally {
        removeChild.mockRestore();
        capture.restore();
      }
    });
  });

  describe("changed and null summary lifecycle on the same mount", () => {
    it("hides the failure context and disables the button once the summary is null", () => {
      const { rerender } = render(
        <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
      );
      const capture = installCapture();
      try {
        capture.createObjectURL.mockImplementationOnce(() => {
          throw new Error("synthetic allocation denial");
        });
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(screen.getByRole("status").textContent ?? "").toMatch(
          /failed|unable|could not/i,
        );

        rerender(<EditorCsvExport lastSummary={null} currentPack={null} />);
        const button = screen.getByTestId(
          "strategies-editor-csv-export",
        ) as HTMLButtonElement;
        expect(button.disabled).toBe(true);
        expect(screen.getByTestId("strategies-editor-csv-empty").textContent).toBe(
          "Save revision first.",
        );
        expect(screen.queryByRole("status")).toBeNull();

        fireEvent.click(button);
        expect(capture.createObjectURL).toHaveBeenCalledTimes(1);
        expect(capture.anchors).toHaveLength(0);
      } finally {
        capture.restore();
      }
    });

    it("exports the current revision on an ordinary retry after the summary changed", async () => {
      const first = makeSummary({ revision_id: "rev-1" });
      const { rerender } = render(
        <EditorCsvExport lastSummary={first} currentPack={validatedPack} />,
      );
      const capture = installCapture();
      try {
        capture.createObjectURL.mockImplementationOnce(() => {
          throw new Error("synthetic allocation denial");
        });
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(screen.getByRole("status").textContent ?? "").toMatch(
          /failed|unable|could not/i,
        );

        rerender(
          <EditorCsvExport
            lastSummary={makeSummary({ revision_id: "rev-2" })}
            currentPack={{ label: "Beta", period: 14 }}
          />,
        );
        fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
        expect(capture.click).toHaveBeenCalledTimes(1);
        expect(capture.anchors[0].download).toMatch(
          /^krellbot-revision-rev-2-\d{14}\.csv$/,
        );
        const blobs = capture.blobs();
        expect(blobs).toHaveLength(2);
        const lines = (await blobs[1].text()).split("\n");
        expect(lines[1]).toBe("rev-2,validated,0,Beta,1,0");
        expect(screen.queryByRole("status")).toBeNull();
        expect(windowErrors).toEqual([]);
      } finally {
        capture.restore();
      }
    });
  });
});
