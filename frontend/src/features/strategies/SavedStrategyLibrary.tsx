import "./SavedStrategyLibrary.signal.css";
import { useEffect, useMemo, useState, type JSX } from "react";
import type {
  LibraryClient,
  OwnedDraftSummary,
} from "./libraryClient";
import { summarizeDraftState } from "./draftStateLabel";
import { RevisionCompare } from "./RevisionCompare";

export type {
  LibraryClient,
  OwnedDraftSummary,
  OwnedRevisionBytes,
} from "./libraryClient";

export type SavedStrategyLibraryProps = {
  client: LibraryClient;
  /** Host loads the fetched bytes into the Editor's revision state. */
  onReopen: (summary: OwnedDraftSummary, bytes: string) => void;
  /** Host starts a fresh, empty owned draft in the existing Editor. */
  onNewStrategy?: () => void;
  /** Host seeds a new draft from a copy of this owned revision's bytes. */
  onCopyAsNew?: (summary: OwnedDraftSummary, bytes: string) => void;
};

type LoadPhase = "loading" | "ready" | "error";

type StrategyGroup = {
  key: string;
  heading: string;
  revisions: OwnedDraftSummary[];
};

function rowTitle(row: OwnedDraftSummary): string {
  return row.label || row.id || row.strategy_id || "(untitled)";
}

function displayValue(value: string, placeholder: string): string {
  return value || placeholder;
}

/** Case-insensitive local match over the identity fields the rows carry. */
function matchesQuery(row: OwnedDraftSummary, query: string): boolean {
  const haystack = [
    row.label,
    row.id,
    row.strategy_id,
    row.revision_id,
    row.pair,
    row.timeframe,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function groupByStrategy(
  rows: ReadonlyArray<OwnedDraftSummary>,
): StrategyGroup[] {
  const groups: StrategyGroup[] = [];
  const byKey = new Map<string, StrategyGroup>();
  for (const row of rows) {
    const key = row.strategy_id || row.id || row.revision_id;
    const heading = row.strategy_id || row.id || "(untitled strategy)";
    let group = byKey.get(key);
    if (!group) {
      group = { key, heading, revisions: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.revisions.push(row);
  }
  return groups;
}

export function SavedStrategyLibrary({
  client,
  onReopen,
  onNewStrategy,
  onCopyAsNew,
}: SavedStrategyLibraryProps): JSX.Element {
  const [rows, setRows] = useState<ReadonlyArray<OwnedDraftSummary>>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [reopenError, setReopenError] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [openingRevision, setOpeningRevision] = useState<string | null>(null);
  const [compareRow, setCompareRow] = useState<OwnedDraftSummary | null>(null);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | OwnedDraftSummary["state"]>("all");

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setError(null);
    client
      .listOwned()
      .then((owned) => {
        if (cancelled) {
          return;
        }
        setRows(owned);
        setPhase("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        // Empty-on-error: never render fabricated rows.
        setRows([]);
        setError(err instanceof Error ? err.message : String(err));
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const trimmedQuery = query.trim().toLowerCase();
  const filteredRows = useMemo(() => {
    const stateRows = stateFilter === "all"
      ? rows
      : rows.filter((row) => row.state === stateFilter);
    if (trimmedQuery === "") {
      return stateRows;
    }
    return stateRows.filter((row) => matchesQuery(row, trimmedQuery));
  }, [rows, stateFilter, trimmedQuery]);
  const groups = useMemo(() => groupByStrategy(filteredRows), [filteredRows]);

  const handleReopen = (summary: OwnedDraftSummary): void => {
    if (openingRevision !== null) {
      return;
    }
    setReopenError(null);
    setOpeningRevision(summary.revision_id);
    client
      .getJson(summary.revision_id)
      .then((loaded) => {
        // Read-only open: the stored revision's state and bytes are
        // never rewritten and nothing is armed here.
        onReopen(summary, loaded.bytes);
      })
      .catch((err: unknown) => {
        setReopenError(
          err instanceof Error ? err.message : String(err),
        );
      })
      .finally(() => {
        setOpeningRevision(null);
      });
  };

  const handleCopyAsNew = (summary: OwnedDraftSummary): void => {
    if (openingRevision !== null) {
      return;
    }
    setCopyError(null);
    setOpeningRevision(summary.revision_id);
    client
      .getJson(summary.revision_id)
      .then((loaded) => {
        // Copy only reads bytes: the origin revision's stored bytes,
        // state and arm/deploy state are never touched, and no save,
        // validate or arm happens here.
        onCopyAsNew?.(summary, loaded.bytes);
      })
      .catch((err: unknown) => {
        setCopyError(
          err instanceof Error ? err.message : String(err),
        );
      })
      .finally(() => {
        setOpeningRevision(null);
      });
  };

  const clearQuery = (): void => {
    setQuery("");
  };

  const searching = trimmedQuery !== "";
  const showInventory = phase === "ready" && rows.length > 0;

  return (
    <section
      className="kbot-strategy-library"
      role="region"
      aria-label="Saved strategy library"
      data-testid="saved-strategy-library"
    >
      <header className="kbot-strategy-library__head">
        <div className="kbot-strategy-library__heading">
          <h2 className="kbot-strategy-library__title">
            Saved strategy library
          </h2>
          <p className="kbot-strategy-library__intro">
            Revisions saved in this local workspace. Reopen and Copy as new
            stay read-only until you explicitly save from the editor.
          </p>
        </div>
        {onNewStrategy ? (
          <button
            type="button"
            data-testid="library-new-owned-strategy"
            className="kbot-strategy-library__new"
            onClick={onNewStrategy}
          >
            New owned strategy
          </button>
        ) : null}
      </header>
      {showInventory ? (
        <div className="kbot-strategy-library__toolbar">
          <div className="kbot-strategy-library__search">
            <input
              type="search"
              className="kbot-strategy-library__search-input"
              data-testid="library-search"
              aria-label="Search saved strategies"
              placeholder="Search label, id, pair or timeframe"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  clearQuery();
                }
              }}
            />
            {searching ? (
              <button
                type="button"
                className="kbot-strategy-library__search-clear"
                data-testid="library-search-clear"
                onClick={clearQuery}
              >
                Clear search
              </button>
            ) : null}
          </div>
          <div className="kbot-strategy-library__search">
            <label htmlFor="library-state-filter">State</label>
            <select
              id="library-state-filter"
              data-testid="library-state-filter"
              className="kbot-strategy-library__select kbot-strategy-library__search-input"
              value={stateFilter}
              onChange={(event) => {
                setStateFilter(event.target.value as "all" | OwnedDraftSummary["state"]);
              }}
            >
              <option value="all">All states</option>
              <option value="draft">{summarizeDraftState("draft").label}</option>
              <option value="validated">{summarizeDraftState("validated").label}</option>
              <option value="deployed">{summarizeDraftState("deployed").label}</option>
              <option value="archived">{summarizeDraftState("archived").label}</option>
            </select>
          </div>
          <p
            className="kbot-strategy-library__count"
            data-testid="library-search-count"
            aria-live="polite"
          >
            {filteredRows.length} of {rows.length} saved revisions
          </p>
        </div>
      ) : null}
      {phase === "loading" ? (
        <p
          className="kbot-strategy-library__loading"
          data-testid="library-loading"
        >
          Loading saved strategies…
        </p>
      ) : null}
      {phase === "error" ? (
        <p
          className="kbot-strategy-library__empty"
          data-testid="library-error"
          role="alert"
        >
          No saved strategies to show: {error ?? "list request failed"}
        </p>
      ) : null}
      {phase === "ready" && rows.length === 0 ? (
        <p className="kbot-strategy-library__empty" data-testid="library-empty">
          No saved strategies yet. Save a draft in the editor to build your
          library.
        </p>
      ) : null}
      {showInventory && filteredRows.length === 0 ? (
        <p
          className="kbot-strategy-library__empty"
          data-testid="library-search-empty"
        >
          No saved strategies match “{query.trim()}”. Clear the search
          to see all {rows.length} saved revisions.
        </p>
      ) : null}
      {showInventory && filteredRows.length > 0
        ? groups.map((group) => (
            <section
              key={group.key}
              className="kbot-strategy-library__group"
              aria-label={"Strategy " + group.heading}
            >
              <div className="kbot-strategy-library__group-head">
                <h3 className="kbot-strategy-library__group-title">
                  {group.heading}
                </h3>
                <p className="kbot-strategy-library__group-count">
                  {group.revisions.length === 1
                    ? "1 revision"
                    : group.revisions.length + " revisions"}
                </p>
              </div>
              <ul className="kbot-strategy-library__list">
                {group.revisions.map((row) => {
                  const state = summarizeDraftState(row.state);
                  return (
                    <li
                      key={row.revision_id}
                      className="kbot-strategy-library__row"
                      data-testid="library-row"
                      data-revision-id={row.revision_id}
                      aria-busy={
                        openingRevision === row.revision_id || undefined
                      }
                    >
                      <div className="kbot-strategy-library__row-main">
                        <p className="kbot-strategy-library__row-title">
                          {rowTitle(row)}
                        </p>
                        <p className="kbot-strategy-library__row-meta">
                          <span className="kbot-strategy-library__meta-item">
                            {displayValue(row.pair, "(no pair)")}
                          </span>
                          <span
                            className="kbot-strategy-library__meta-sep"
                            aria-hidden="true"
                          >
                            ·
                          </span>
                          <span className="kbot-strategy-library__meta-item">
                            {displayValue(row.timeframe, "(no timeframe)")}
                          </span>
                        </p>
                        <p
                          className="kbot-strategy-library__row-identity"
                          title={"Revision " + row.revision_id + " saved " + row.created_at}
                        >
                          <span
                            className="kbot-strategy-library__state"
                            data-state={row.state}
                          >
                            {state.label}
                          </span>
                          <span className="kbot-strategy-library__identity-item">
                            {row.strategy_id || row.id || "(unknown strategy)"}
                          </span>
                          <span className="kbot-strategy-library__identity-item">
                            {row.revision_id}
                          </span>
                          <span className="kbot-strategy-library__identity-item">
                            {row.created_at || "(unknown date)"}
                          </span>
                        </p>
                      </div>
                      <div className="kbot-strategy-library__row-actions">
                        <button
                          type="button"
                          className="kbot-strategy-library__reopen"
                          onClick={() => {
                            handleReopen(row);
                          }}
                          disabled={openingRevision !== null}
                        >
                          Reopen
                        </button>
                        <button
                          type="button"
                          className="kbot-strategy-library__compare"
                          data-testid="library-row-compare"
                          onClick={() => {
                            setCompareRow(row);
                          }}
                        >
                          Compare
                        </button>
                        {onCopyAsNew ? (
                          <button
                            type="button"
                            className="kbot-strategy-library__copy"
                            data-testid="library-copy-as-new"
                            onClick={() => {
                              handleCopyAsNew(row);
                            }}
                            disabled={openingRevision !== null}
                          >
                            Copy as new
                          </button>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        : null}
      {compareRow !== null && phase === "ready" ? (
        <RevisionCompare
          client={client}
          rows={rows}
          row={compareRow}
          onClose={() => {
            setCompareRow(null);
          }}
        />
      ) : null}
      {reopenError !== null ? (
        <p
          className="kbot-strategy-library__error"
          role="alert"
          data-testid="library-reopen-error"
        >
          Reopen failed: {reopenError}
        </p>
      ) : null}
      {copyError !== null ? (
        <p
          className="kbot-strategy-library__error"
          role="alert"
          data-testid="library-copy-error"
        >
          Copy as new failed: {copyError}
        </p>
      ) : null}
    </section>
  );
}
