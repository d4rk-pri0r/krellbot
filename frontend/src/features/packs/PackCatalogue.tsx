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
  CheckoutResult,
  PackInstallResult,
  PacksClient,
} from "./client";
import { PackLibraryHttpError } from "./client";
import {
  isLaunchPackFamilySku,
  LAUNCH_PACK_FAMILY_HONESTY,
  LAUNCH_PACK_FAMILY_SKU,
} from "./launchPackFamily";
import { PACK_SOURCES, SIGNED_CATALOGUE_BADGE } from "./packSources";
import "./PackCatalogue.signal.css";

export type PackCatalogueProps = {
  client: PacksClient;
  /** Fired after a successful install so the library can refresh. */
  onInstalled?: (result: PackInstallResult) => void;
  /** Fired after paid checkout so entitlements / library can refresh. */
  onCheckoutPaid?: (result: CheckoutResult) => void;
};

function failureMessage(err: unknown): string {
  if (err instanceof PackLibraryHttpError) {
    return `Catalogue failed (HTTP ${err.status})`;
  }
  return "Catalogue failed";
}

function checkoutFailureMessage(err: unknown): string {
  if (err instanceof PackLibraryHttpError) {
    return `Checkout failed (HTTP ${err.status})`;
  }
  return "Checkout failed";
}

export function PackCatalogue({
  client,
  onInstalled,
  onCheckoutPaid,
}: PackCatalogueProps): JSX.Element {
  const [document, setDocument] = useState<CatalogueDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rowFeedback, setRowFeedback] = useState<Record<string, string>>({});
  const requestSeq = useRef(0);
  const actionSeq = useRef(0);

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
      const seq = (actionSeq.current += 1);
      setBusyId(pack.id);
      setRowFeedback((prev) => {
        const next = { ...prev };
        delete next[pack.id];
        return next;
      });
      client
        .install(pack.id)
        .then((result) => {
          if (seq !== actionSeq.current) return;
          if (result.ok) {
            const bucket = result.pack?.bucket ?? "download_pending";
            const version = result.pack?.version ?? pack.version ?? "—";
            setRowFeedback((prev) => ({
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
          setRowFeedback((prev) => ({
            ...prev,
            [pack.id]: detail,
          }));
        })
        .catch((err: unknown) => {
          if (seq !== actionSeq.current) return;
          setRowFeedback((prev) => ({
            ...prev,
            [pack.id]: failureMessage(err),
          }));
        })
        .finally(() => {
          if (seq === actionSeq.current) {
            setBusyId(null);
          }
        });
    },
    [client, onInstalled],
  );

  const handleCheckout = useCallback(
    (pack: CataloguePack): void => {
      const seq = (actionSeq.current += 1);
      setBusyId(pack.id);
      setRowFeedback((prev) => {
        const next = { ...prev };
        delete next[pack.id];
        return next;
      });
      client
        .startCheckout(pack.id)
        .then((result) => {
          if (seq !== actionSeq.current) return;
          if (result.status === "paid") {
            setRowFeedback((prev) => ({
              ...prev,
              [pack.id]: "Entitled · entitlements refreshed",
            }));
            onCheckoutPaid?.(result);
            return;
          }
          const detail =
            result.status === "failed"
              ? "Checkout refused. Trading and export stay available."
              : result.status === "refused"
                ? result.message === "sku not paid"
                  ? "Checkout is only for paid catalogue SKUs."
                  : "Checkout refused."
                : "Checkout unreachable. Trading and export stay available.";
          setRowFeedback((prev) => ({
            ...prev,
            [pack.id]: detail,
          }));
        })
        .catch((err: unknown) => {
          if (seq !== actionSeq.current) return;
          setRowFeedback((prev) => ({
            ...prev,
            [pack.id]: checkoutFailureMessage(err),
          }));
        })
        .finally(() => {
          if (seq === actionSeq.current) {
            setBusyId(null);
          }
        });
    },
    [client, onCheckoutPaid],
  );

  const packs = document?.packs ?? [];
  const hasLaunchFamily = packs.some((pack) => isLaunchPackFamilySku(pack.id));

  return (
    <section
      className="kbot-pack-catalogue"
      role="region"
      aria-label="Signed Strategy Pack catalogue"
      data-testid="pack-catalogue-panel"
      data-pack-source="signed_catalogue"
    >
      <header className="kbot-pack-catalogue__head">
        <h2 className="kbot-pack-catalogue__title">Browse signed catalogue</h2>
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
      <p
        className="kbot-pack-catalogue__source"
        data-testid="pack-catalogue-source-badge"
      >
        {SIGNED_CATALOGUE_BADGE}
      </p>
      <p className="kbot-pack-catalogue__helper" data-testid="pack-catalogue-honesty">
        {PACK_SOURCES.signed_catalogue.honesty} One-click install queues a free
        pack into the local library. Paid SKUs use Checkout to start a local
        entitlement (fake processor in CI). This lane is not the community
        index and not starter examples.
      </p>
      {hasLaunchFamily ? (
        <p
          className="kbot-pack-catalogue__helper"
          data-testid="pack-catalogue-launch-family-honesty"
        >
          {LAUNCH_PACK_FAMILY_HONESTY}
        </p>
      ) : null}
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
            No catalogue packs. Refresh the catalogue or check the signed feed.
          </p>
        ) : (
          <ul className="kbot-pack-catalogue__list" data-testid="pack-catalogue-list">
            {packs.map((pack) => {
              const busy = busyId === pack.id;
              const feedback = rowFeedback[pack.id];
              const isError =
                feedback !== undefined &&
                !feedback.startsWith("Installed") &&
                !feedback.startsWith("Entitled");
              const isPaid = pack.tier === "paid";
              const isLaunchFamily = isLaunchPackFamilySku(pack.id);
              return (
                <li
                  key={pack.id}
                  className="kbot-pack-catalogue__row"
                  data-testid={`pack-catalogue-row-${pack.id}`}
                  data-launch-family={isLaunchFamily ? LAUNCH_PACK_FAMILY_SKU : undefined}
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
                        (isPaid ? " kbot-pack-catalogue__tier--paid" : "")
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
                  {isLaunchFamily ? (
                    <p
                      className="kbot-pack-catalogue__description"
                      data-testid={`pack-catalogue-launch-honesty-${pack.id}`}
                    >
                      {LAUNCH_PACK_FAMILY_HONESTY}
                    </p>
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
                    {isPaid ? (
                      <button
                        type="button"
                        className="kbot-pack-catalogue__checkout"
                        data-testid={`pack-catalogue-checkout-${pack.id}`}
                        disabled={busy}
                        aria-disabled={busy}
                        aria-busy={busy}
                        onClick={() => {
                          handleCheckout(pack);
                        }}
                      >
                        {busy ? "Checking out…" : "Checkout"}
                      </button>
                    ) : (
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
                        {busy ? "Installing…" : "Install"}
                      </button>
                    )}
                    {feedback ? (
                      <p
                        className={
                          isError
                            ? "kbot-pack-catalogue__error"
                            : "kbot-pack-catalogue__status"
                        }
                        role={isError ? "alert" : "status"}
                        data-testid={
                          isPaid
                            ? `pack-catalogue-checkout-status-${pack.id}`
                            : `pack-catalogue-install-status-${pack.id}`
                        }
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
