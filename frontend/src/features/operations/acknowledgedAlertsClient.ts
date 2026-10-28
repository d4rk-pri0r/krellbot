import { getCsrf } from "../../session";
import type { AlertRow } from "./client";

export type AcknowledgedAlertsClient = {
  listAcknowledged(): Promise<ReadonlyArray<AlertRow>>;
};

function adaptAlert(raw: unknown): AlertRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const obj = raw as Record<string, unknown>;
  if (
    typeof obj.id !== "string" ||
    typeof obj.kind !== "string" ||
    typeof obj.severity !== "string" ||
    typeof obj.count !== "number" ||
    typeof obj.first_ts !== "number" ||
    typeof obj.last_ts !== "number" ||
    typeof obj.acknowledged !== "boolean"
  ) {
    return null;
  }
  return {
    id: obj.id,
    kind: obj.kind,
    severity: obj.severity,
    code: typeof obj.code === "string" ? obj.code : null,
    venue: typeof obj.venue === "string" ? obj.venue : null,
    pair: typeof obj.pair === "string" ? obj.pair : null,
    count: obj.count,
    first_ts: obj.first_ts,
    last_ts: obj.last_ts,
    acknowledged: obj.acknowledged,
  };
}

export const ACKNOWLEDGED_READ_DEADLINE_MS = 10000;

function readDeadlineError(ms: number): Error {
  return new Error(
    `acknowledged alerts read timed out after ${ms}ms — no operations response before the deadline`,
  );
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export async function listAcknowledgedAlerts(): Promise<ReadonlyArray<AlertRow>> {
  // One bounded read: response headers and the JSON body share a single fixed
  // deadline. A stalled read rejects with an honest read-timeout Error and
  // aborts its owned request, so rows landing after the deadline can never
  // settle this attempt. The timer is cleared on every exit path.
  const controller = new AbortController();
  let expireDeadline!: () => void;
  const deadline = new Promise<never>((_, reject) => {
    expireDeadline = () => reject(readDeadlineError(ACKNOWLEDGED_READ_DEADLINE_MS));
  });
  const timer = setTimeout(() => {
    controller.abort();
    expireDeadline();
  }, ACKNOWLEDGED_READ_DEADLINE_MS);
  try {
    const response = await Promise.race([
      fetch("/api/v1/operations", {
        method: "GET",
        credentials: "include",
        headers: {
          "X-Krellbot-CSRF": getCsrf(),
        },
        signal: controller.signal,
      }),
      deadline,
    ]);
    if (!response.ok) {
      throw new Error(`operations view failed: ${response.status}`);
    }
    const raw = (await Promise.race([response.json(), deadline])) as Record<string, unknown>;
    const alertsRaw = Array.isArray(raw.alerts) ? raw.alerts : [];
    return alertsRaw
      .map(adaptAlert)
      .filter((a): a is AlertRow => a !== null)
      .filter((a) => a.acknowledged === true);
  } catch (error) {
    if (controller.signal.aborted && isAbortError(error)) {
      throw readDeadlineError(ACKNOWLEDGED_READ_DEADLINE_MS);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export function createAcknowledgedAlertsHttpClient(): AcknowledgedAlertsClient {
  return {
    listAcknowledged(): Promise<ReadonlyArray<AlertRow>> {
      return listAcknowledgedAlerts();
    },
  };
}
