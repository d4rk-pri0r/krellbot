import { getCsrf } from "../../session";

export type KeysVenue = "kraken" | "coinbase";

/** Default venue for single-panel callers (Kraken remains the primary path). */
export const KEYS_VENUE: KeysVenue = "kraken";

export const KEYS_VENUES: ReadonlyArray<KeysVenue> = ["kraken", "coinbase"];

export type KeysBalanceRow = {
  asset: string;
  free: string;
};

export type KeysStatus = {
  schema_version: string;
  venue: string;
  present: boolean;
  corrupt: boolean;
  message: string;
  backend_label: string | null;
  balances: ReadonlyArray<KeysBalanceRow> | null;
  balances_available: boolean;
};

export type KeysMutationResult = {
  schema_version: string;
  venue: string;
  status: string;
  ok: boolean;
  message: string;
  effect: string;
  backend_label: string | null;
};

export type KeysClient = {
  getStatus(venue?: KeysVenue): Promise<KeysStatus>;
  probeAndStore(
    key: string,
    secret: string,
    venue?: KeysVenue,
  ): Promise<KeysMutationResult>;
  remove(venue?: KeysVenue): Promise<KeysMutationResult>;
};

function keysPath(venue: string): string {
  return `/api/v1/keys/${encodeURIComponent(venue)}`;
}

function adaptBalance(raw: unknown): KeysBalanceRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const row = raw as { asset?: unknown; free?: unknown };
  if (typeof row.asset !== "string" || typeof row.free !== "string") {
    return null;
  }
  return { asset: row.asset, free: row.free };
}

function adaptStatus(raw: unknown): KeysStatus {
  const body = (raw ?? {}) as Record<string, unknown>;
  const balancesRaw = body.balances;
  let balances: KeysBalanceRow[] | null = null;
  if (Array.isArray(balancesRaw)) {
    balances = balancesRaw
      .map(adaptBalance)
      .filter((row): row is KeysBalanceRow => row !== null);
  }
  return {
    schema_version: typeof body.schema_version === "string" ? body.schema_version : "1",
    venue: typeof body.venue === "string" ? body.venue : KEYS_VENUE,
    present: body.present === true,
    corrupt: body.corrupt === true,
    message: typeof body.message === "string" ? body.message : "keyring state could not be read",
    backend_label: typeof body.backend_label === "string" ? body.backend_label : null,
    balances,
    balances_available: body.balances_available === true,
  };
}

function adaptMutation(raw: unknown): KeysMutationResult {
  const body = (raw ?? {}) as Record<string, unknown>;
  return {
    schema_version: typeof body.schema_version === "string" ? body.schema_version : "1",
    venue: typeof body.venue === "string" ? body.venue : KEYS_VENUE,
    status: typeof body.status === "string" ? body.status : "store_failed",
    ok: body.ok === true,
    message: typeof body.message === "string" ? body.message : "keyring write failed and rollback is uncertain",
    effect: typeof body.effect === "string" ? body.effect : "refused",
    backend_label: typeof body.backend_label === "string" ? body.backend_label : null,
  };
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const raw = (await response.json()) as { detail?: unknown };
    if (typeof raw.detail === "string" && raw.detail.trim() !== "") {
      return raw.detail;
    }
  } catch {
    // Keep the status fallback when the body is not JSON.
  }
  return `${fallback}: ${response.status}`;
}

async function fetchStatus(venue: KeysVenue): Promise<KeysStatus> {
  const response = await fetch(keysPath(venue), {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "keys status failed"));
  }
  return adaptStatus(await response.json());
}

async function postProbeAndStore(
  venue: KeysVenue,
  key: string,
  secret: string,
): Promise<KeysMutationResult> {
  const response = await fetch(keysPath(venue), {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({ key, secret }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "keys probe-and-store failed"));
  }
  return adaptMutation(await response.json());
}

async function deleteStored(venue: KeysVenue): Promise<KeysMutationResult> {
  const response = await fetch(keysPath(venue), {
    method: "DELETE",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "keys remove failed"));
  }
  return adaptMutation(await response.json());
}

export function createHttpClient(): KeysClient {
  return {
    getStatus(venue = KEYS_VENUE): Promise<KeysStatus> {
      return fetchStatus(venue);
    },
    probeAndStore(key: string, secret: string, venue = KEYS_VENUE): Promise<KeysMutationResult> {
      return postProbeAndStore(venue, key, secret);
    },
    remove(venue = KEYS_VENUE): Promise<KeysMutationResult> {
      return deleteStored(venue);
    },
  };
}

export function createKeysHttpClient(): KeysClient {
  return createHttpClient();
}
