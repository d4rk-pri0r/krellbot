/**
 * M25.8 — first-win celebrate shows once, then silence.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FirstWinCelebrate,
  FIRST_WIN_CELEBRATE_MESSAGE,
} from "./FirstWinCelebrate";
import {
  FIRST_WIN_CELEBRATE_STORAGE_KEY,
  isFirstWinCelebrateShown,
  markFirstWinCelebrateShown,
  readFirstWinCelebrateState,
  writeFirstWinCelebrateState,
} from "./firstWinCelebratePersistence";

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("first-win celebrate persistence", () => {
  it("defaults to not shown and persists after mark", () => {
    expect(isFirstWinCelebrateShown()).toBe(false);
    markFirstWinCelebrateShown();
    expect(isFirstWinCelebrateShown()).toBe(true);
    expect(readFirstWinCelebrateState()).toEqual({ shown: true });
    expect(window.localStorage.getItem(FIRST_WIN_CELEBRATE_STORAGE_KEY)).toMatch(
      /"shown":true/,
    );
  });

  it("rejects corrupt storage without throwing", () => {
    writeFirstWinCelebrateState({ shown: true });
    window.localStorage.setItem(FIRST_WIN_CELEBRATE_STORAGE_KEY, "{not-json");
    expect(isFirstWinCelebrateShown()).toBe(false);
  });
});

describe("FirstWinCelebrate toast", () => {
  it("renders the live-on-this-computer celebrate copy when open", () => {
    render(<FirstWinCelebrate open onDismiss={() => {}} autoDismissMs={0} />);
    expect(screen.getByTestId("first-win-celebrate").getAttribute("role")).toBe(
      "status",
    );
    expect(screen.getByTestId("first-win-celebrate-title").textContent).toBe(
      FIRST_WIN_CELEBRATE_MESSAGE,
    );
    expect(screen.getByTestId("first-win-celebrate").textContent).toMatch(
      /guide stays quiet/i,
    );
  });

  it("renders nothing when closed", () => {
    render(
      <FirstWinCelebrate open={false} onDismiss={() => {}} autoDismissMs={0} />,
    );
    expect(screen.queryByTestId("first-win-celebrate")).toBeNull();
  });

  it("dismisses from Got it and from the auto-dismiss timer", () => {
    const onDismiss = vi.fn();
    const { rerender } = render(
      <FirstWinCelebrate open onDismiss={onDismiss} autoDismissMs={2000} />,
    );
    fireEvent.click(screen.getByTestId("first-win-celebrate-dismiss"));
    expect(onDismiss).toHaveBeenCalledTimes(1);

    onDismiss.mockClear();
    rerender(<FirstWinCelebrate open onDismiss={onDismiss} autoDismissMs={2000} />);
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
