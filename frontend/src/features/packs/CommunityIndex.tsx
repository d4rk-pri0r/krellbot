import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type JSX,
} from "react";
import type {
  CommunityIndexDocument,
  CommunityIndexPack,
  CommunityInstallResult,
  PacksClient,
} from "./client";
import { PackLibraryHttpError } from "./client";
import { COMMUNITY_BADGE, PACK_SOURCES } from "./packSources";
import "./CommunityIndex.signal.css";

export type CommunityIndexProps = {
  client: PacksClient;
  /** Fired after a successful community install so the library can refresh. */
  onInstalled?: (result: CommunityInstallResult) => void;
};

function failureMessage(err: unknown): string {
  if (err instanceof PackLibraryHttpError) {
    return `Community index failed (HTTP ${err.status})`;
  }
  return "Community index failed";
}

/** Closed, user-facing copy for typed community install refusal codes. */
export function communityInstallFailureCopy(
  code: string | undefined,
  fallback?: string,
): string {
  switch (code) {
    case "foreign_url":
      return "Foreign URL refused — pack host is not allow-listed.";
    case "payload_refused":
      return "Payload refused — oversized body or validate fail.";
    case "pack_not_found":
      return "Community pack not found in the index.";
    case "index_rejected":
      return "Community index rejected.";
    case "unreachable":
      return "Community pack unreachable.";
    default:
      return fallback ?? "Community install refused.";
  }
}

/**
 * Community index browse + one-click install into ``packs/community/``.
 * Never claims ed25519 / paid SKU. Contract: KRELL-SIGNAL-20261010.
 */
export function CommunityIndex({
  client,
  onInstalled,
}: CommunityIndexProps): JSX.Element {
  const [document, setDocument] = useState<CommunityIndexDocument | null>(null);
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
      .listCommunityIndex()
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
    (pack: CommunityIndexPack): void => {
      const seq = (installSeq.current += 1);
      setInstallingId(pack.id);
      setInstallFeedback((prev) => {
        const next = { ...prev };
        delete next[pack.id];
        return next;
      });
      client
        .installCommunity(pack.id)
        .then((result) => {
          if (seq !== installSeq.current) return;
          if (result.ok) {
            const version = result.pack?.version ?? "—";
            const author = result.pack?.author ?? pack.author ?? "—";
            const path = result.path ?? "packs/community/";
            setInstallFeedback((prev) => ({
              ...prev,
              [pack.id]: `Installed · ${result.pack?.id ?? pack.id} · ${version} · author ${author} · ${path}`,
            }));
            onInstalled?.(result);
            return;
          }
          setInstallFeedback((prev) => ({
            ...prev,
            [pack.id]: communityInstallFailureCopy(result.code, result.message),
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
  const meta = PACK_SOURCES.community;

  return (
    <section
      className="kbot-community-index"
      role="region"
      aria-label="Community pack index"
      data-testid="community-index-panel"
      data-pack-source="community"
    >
      <header className="kbot-community-index__head">
        <h2 className="kbot-community-index__title">Community index</h2>
        <button
          type="button"
          className="kbot-community-index__refresh"
          data-testid="community-index-refresh"
          disabled={refreshing}
          aria-disabled={refreshing}
          aria-busy={refreshing}
          onClick={load}
        >
          {refreshing ? "Refreshing…" : "Refresh index"}
        </button>
      </header>
      <p
        className="kbot-community-index__source"
        data-testid="community-index-source-badge"
      >
        {COMMUNITY_BADGE}
      </p>
      <p className="kbot-community-index__helper" data-testid="community-index-honesty">
        {meta.honesty} One-click install writes under packs/community/ after
        allow-list checks.
      </p>
      {document !== null ? (
        <p className="kbot-community-index__meta" data-testid="community-index-meta">
          {document.index_url ? `index ${document.index_url}` : "index unavailable"}
          {document.fetched_at ? ` · fetched ${document.fetched_at}` : ""}
        </p>
      ) : null}

      <div className="kbot-community-index__body">
        {document === null && error === null ? (
          <p className="kbot-community-index__loading" data-testid="community-index-loading">
            Loading community index…
          </p>
        ) : document === null ? (
          <p className="kbot-community-index__failed" data-testid="community-index-failed">
            Community index not loaded.
          </p>
        ) : packs.length === 0 ? (
          <p className="kbot-community-index__empty" data-testid="community-index-empty">
            No community packs in the index.
          </p>
        ) : (
          <ul className="kbot-community-index__list" data-testid="community-index-list">
            {packs.map((pack) => {
              const busy = installingId === pack.id;
              const feedback = installFeedback[pack.id];
              const isError =
                feedback !== undefined && !feedback.startsWith("Installed");
              return (
                <li
                  key={pack.id}
                  className="kbot-community-index__row"
                  data-testid={`community-index-row-${pack.id}`}
                  data-pack-source="community"
                >
                  <div className="kbot-community-index__row-head">
                    <span
                      className="kbot-community-index__label"
                      data-testid={`community-index-label-${pack.id}`}
                    >
                      {pack.label ?? pack.id}
                    </span>
                    <span
                      className="kbot-community-index__source"
                      data-testid={`community-index-source-${pack.id}`}
                    >
                      {COMMUNITY_BADGE}
                    </span>
                  </div>
                  <span
                    className="kbot-community-index__id"
                    data-testid={`community-index-id-${pack.id}`}
                  >
                    {pack.id}
                  </span>
                  {pack.author ? (
                    <span
                      className="kbot-community-index__author"
                      data-testid={`community-index-author-${pack.id}`}
                    >
                      author {pack.author}
                    </span>
                  ) : null}
                  <div className="kbot-community-index__actions">
                    <button
                      type="button"
                      className="kbot-community-index__install"
                      data-testid={`community-index-install-${pack.id}`}
                      disabled={busy}
                      aria-disabled={busy}
                      aria-busy={busy}
                      onClick={() => {
                        handleInstall(pack);
                      }}
                    >
                      {busy ? "Installing…" : "Install"}
                    </button>
                    {feedback ? (
                      <p
                        className={
                          isError
                            ? "kbot-community-index__error"
                            : "kbot-community-index__status"
                        }
                        role={isError ? "alert" : "status"}
                        data-testid={`community-index-install-status-${pack.id}`}
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
            className="kbot-community-index__error"
            role="alert"
            data-testid="community-index-error"
          >
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
