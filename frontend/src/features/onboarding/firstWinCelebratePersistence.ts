/**
 * First-win celebrate persistence (M25.8).
 *
 * Shows at most once after the first successful paper arm on this machine.
 * Survives reloads so the toast never nags.
 */

export const FIRST_WIN_CELEBRATE_STORAGE_KEY = "krellbot.home.firstWinCelebrate";

export type FirstWinCelebratePersisted = {
  shown: boolean;
};

export const DEFAULT_FIRST_WIN_CELEBRATE_STATE: FirstWinCelebratePersisted = {
  shown: false,
};

export function readFirstWinCelebrateState(
  storageKey: string = FIRST_WIN_CELEBRATE_STORAGE_KEY,
): FirstWinCelebratePersisted {
  if (typeof window === "undefined") {
    return { ...DEFAULT_FIRST_WIN_CELEBRATE_STATE };
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return { ...DEFAULT_FIRST_WIN_CELEBRATE_STATE };
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as FirstWinCelebratePersisted).shown === "boolean"
    ) {
      return { shown: (parsed as FirstWinCelebratePersisted).shown };
    }
    return { ...DEFAULT_FIRST_WIN_CELEBRATE_STATE };
  } catch {
    return { ...DEFAULT_FIRST_WIN_CELEBRATE_STATE };
  }
}

export function writeFirstWinCelebrateState(
  next: FirstWinCelebratePersisted,
  storageKey: string = FIRST_WIN_CELEBRATE_STORAGE_KEY,
): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(next));
  } catch {
    // Best-effort only.
  }
}

export function isFirstWinCelebrateShown(
  storageKey: string = FIRST_WIN_CELEBRATE_STORAGE_KEY,
): boolean {
  return readFirstWinCelebrateState(storageKey).shown === true;
}

/** Mark the celebrate as consumed so silence holds across reloads. */
export function markFirstWinCelebrateShown(
  storageKey: string = FIRST_WIN_CELEBRATE_STORAGE_KEY,
): FirstWinCelebratePersisted {
  const next: FirstWinCelebratePersisted = { shown: true };
  writeFirstWinCelebrateState(next, storageKey);
  return next;
}
