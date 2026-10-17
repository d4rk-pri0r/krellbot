import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndicatorSpecJsonExport } from "./IndicatorSpecJsonExport";

const spec = { name: "ema 200/fast", len: 200 };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("IndicatorSpecJsonExport ARIA", () => {
  it("names the indicator and mounts an initially empty polite status", () => {
    const { rerender } = render(<IndicatorSpecJsonExport spec={spec} />);
    const button = screen.getByRole("button", {
      name: `Export spec JSON for indicator ${spec.name}`,
    });
    const status = screen.getByTestId("studio-indicator-spec-export-status");
    expect(button.getAttribute("data-testid")).toBe("studio-indicator-spec-export");
    expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
    expect(button.hasAttribute("aria-busy")).toBe(false);
    expect(button.hasAttribute("aria-describedby")).toBe(false);
    expect(button.textContent).toBe("Export spec JSON");
    expect(button.className).toBe("kbot-studio-node-inspector__export");
    expect(status.tagName).toBe("P");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.getAttribute("aria-atomic")).toBe("true");
    expect(status.textContent).toBe("");
    const id = status.id;
    expect(id).not.toBe("");
    rerender(<IndicatorSpecJsonExport spec={{ name: "rsi", len: 14 }} />);
    expect(status.id).toBe(id);
    expect(button.getAttribute("aria-label")).toBe(
      "Export spec JSON for indicator rsi",
    );
  });

  it("announces busy then completion after exactly one synchronous download per activation", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    // jsdom cannot create object URLs or navigate a download; keep the handler real.
    const createObjectURL = vi.fn(() => "blob:indicator-spec");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    render(<IndicatorSpecJsonExport spec={spec} timestamp="20261008T055500Z" />);
    const button = screen.getByTestId("studio-indicator-spec-export");
    const status = screen.getByTestId("studio-indicator-spec-export-status");
    button.focus();

    for (const count of [1, 2]) {
      fireEvent.click(button);
      expect(document.activeElement).toBe(button);
      expect(button.getAttribute("aria-busy")).toBe("true");
      expect(button.getAttribute("aria-describedby")).toBe(status.id);
      expect(document.getElementById(status.id)).toBe(status);
      expect(status.textContent).toBe(`Exporting spec ${spec.name}…`);
      expect(createObjectURL).toHaveBeenCalledTimes(count);
      expect(anchorClick).toHaveBeenCalledTimes(count);
      expect(revokeObjectURL).toHaveBeenCalledTimes(count);
      expect(revokeObjectURL).toHaveBeenLastCalledWith("blob:indicator-spec");
      expect(anchorClick.mock.invocationCallOrder[count - 1]).toBeLessThan(
        revokeObjectURL.mock.invocationCallOrder[count - 1],
      );

      await act(async () => {
        await Promise.resolve();
      });
      expect(button.hasAttribute("aria-busy")).toBe(false);
      expect(button.hasAttribute("aria-describedby")).toBe(false);
      expect(status.textContent).toBe(`Export complete for spec ${spec.name}`);
      act(() => {
        vi.runOnlyPendingTimers();
      });
      expect(status.textContent).toBe("");
      expect(anchorClick).toHaveBeenCalledTimes(count);
      expect(revokeObjectURL).toHaveBeenCalledTimes(count);
    }
  });

  it("uses distinct description ids for separate exports", () => {
    render(
      <>
        <IndicatorSpecJsonExport spec={spec} />
        <IndicatorSpecJsonExport spec={spec} />
      </>,
    );
    const statuses = screen.getAllByTestId("studio-indicator-spec-export-status");
    expect(statuses[0].id).not.toBe(statuses[1].id);
  });

  it("renders no button or status for null, including after a non-null spec", () => {
    const { container, rerender } = render(<IndicatorSpecJsonExport spec={null} />);
    expect(container.innerHTML).toBe("");
    rerender(<IndicatorSpecJsonExport spec={spec} />);
    expect(screen.getByTestId("studio-indicator-spec-export-status")).not.toBeNull();
    rerender(<IndicatorSpecJsonExport spec={null} />);
    expect(container.innerHTML).toBe("");
    expect(screen.queryByTestId("studio-indicator-spec-export")).toBeNull();
    expect(screen.queryByTestId("studio-indicator-spec-export-status")).toBeNull();
  });
});
