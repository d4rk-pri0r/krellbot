import { useCallback, useState, type JSX } from "react";
import { PackCatalogue } from "./PackCatalogue";
import { PackLibrary } from "./PackLibrary";
import type { PackInstallResult, PacksClient } from "./client";
import "./PacksView.signal.css";

export type PacksViewProps = {
  client: PacksClient;
};

/**
 * First-class Packs destination: browse the signed catalogue, one-click
 * install free packs, and show the local library bucket/version.
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
          Browse the signed catalogue and install into the local library. Free
          and user-authored strategies work without a paid account. Bucket and
          version come from the workstation — never invented.
        </p>
      </header>
      <PackCatalogue client={client} onInstalled={handleInstalled} />
      <PackLibrary key={libraryEpoch} client={client} />
    </div>
  );
}
