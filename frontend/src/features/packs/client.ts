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

/** Closed outcome from ``POST /api/v1/activation/redeem`` (never echoes a key). */
export type ActivationRedeemStatus = "paid" | "grace" | "dead" | "unreachable";

export type ActivationRedeemResult = {
  schema_version: string;
  status: ActivationRedeemStatus;
  message: string;
  catalog_downloaded: boolean;
};

export type CatalogueTier = "free" | "paid";

export type CataloguePack = {
  id: string;
  tier: CatalogueTier;
  label: string | null;
  description: string | null;
  version: string | null;
  permissions: string[];
};

export type CatalogueDocument = {
  schema_version: string;
  catalogue_version: string;
  updated: string | null;
  packs: CataloguePack[];
};

export type PackInstallResult = {
  ok: boolean;
  code?: string;
  message?: string;
  pack?: PackRow;
};

/** Closed community index row from ``GET /api/v1/community/index``. */
export type CommunityIndexPack = {
  id: string;
  url: string;
  author: string | null;
  label: string | null;
};

export type CommunityIndexDocument = {
  schema_version: string;
  index_url: string;
  packs: CommunityIndexPack[];
  /** Client-side fetch time (ISO); optional honesty metadata for M17.4. */
  fetched_at: string | null;
};

/** Closed installed community pack row from ``POST /api/v1/community/install``. */
export type CommunityInstalledPack = {
  id: string;
  version: string | null;
  label: string | null;
  author: string | null;
  origin: string | null;
};

export type CommunityInstallCode =
  | "foreign_url"
  | "pack_not_found"
  | "index_rejected"
  | "payload_refused"
  | "unreachable"
  | string;

export type CommunityInstallResult = {
  ok: boolean;
  code?: CommunityInstallCode;
  message?: string;
  pack?: CommunityInstalledPack;
  path?: string;
};

export class PackLibraryHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "PackLibraryHttpError";
    this.status = status;
  }
}

/**
 * Library + redeem surface. No ``rollback`` method: there is no
 * ``POST /api/v1/packs/rollback`` until a prior-revision store exists.
 * Rows may still carry read-only ``rollback_ref`` metadata.
 */
export type PackLibraryClient = {
  listInstalled(): Promise<PackRow[]>;
  /** Redeem an activation key; on paid/grace the caller refreshes the library. */
  redeemActivation(key: string): Promise<ActivationRedeemResult>;
};

/** Opened community pack from ``GET /api/v1/community/packs/{id}``. */
export type CommunityPackDocument = {
  schema_version: string;
  source: "community";
  path: string;
  pack: Record<string, unknown>;
};

/** First-class Packs destination client: library + catalogue + community. */
export type PacksClient = PackLibraryClient & {
  listCatalogue(): Promise<CatalogueDocument>;
  install(pack_id: string): Promise<PackInstallResult>;
  /** Browse the allow-listed community index (not the signed catalogue). */
  listCommunityIndex(): Promise<CommunityIndexDocument>;
  /** One-click install from the community index into ``packs/community/``. */
  installCommunity(pack_id: string): Promise<CommunityInstallResult>;
  /** Open an installed community pack for Strategies validate-before-arm. */
  openCommunityPack(pack_id: string): Promise<CommunityPackDocument>;
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

function adaptCataloguePack(raw: Record<string, unknown>): CataloguePack | null {
  const id = typeof raw.id === "string" ? raw.id : "";
  const tier = raw.tier === "free" || raw.tier === "paid" ? raw.tier : null;
  if (!id || tier === null) {
    return null;
  }
  return {
    id,
    tier,
    label: typeof raw.label === "string" ? raw.label : null,
    description: typeof raw.description === "string" ? raw.description : null,
    version: typeof raw.version === "string" ? raw.version : null,
    permissions: Array.isArray(raw.permissions)
      ? raw.permissions.filter((p): p is string => typeof p === "string")
      : [],
  };
}

async function getCatalogue(url: string): Promise<CatalogueDocument> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new PackLibraryHttpError(response.status, `catalogue failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const packsRaw = Array.isArray(raw.packs) ? raw.packs : [];
  const packs = packsRaw
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map(adaptCataloguePack)
    .filter((entry): entry is CataloguePack => entry !== null);
  return {
    schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
    catalogue_version: typeof raw.catalogue_version === "string" ? raw.catalogue_version : "0",
    updated: typeof raw.updated === "string" ? raw.updated : null,
    packs,
  };
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

function adaptCommunityIndexPack(raw: Record<string, unknown>): CommunityIndexPack | null {
  const id = typeof raw.id === "string" ? raw.id : "";
  const url = typeof raw.url === "string" ? raw.url : "";
  if (!id || !url) {
    return null;
  }
  return {
    id,
    url,
    author: typeof raw.author === "string" ? raw.author : null,
    label: typeof raw.label === "string" ? raw.label : null,
  };
}

async function getCommunityIndex(url: string): Promise<CommunityIndexDocument> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new PackLibraryHttpError(
      response.status,
      `community index failed: ${response.status}`,
    );
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const packsRaw = Array.isArray(raw.packs) ? raw.packs : [];
  const packs = packsRaw
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map(adaptCommunityIndexPack)
    .filter((entry): entry is CommunityIndexPack => entry !== null);
  return {
    schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
    index_url: typeof raw.index_url === "string" ? raw.index_url : "",
    packs,
    fetched_at: new Date().toISOString(),
  };
}

function adaptCommunityInstalledPack(
  raw: Record<string, unknown>,
): CommunityInstalledPack | null {
  const id = typeof raw.id === "string" ? raw.id : "";
  if (!id) {
    return null;
  }
  return {
    id,
    version: typeof raw.version === "string" ? raw.version : null,
    label: typeof raw.label === "string" ? raw.label : null,
    author: typeof raw.author === "string" ? raw.author : null,
    origin: typeof raw.origin === "string" ? raw.origin : null,
  };
}

async function postCommunityInstall(pack_id: string): Promise<CommunityInstallResult> {
  const response = await fetch("/api/v1/community/install", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({ pack_id }),
  });
  let raw: Record<string, unknown> = {};
  try {
    raw = (await response.json()) as Record<string, unknown>;
  } catch {
    raw = {};
  }
  const code = typeof raw.code === "string" ? raw.code : undefined;
  const message =
    typeof raw.message === "string"
      ? raw.message
      : typeof raw.detail === "string"
        ? raw.detail
        : undefined;
  if (!response.ok || raw.ok !== true) {
    return {
      ok: false,
      ...(code !== undefined ? { code } : { code: `http_${response.status}` }),
      ...(message !== undefined
        ? { message }
        : { message: `community install failed: ${response.status}` }),
    };
  }
  const packRaw = raw.pack;
  const pack =
    packRaw && typeof packRaw === "object"
      ? adaptCommunityInstalledPack(packRaw as Record<string, unknown>)
      : undefined;
  const path = typeof raw.path === "string" ? raw.path : undefined;
  return {
    ok: true,
    ...(code !== undefined ? { code } : {}),
    ...(message !== undefined ? { message } : {}),
    ...(pack !== undefined && pack !== null ? { pack } : {}),
    ...(path !== undefined ? { path } : {}),
  };
}

async function postInstall(pack_id: string): Promise<PackInstallResult> {
  const response = await fetch("/api/v1/packs/install", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({
      schema_version: "1",
      command: "packs.install",
      pack_id,
    }),
  });
  let raw: Record<string, unknown> = {};
  try {
    raw = (await response.json()) as Record<string, unknown>;
  } catch {
    raw = {};
  }
  const code = typeof raw.code === "string" ? raw.code : undefined;
  const message =
    typeof raw.message === "string"
      ? raw.message
      : typeof raw.detail === "string"
        ? raw.detail
        : undefined;
  if (!response.ok) {
    return {
      ok: false,
      ...(code !== undefined ? { code } : { code: `http_${response.status}` }),
      ...(message !== undefined
        ? { message }
        : { message: `install failed: ${response.status}` }),
    };
  }
  const packRaw = raw.pack;
  const pack =
    packRaw && typeof packRaw === "object"
      ? adaptRow(packRaw as Record<string, unknown>)
      : undefined;
  return {
    ok: raw.ok === true,
    ...(code !== undefined ? { code } : {}),
    ...(message !== undefined ? { message } : {}),
    ...(pack !== undefined ? { pack } : {}),
  };
}

async function getCommunityPack(packId: string): Promise<CommunityPackDocument> {
  const response = await fetch(
    `/api/v1/community/packs/${encodeURIComponent(packId)}`,
    {
      method: "GET",
      credentials: "include",
      headers: {
        "X-Krellbot-CSRF": getCsrf(),
      },
    },
  );
  if (!response.ok) {
    throw new PackLibraryHttpError(
      response.status,
      `community pack open failed: ${response.status}`,
    );
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const pack =
    raw.pack && typeof raw.pack === "object"
      ? (raw.pack as Record<string, unknown>)
      : {};
  return {
    schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
    source: "community",
    path: typeof raw.path === "string" ? raw.path : "",
    pack,
  };
}

export function createHttpClient(): PacksClient {
  return {
    listInstalled(): Promise<PackRow[]> {
      return getJson("/api/v1/packs");
    },
    redeemActivation(key: string): Promise<ActivationRedeemResult> {
      return postRedeemActivation(key);
    },
    listCatalogue(): Promise<CatalogueDocument> {
      return getCatalogue("/api/v1/catalogue");
    },
    install(pack_id: string): Promise<PackInstallResult> {
      return postInstall(pack_id);
    },
    listCommunityIndex(): Promise<CommunityIndexDocument> {
      return getCommunityIndex("/api/v1/community/index");
    },
    installCommunity(pack_id: string): Promise<CommunityInstallResult> {
      return postCommunityInstall(pack_id);
    },
    openCommunityPack(pack_id: string): Promise<CommunityPackDocument> {
      return getCommunityPack(pack_id);
    },
  };
}

/**
 * Same client under the name the WorkstationShell imports; kept separate
 * so existing `createHttpClient` callers are untouched.
 */
export function createPacksHttpClient(): PacksClient {
  return createHttpClient();
}
