import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";

afterEach(cleanup);

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-edit",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-validate",
      state: "draft",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const malformedBytes = '{"label": "broken", ';

const validMinimalPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

function rawJsonTextarea(): HTMLTextAreaElement {
  return screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
}

describe("Editor raw JSON invalid state is announced on the field", () => {
  it("a clean draft carries no aria-invalid and no aria-describedby on the raw JSON textarea", () => {
    render(<Editor client={makeClient()} />);
    const textarea = rawJsonTextarea();
    expect(textarea.hasAttribute("aria-invalid")).toBe(false);
    expect(textarea.hasAttribute("aria-describedby")).toBe(false);
    expect(screen.queryByTestId("editor-import-error")).toBeNull();
  });

  it("importing malformed JSON marks the textarea aria-invalid and wires it to the inline error", () => {
    render(<Editor client={makeClient()} />);
    fireEvent.change(rawJsonTextarea(), { target: { value: malformedBytes } });
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    const error = screen.getByTestId("editor-import-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toContain("Invalid JSON");

    const textarea = rawJsonTextarea();
    expect(textarea.getAttribute("aria-invalid")).toBe("true");
    expect(textarea.getAttribute("aria-describedby")).toBe("editor-import-error");
    // The describedby reference must name the real, present error element.
    expect(error.getAttribute("id")).toBe("editor-import-error");
    expect(document.getElementById("editor-import-error")).toBe(error);
  });

  it("a subsequent valid edit clears aria-invalid and removes the aria-describedby wiring", () => {
    render(<Editor client={makeClient()} />);
    fireEvent.change(rawJsonTextarea(), { target: { value: malformedBytes } });
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));
    expect(rawJsonTextarea().getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(rawJsonTextarea(), {
      target: { value: JSON.stringify(validMinimalPack, null, 2) },
    });

    const textarea = rawJsonTextarea();
    expect(textarea.hasAttribute("aria-invalid")).toBe(false);
    expect(textarea.hasAttribute("aria-describedby")).toBe(false);
    expect(screen.queryByTestId("editor-import-error")).toBeNull();
  });
});
