import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type JSX,
} from "react";
import type { CommunityIndexDocument, PacksClient } from "./client";
import { PackLibraryHttpError } from "./client";
import { COMMUNITY_BADGE, PACK_SOURCES } from "./packSources";
import "./CommunityIndex.signal.css";

export type CommunityIndexProps = {
  client: PacksClient;
};

function failureMessage(err: unknown): string {
  if (err instanceof PackLibraryHttpError) {
    return `Community index failed (HTTP ${err.status})`;
  }
  return "Community index failed";
}

/**
 * Browse-only community index with source honesty.
 * Install journey is M17.5 — this panel must never claim ed25519 / paid SKU.
 * Contract: KRELL-SIGNAL-20261010.
 */
export function CommunityIndex({ client }: CommunityIndexProps): JSX.Element {
  const [document, setDocument] = useState<CommunityIndexDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const requestSeq = useRef(0);

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
        {meta.honesty}
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
            {packs.map((pack) => (
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
              </li>
            ))}
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
