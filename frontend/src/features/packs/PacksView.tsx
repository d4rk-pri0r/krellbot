import { useCallback, useState, type JSX } from "react";
import { CommunityIndex } from "./CommunityIndex";
import { PackCatalogue } from "./PackCatalogue";
import { PackLibrary } from "./PackLibrary";
import type { PackInstallResult, PacksClient } from "./client";
import { PACK_SOURCES } from "./packSources";
import "./PacksView.signal.css";

export type PacksViewProps = {
  client: PacksClient;
};

/**
 * First-class Packs destination: signed catalogue, community index honesty,
 * and local library. Starters live on Strategies — never conflated here.
 * Contract: KRELL-SIGNAL-20261010.
 */
export function PacksView({ client }: PacksViewProps): JSX.Element {
  // Bumping the key remounts PackLibrary so it re-reads after install.
  const [libraryEpoch, setLibraryEpoch] = useState(0);

  const handleInstalled = useCallback((_result: PackInstallResult): void => {
    setLibraryEpoch((value) => value + 1);
  }, []);

  return (
    <div className="kbot-packs-view" data-testid="packs-view">
      <header className="kbot-packs-view__head">
        <h1 className="kbot-packs-view__title">Packs</h1>
        <p className="kbot-packs-view__lede">
          Three pack lanes stay distinct: the ed25519-signed catalogue, the
          unpaid community index, and starter examples on Strategies. Community
          entries are never paid SKUs.
        </p>
        <ul
          className="kbot-packs-view__sources"
          data-testid="packs-source-legend"
          aria-label="Pack source lanes"
        >
          <li data-testid="packs-source-legend-signed_catalogue">
            <span className="kbot-packs-view__source-badge kbot-packs-view__source-badge--signed">
              {PACK_SOURCES.signed_catalogue.badge}
            </span>
            <span className="kbot-packs-view__source-copy">
              {PACK_SOURCES.signed_catalogue.honesty}
            </span>
          </li>
          <li data-testid="packs-source-legend-community">
            <span className="kbot-packs-view__source-badge kbot-packs-view__source-badge--community">
              {PACK_SOURCES.community.badge}
            </span>
            <span className="kbot-packs-view__source-copy">
              {PACK_SOURCES.community.honesty}
            </span>
          </li>
          <li data-testid="packs-source-legend-starter">
            <span className="kbot-packs-view__source-badge kbot-packs-view__source-badge--starter">
              {PACK_SOURCES.starter.badge}
            </span>
            <span className="kbot-packs-view__source-copy">
              {PACK_SOURCES.starter.honesty}
            </span>
          </li>
        </ul>
      </header>
      <PackCatalogue client={client} onInstalled={handleInstalled} />
      <CommunityIndex client={client} />
      <PackLibrary key={libraryEpoch} client={client} />
    </div>
  );
}
