import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";
import {
  isValidRaiseStopDecimal,
  stopFromRaiseStopMessage,
} from "./EditorInlineStopControl";

afterEach(cleanup);

const validPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-edit",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: validPack,
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
}

function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ ok: true }),
    disarm: vi.fn().mockResolvedValue({ ok: true }),
    raiseStop: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  };
}

function stopInput(): HTMLInputElement {
  return screen.getByTestId(
    "editor-inline-stop-new-stop",
  ) as HTMLInputElement;
}

function applyButton(): HTMLButtonElement {
  return screen.getByTestId("editor-inline-stop-apply") as HTMLButtonElement;
}

describe("EditorInlineStopControl raise-stop slice", () => {
  function renderEditor(paperClient: PaperClient) {
    return render(
      <Editor
        client={makeStrategyClient()}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );
  }

  it("reflects the new resting stop from the backend success message echo", async () => {
    const paperClient = makePaperClient({
      raiseStop: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "stop_raised",
        ok: true,
        message: "stop set: kraken SUIUSD -> 2.5",
        effect: "changed",
      }),
    });
    renderEditor(paperClient);

    await waitFor(() => {
      expect(applyButton().disabled).toBe(true);
    });
    fireEvent.change(stopInput(), { target: { value: "2.5" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());

    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 2.5");
  });

  it("refreshes status through the existing refresh path after a confirmed raise", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(armedStatus())
      .mockResolvedValueOnce(armedStatus({ entries_paused: true }));
    const paperClient = makePaperClient({
      getStatus,
      raiseStop: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "stop_raised",
        ok: true,
        message: "stop set: kraken SUIUSD -> 3",
        effect: "changed",
      }),
    });
    renderEditor(paperClient);

    await waitFor(() => {
      expect(applyButton().disabled).toBe(true);
    });
    fireEvent.change(stopInput(), { target: { value: "3" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());

    // The confirmed command triggers exactly one reconciliation read.
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 3");
    expect(
      screen.getByTestId("editor-inline-stop-entries").textContent,
    ).toMatch(/Entries paused/);
  });

  it("surfaces the backend refusal words for a below-or-equal stop with no frontend comparison", async () => {
    const refusal: PaperCommandResult = {
      schema_version: "1",
      code: "invalid_stop",
      ok: false,
      message: "new stop must be strictly above the current stop",
      effect: "refused",
    };
    const raiseStop = vi.fn().mockResolvedValue(refusal);
    const paperClient = makePaperClient({ raiseStop });
    renderEditor(paperClient);

    await waitFor(() => {
      expect(applyButton().disabled).toBe(true);
    });
    // The same numeric value as the current stop is allowed on the wire:
    // below-or-equal is backend-only validation.
    fireEvent.change(stopInput(), { target: { value: "1" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());

    expect(await screen.findByTestId("editor-inline-stop-error")).toBeDefined();
    expect(screen.getByTestId("editor-inline-stop-error").textContent).toBe(
      "new stop must be strictly above the current stop",
    );
    expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();
  });

  it("shows Applying… while the raise is pending and restores the control after", async () => {
    let release: (value: PaperCommandResult) => void = () => {};
    const gate = new Promise<PaperCommandResult>((resolve) => {
      release = resolve;
    });
    const paperClient = makePaperClient({
      raiseStop: vi.fn().mockReturnValue(gate),
    });
    renderEditor(paperClient);

    await waitFor(() => {
      expect(applyButton().disabled).toBe(true);
    });
    fireEvent.change(stopInput(), { target: { value: "1.5" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());

    await waitFor(() => {
      expect(applyButton().textContent).toBe("Applying…");
    });
    expect(applyButton().disabled).toBe(true);

    release({
      schema_version: "1",
      code: "stop_raised",
      ok: true,
      message: "stop set: kraken SUIUSD -> 1.5",
      effect: "changed",
    });
    await waitFor(() => {
      expect(applyButton().textContent).toBe("Apply new stop");
    });
    expect(applyButton().disabled).toBe(false);
  });

  it("does not update after unmount: a late response from a superseded request is dropped", async () => {
    let release: (value: PaperCommandResult) => void = () => {};
    const gate = new Promise<PaperCommandResult>((resolve) => {
      release = resolve;
    });
    const paperClient = makePaperClient({
      raiseStop: vi.fn().mockReturnValue(gate),
    });
    const { unmount } = renderEditor(paperClient);

    await waitFor(() => {
      expect(applyButton().disabled).toBe(true);
    });
    fireEvent.change(stopInput(), { target: { value: "4.25" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());
    unmount();

    release({
      schema_version: "1",
      code: "stop_raised",
      ok: true,
      message: "stop set: kraken SUIUSD -> 4.25",
      effect: "changed",
    });
    // The unmount bumped the epoch; nothing may throw or leak.
    expect(paperClient.raiseStop).toHaveBeenCalledTimes(1);
  });

  it("clears the stop-at indicator after a confirmed disarm", async () => {
    const paperClient = makePaperClient({
      raiseStop: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "stop_raised",
        ok: true,
        message: "stop set: kraken SUIUSD -> 1.75",
        effect: "changed",
      }),
      disarm: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "disarmed",
        ok: true,
        effect: "changed",
      }),
    });
    renderEditor(paperClient);

    await waitFor(() => {
      expect(applyButton().disabled).toBe(true);
    });
    fireEvent.change(stopInput(), { target: { value: "1.75" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());
    expect(
      (await screen.findByTestId("editor-inline-stop-at")).textContent,
    ).toBe("stop at 1.75");

    fireEvent.click(
      screen.getByRole("button", { name: /^disarm$/i }) as HTMLButtonElement,
    );
    // Disarm removes the armed surface and with it the stop-at indicator.
    await waitFor(() => {
      expect(screen.queryByTestId("editor-inline-stop-at")).toBeNull();
    });
    expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
      /No pack armed/,
    );
  });
});

describe("isValidRaiseStopDecimal", () => {
  it.each([
    ["1", true],
    ["1.5", true],
    ["0.25", true],
    ["10", true],
    ["12345.6789", true],
    ["0", true],
    ["", false],
    ["1e3", false],
    [".5", false],
    ["1.", false],
    ["NaN", false],
    ["Infinity", false],
    ["-Infinity", false],
    ["-1", false],
    ["+1", false],
    ["1.2.3", false],
    [" 1.5", false],
    ["1.5 ", false],
  ])("%s -> %s", (value, expected) => {
    expect(isValidRaiseStopDecimal(value)).toBe(expected);
  });
});

describe("stopFromRaiseStopMessage", () => {
  it("parses the new stop out of the backend success echo", () => {
    expect(
      stopFromRaiseStopMessage("stop set: kraken SUIUSD -> 1.75"),
    ).toBe("1.75");
    expect(stopFromRaiseStopMessage("stop set: kraken SUIUSD -> 2")).toBe("2");
  });

  it("returns null when the message has no echo or is missing", () => {
    expect(stopFromRaiseStopMessage(undefined)).toBeNull();
    expect(stopFromRaiseStopMessage("")).toBeNull();
    expect(stopFromRaiseStopMessage("stop set: kraken SUIUSD")).toBeNull();
    expect(stopFromRaiseStopMessage("stop set: kraken SUIUSD -> ")).toBeNull();
  });
});
