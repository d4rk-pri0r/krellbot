import { useEffect, useState, type JSX } from "react";
import type { PackLibraryClient, PackRollbackResult, PackRow } from "./client";

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

function bucketLabel(bucket: PackRow["bucket"]): string {
  return BUCKET_LABELS[bucket] ?? bucket;
}

export function PackLibrary({ client }: PackLibraryProps): JSX.Element {
  const [rows, setRows] = useState<PackRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client
      .listInstalled()
      .then((next) => {
        if (cancelled) return;
        setRows(next);
      })
      .catch(() => {
        if (cancelled) return;
        // Empty list on failure: the library is presentation-only; the
        // user can re-load. No invented performance numbers, no
        // fabricated catalog stats.
        setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const handleRollback = async (pack_id: string): Promise<void> => {
    setError(null);
    let result: PackRollbackResult;
    try {
      result = await client.rollback(pack_id);
    } catch {
      setError(`Rollback failed for ${pack_id}`);
      return;
    }
    if (!result.ok) {
      setError(result.message ?? `Rollback refused for ${pack_id}`);
    }
  };

  return (
    <section
      className="kbot-pack-library"
      role="region"
      aria-label="Pack library"
      data-testid="pack-library-panel"
    >
      <header className="kbot-pack-library__head">
        <h2 className="kbot-pack-library__title">Pack library</h2>
      </header>
      <div className="kbot-pack-library__body">
        {rows === null ? (
          <p className="kbot-pack-library__loading" data-testid="pack-library-loading">
            Loading…
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
                onRollback={() => {
                  void handleRollback(row.pack_id);
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
  onRollback: () => void;
};

function PackRowItem({ row, onRollback }: PackRowItemProps): JSX.Element {
  const isDeployed = row.bucket === "deployed";
  const canRollback = isDeployed && row.rollback_ref !== null;
  return (
    <li
      className="kbot-pack-library__row"
      data-testid={`pack-library-row-${row.pack_id}`}
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
      {isDeployed ? (
        <button
          type="button"
          className="kbot-pack-library__rollback"
          data-testid={`pack-library-rollback-${row.pack_id}`}
          disabled={!canRollback}
          aria-disabled={!canRollback}
          onClick={onRollback}
        >
          Rollback
        </button>
      ) : null}
    </li>
  );
}
