import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import type { PackLibraryClient, PackRow } from "./client";
import { PackLibraryHttpError } from "./client";

export type { PackLibraryClient, PackRow, PackRollbackResult } from "./client";

export type PackLibraryProps = {
  client: PackLibraryClient;
};

const BUCKET_LABELS: Record<PackRow["bucket"], string> = {
  deployed: "Deployed",
  configured: "Configured",
  installed: "Installed",
  download_pending: "Download pending",
  purchased: "Purchased",
};

const COPY_FEEDBACK_MS = 2000;

function bucketLabel(bucket: PackRow["bucket"]): string {
  return BUCKET_LABELS[bucket] ?? bucket;
}

function failureMessage(err: unknown): string {
  if (err instanceof PackLibraryHttpError) {
    return `Pack library failed (HTTP ${err.status})`;
  }
  return "Pack library failed";
}

export function PackLibrary({ client }: PackLibraryProps): JSX.Element {
  const [rows, setRows] = useState<PackRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const requestSeq = useRef(0);
  const copyTimer = useRef<number | null>(null);

  useEffect(() => {
    const seq = (requestSeq.current += 1);
    let cancelled = false;
    client
      .listInstalled()
      .then((next) => {
        if (cancelled || seq !== requestSeq.current) return;
        setRows(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled || seq !== requestSeq.current) return;
        // Truthful failure: the refusal is surfaced, never masked as an
        // empty library, and there is no automatic retry.
        setError(failureMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    return () => {
      if (copyTimer.current !== null) {
        window.clearTimeout(copyTimer.current);
      }
    };
  }, []);

  const handleRefresh = useCallback((): void => {
    const seq = (requestSeq.current += 1);
    setRefreshing(true);
    setError(null);
    client
      .listInstalled()
      .then((next) => {
        if (seq !== requestSeq.current) return;
        setRows(next);
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

  const handleCopy = useCallback((pack_id: string): void => {
    const settle = (): void => {
      setCopiedId(pack_id);
      if (copyTimer.current !== null) {
        window.clearTimeout(copyTimer.current);
      }
      copyTimer.current = window.setTimeout(() => {
        setCopiedId(null);
      }, COPY_FEEDBACK_MS);
    };
    const clipboard = navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") {
      // No clipboard API (e.g. jsdom): still show the pack_id, claim
      // nothing about a copy that could not happen.
      return;
    }
    void clipboard.writeText(pack_id).then(settle, () => {
      // Copy refused (permissions): report nothing false.
    });
  }, []);

  return (
    <section
      className="kbot-pack-library"
      role="region"
      aria-label="Pack library"
      data-testid="pack-library-panel"
    >
      <header className="kbot-pack-library__head">
        <h2 className="kbot-pack-library__title">Pack library</h2>
        <button
          type="button"
          className="kbot-pack-library__refresh"
          data-testid="pack-library-refresh"
          disabled={refreshing}
          aria-disabled={refreshing}
          onClick={handleRefresh}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      <div className="kbot-pack-library__body">
        {rows === null && error === null ? (
          <p className="kbot-pack-library__loading" data-testid="pack-library-loading">
            Loading…
          </p>
        ) : rows === null ? (
          <p className="kbot-pack-library__failed" data-testid="pack-library-failed">
            Not loaded.
          </p>
        ) : rows.length === 0 ? (
          <p className="kbot-pack-library__empty" data-testid="pack-library-empty">
            No packs.
          </p>
        ) : (
          <ul className="kbot-pack-library__list" data-testid="pack-library-list">
            {rows.map((row) => (
              <PackRowItem
                key={row.pack_id}
                row={row}
                copied={copiedId === row.pack_id}
                onCopy={() => {
                  handleCopy(row.pack_id);
                }}
              />
            ))}
          </ul>
        )}
        {error !== null ? (
          <p
            className="kbot-pack-library__error"
            role="alert"
            data-testid="pack-library-error"
          >
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}

type PackRowItemProps = {
  row: PackRow;
  copied: boolean;
  onCopy: () => void;
};

function PackRowItem({ row, copied, onCopy }: PackRowItemProps): JSX.Element {
  return (
    <li
      className="kbot-pack-library__row"
      data-testid={`pack-library-row-${row.pack_id}`}
    >
      <button
        type="button"
        className="kbot-pack-library__row-copy"
        data-testid={`pack-library-copy-${row.pack_id}`}
        aria-label={`Copy pack_id ${row.pack_id}`}
        title="Copy pack_id"
        onClick={onCopy}
      >
        <span
          className={`kbot-pack-library__bucket kbot-pack-library__bucket--${row.bucket}`}
          data-testid={`pack-library-bucket-${row.pack_id}`}
        >
          {row.bucket} <span className="kbot-pack-library__bucket-label">({bucketLabel(row.bucket)})</span>
        </span>
        <span className="kbot-pack-library__id" data-testid={`pack-library-id-${row.pack_id}`}>
          {row.pack_id}
        </span>
        <span className="kbot-pack-library__version" data-testid={`pack-library-version-${row.pack_id}`}>
          {row.version ?? "—"}
        </span>
        <span
          className="kbot-pack-library__permissions"
          data-testid={`pack-library-permissions-${row.pack_id}`}
        >
          {row.permissions.length > 0 ? row.permissions.join(", ") : "no permissions"}
        </span>
        <span
          className="kbot-pack-library__rollback-ref"
          data-testid={`pack-library-rollback-ref-${row.pack_id}`}
        >
          {row.rollback_ref !== null ? row.rollback_ref.prior_revision_id : "—"}
        </span>
        <span
          className="kbot-pack-library__copy-feedback"
          data-testid={`pack-library-copy-feedback-${row.pack_id}`}
        >
          {copied ? "Copied" : "Copy"}
        </span>
      </button>
    </li>
  );
}
