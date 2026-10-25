/**
 * CommandPalette — modal Tab focus-safety regressions (JSDOM evidence only).
 *
 * User gap (independently reproduced in production Chromium): while the
 * palette is open and its sole Command input owns focus, native Tab moved
 * focus to BODY/browser chrome and Shift+Tab moved focus to a background
 * Home card, even though the dialog declares aria-modal="true". Escape
 * close and opener return-focus already worked and stay pinned here.
 *
 * Scope of this proof — JSDOM:
 *   - JSDOM does not implement native sequential focus navigation, so it
 *     cannot demonstrate the focus move the browser performs for Tab.
 *     The distinguishing evidence in this file is the cancelable-event
 *     contract: an owned, unmodified, non-composing, not-already-prevented
 *     Tab/Shift+Tab keydown on the focused command input MUST be consumed
 *     (defaultPrevented), which is what stops the browser default focus
 *     move; every other Tab keydown MUST be left unclaimed.
 *   - Genuine browser Tab/Shift+Tab proof at 1440x900/390x844 with the
 *     guarded backend is separately verified by the parent operator;
 *     no worker browser run is claimed here.
 *
 * activeElement is read from the real document in every assertion; it is
 * never mocked or stubbed.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

const PLACEHOLDER = "Type to search actions, strategies, or views";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function getCommandInput(): HTMLInputElement {
  return screen.getByPlaceholderText(PLACEHOLDER) as HTMLInputElement;
}

function nativeTabKeydown(init: KeyboardEventInit = {}): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key: "Tab",
    bubbles: true,
    cancelable: true,
    composed: true,
    ...init,
  });
}

function appendFocusedSibling(): HTMLButtonElement {
  const sibling = document.createElement("button");
  sibling.textContent = "background sibling";
  document.body.appendChild(sibling);
  sibling.focus();
  expect(document.activeElement).toBe(sibling);
  return sibling;
}

/* ------------------------------------------------------------------ */
/* 1. Owned forward/reverse Tab is consumed                            */
/* ------------------------------------------------------------------ */

describe("CommandPalette — owned Tab keydown consumed while open", () => {
  it("consumes a native-like forward Tab on the focused input and keeps focus and text", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    fireEvent.change(input, { target: { value: "rehearsal" } });

    const tab = nativeTabKeydown();
    expect(tab.cancelable).toBe(true);
    fireEvent(input, tab);

    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("rehearsal");
  });

  it("consumes a native-like reverse Shift+Tab on the focused input and keeps focus and text", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    fireEvent.change(input, { target: { value: "esc" } });

    const shiftTab = nativeTabKeydown({ shiftKey: true });
    expect(shiftTab.cancelable).toBe(true);
    fireEvent(input, shiftTab);

    expect(shiftTab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("esc");
  });

  it("keeps consuming Tab after an ordinary rerender that preserves the typed value", () => {
    const { rerender } = render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    fireEvent.change(input, { target: { value: "paper" } });

    rerender(<CommandPalette open onClose={() => {}} />);

    expect(input.value).toBe("paper");
    expect(document.activeElement).toBe(input);

    const tab = nativeTabKeydown();
    fireEvent(input, tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("paper");
  });
});

/* ------------------------------------------------------------------ */
/* 2. Modified / composing / pre-claimed Tab stays unclaimed           */
/* ------------------------------------------------------------------ */

describe("CommandPalette — unclaimable Tab keydowns stay untouched", () => {
  it.each(["ctrlKey", "altKey", "metaKey"] as const)(
    "leaves a %s-modified Tab keydown unclaimed",
    (modifier) => {
      render(<CommandPalette open onClose={() => {}} />);
      const input = getCommandInput();
      expect(document.activeElement).toBe(input);

      const tab = nativeTabKeydown({ [modifier]: true });
      const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
      fireEvent(input, tab);

      expect(tab.defaultPrevented).toBe(false);
      expect(preventDefaultSpy).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(input);
    },
  );

  it("leaves a Shift+Tab with an additional ctrl modifier unclaimed", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();

    const tab = nativeTabKeydown({ shiftKey: true, ctrlKey: true });
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(input, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
  });

  it("leaves a composing Tab keydown (isComposing) unclaimed", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    const tab = nativeTabKeydown({ isComposing: true });
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(input, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(input);
  });

  it("leaves a composition-marker Tab keydown (keyCode 229) unclaimed", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    const tab = nativeTabKeydown();
    Object.defineProperty(tab, "keyCode", { value: 229 });
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(input, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
  });

  it("does not re-claim a Tab keydown another handler already prevented", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    const tab = nativeTabKeydown();
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    tab.preventDefault();

    fireEvent(input, tab);

    expect(tab.defaultPrevented).toBe(true);
    expect(preventDefaultSpy).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/* 3. Tab owned outside the palette is untouched; no focus stealing    */
/* ------------------------------------------------------------------ */

describe("CommandPalette — unowned Tab and sibling focus", () => {
  it("leaves a Tab keydown owned by a focused sibling unclaimed and steals no focus", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    const sibling = appendFocusedSibling();

    const tab = nativeTabKeydown();
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(sibling, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(sibling);

    document.body.removeChild(sibling);
  });

  it("ignores a Tab keydown dispatched on the input while a sibling programmatically owns focus", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();

    const sibling = appendFocusedSibling();

    const tab = nativeTabKeydown();
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(input, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(sibling);

    document.body.removeChild(sibling);
  });
});

/* ------------------------------------------------------------------ */
/* 4. Preserved contracts: initial focus, Escape, return focus, reopen */
/* ------------------------------------------------------------------ */

describe("CommandPalette — preserved focus lifecycle around the Tab trap", () => {
  it("focuses the input on open, returns focus to the opener on Escape close, and refocuses on reopen", () => {
    const opener = document.createElement("button");
    opener.textContent = "palette opener";
    document.body.appendChild(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    const onClose = vi.fn();
    const { rerender } = render(<CommandPalette open onClose={onClose} />);

    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    fireEvent.change(input, { target: { value: "cycle" } });
    const tab = nativeTabKeydown();
    fireEvent(input, tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<CommandPalette open={false} onClose={onClose} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();
    expect(document.activeElement).toBe(opener);

    rerender(<CommandPalette open onClose={onClose} />);
    const reopenedInput = getCommandInput();
    expect(document.activeElement).toBe(reopenedInput);

    const reopenTab = nativeTabKeydown({ shiftKey: true });
    fireEvent(reopenedInput, reopenTab);
    expect(reopenTab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(reopenedInput);

    fireEvent.keyDown(window, { key: "Escape" });
    rerender(<CommandPalette open={false} onClose={onClose} />);
    expect(document.activeElement).toBe(opener);

    document.body.removeChild(opener);
  });

  it("still allows ordinary text entry while the Tab trap is armed", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();

    fireEvent.change(input, { target: { value: "str" } });
    fireEvent.keyDown(input, { key: "a" });
    fireEvent.change(input, { target: { value: "strategy" } });

    expect(input.value).toBe("strategy");
    expect(document.activeElement).toBe(input);
  });
});

/* ------------------------------------------------------------------ */
/* 5. Closed / unmounted lifecycle: no active Tab handler              */
/* ------------------------------------------------------------------ */

describe("CommandPalette — closed and unmounted lifecycle", () => {
  it("claims no Tab keydown while the palette is closed", () => {
    render(<CommandPalette open={false} onClose={() => {}} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();

    const tab = nativeTabKeydown();
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(document.body, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
  });

  it("claims no Tab keydown after close removed the palette", () => {
    const { rerender } = render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    const owned = nativeTabKeydown();
    fireEvent(input, owned);
    expect(owned.defaultPrevented).toBe(true);

    rerender(<CommandPalette open={false} onClose={() => {}} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();

    const tab = nativeTabKeydown();
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(document.body, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();
  });

  it("claims no Tab keydown after unmount and restores the opener's focus", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    const { unmount } = render(<CommandPalette open onClose={() => {}} />);
    const input = getCommandInput();
    expect(document.activeElement).toBe(input);

    unmount();
    expect(document.activeElement).toBe(opener);

    const tab = nativeTabKeydown();
    const preventDefaultSpy = vi.spyOn(tab, "preventDefault");
    fireEvent(document.body, tab);

    expect(tab.defaultPrevented).toBe(false);
    expect(preventDefaultSpy).not.toHaveBeenCalled();

    document.body.removeChild(opener);
  });
});
