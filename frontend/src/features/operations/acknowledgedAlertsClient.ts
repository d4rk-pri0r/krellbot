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

export async function listAcknowledgedAlerts(): Promise<ReadonlyArray<AlertRow>> {
  const response = await fetch("/api/v1/operations", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`operations view failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const alertsRaw = Array.isArray(raw.alerts) ? raw.alerts : [];
  return alertsRaw
    .map(adaptAlert)
    .filter((a): a is AlertRow => a !== null)
    .filter((a) => a.acknowledged === true);
}

export function createAcknowledgedAlertsHttpClient(): AcknowledgedAlertsClient {
  return {
    listAcknowledged(): Promise<ReadonlyArray<AlertRow>> {
      return listAcknowledgedAlerts();
    },
  };
}
