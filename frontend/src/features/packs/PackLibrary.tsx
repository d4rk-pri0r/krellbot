import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type JSX,
} from "react";
import type { PackLibraryClient, PackRow } from "./client";
import { PackLibraryHttpError } from "./client";
import "./PackLibrary.signal.css";

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

const ALL_BUCKETS = "all";

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

/**
 * Local, read-only view query over the already-loaded records. Matches the
 * real pack_id, version and permission strings; never fetches or mutates.
 */
function rowMatchesQuery(row: PackRow, query: string): boolean {
  if (query === "") {
    return true;
  }
  const haystacks = [row.pack_id];
  if (row.version !== null) {
    haystacks.push(row.version);
  }
  haystacks.push(...row.permissions);
  return haystacks.some((value) => value.toLowerCase().includes(query));
}

export function PackLibrary({ client }: PackLibraryProps): JSX.Element {
  const [rows, setRows] = useState<PackRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copyErrorId, setCopyErrorId] = useState<string | null>(null);
  const copySeq = useRef(0);
  const [query, setQuery] = useState("");
  const [bucketFilter, setBucketFilter] = useState<string>(ALL_BUCKETS);
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
      copySeq.current += 1;
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
    const seq = (copySeq.current += 1);
    if (copyTimer.current !== null) {
      window.clearTimeout(copyTimer.current);
      copyTimer.current = null;
    }
    setCopiedId(null);
    setCopyErrorId(null);
    const fail = (): void => {
      if (seq === copySeq.current) setCopyErrorId(pack_id);
    };
    const settle = (): void => {
      if (seq !== copySeq.current) return;
      setCopiedId(pack_id);
      copyTimer.current = window.setTimeout(() => {
        if (seq !== copySeq.current) return;
        setCopiedId(null);
        copyTimer.current = null;
      }, COPY_FEEDBACK_MS);
    };
    try {
      const clipboard = navigator.clipboard;
      if (!clipboard || typeof clipboard.writeText !== "function") {
        fail();
        return;
      }
      void clipboard.writeText(pack_id).then(settle, fail);
    } catch {
      fail();
    }
  }, []);

  // Buckets offered for filtering are only those the loaded records actually
  // report; the control never promises products the server did not send.
  const buckets = useMemo(() => {
    if (rows === null) {
      return [] as PackRow["bucket"][];
    }
    const seen = new Set<PackRow["bucket"]>();
    for (const row of rows) {
      seen.add(row.bucket);
    }
    return [...seen];
  }, [rows]);

  const visibleRows = useMemo(() => {
    if (rows === null) {
      return [] as PackRow[];
    }
    const q = query.trim().toLowerCase();
    return rows.filter(
      (row) =>
        (bucketFilter === ALL_BUCKETS || row.bucket === bucketFilter) &&
        rowMatchesQuery(row, q),
    );
  }, [rows, query, bucketFilter]);

  const filtersActive = query.trim() !== "" || bucketFilter !== ALL_BUCKETS;

  const handleClearFilters = useCallback((): void => {
    setQuery("");
    setBucketFilter(ALL_BUCKETS);
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
          aria-busy={refreshing}
          onClick={handleRefresh}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
        {/* Visually hidden polite status: mirrors the in-flight `refreshing`
            truth the button already carries, so AT hears the read in flight. */}
        <p
          data-testid="pack-library-refresh-status"
          role="status"
          aria-live="polite"
          className="kbot-pack-library__refresh-status"
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            padding: 0,
            overflow: "hidden",
            clip: "rect(0 0 0 0)",
            whiteSpace: "nowrap",
          }}
        >
          {refreshing ? "Reading installed packs…" : ""}
        </p>
      </header>

      {rows !== null && rows.length > 0 ? (
        <div className="kbot-pack-library__toolbar">
          <label className="kbot-pack-library__search-label" htmlFor="pack-library-search">
            <span className="kbot-pack-library__search-caption">Search packs</span>
            <input
              id="pack-library-search"
              type="search"
              className="kbot-pack-library__search"
              data-testid="pack-library-search"
              placeholder="pack_id, version or permission"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
            />
          </label>
          <label className="kbot-pack-library__bucket-label" htmlFor="pack-library-bucket">
            <span className="kbot-pack-library__bucket-caption">Filter by bucket</span>
            <select
              id="pack-library-bucket"
              className="kbot-pack-library__bucket-select"
              data-testid="pack-library-bucket-select"
              value={bucketFilter}
              onChange={(event) => {
                setBucketFilter(event.target.value);
              }}
            >
              <option value={ALL_BUCKETS}>All buckets</option>
              {buckets.map((bucket) => (
                <option key={bucket} value={bucket}>
                  {bucket}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="kbot-pack-library__clear"
            data-testid="pack-library-clear-filters"
            disabled={!filtersActive}
            aria-disabled={!filtersActive}
            onClick={handleClearFilters}
          >
            Clear search &amp; filter
          </button>
          <p
            className="kbot-pack-library__count"
            data-testid="pack-library-count"
            aria-live="polite"
          >
            {visibleRows.length} of {rows.length} packs shown
          </p>
        </div>
      ) : null}

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
        ) : visibleRows.length === 0 ? (
          <p
            className="kbot-pack-library__no-matches"
            role="status"
            data-testid="pack-library-no-matches"
          >
            No packs match the current search or bucket filter.
          </p>
        ) : (
          <ul className="kbot-pack-library__list" data-testid="pack-library-list">
            {visibleRows.map((row) => (
              <PackRowItem
                key={row.pack_id}
                row={row}
                copied={copiedId === row.pack_id}
                copyFailed={copyErrorId === row.pack_id}
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
  copyFailed: boolean;
  onCopy: () => void;
};

function PackRowItem({ row, copied, copyFailed, onCopy }: PackRowItemProps): JSX.Element {
  const copyErrorId = useId();
  const priorRevision =
    row.rollback_ref !== null ? row.rollback_ref.prior_revision_id : "—";
  return (
    <li
      className="kbot-pack-library__row"
      data-testid={`pack-library-row-${row.pack_id}`}
    >
      <div className="kbot-pack-library__row-head">
        <span
          className={`kbot-pack-library__bucket kbot-pack-library__bucket--${row.bucket}`}
          data-testid={`pack-library-bucket-${row.pack_id}`}
        >
          {row.bucket} <span className="kbot-pack-library__bucket-label">({bucketLabel(row.bucket)})</span>
        </span>
        <span className="kbot-pack-library__id" data-testid={`pack-library-id-${row.pack_id}`}>
          {row.pack_id}
        </span>
        <button
          type="button"
          className="kbot-pack-library__row-copy"
          data-testid={`pack-library-copy-${row.pack_id}`}
          aria-label={`Copy pack_id ${row.pack_id}`}
          aria-describedby={copyFailed ? copyErrorId : undefined}
          title="Copy pack_id"
          onClick={onCopy}
        >
          <span
            className="kbot-pack-library__copy-feedback"
            data-testid={`pack-library-copy-feedback-${row.pack_id}`}
          >
            {copied ? "Copied" : "Copy"}
          </span>
        </button>
      </div>
      {copyFailed ? (
        <p id={copyErrorId} className="kbot-pack-library__error" role="alert">
          Could not copy pack_id {row.pack_id}. Clipboard access is unavailable or denied. Try Copy again.
        </p>
      ) : null}
      <dl className="kbot-pack-library__row-meta">
        <div className="kbot-pack-library__meta">
          <dt className="kbot-pack-library__meta-term">Version</dt>
          <dd
            className="kbot-pack-library__meta-value kbot-pack-library__version"
            data-testid={`pack-library-version-${row.pack_id}`}
          >
            {row.version ?? "—"}
          </dd>
        </div>
        <div className="kbot-pack-library__meta kbot-pack-library__meta--wide">
          <dt className="kbot-pack-library__meta-term">Permissions</dt>
          <dd
            className="kbot-pack-library__meta-value kbot-pack-library__permissions"
            data-testid={`pack-library-permissions-${row.pack_id}`}
          >
            {row.permissions.length > 0 ? row.permissions.join(", ") : "no permissions"}
          </dd>
        </div>
        <div className="kbot-pack-library__meta kbot-pack-library__meta--wide">
          <dt className="kbot-pack-library__meta-term">Prior revision</dt>
          <dd
            className="kbot-pack-library__meta-value kbot-pack-library__rollback-ref"
            data-testid={`pack-library-rollback-ref-${row.pack_id}`}
          >
            {priorRevision}
          </dd>
        </div>
      </dl>
    </li>
  );
}
