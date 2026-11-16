import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type JSX,
} from "react";
import type {
  CatalogueDocument,
  CataloguePack,
  PackInstallResult,
  PacksClient,
} from "./client";
import { PackLibraryHttpError } from "./client";
import "./PackCatalogue.signal.css";

export type PackCatalogueProps = {
  client: PacksClient;
  /** Fired after a successful install so the library can refresh. */
  onInstalled?: (result: PackInstallResult) => void;
};

function failureMessage(err: unknown): string {
  if (err instanceof PackLibraryHttpError) {
    return `Catalogue failed (HTTP ${err.status})`;
  }
  return "Catalogue failed";
}

function installLabel(tier: CataloguePack["tier"]): string {
  return tier === "paid" ? "Install (paid)" : "Install";
}

export function PackCatalogue({ client, onInstalled }: PackCatalogueProps): JSX.Element {
  const [document, setDocument] = useState<CatalogueDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [installFeedback, setInstallFeedback] = useState<Record<string, string>>({});
  const requestSeq = useRef(0);
  const installSeq = useRef(0);

  const load = useCallback((): void => {
    const seq = (requestSeq.current += 1);
    setRefreshing(true);
    setError(null);
    client
      .listCatalogue()
      .then((next) => {
        if (seq !== requestSeq.current) return;
        setDocument(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (seq !== requestSeq.current) return;
        setError(failureMessage(err));
      })
      .finally(() => {
        if (seq === requestSeq.current) {
          setRefreshing(false);
        }
      });
  }, [client]);

  useEffect(() => {
    load();
  }, [load]);

  const handleInstall = useCallback(
    (pack: CataloguePack): void => {
      const seq = (installSeq.current += 1);
      setInstallingId(pack.id);
      setInstallFeedback((prev) => {
        const next = { ...prev };
        delete next[pack.id];
        return next;
      });
      client
        .install(pack.id)
        .then((result) => {
          if (seq !== installSeq.current) return;
          if (result.ok) {
            const bucket = result.pack?.bucket ?? "download_pending";
            const version = result.pack?.version ?? pack.version ?? "—";
            setInstallFeedback((prev) => ({
              ...prev,
              [pack.id]: `Installed · ${bucket} · ${version}`,
            }));
            onInstalled?.(result);
            return;
          }
          const detail =
            result.code === "activation_required"
              ? "Activation required for paid packs."
              : (result.message ?? "Install refused");
          setInstallFeedback((prev) => ({
            ...prev,
            [pack.id]: detail,
          }));
        })
        .catch((err: unknown) => {
          if (seq !== installSeq.current) return;
          setInstallFeedback((prev) => ({
            ...prev,
            [pack.id]: failureMessage(err),
          }));
        })
        .finally(() => {
          if (seq === installSeq.current) {
            setInstallingId(null);
          }
        });
    },
    [client, onInstalled],
  );

  const packs = document?.packs ?? [];

  return (
    <section
      className="kbot-pack-catalogue"
      role="region"
      aria-label="Strategy Pack catalogue"
      data-testid="pack-catalogue-panel"
    >
      <header className="kbot-pack-catalogue__head">
        <h2 className="kbot-pack-catalogue__title">Browse catalogue</h2>
        <button
          type="button"
          className="kbot-pack-catalogue__refresh"
          data-testid="pack-catalogue-refresh"
          disabled={refreshing}
          aria-disabled={refreshing}
          aria-busy={refreshing}
          onClick={load}
        >
          {refreshing ? "Refreshing…" : "Refresh catalogue"}
        </button>
      </header>
      <p className="kbot-pack-catalogue__helper">
        Signed free and paid Strategy Packs. One-click install queues a free
        pack into the local library (bucket and version shown below). Paid
        packs need activation redeem before install.
      </p>
      {document !== null ? (
        <p className="kbot-pack-catalogue__meta" data-testid="pack-catalogue-version">
          catalogue {document.catalogue_version}
          {document.updated ? ` · updated ${document.updated}` : ""}
        </p>
      ) : null}

      <div className="kbot-pack-catalogue__body">
        {document === null && error === null ? (
          <p className="kbot-pack-catalogue__loading" data-testid="pack-catalogue-loading">
            Loading catalogue…
          </p>
        ) : document === null ? (
          <p className="kbot-pack-catalogue__failed" data-testid="pack-catalogue-failed">
            Catalogue not loaded.
          </p>
        ) : packs.length === 0 ? (
          <p className="kbot-pack-catalogue__empty" data-testid="pack-catalogue-empty">
            No catalogue packs.
          </p>
        ) : (
          <ul className="kbot-pack-catalogue__list" data-testid="pack-catalogue-list">
            {packs.map((pack) => {
              const busy = installingId === pack.id;
              const feedback = installFeedback[pack.id];
              const isError =
                feedback !== undefined &&
                !feedback.startsWith("Installed");
              return (
                <li
                  key={pack.id}
                  className="kbot-pack-catalogue__row"
                  data-testid={`pack-catalogue-row-${pack.id}`}
                >
                  <div className="kbot-pack-catalogue__row-head">
                    <span
                      className="kbot-pack-catalogue__label"
                      data-testid={`pack-catalogue-label-${pack.id}`}
                    >
                      {pack.label ?? pack.id}
                    </span>
                    <span
                      className={
                        "kbot-pack-catalogue__tier" +
                        (pack.tier === "paid" ? " kbot-pack-catalogue__tier--paid" : "")
                      }
                      data-testid={`pack-catalogue-tier-${pack.id}`}
                    >
                      {pack.tier}
                    </span>
                  </div>
                  <span
                    className="kbot-pack-catalogue__id"
                    data-testid={`pack-catalogue-id-${pack.id}`}
                  >
                    {pack.id}
                  </span>
                  {pack.description ? (
                    <p className="kbot-pack-catalogue__description">{pack.description}</p>
                  ) : null}
                  <dl className="kbot-pack-catalogue__row-meta">
                    <div>
                      <dt>Version</dt>
                      <dd data-testid={`pack-catalogue-version-${pack.id}`}>
                        {pack.version ?? "—"}
                      </dd>
                    </div>
                  </dl>
                  <div className="kbot-pack-catalogue__actions">
                    <button
                      type="button"
                      className="kbot-pack-catalogue__install"
                      data-testid={`pack-catalogue-install-${pack.id}`}
                      disabled={busy}
                      aria-disabled={busy}
                      aria-busy={busy}
                      onClick={() => {
                        handleInstall(pack);
                      }}
                    >
                      {busy ? "Installing…" : installLabel(pack.tier)}
                    </button>
                    {feedback ? (
                      <p
                        className={
                          isError
                            ? "kbot-pack-catalogue__error"
                            : "kbot-pack-catalogue__status"
                        }
                        role={isError ? "alert" : "status"}
                        data-testid={`pack-catalogue-install-status-${pack.id}`}
                      >
                        {feedback}
                      </p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {error !== null ? (
          <p
            className="kbot-pack-catalogue__error"
            role="alert"
            data-testid="pack-catalogue-error"
          >
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
