import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  ResearchDateWindow,
  msToUtcFieldValue,
  type ResearchDateWindowProps,
} from "./ResearchDateWindow";

afterEach(cleanup);

// 8.64e15 ms (+/-275760-09-13 / -271821-04-20) is the exact JS Date range.
// Beyond it a Date is invalid; values in (8.64e15, 9.007199254740991e15] are
// still safe integers, so the advanced-field guard lets them through and the
// UTC control used to render a NaN field value.
const DATE_RANGE_MAX_MS = 8_640_000_000_000_000;
const OUT_OF_RANGE_SAFE_MS = 8_700_000_000_000_000;
const OUT_OF_RANGE_BEYOND_SAFE_MS = 9_100_000_000_000_000;

function panelProps(): ResearchDateWindowProps {
  return {
    fromMsText: "",
    toMsText: "",
    holdoutFromMsText: "",
    holdoutToMsText: "",
    fromUtcText: "",
    toUtcText: "",
    holdoutFromUtcText: "",
    holdoutToUtcText: "",
    fromEditedUtcLast: false,
    toEditedUtcLast: false,
    holdoutFromEditedUtcLast: false,
    holdoutToEditedUtcLast: false,
    onFromUtcChange() {},
    onToUtcChange() {},
    onHoldoutFromUtcChange() {},
    onHoldoutToUtcChange() {},
  };
}

function utcInput(id: string): HTMLInputElement {
  const input = document.getElementById(id) as HTMLInputElement | null;
  if (input === null) {
    throw new Error(`missing UTC control #${id}`);
  }
  return input;
}

describe("ResearchDateWindow out-of-range advanced millisecond bounds", () => {
  it.each([
    { name: "positive out-of-range safe integer", msText: String(OUT_OF_RANGE_SAFE_MS) },
    { name: "negative out-of-range safe integer", msText: String(-OUT_OF_RANGE_SAFE_MS) },
    { name: "positive beyond the safe-integer range", msText: String(OUT_OF_RANGE_BEYOND_SAFE_MS) },
    { name: "negative beyond the safe-integer range", msText: String(-OUT_OF_RANGE_BEYOND_SAFE_MS) },
  ])(
    "renders an empty UTC field, never a NaN value, for a $name ms bound",
    ({ msText }) => {
      render(
        <ResearchDateWindow
          {...panelProps()}
          fromMsText={msText}
          toMsText={msText}
          holdoutFromMsText={msText}
          holdoutToMsText={msText}
        />,
      );
      for (const id of [
        "kbot-research-utc-from",
        "kbot-research-utc-to",
        "kbot-research-holdout-utc-start",
        "kbot-research-holdout-utc-end",
      ]) {
        const input = utcInput(id);
        expect(input.value).toBe("");
        expect(input.getAttribute("value")).toBe("");
        expect(input.getAttribute("aria-invalid")).toBe("false");
        expect(screen.queryByTestId(`${id}-invalid`)).toBeNull();
      }
      expect(screen.queryByTestId("research-date-window-ordering")).toBeNull();
    },
  );

  it("keeps the exact byte-equal canonical UTC value for healthy in-range ms bounds", () => {
    render(
      <ResearchDateWindow
        {...panelProps()}
        fromMsText="1700000000000"
        toMsText="0"
        holdoutFromMsText="1700000000000"
        holdoutToMsText="0"
      />,
    );
    const from = utcInput("kbot-research-utc-from");
    expect(from.value).toBe("2023-11-14T22:13:20");
    expect(from.getAttribute("value")).toBe("2023-11-14T22:13:20");
    const to = utcInput("kbot-research-utc-to");
    expect(to.value).toBe("1970-01-01T00:00");
    expect(to.getAttribute("value")).toBe("1970-01-01T00:00");
    const holdoutStart = utcInput("kbot-research-holdout-utc-start");
    expect(holdoutStart.value).toBe("2023-11-14T22:13:20");
    const holdoutEnd = utcInput("kbot-research-holdout-utc-end");
    expect(holdoutEnd.value).toBe("1970-01-01T00:00");
  });

  it("renders an empty UTC field for empty advanced ms text", () => {
    render(<ResearchDateWindow {...panelProps()} />);
    for (const id of [
      "kbot-research-utc-from",
      "kbot-research-utc-to",
      "kbot-research-holdout-utc-start",
      "kbot-research-holdout-utc-end",
    ]) {
      const input = utcInput(id);
      expect(input.value).toBe("");
      expect(input.getAttribute("value")).toBe("");
    }
  });

  it("keeps the ordering note exactly as before for inverted UTC edits", () => {
    render(
      <ResearchDateWindow
        {...panelProps()}
        fromUtcText="2026-01-02T00:00"
        toUtcText="2026-01-01T00:00"
        fromEditedUtcLast
        toEditedUtcLast
      />,
    );
    expect(screen.getByTestId("research-date-window-ordering").textContent).toBe(
      "From (UTC) is after To (UTC). Run is refused until the inclusive window is ordered.",
    );
  });
});

describe("msToUtcFieldValue for ms bounds outside the JS Date range", () => {
  it.each([
    OUT_OF_RANGE_BEYOND_SAFE_MS,
    -OUT_OF_RANGE_BEYOND_SAFE_MS,
    OUT_OF_RANGE_SAFE_MS,
    -OUT_OF_RANGE_SAFE_MS,
    DATE_RANGE_MAX_MS + 1,
    -DATE_RANGE_MAX_MS - 1,
  ])("returns the empty field value for %d ms (invalid Date)", (ms) => {
    expect(msToUtcFieldValue(ms)).toBe("");
  });

  it.each([
    [1_700_000_000_000, "2023-11-14T22:13:20"],
    [0, "1970-01-01T00:00"],
    [DATE_RANGE_MAX_MS, "275760-09-13T00:00"],
    [-DATE_RANGE_MAX_MS, "-271821-04-20T00:00"],
    [1_767_225_600_500, "2026-01-01T00:00:00.5"],
  ])("keeps the exact canonical UTC field value for %d ms", (ms, expected) => {
    expect(msToUtcFieldValue(ms)).toBe(expected);
  });
});
