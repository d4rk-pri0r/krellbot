import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient } from "./ResearchView";

afterEach(cleanup);

function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-abc" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-abc", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(new Blob(["{}"])),
    ...overrides,
  };
}

function fillAdvancedForm(fromMs: string, toMs: string): void {
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/synthetic.csv" },
  });
  fireEvent.change(screen.getByLabelText(/fee basis points/i), {
    target: { value: "40" },
  });
  fireEvent.change(screen.getByLabelText(/^from$/i), {
    target: { value: fromMs },
  });
  fireEvent.change(screen.getByLabelText(/^to$/i), {
    target: { value: toMs },
  });
}

function submitRunCall(client: ResearchClient): Record<string, unknown> {
  expect(client.submitRun).toHaveBeenCalledTimes(1);
  return (client.submitRun as ReturnType<typeof vi.fn>).mock.calls[0][0] as Record<
    string,
    unknown
  >;
}

const SAMPLE_FROM_MS = 1767225600000; // 2026-01-01T00:00:00Z
const SAMPLE_TO_MS = 1767311999999; // 2026-01-01T23:59:59.999Z

describe("ResearchDateWindow", () => {
  it("mounts a UTC date window (RED on old UI: only integer-timestamp inputs existed)", () => {
    // Observed source gap: the old mounted view exposed the scored window
    // From/To and holdout bounds only as integer millisecond text inputs, so
    // a user could not choose understandable dates without deriving epoch
    // ms by hand. This case fails until the date window is mounted.
    render(<ResearchView client={makeClient()} />);
    expect(screen.getByTestId("research-date-window")).toBeDefined();
  });

  it("renders UTC date/time controls for window and holdout, explicit UTC labelling and inclusive-window explanation", () => {
    render(<ResearchView client={makeClient()} />);
    const panel = screen.getByTestId("research-date-window");
    expect(panel.textContent).toMatch(/UTC/);
    expect(panel.textContent).toMatch(/inclusive/i);
    expect(screen.getByLabelText(/^from \(utc\)$/i)).toBeDefined();
    expect(screen.getByLabelText(/^to \(utc\)$/i)).toBeDefined();
    expect(screen.getByLabelText(/^holdout start \(utc\)$/i)).toBeDefined();
    expect(screen.getByLabelText(/^holdout end \(utc\)$/i)).toBeDefined();
  });

  it("typing a UTC date/time writes the exact derived milliseconds into the existing From field", () => {
    render(<ResearchView client={makeClient()} />);
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "2026-01-01T00:00" },
    });
    expect((screen.getByLabelText(/^from$/i) as HTMLInputElement).value).toBe(
      String(SAMPLE_FROM_MS),
    );
    fireEvent.change(screen.getByLabelText(/^to \(utc\)$/i), {
      target: { value: "2026-01-01T23:59:59.999" },
    });
    expect((screen.getByLabelText(/^to$/i) as HTMLInputElement).value).toBe(
      String(SAMPLE_TO_MS),
    );
  });

  it("editing the advanced From field round-trips into the UTC control (ms -> date -> ms is exact)", () => {
    render(<ResearchView client={makeClient()} />);
    fireEvent.change(screen.getByLabelText(/^from$/i), {
      target: { value: String(SAMPLE_FROM_MS) },
    });
    expect((screen.getByLabelText(/^from \(utc\)$/i) as HTMLInputElement).value).toBe(
      "2026-01-01T00:00",
    );
    fireEvent.change(screen.getByLabelText(/^to$/i), {
      target: { value: String(SAMPLE_TO_MS) },
    });
    expect((screen.getByLabelText(/^to \(utc\)$/i) as HTMLInputElement).value).toBe(
      "2026-01-01T23:59:59.999",
    );
    // Round trip back: clearing the UTC control re-syncs to the exact ms.
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "" },
    });
    expect((screen.getByLabelText(/^from$/i) as HTMLInputElement).value).toBe("");
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "2026-01-01T00:00" },
    });
    expect((screen.getByLabelText(/^from$/i) as HTMLInputElement).value).toBe(
      String(SAMPLE_FROM_MS),
    );
  });

  it("a sub-minute advanced timestamp is shown exactly, no silent shift, and submits unchanged", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    // 500ms into the minute: representable exactly in ms. The UTC control
    // shows the exact instant (canonical shortest fraction ".5" = 500ms) —
    // never rounds or silently shifts to a whole minute — and the exact ms
    // is submitted.
    const subMinute = SAMPLE_FROM_MS + 500;
    fillAdvancedForm(String(subMinute), String(SAMPLE_TO_MS));
    expect(
      (screen.getByLabelText(/^from \(utc\)$/i) as HTMLInputElement).value,
    ).toBe("2026-01-01T00:00:00.5");
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    const callArg = submitRunCall(client);
    expect(callArg.fromMs).toBe(subMinute);
    expect(callArg.toMs).toBe(SAMPLE_TO_MS);
  });

  it("both directions of controlled edits never drift: UTC -> ms -> UTC is identity", () => {
    render(<ResearchView client={makeClient()} />);
    const utcFrom = screen.getByLabelText(/^from \(utc\)$/i) as HTMLInputElement;
    const from = screen.getByLabelText(/^from$/i) as HTMLInputElement;
    const cases: Array<[string, number]> = [
      ["2026-03-08T12:34", Date.UTC(2026, 2, 8, 12, 34)],
      ["2026-11-01T00:00", Date.UTC(2026, 10, 1, 0, 0)],
      ["2024-02-29T23:59:59.999", Date.UTC(2024, 1, 29, 23, 59, 59, 999)],
    ];
    for (const [text, ms] of cases) {
      fireEvent.change(utcFrom, { target: { value: text } });
      expect(from.value).toBe(String(ms));
      expect(utcFrom.value).toBe(text);
    }
  });

  it("holdout UTC controls mirror into the existing holdout fields and submit without shifting", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillAdvancedForm(String(SAMPLE_FROM_MS), String(SAMPLE_TO_MS));
    fireEvent.change(screen.getByLabelText(/^holdout start \(utc\)$/i), {
      target: { value: "2026-01-01T08:00" },
    });
    fireEvent.change(screen.getByLabelText(/^holdout end \(utc\)$/i), {
      target: { value: "2026-01-01T16:00" },
    });
    expect(
      (screen.getByLabelText(/holdout from/i) as HTMLInputElement).value,
    ).toBe(String(Date.UTC(2026, 0, 1, 8, 0)));
    expect(
      (screen.getByLabelText(/holdout to/i) as HTMLInputElement).value,
    ).toBe(String(Date.UTC(2026, 0, 1, 16, 0)));
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = submitRunCall(client);
    expect(callArg.fromMs).toBe(SAMPLE_FROM_MS);
    expect(callArg.toMs).toBe(SAMPLE_TO_MS);
    expect(callArg.holdoutFromMs).toBe(Date.UTC(2026, 0, 1, 8, 0));
    expect(callArg.holdoutToMs).toBe(Date.UTC(2026, 0, 1, 16, 0));
  });

  it("Run with valid UTC dates submits exact millisecond fromMs/toMs through the existing client", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fireEvent.change(screen.getByLabelText(/dataset path/i), {
      target: { value: "fixtures/synthetic.csv" },
    });
    fireEvent.change(screen.getByLabelText(/fee basis points/i), {
      target: { value: "40" },
    });
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "2026-01-01T00:00" },
    });
    fireEvent.change(screen.getByLabelText(/^to \(utc\)$/i), {
      target: { value: "2026-01-01T23:59:59.999" },
    });
    expect((screen.getByLabelText(/^from$/i) as HTMLInputElement).value).toBe(
      String(SAMPLE_FROM_MS),
    );
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    const callArg = submitRunCall(client);
    expect(callArg.fromMs).toBe(SAMPLE_FROM_MS);
    expect(callArg.toMs).toBe(SAMPLE_TO_MS);
  });

  it("invalid ordering of UTC dates is refused with the existing inclusive-window error and preserves prior state", async () => {
    const client = makeClient({
      getResult: vi.fn().mockResolvedValue({
        legacy_receipt: { data_manifest_sha256: "aa" },
        trace: [],
      }),
    });
    render(<ResearchView client={client} />);
    fillAdvancedForm("0", "1000");
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    // The auto-poll loads the stored result for the first (valid) run.
    await screen.findByTestId("research-result");
    // Now pick a UTC window whose To is before its From.
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "2026-01-02T00:00" },
    });
    fireEvent.change(screen.getByLabelText(/^to \(utc\)$/i), {
      target: { value: "2026-01-01T00:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByText(
      "From must be less than or equal to To for the inclusive scored window",
    );
    expect(client.submitRun).toHaveBeenCalledTimes(1);
    // BUILD-RESEARCH-INPUTS-01: a refused setup keeps the loaded result.
    expect(screen.getByTestId("research-result")).toBeDefined();
  });

  it("an invented UTC date (Feb 30) never reaches the engine: From is cleared and Run is refused", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillAdvancedForm("0", "1000");
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "2026-02-30T00:00" },
    });
    // The datetime-local input sanitizes spec-invalid dates to an empty
    // value (HTML value sanitization algorithm), and the cleared advanced
    // field fails the existing integer validation — no fabricated instant
    // is silently rolled to another day or submitted.
    expect((screen.getByLabelText(/^from \(utc\)$/i) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(/^from$/i) as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByText("From must be an integer timestamp");
    expect(client.submitRun).not.toHaveBeenCalled();
  });

  it("clearing UTC from but not UTC to is refused with the existing pair error, no submit", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillAdvancedForm("0", "1000");
    fireEvent.change(screen.getByLabelText(/^holdout start \(utc\)$/i), {
      target: { value: "2026-01-01T08:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await screen.findByText("holdout bounds must both be set");
    expect(client.submitRun).not.toHaveBeenCalled();
  });
});

describe("ResearchDateWindow ordering feedback", () => {
  it("shows a nonblocking ordering hint when UTC from is after UTC to", () => {
    render(<ResearchView client={makeClient()} />);
    fireEvent.change(screen.getByLabelText(/^from \(utc\)$/i), {
      target: { value: "2026-01-02T00:00" },
    });
    fireEvent.change(screen.getByLabelText(/^to \(utc\)$/i), {
      target: { value: "2026-01-01T00:00" },
    });
    expect(screen.getByTestId("research-date-window-ordering")).toBeDefined();
  });
});
