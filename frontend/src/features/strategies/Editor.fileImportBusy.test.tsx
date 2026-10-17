import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "./Editor";
import { createHttpClient } from "./client";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const bytes = JSON.stringify(seedOwnedStrategyPack("Local import"), null, 2);

function openPicker(): HTMLInputElement {
  render(<Editor client={createHttpClient()} />);
  const details = screen.getByTestId("editor-technical-section") as HTMLDetailsElement;
  expect(details.open).toBe(false);
  fireEvent.click(details.querySelector("summary")!);
  expect(details.open).toBe(true);
  const input = screen.getByLabelText("Import pack file") as HTMLInputElement;
  input.focus();
  expect(document.activeElement).toBe(input);
  return input;
}

function pick(input: HTMLInputElement, name = "local-pack.json", text = bytes): void {
  fireEvent.change(input, { target: { files: [new File([text], name, { type: "application/json" })] } });
}

async function settled(input: HTMLInputElement): Promise<void> {
  await waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
}

function status(): HTMLElement {
  return screen.getByTestId("editor-file-import-busy-status");
}

describe("Editor file import busy accessibility", () => {
  it("aria_busy_on_input_while_in_flight", async () => {
    const input = openPicker();
    expect(input.hasAttribute("aria-busy")).toBe(false);
    pick(input);
    expect(input.getAttribute("aria-busy")).toBe("true");
    expect(document.activeElement).toBe(input);
    await settled(input);
  });

  it("aria_label_import_pack_file", () => {
    const input = openPicker();
    expect(input.getAttribute("aria-label")).toBe("Import pack file");
    expect(input.id).toBe("kbot-strategy-editor-file");
    expect(input.type).toBe("file");
    expect(input.accept).toBe("application/json,.json");
    expect(input.hasAttribute("aria-describedby")).toBe(false);
    expect(input.disabled).toBe(false);
    expect(screen.queryByTestId("editor-file-import-busy-status")).toBeNull();
  });

  it("polite_live_sibling_during_in_flight", async () => {
    const input = openPicker();
    pick(input);
    const message = status();
    expect(message.tagName).toBe("P");
    expect(message.id).toBe("editor-file-import-busy-status");
    expect(message.getAttribute("role")).toBe("status");
    expect(message.getAttribute("aria-live")).toBe("polite");
    expect(message.getAttribute("aria-atomic")).toBe("true");
    expect(message.textContent).toBe("Reading pack file local-pack.json");
    expect(message.previousElementSibling).toBe(input.closest("label"));
    expect(message.closest("label")).toBeNull();
    expect(message.closest(".kbot-strategy-editor__actions")).toBeNull();
    expect(screen.getByTestId("editor-technical-section").getAttribute("aria-labelledby"))
      .toBe("kbot-strategy-editor-technical-title");
    await settled(input);
  });

  it("polite_live_announces_success_on_settle", async () => {
    const input = openPicker();
    pick(input);
    await settled(input);
    expect(status().textContent).toBe("Loaded pack from local-pack.json");
    expect(status().getAttribute("aria-live")).toBe("polite");
    expect((screen.getByLabelText("Raw JSON") as HTMLTextAreaElement).value).toBe(bytes);
    expect(screen.queryByTestId("editor-import-error")).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it("polite_live_announces_failure_on_settle", async () => {
    const input = openPicker();
    for (const invalid of ["{broken", "[]", "null"]) {
      pick(input, "invalid.json", invalid);
      expect(status().textContent).toBe("Reading pack file invalid.json");
      await settled(input);
      expect(status().textContent).toBe("Invalid JSON in invalid.json");
      expect(status().getAttribute("aria-live")).toBe("polite");
      expect((screen.getByLabelText("Raw JSON") as HTMLTextAreaElement).value).toBe("");
    }
  });

  it("existing_role_alert_on_parse_failure", async () => {
    const input = openPicker();
    pick(input, "invalid.json", "{broken");
    const error = await screen.findByTestId("editor-import-error");
    expect(error.id).toBe("editor-import-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe("Invalid JSON");
    expect(screen.getByLabelText("Raw JSON").getAttribute("aria-describedby")).toBe(error.id);
    expect(screen.getByTestId("editor-save-status").textContent).toBe("Invalid JSON; save blocked");
    await settled(input);
  });

  it("aria_busy_removed_on_settle", async () => {
    const input = openPicker();
    for (const text of [bytes, "{broken"]) {
      pick(input, "pack.json", text);
      expect(input.getAttribute("aria-busy")).toBe("true");
      await settled(input);
      expect(input.getAttribute("aria-busy")).toBeNull();
      expect(document.activeElement).toBe(input);
    }
  });

  it("second_file_pick_short_circuited", async () => {
    const input = openPicker();
    // Observe native reads without replacing FileReader or its asynchronous completion.
    const reads = vi.spyOn(FileReader.prototype, "readAsText");
    act(() => {
      pick(input);
      fireEvent.mouseDown(input);
      pick(input);
      pick(input, "ignored.json", "{broken");
    });
    expect(reads).toHaveBeenCalledTimes(1);
    expect(status().textContent).toBe("Reading pack file local-pack.json");
    await settled(input);
    expect(status().textContent).toBe("Loaded pack from local-pack.json");
    expect((screen.getByLabelText("Raw JSON") as HTMLTextAreaElement).value).toBe(bytes);
    pick(input, "next.json", "{broken");
    expect(reads).toHaveBeenCalledTimes(2);
    expect(status().textContent).toBe("Reading pack file next.json");
    await settled(input);
    expect(status().textContent).toBe("Invalid JSON in next.json");
    pick(input, "recovered.json");
    await settled(input);
    expect(status().textContent).toBe("Loaded pack from recovered.json");
    expect(screen.queryByTestId("editor-import-error")).toBeNull();
  });

  it("cancelled_pick_does_not_start_read", () => {
    const input = openPicker();
    const reads = vi.spyOn(FileReader.prototype, "readAsText");
    fireEvent.change(input, { target: { files: [] } });
    expect(reads).not.toHaveBeenCalled();
    expect(input.hasAttribute("aria-busy")).toBe(false);
    expect(screen.queryByTestId("editor-file-import-busy-status")).toBeNull();
  });
});
