import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

// issue149 regression (holdout bound safety). Every client, result and
// trace below is a SYNTHETIC JSDOM fixture: no real backend, browser or
// engine is involved. The scored-window/fee fixtures follow the existing
// ResearchView test conventions.
//
// Contract under test: leaving both optional holdout fields blank stays
// an optional omission, but whenever a holdout field is filled it must
// be a finite safe integer BEFORE the current result/selection is
// cleared or a request is submitted. Unsafe integer text (which plain
// Number() would round, e.g. 9007199254740993 -> 9007199254740992) and
// arbitrarily long digit text (which becomes Infinity) must be refused
// with a truthful field-naming holdout error, while the existing exact
// malformed-input and both-bounds-required messages, safe boundary
// values, zeros, ordinary millisecond/UTC echoes and the current
// job/result/selection/export all stay unchanged.

const MAX_SAFE = 9007199254740991;
const MIN_SAFE = -9007199254740991;
const UNSAFE_ABOVE_MAX = "9007199254740993";
const UNSAFE_BELOW_MIN = "-9007199254740993";
const TWO_POW_53 = "9007199254740992";
const NEGATIVE_TWO_POW_53 = "-9007199254740992";
const HUGE_DIGIT_STRING = `1${"0".repeat(400)}`;

afterEach(cleanup);

function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  const defaultResponse = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
  } as unknown as Response;
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-hb" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-hb", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(defaultResponse),
    ...overrides,
  };
}

const sampleStored: StoredResult = {
  legacy_receipt: { equity: 123.45, fee_bps: 40, trades: [{}], data_manifest_sha256: "deadbeef" },
  trace: [
    {
      bar_ts: 1000,
      input: { close: 1.5 },
      conditions: [{ path: ".all[0]", outcome: true }],
    },
    {
      bar_ts: 2000,
      input: { close: 1.65 },
      conditions: [{ path: ".any[0]", outcome: "unknown" }],
    },
  ],
};

function fillRequiredFields(): void {
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/synthetic.csv" },
  });
  fireEvent.change(screen.getByLabelText(/fee basis points/i), {
    target: { value: "40" },
  });
  fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "1000" } });
}

function setField(label: RegExp, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function run(): void {
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
}

function submitRunCalls(client: ResearchClient): Array<Record<string, unknown>> {
  return (client.submitRun as ReturnType<typeof vi.fn>).mock.calls.map(
    (call) => call[0] as Record<string, unknown>,
  );
}

async function expectHoldoutRefusal(
  client: ResearchClient,
  errorPattern: RegExp,
): Promise<void> {
  const alert = await screen.findByRole("alert");
  expect(alert.textContent ?? "").toMatch(errorPattern);
  expect(client.submitRun).not.toHaveBeenCalled();
  expect(screen.queryByTestId("research-job-id")).toBeNull();
}

describe("ResearchView holdout bounds (issue149: finite safe integer before submit)", () => {
  it("both blank stays an optional omission: no holdout keys in the request", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = submitRunCalls(client)[0];
    expect(callArg).not.toHaveProperty("holdoutFromMs");
    expect(callArg).not.toHaveProperty("holdoutToMs");
  });

  it("one blank holdout field still refuses with the existing both-bounds message", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "500");
    run();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("holdout bounds must both be set");
    expect(client.submitRun).not.toHaveBeenCalled();
  });

  it("malformed holdout input still refuses with the existing integer message", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "true");
    setField(/holdout to/i, "900");
    run();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("holdout bound must be an integer");
    expect(client.submitRun).not.toHaveBeenCalled();
  });

  it("fractional holdout input still refuses with the existing integer message, never rounds", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "500.5");
    setField(/holdout to/i, "900");
    run();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("holdout bound must be an integer");
    expect(client.submitRun).not.toHaveBeenCalled();
  });

  it("unsafe positive Holdout from is refused and never submitted rounded", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, UNSAFE_ABOVE_MAX);
    setField(/holdout to/i, "900");
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
    expect(client.submitRun).not.toHaveBeenCalled();
  });

  it("unsafe positive Holdout to is refused and never submitted rounded", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "500");
    setField(/holdout to/i, UNSAFE_ABOVE_MAX);
    run();
    await expectHoldoutRefusal(client, /holdout to must be a finite safe integer/i);
  });

  it("unsafe negative Holdout from is refused", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, UNSAFE_BELOW_MIN);
    setField(/holdout to/i, "900");
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
  });

  it("unsafe negative Holdout to is refused", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "500");
    setField(/holdout to/i, UNSAFE_BELOW_MIN);
    run();
    await expectHoldoutRefusal(client, /holdout to must be a finite safe integer/i);
  });

  it("both holdout bounds unsafe is refused with one holdout-naming error", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, UNSAFE_ABOVE_MAX);
    setField(/holdout to/i, UNSAFE_BELOW_MIN);
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
  });

  it("a huge digit string Holdout from is refused, never submitted as Infinity", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, HUGE_DIGIT_STRING);
    setField(/holdout to/i, "900");
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
    const calls = submitRunCalls(client);
    expect(calls.length).toBe(0);
  });

  it("a huge digit string Holdout to is refused, never submitted as Infinity", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "500");
    setField(/holdout to/i, HUGE_DIGIT_STRING);
    run();
    await expectHoldoutRefusal(client, /holdout to must be a finite safe integer/i);
    expect(submitRunCalls(client).length).toBe(0);
  });

  it("2^53 (first unsafe positive boundary) is refused", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "500");
    setField(/holdout to/i, TWO_POW_53);
    run();
    await expectHoldoutRefusal(client, /holdout to must be a finite safe integer/i);
  });

  it("-2^53 (first unsafe negative boundary) is refused", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, NEGATIVE_TWO_POW_53);
    setField(/holdout to/i, "900");
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
  });

  it("safe boundary values ±MAX_SAFE_INTEGER submit exactly, unclamped", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, String(MIN_SAFE));
    setField(/holdout to/i, String(MAX_SAFE));
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    expect(client.submitRun).toHaveBeenCalledWith({
      datasetPath: "fixtures/synthetic.csv",
      feeBps: 40,
      fromMs: 0,
      toMs: 1000,
      packPath: "",
      holdoutFromMs: MIN_SAFE,
      holdoutToMs: MAX_SAFE,
    });
  });

  it("zero holdout bounds submit exact zeros", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "0");
    setField(/holdout to/i, "0");
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = submitRunCalls(client)[0];
    expect(callArg.holdoutFromMs).toBe(0);
    expect(callArg.holdoutToMs).toBe(0);
  });

  it("ordinary negative holdout values are preserved exactly", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, "-5000");
    setField(/holdout to/i, "5000");
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = submitRunCalls(client)[0];
    expect(callArg.holdoutFromMs).toBe(-5000);
    expect(callArg.holdoutToMs).toBe(5000);
  });

  it("ordinary millisecond holdout text echoes as its exact UTC instant in the UTC controls", () => {
    render(<ResearchView client={makeClient()} />);
    setField(/holdout from/i, "1735689600000"); // 2025-01-01T00:00:00Z
    setField(/holdout to/i, "1735689600500"); // 2025-01-01T00:00:00.500Z
    expect(
      (screen.getByLabelText(/^holdout start \(utc\)$/i) as HTMLInputElement).value,
    ).toBe("2025-01-01T00:00");
    expect(
      (screen.getByLabelText(/^holdout end \(utc\)$/i) as HTMLInputElement).value,
    ).toBe("2025-01-01T00:00:00.5");
  });

  it("UTC datetime picks fill exact holdout milliseconds and submit exactly those values", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText(/^holdout start \(utc\)$/i), {
      target: { value: "2025-01-01T00:00" },
    });
    fireEvent.change(screen.getByLabelText(/^holdout end \(utc\)$/i), {
      target: { value: "2025-01-01T00:00:00.500" },
    });
    expect(
      (screen.getByLabelText(/holdout from/i) as HTMLInputElement).value,
    ).toBe("1735689600000");
    expect(
      (screen.getByLabelText(/holdout to/i) as HTMLInputElement).value,
    ).toBe("1735689600500");
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = submitRunCalls(client)[0];
    expect(callArg.holdoutFromMs).toBe(1735689600000);
    expect(callArg.holdoutToMs).toBe(1735689600500);
  });

  it("correction after an unsafe refusal submits normally with no stale refused-state lockout", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, UNSAFE_ABOVE_MAX);
    setField(/holdout to/i, HUGE_DIGIT_STRING);
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
    // Blank-to-filled / unsafe-to-safe correction: a later Run submits
    // normally and clears the refusal alert.
    setField(/holdout from/i, "200");
    setField(/holdout to/i, "800");
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    expect(client.submitRun).toHaveBeenCalledWith({
      datasetPath: "fixtures/synthetic.csv",
      feeBps: 40,
      fromMs: 0,
      toMs: 1000,
      packPath: "",
      holdoutFromMs: 200,
      holdoutToMs: 800,
    });
    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
    });
    expect(
      (await screen.findByTestId("research-job-id")).textContent,
    ).toMatch(/job-hb/);
  });

  it("clearing both holdout fields after a refusal submits as optional omission", async () => {
    const client = makeClient();
    render(<ResearchView client={client} />);
    fillRequiredFields();
    setField(/holdout from/i, UNSAFE_BELOW_MIN);
    setField(/holdout to/i, "900");
    run();
    await expectHoldoutRefusal(client, /holdout from must be a finite safe integer/i);
    setField(/holdout from/i, "");
    setField(/holdout to/i, "");
    run();
    await waitFor(() => {
      expect(client.submitRun).toHaveBeenCalledTimes(1);
    });
    const callArg = submitRunCalls(client)[0];
    expect(callArg).not.toHaveProperty("holdoutFromMs");
    expect(callArg).not.toHaveProperty("holdoutToMs");
    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
    });
  });

  it("an unsafe holdout retry after a real result preserves job, result, selection and export, then the correction submits", async () => {
    const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(
      () => "blob:research-result",
    );
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
    try {
      const client = makeClient({
        getResult: vi.fn().mockResolvedValue(sampleStored),
      });
      render(<ResearchView client={client} />);
      fillRequiredFields();
      run();
      await screen.findByTestId("research-job-id");
      fireEvent.click(screen.getByRole("button", { name: /load result/i }));
      await screen.findByTestId("research-result");
      fireEvent.click(screen.getByRole("button", { name: "1000" }));
      await screen.findByTestId("research-bar-detail");

      // Unsafe holdout retry after a real result: the alert names the
      // holdout field, no new submit happens, and the prior
      // job/result/selection and export all survive untouched.
      setField(/holdout from/i, UNSAFE_ABOVE_MAX);
      setField(/holdout to/i, "900");
      run();
      const alert = await screen.findByRole("alert");
      expect(alert.textContent ?? "").toMatch(/holdout from must be a finite safe integer/i);
      expect(client.submitRun).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("research-job-id").textContent).toMatch(/job-hb/);
      expect(screen.getByTestId("research-result")).toBeDefined();
      expect(screen.getByTestId("research-bar-detail")).toBeDefined();
      fireEvent.click(screen.getByRole("button", { name: /export result/i }));
      await waitFor(() => {
        expect(client.getResultDownload).toHaveBeenCalledWith("job-hb");
      });

      // Corrected holdout bounds submit exactly and the refusal clears.
      setField(/holdout from/i, "100");
      setField(/holdout to/i, "900");
      run();
      await waitFor(() => {
        expect(client.submitRun).toHaveBeenCalledTimes(2);
      });
      expect(client.submitRun).toHaveBeenLastCalledWith({
        datasetPath: "fixtures/synthetic.csv",
        feeBps: 40,
        fromMs: 0,
        toMs: 1000,
        packPath: "",
        holdoutFromMs: 100,
        holdoutToMs: 900,
      });
      await waitFor(() => {
        expect(screen.queryByRole("alert")).toBeNull();
      });
      await screen.findByTestId("research-result");
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });
});
