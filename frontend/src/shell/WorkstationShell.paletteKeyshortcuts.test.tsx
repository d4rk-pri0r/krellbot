import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WorkstationShell } from "./WorkstationShell";

afterEach(cleanup);

async function renderShell(): Promise<HTMLElement> {
  render(<WorkstationShell />);
  await waitFor(() =>
    expect(screen.getByTestId("kbot-shell").getAttribute("data-bootstrap-done")).toBe("1"),
  );
  return screen.getByTestId("kbot-shell-palette-hint");
}

describe("brand-bar palette shortcuts (KRELL-SIGNAL-20261010)", () => {
  it("exposes both shortcuts on the existing button without changing the visible glyph", async () => {
    const trigger = await renderShell();
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger.getAttribute("aria-keyshortcuts")).toBe("Control+K Meta+K");
    const keys = trigger.querySelector(".kbot-shell__palette-keys");
    expect(keys?.textContent).toBe("⌘K");
    expect(keys?.getAttribute("aria-hidden")).toBe("true");
    expect(trigger.querySelector(".kbot-palette__label")?.textContent).toBe("Open command palette");
  });

  it.each(["ctrlKey", "metaKey"] as const)("keeps %s+K opening, default prevention, Escape and focus return", async (modifier) => {
    const trigger = await renderShell();
    trigger.focus();
    expect(screen.queryByTestId("command-palette")).toBeNull();
    const event = new KeyboardEvent("keydown", {
      key: "k", [modifier]: true, bubbles: true, cancelable: true,
    });
    fireEvent(window, event);
    expect(event.defaultPrevented).toBe(true);
    const dialog = screen.getByTestId("command-palette");
    expect(dialog.getAttribute("aria-keyshortcuts")).toBe("Escape");
    expect(dialog.querySelector(".kbot-shell__palette-hint")?.textContent).toBe(
      "Press Esc to close · Ctrl+K from anywhere",
    );
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Command input" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("preserves click opening and leaves unmodified K alone", async () => {
    const trigger = await renderShell();
    const event = new KeyboardEvent("keydown", { key: "k", cancelable: true });
    fireEvent(window, event);
    expect(event.defaultPrevented).toBe(false);
    expect(screen.queryByTestId("command-palette")).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByTestId("command-palette")).toBeDefined();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });
});
