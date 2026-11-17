/**
 * Packs destination source honesty — three lanes, never conflated.
 * Contract: KRELL-SIGNAL-20261010. Community is unpaid/unverified and is
 * never presented as an ed25519-signed catalogue SKU (M5) or a starter.
 */

export type PackSourceId = "signed_catalogue" | "community" | "starter";

export type PackSourceMeta = {
  id: PackSourceId;
  /** Short UI badge. */
  badge: string;
  /** One-line honesty sentence for helpers / legends. */
  honesty: string;
};

export const PACK_SOURCES: Record<PackSourceId, PackSourceMeta> = {
  signed_catalogue: {
    id: "signed_catalogue",
    badge: "Signed catalogue · ed25519",
    honesty:
      "Free and paid Strategy Packs verified with an ed25519 catalogue signature. Paid rows need activation.",
  },
  community: {
    id: "community",
    badge: "Community · unverified",
    honesty:
      "Unpaid community index from krellbot-community-packs. Not ed25519-signed. Not a paid SKU. Read before install.",
  },
  starter: {
    id: "starter",
    badge: "Starter examples",
    honesty:
      "Shipped read-only starter examples on the Strategies editor. Not the signed catalogue and not community.",
  },
};

/** Closed badge strings used by unit tests for honesty distinction. */
export const SIGNED_CATALOGUE_BADGE = PACK_SOURCES.signed_catalogue.badge;
export const COMMUNITY_BADGE = PACK_SOURCES.community.badge;
export const STARTER_BADGE = PACK_SOURCES.starter.badge;

export function isCommunitySource(source: PackSourceId): boolean {
  return source === "community";
}

export function isSignedCatalogueSource(source: PackSourceId): boolean {
  return source === "signed_catalogue";
}
