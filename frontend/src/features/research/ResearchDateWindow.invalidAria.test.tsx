import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  ResearchDateWindow,
  type ResearchDateWindowProps,
  utcFieldValueToMs,
} from "./ResearchDateWindow";

afterEach(cleanup);

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

const fields = [
  { id: "kbot-research-utc-from", prefix: "from", label: "From (UTC)" },
  { id: "kbot-research-utc-to", prefix: "to", label: "To (UTC)" },
  { id: "kbot-research-holdout-utc-start", prefix: "holdoutFrom", label: "Holdout start (UTC)" },
  { id: "kbot-research-holdout-utc-end", prefix: "holdoutTo", label: "Holdout end (UTC)" },
] as const;
const invalidUtc = "2026-13-45T99:99";
const validUtc = "2026-01-01T00:00";

describe("ResearchDateWindow per-input invalid ARIA", () => {
  it.each(fields)("wires only the invalid hint for $id", ({ id, prefix, label }) => {
    expect(utcFieldValueToMs(invalidUtc)).toBeNull();
    // Controlled props reach the invalid branch without datetime-local sanitizing the text.
    const props = {
      ...panelProps(),
      [`${prefix}EditedUtcLast`]: true,
      [`${prefix}UtcText`]: invalidUtc,
      [`${prefix}MsText`]: "",
    };
    const { container } = render(<ResearchDateWindow {...props} />);
    expect(screen.getByTestId("research-date-window")).toBeDefined();
    const input = container.querySelector<HTMLInputElement>(`#${id}`)!;
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe(`${id}-problem`);
    expect(input.labels?.[0].htmlFor).toBe(id);
    expect(input.labels?.[0].textContent).toContain(label);
    const hint = screen.getByTestId(`${id}-invalid`);
    expect(hint.tagName).toBe("SPAN");
    expect(hint.id).toBe(`${id}-problem`);
    expect(container.querySelector(`#${id}-problem`)).toBe(hint);
    expect(hint.textContent?.trim()).toBe("Enter a valid UTC date/time");
    for (const other of fields.filter((field) => field.id !== id)) {
      const otherInput = container.querySelector(`#${other.id}`)!;
      expect(otherInput.getAttribute("aria-invalid")).toBe("false");
      expect(otherInput.hasAttribute("aria-describedby")).toBe(false);
      expect(screen.queryByTestId(`${other.id}-invalid`)).toBeNull();
    }
  });

  describe.each(fields)("$id", ({ id, prefix }) => {
    it.each(["corrected", "cleared", "advanced edit"])(
      "removes stale problem wiring after %s",
      (resolution) => {
        const props = {
          ...panelProps(),
          [`${prefix}EditedUtcLast`]: true,
          [`${prefix}UtcText`]: invalidUtc,
        };
        const { container, rerender } = render(<ResearchDateWindow {...props} />);
        const input = container.querySelector<HTMLInputElement>(`#${id}`)!;
        expect(input.getAttribute("aria-invalid")).toBe("true");
        expect(input.getAttribute("aria-describedby")).toBe(`${id}-problem`);
        rerender(
          <ResearchDateWindow
            {...props}
            {...{
              [`${prefix}EditedUtcLast`]: resolution !== "advanced edit",
              [`${prefix}UtcText`]: resolution === "cleared" ? "" : validUtc,
              [`${prefix}MsText`]: resolution === "cleared" ? "" : String(utcFieldValueToMs(validUtc)),
            }}
          />,
        );
        expect(container.querySelector(`#${id}`)).toBe(input);
        expect(input.getAttribute("aria-invalid")).toBe("false");
        expect(input.hasAttribute("aria-describedby")).toBe(false);
        expect(screen.queryByTestId(`${id}-invalid`)).toBeNull();
        expect(container.querySelector(`#${id}-problem`)).toBeNull();
      },
    );
  });
});
