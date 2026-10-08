import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DraftSummary } from "./client";
import { Editor, type StrategyClient } from "./Editor";
import { EditorCsvExport } from "./EditorCsvExport";

afterEach(cleanup);

const validatedPack = {
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

function makeClient(): StrategyClient {
  return {
    create: vi.fn(),
    edit: vi.fn(),
    validate: vi.fn(),
    arm: vi.fn(),
  };
}

function installDownloadCapture() {
  const originalCreateElement = document.createElement.bind(document);
  const createObjectURL = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:test-url");
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
    restore: () => {
      click.mockRestore();
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
      createElement.mockRestore();
    },
  };
}

describe("EditorCsvExport rendering", () => {
  it("renders exactly one button with data-testid strategies-editor-csv-export", () => {
    render(
      <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
    );
    const matches = screen.getAllByTestId("strategies-editor-csv-export");
    expect(matches.length).toBe(1);
    expect(matches[0].getAttribute("data-testid")).toBe(
      "strategies-editor-csv-export",
    );
    expect(matches[0].textContent).toBe("Export CSV");
  });

  it("renders the button disabled with the empty-state message when lastSummary is null", () => {
    render(<EditorCsvExport lastSummary={null} currentPack={validatedPack} />);
    const button = screen.getByTestId(
      "strategies-editor-csv-export",
    ) as HTMLButtonElement;
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId("strategies-editor-csv-empty").textContent).toBe(
      "Save revision first.",
    );

    const capture = installDownloadCapture();
    try {
      fireEvent.click(button);
      expect(capture.blobs().length).toBe(0);
    } finally {
      capture.restore();
    }
  });

  it("hides the empty-state message once a revision summary exists", () => {
    render(
      <EditorCsvExport lastSummary={makeSummary()} currentPack={validatedPack} />,
    );
    expect(screen.queryByTestId("strategies-editor-csv-empty")).toBeNull();
  });
});

describe("EditorCsvExport CSV payload", () => {
  it("exports a 2-line CSV (header + 1 row) with the button enabled for a validated revision", async () => {
    const summary = makeSummary({
      revision_id: "rev-1",
      state: "validated",
      errors: [
        { field: "entry", message: "bad" },
        { message: "worse" },
      ],
    });
    render(<EditorCsvExport lastSummary={summary} currentPack={validatedPack} />);
    const button = screen.getByTestId(
      "strategies-editor-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    const capture = installDownloadCapture();
    try {
      fireEvent.click(button);
      const blobs = capture.blobs();
      expect(blobs.length).toBe(1);
      const csv = await blobs[0].text();
      const lines = csv.split("\n");
      expect(lines.length).toBe(2);
      expect(lines[0]).toBe(
        "revision_id,state,error_count,label,parameter_count,kind_count",
      );
      expect(lines[1]).toBe("rev-1,validated,2,Alpha,2,3");
      expect(csv).not.toContain("\r");
    } finally {
      capture.restore();
    }
  });

  it("wraps a label containing a comma in double quotes", async () => {
    const pack = { ...validatedPack, label: "hello, world" };
    render(
      <EditorCsvExport lastSummary={makeSummary({ pack })} currentPack={pack} />,
    );
    const capture = installDownloadCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const lines = (await capture.blobs()[0].text()).split("\n");
      expect(lines.length).toBe(2);
      expect(lines[1]).toBe('rev-1,validated,0,"hello, world",2,3');
    } finally {
      capture.restore();
    }
  });

  it("doubles internal double quotes inside a quoted field", async () => {
    const pack = { ...validatedPack, label: 'say "hi"' };
    render(
      <EditorCsvExport lastSummary={makeSummary({ pack })} currentPack={pack} />,
    );
    const capture = installDownloadCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const lines = (await capture.blobs()[0].text()).split("\n");
      expect(lines[1]).toBe('rev-1,validated,0,"say ""hi""",2,3');
    } finally {
      capture.restore();
    }
  });

  it("falls back to an empty label and zero counts when currentPack is null", async () => {
    render(
      <EditorCsvExport lastSummary={makeSummary({ pack: {} })} currentPack={null} />,
    );
    const capture = installDownloadCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const lines = (await capture.blobs()[0].text()).split("\n");
      expect(lines[1]).toBe("rev-1,validated,0,,0,0");
    } finally {
      capture.restore();
    }
  });
});

describe("EditorCsvExport filename", () => {
  it("uses the revisionId when present", () => {
    render(
      <EditorCsvExport
        lastSummary={makeSummary({ revision_id: "rev-9" })}
        currentPack={validatedPack}
      />,
    );
    const capture = installDownloadCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const downloads = capture.anchors
        .map((anchor) => anchor.download)
        .filter((name) => name.startsWith("krellbot-revision-"));
      expect(downloads.length).toBe(1);
      expect(downloads[0]).toMatch(/^krellbot-revision-rev-9-\d{14}\.csv$/);
    } finally {
      capture.restore();
    }
  });

  it("falls back to 'unknown' when revisionId is missing", () => {
    render(
      <EditorCsvExport
        lastSummary={makeSummary({ revision_id: "" })}
        currentPack={validatedPack}
      />,
    );
    const capture = installDownloadCapture();
    try {
      fireEvent.click(screen.getByTestId("strategies-editor-csv-export"));
      const downloads = capture.anchors
        .map((anchor) => anchor.download)
        .filter((name) => name.startsWith("krellbot-revision-"));
      expect(downloads.length).toBe(1);
      expect(downloads[0]).toMatch(/^krellbot-revision-unknown-\d{14}\.csv$/);
    } finally {
      capture.restore();
    }
  });
});

describe("EditorCsvExport mounted in the Editor actions row", () => {
  it("is enabled next to the Export pack button once a revision is loaded", () => {
    render(
      <Editor
        client={makeClient()}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validatedPack, null, 2),
        }}
      />,
    );
    expect(
      screen.getByRole("button", { name: /^export pack$/i }),
    ).toBeDefined();
    const button = screen.getByTestId(
      "strategies-editor-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(screen.queryByTestId("strategies-editor-csv-empty")).toBeNull();
  });

  it("is disabled with the empty-state message before any revision is saved", () => {
    render(<Editor client={makeClient()} />);
    const button = screen.getByTestId(
      "strategies-editor-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId("strategies-editor-csv-empty").textContent).toBe(
      "Save revision first.",
    );
  });
});
