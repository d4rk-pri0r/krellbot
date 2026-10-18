import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { explainPack } from "./explainPack";
import { StrategyExplanationCsvExport } from "./StrategyExplanationCsvExport";

const empty = explainPack("{}", null);
const populated = explainPack('{"label":"LOCAL TEST ONLY explanation"}', "rev-local");
const button = () => screen.getByTestId("strategies-explanation-csv-export") as HTMLButtonElement;
const status = () => screen.getByTestId("strategies-explanation-csv-status");

// jsdom cannot perform downloads; capture only browser platform boundaries.
function capture() {
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  return vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:keyboard-test");
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("explanation CSV keyboard accessibility", () => {
  it("names the artifact and describes the unchanged filename and click-equivalent bytes", () => {
    render(<StrategyExplanationCsvExport result={populated} />);
    expect(screen.getByRole("button", { name: "Export explanation: strategy explanation CSV" })).toBe(button());
    const description = document.getElementById(button().getAttribute("aria-describedby") ?? "");
    expect(description?.textContent).toContain("strategy-explanation-YYYY-MM-DDTHH-MM-SS.csv");
    expect(description?.textContent).toContain("same CSV bytes as clicking");
    expect(button().getAttribute("aria-disabled")).toBe("false");
  });

  it.each(["Enter", " "])("%s delegates once, ignores repeats, retains focus and matches click bytes", async (key) => {
    const urls = capture();
    render(<StrategyExplanationCsvExport result={populated} />);
    button().focus();
    expect(fireEvent.keyDown(button(), { key })).toBe(false);
    fireEvent.keyDown(button(), { key, repeat: true });
    fireEvent.keyDown(button(), { key, repeat: true });
    fireEvent.keyUp(button(), { key });
    expect(urls).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(button());
    expect(status().textContent).toContain("Strategy explanation CSV download started");
    fireEvent.click(button());
    expect(urls).toHaveBeenCalledTimes(2);
    const keyboardBlob = urls.mock.calls[0][0] as Blob;
    const clickBlob = urls.mock.calls[1][0] as Blob;
    expect(await keyboardBlob.text()).toBe(await clickBlob.text());
    expect(keyboardBlob.type).toBe("text/csv;charset=utf-8");
    fireEvent.keyDown(button(), { key });
    expect(urls).toHaveBeenCalledTimes(3);
  });

  it("announces availability flips with no repeated mutations on static rerenders", () => {
    const urls = capture();
    const { rerender } = render(<StrategyExplanationCsvExport result={empty} />);
    expect(button().disabled).toBe(true);
    expect(button().getAttribute("aria-disabled")).toBe("true");
    expect(status().getAttribute("aria-live")).toBe("polite");
    expect(status().textContent).toBe("Export unavailable: no exportable rows in this explanation");
    fireEvent.keyDown(button(), { key: "Enter" });
    fireEvent.keyDown(button(), { key: " " });
    expect(urls).not.toHaveBeenCalled();
    const unavailable = status().firstChild;
    rerender(<StrategyExplanationCsvExport result={{ ...empty }} />);
    expect(status().firstChild).toBe(unavailable);
    rerender(<StrategyExplanationCsvExport result={populated} />);
    expect(status().textContent).toBe("Export now available");
    const available = status().firstChild;
    rerender(<StrategyExplanationCsvExport result={{ ...populated }} />);
    expect(status().firstChild).toBe(available);
    rerender(<StrategyExplanationCsvExport result={populated} disabled />);
    expect(status().textContent).toBe("Export unavailable: this explanation is disabled");
    expect(button().disabled).toBe(true);
    fireEvent.keyDown(button(), { key: "Enter" });
    expect(urls).not.toHaveBeenCalled();
  });

  it("ignores unrelated keys and does not claim success when the download throws", () => {
    const urls = capture();
    render(<StrategyExplanationCsvExport result={populated} />);
    fireEvent.keyDown(button(), { key: "Escape" });
    expect(urls).not.toHaveBeenCalled();
    const preventError = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", preventError);
    try {
      urls.mockImplementation(() => { throw new Error("download blocked"); });
      fireEvent.keyDown(button(), { key: "Enter" });
      expect(status().textContent).not.toContain("download started");
    } finally {
      window.removeEventListener("error", preventError);
    }
  });
});
