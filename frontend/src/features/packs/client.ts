import { getCsrf } from "../../session";

export type PackBucket =
  | "purchased"
  | "download_pending"
  | "installed"
  | "configured"
  | "deployed";

export type PackRollbackRef = {
  pack_id: string;
  prior_revision_id: string;
};

export type PackRow = {
  bucket: PackBucket;
  pack_id: string;
  version: string | null;
  permissions: string[];
  rollback_ref: PackRollbackRef | null;
};

export type PackRollbackResult = {
  ok: boolean;
  message?: string;
};

/** Closed outcome from ``POST /api/v1/activation/redeem`` (never echoes a key). */
export type ActivationRedeemStatus = "paid" | "grace" | "dead" | "unreachable";

export type ActivationRedeemResult = {
  schema_version: string;
  status: ActivationRedeemStatus;
  message: string;
  catalog_downloaded: boolean;
};

export class PackLibraryHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "PackLibraryHttpError";
    this.status = status;
  }
}

export type PackLibraryClient = {
  listInstalled(): Promise<PackRow[]>;
  rollback(pack_id: string): Promise<PackRollbackResult>;
  /** Redeem an activation key; on paid/grace the caller refreshes the library. */
  redeemActivation(key: string): Promise<ActivationRedeemResult>;
};

async function getJson(url: string): Promise<PackRow[]> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new PackLibraryHttpError(response.status, `pack library failed: ${response.status}`);
  }
  const raw = (await response.json()) as unknown;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map(adaptRow);
}

function adaptRow(raw: Record<string, unknown>): PackRow {
  const bucket = typeof raw.bucket === "string" ? (raw.bucket as PackBucket) : "installed";
  const pack_id = typeof raw.pack_id === "string" ? raw.pack_id : "";
  const version = typeof raw.version === "string" ? raw.version : null;
  const permissions = Array.isArray(raw.permissions)
    ? raw.permissions.filter((p): p is string => typeof p === "string")
    : [];
  const rollback_raw = raw.rollback_ref;
  let rollback_ref: PackRollbackRef | null = null;
  if (
    rollback_raw &&
    typeof rollback_raw === "object" &&
    typeof (rollback_raw as Record<string, unknown>).prior_revision_id === "string" &&
    typeof (rollback_raw as Record<string, unknown>).pack_id === "string"
  ) {
    const r = rollback_raw as Record<string, unknown>;
    rollback_ref = {
      pack_id: r.pack_id as string,
      prior_revision_id: r.prior_revision_id as string,
    };
  }
  return { bucket, pack_id, version, permissions, rollback_ref };
}

async function postRollback(pack_id: string): Promise<PackRollbackResult> {
  const response = await fetch("/api/v1/packs/rollback", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({
      schema_version: "1",
      command: "packs.rollback",
      payload: { pack_id },
    }),
  });
  if (!response.ok) {
    return { ok: false, message: `rollback failed: ${response.status}` };
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const ok = raw.ok === true;
  const message = typeof raw.message === "string" ? raw.message : undefined;
  return ok ? { ok: true } : { ok: false, ...(message !== undefined ? { message } : {}) };
}

const REDEEM_STATUSES = new Set<ActivationRedeemStatus>([
  "paid",
  "grace",
  "dead",
  "unreachable",
]);

function adaptRedeemResult(raw: unknown): ActivationRedeemResult {
  const body = (raw ?? {}) as Record<string, unknown>;
  const statusRaw = typeof body.status === "string" ? body.status : "dead";
  const status: ActivationRedeemStatus = REDEEM_STATUSES.has(
    statusRaw as ActivationRedeemStatus,
  )
    ? (statusRaw as ActivationRedeemStatus)
    : "dead";
  return {
    schema_version:
      typeof body.schema_version === "string" ? body.schema_version : "1",
    status,
    message:
      typeof body.message === "string" ? body.message : "license not accepted",
    catalog_downloaded: body.catalog_downloaded === true,
  };
}

async function postRedeemActivation(key: string): Promise<ActivationRedeemResult> {
  const response = await fetch("/api/v1/activation/redeem", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({ key }),
  });
  if (!response.ok) {
    throw new PackLibraryHttpError(
      response.status,
      `activation redeem failed: ${response.status}`,
    );
  }
  return adaptRedeemResult(await response.json());
}

export function createHttpClient(): PackLibraryClient {
  return {
    listInstalled(): Promise<PackRow[]> {
      return getJson("/api/v1/packs");
    },
    rollback(pack_id: string): Promise<PackRollbackResult> {
      return postRollback(pack_id);
    },
    redeemActivation(key: string): Promise<ActivationRedeemResult> {
      return postRedeemActivation(key);
    },
  };
}

/**
 * Same client under the name the WorkstationShell imports; kept separate
 * so existing `createHttpClient` callers are untouched.
 */
export function createPacksHttpClient(): PackLibraryClient {
  return createHttpClient();
}
