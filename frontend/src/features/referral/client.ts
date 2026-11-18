import { getCsrf } from "../../session";

export type ReferralKind = "exchange_signup" | "pack_purchase";

export type ReferralDisclosure = {
  schema_version: string;
  headline: string;
  body: string;
  packs_body: string;
  earn_rule: string;
  source: string;
};

export type ReferralReceipt = {
  receipt_id: string;
  kind: string;
  ts: number;
  venue: string;
  pack_id: string;
  server_posted: boolean;
};

export type ReferralStatus = ReferralDisclosure & {
  receipt_count: number;
  receipts: ReferralReceipt[];
};

export type ReferralAttributeResult = {
  schema_version: string;
  ok: boolean;
  code: string;
  message: string;
  receipt_id: string;
  kind: string;
  server_posted: boolean;
  disclosure: ReferralDisclosure;
};

export type ReferralAttributeInput = {
  kind: ReferralKind;
  venue?: string;
  pack_id?: string;
};

export type ReferralClient = {
  getStatus(): Promise<ReferralStatus>;
  attribute(input: ReferralAttributeInput): Promise<ReferralAttributeResult>;
};

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asBool(value: unknown): boolean {
  return value === true;
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function adaptDisclosure(raw: unknown): ReferralDisclosure {
  const row = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    schema_version: asString(row.schema_version, "1"),
    headline: asString(row.headline),
    body: asString(row.body),
    packs_body: asString(row.packs_body),
    earn_rule: asString(row.earn_rule),
    source: asString(row.source),
  };
}

function adaptReceipt(raw: unknown): ReferralReceipt {
  const row = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    receipt_id: asString(row.receipt_id),
    kind: asString(row.kind),
    ts: asNumber(row.ts),
    venue: asString(row.venue),
    pack_id: asString(row.pack_id),
    server_posted: asBool(row.server_posted),
  };
}

export function adaptReferralStatus(raw: unknown): ReferralStatus {
  const row = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const disclosure = adaptDisclosure(row);
  const receiptsRaw = Array.isArray(row.receipts) ? row.receipts : [];
  return {
    ...disclosure,
    receipt_count: asNumber(row.receipt_count),
    receipts: receiptsRaw.map(adaptReceipt),
  };
}

export function adaptReferralAttributeResult(
  raw: unknown,
): ReferralAttributeResult {
  const row = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    schema_version: asString(row.schema_version, "1"),
    ok: asBool(row.ok),
    code: asString(row.code),
    message: asString(row.message),
    receipt_id: asString(row.receipt_id),
    kind: asString(row.kind),
    server_posted: asBool(row.server_posted),
    disclosure: adaptDisclosure(row.disclosure),
  };
}

export function createReferralHttpClient(): ReferralClient {
  return {
    async getStatus(): Promise<ReferralStatus> {
      const response = await fetch("/api/v1/referral", {
        method: "GET",
        credentials: "include",
        headers: {
          "X-Krellbot-CSRF": getCsrf(),
        },
      });
      if (!response.ok) {
        throw new Error(`referral status failed: ${response.status}`);
      }
      return adaptReferralStatus(await response.json());
    },
    async attribute(
      input: ReferralAttributeInput,
    ): Promise<ReferralAttributeResult> {
      const response = await fetch("/api/v1/referral/attribute", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: JSON.stringify({
          kind: input.kind,
          venue: input.venue ?? "",
          pack_id: input.pack_id ?? "",
        }),
      });
      const raw = await response.json().catch(() => ({}));
      const adapted = adaptReferralAttributeResult(raw);
      if (!response.ok || !adapted.ok) {
        throw new Error(
          adapted.message || `referral attribute failed: ${response.status}`,
        );
      }
      return adapted;
    },
  };
}
