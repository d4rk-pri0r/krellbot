import { useCallback, useEffect, useRef, useState } from "react";
import type { OperationsClient, OperationsViewModel } from "./client";

export const OPERATIONS_REFRESH_INTERVAL_MS = 5000;
export const OPERATIONS_READ_TIMEOUT_MS = 4000;
const DISPLAY_TICK_MS = 1000;

export type OperationsRefreshOptions = {
  intervalMs?: number;
  timeoutMs?: number;
};

export type OperationsRefreshState = {
  view: OperationsViewModel | null;
  fetchError: string | null;
  refreshing: boolean;
  lastSuccessAt: number | null;
  lastSuccessAgeMs: number | null;
  refresh: () => Promise<void>;
};

function timeoutError(ms: number): Error {
  return new Error(
    `operations read timed out after ${ms}ms — no response from the local dashboard server`,
  );
}

function readWithTimeout(
  read: Promise<OperationsViewModel>,
  timeoutMs: number,
): Promise<OperationsViewModel> {
  return new Promise<OperationsViewModel>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(timeoutError(timeoutMs));
    }, timeoutMs);
    read.then(
      (next) => {
        clearTimeout(timer);
        resolve(next);
      },
      (err: unknown) => {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error(String(err)));
      },
    );
  });
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useOperationsRefresh(
  client: OperationsClient,
  options: OperationsRefreshOptions = {},
): OperationsRefreshState {
  const intervalMs = options.intervalMs ?? OPERATIONS_REFRESH_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? OPERATIONS_READ_TIMEOUT_MS;

  const [view, setView] = useState<OperationsViewModel | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  const seqRef = useRef(0);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(false);

  // Each read is sequenced at start; only the newest read may apply its result,
  // so an older periodic read can never overwrite a newer action-triggered
  // refresh, and a late resolution of an abandoned read is discarded.
  const startRead = useCallback(async (): Promise<void> => {
    seqRef.current += 1;
    const seq = seqRef.current;
    inFlightRef.current = true;
    setRefreshing(true);
    try {
      const next = await readWithTimeout(client.getOperations(), timeoutMs);
      if (!mountedRef.current || seq !== seqRef.current) {
        return;
      }
      setView(next);
      setFetchError(null);
      setLastSuccessAt(Date.now());
    } catch (err) {
      if (!mountedRef.current || seq !== seqRef.current) {
        return;
      }
      setFetchError(errorMessage(err));
    } finally {
      if (seq === seqRef.current) {
        inFlightRef.current = false;
        if (mountedRef.current) {
          setRefreshing(false);
        }
      }
    }
  }, [client, timeoutMs]);

  // A manual refresh always proceeds and supersedes any in-flight read.
  const refresh = useCallback((): Promise<void> => startRead(), [startRead]);

  useEffect(() => {
    mountedRef.current = true;
    void startRead();
    const interval = window.setInterval(() => {
      // One read at a time: a hung read is abandoned by its bounded timeout so
      // the next tick can try again. The timer only ever reads; it never sends
      // a state-changing command.
      if (inFlightRef.current) {
        return;
      }
      void startRead();
    }, intervalMs);
    return () => {
      mountedRef.current = false;
      window.clearInterval(interval);
    };
  }, [startRead, intervalMs]);

  // Keeps the last-successful-read age truthful while reads fail or hang: the
  // retained view is never re-rendered by a fetch, so age must tick on its own.
  useEffect(() => {
    const ticker = window.setInterval(() => {
      if (mountedRef.current) {
        setNowMs(Date.now());
      }
    }, DISPLAY_TICK_MS);
    return () => {
      window.clearInterval(ticker);
    };
  }, []);

  const lastSuccessAgeMs =
    lastSuccessAt === null ? null : Math.max(0, nowMs - lastSuccessAt);

  return { view, fetchError, refreshing, lastSuccessAt, lastSuccessAgeMs, refresh };
}
