import "./SavedStrategyLibrary.signal.css";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
} from "react";
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
  const [reopeningRevision, setOpeningRevision] = useState<string | null>(null);
  const [copyingRevisions, setCopyingRevisions] = useState<string[]>([]);
  const openingRevision = reopeningRevision ?? copyingRevisions[0] ?? null;
  const [compareRow, setCompareRow] = useState<OwnedDraftSummary | null>(null);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | OwnedDraftSummary["state"]>("all");
  const searchRef = useRef<HTMLInputElement | null>(null);
  const stateFilterRef = useRef<HTMLSelectElement | null>(null);

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
    if (reopeningRevision !== null || copyingRevisions.includes(summary.revision_id)) {
      return;
    }
    setCopyError(null);
    setCopyingRevisions((pending) => [...pending, summary.revision_id]);
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
        setCopyingRevisions((pending) =>
          pending.filter((revisionId) => revisionId !== summary.revision_id),
        );
      });
  };

  const clearQuery = (): void => {
    setQuery("");
  };

  const focusSearch = (): void => {
    searchRef.current?.focus();
  };

  /**
   * Library-scoped keyboard contract. The handler lives on the library
   * region, so it only sees keys typed while focus is inside the mounted
   * library: browser/editor shortcuts elsewhere are never intercepted.
   * Auto-repeat never re-fires an activation.
   */
  const handleLibraryKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    const chordOf = (key: string): boolean =>
      (event.ctrlKey || event.metaKey) &&
      !event.shiftKey &&
      (event.key === key || event.key === key.toUpperCase());

    // Control+Alt+S / Meta+Alt+S → focus the state filter. The chord is
    // claimed only when that control is actually rendered: with no toolbar
    // (loading, empty or failed list) the browser keeps its own shortcut.
    if (event.altKey && chordOf("s")) {
      if (!stateFilterRef.current) {
        return;
      }
      event.preventDefault();
      if (!event.repeat) {
        stateFilterRef.current.focus();
      }
      return;
    }
    // Control+F / Meta+F → focus search, again only when the search input
    // is rendered. Alt/Shift variants stay with the browser so unrelated
    // chords keep their native behavior.
    if (!event.altKey && chordOf("f")) {
      if (!searchRef.current) {
        return;
      }
      event.preventDefault();
      if (!event.repeat) {
        focusSearch();
      }
      return;
    }
    if (!event.altKey || !(event.ctrlKey || event.metaKey)) {
      return;
    }
    // Ctrl+Alt+C / Cmd+Alt+C opens Compare for the row whose Compare button
    // holds focus; when the library region itself holds focus, the first
    // filtered visible row's Compare opens.
    if (event.key !== "c" && event.key !== "C") {
      return;
    }
    event.preventDefault();
    if (event.repeat) {
      return;
    }
    const active = document.activeElement;
    if (
      active instanceof Element &&
      active.matches('button[data-testid="library-row-compare"]')
    ) {
      const revisionId =
        active
          .closest('li[data-testid="library-row"]')
          ?.getAttribute("data-revision-id") ?? null;
      setCompareRow(
        rows.find((row) => row.revision_id === revisionId) ?? null,
      );
      return;
    }
    if (active === event.currentTarget) {
      setCompareRow(filteredRows[0] ?? null);
    }
  };

  const searching = trimmedQuery !== "";
  const showInventory = phase === "ready" && rows.length > 0;

  return (
    <section
      className="kbot-strategy-library"
      role="region"
      aria-label="Saved strategy library"
      data-testid="saved-strategy-library"
      tabIndex={0}
      onKeyDown={handleLibraryKeyDown}
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
              ref={searchRef}
              type="search"
              id="library-search"
              className="kbot-strategy-library__search-input"
              data-testid="library-search"
              aria-label="Search saved strategies"
              aria-keyshortcuts="Control+F Meta+F"
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
                aria-label="Clear search query"
                aria-keyshortcuts="Escape"
                onClick={clearQuery}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    clearQuery();
                    // The Clear control unmounts with the query, so focus
                    // returns to the search input it serves.
                    focusSearch();
                  }
                }}
              >
                Clear search
              </button>
            ) : null}
          </div>
          <div className="kbot-strategy-library__search">
            <label htmlFor="library-state-filter">State</label>
            <select
              ref={stateFilterRef}
              id="library-state-filter"
              data-testid="library-state-filter"
              className="kbot-strategy-library__select kbot-strategy-library__search-input"
              aria-keyshortcuts="Control+Alt+S Meta+Alt+S"
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
                  const copying = copyingRevisions.includes(row.revision_id);
                  return (
                    <li
                      key={row.revision_id}
                      className="kbot-strategy-library__row"
                      data-testid="library-row"
                      data-revision-id={row.revision_id}
                      aria-busy={
                        reopeningRevision === row.revision_id || undefined
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
                          aria-label={`Compare revisions of ${row.label || row.strategy_id || row.id || "(untitled)"}`}
                          aria-keyshortcuts="Control+Alt+C Meta+Alt+C"
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
                            disabled={
                              openingRevision !== null &&
                              (reopeningRevision !== null || copying)
                            }
                            aria-busy={copying || undefined}
                          >
                            {copying ? "Copying as new…" : "Copy as new"}
                          </button>
                        ) : null}
                      </div>
                      {onCopyAsNew ? (
                        <span
                          className="kbot-strategy-library__row-busy-status"
                          aria-live="polite"
                        >
                          {copying ? "Copying as new…" : ""}
                        </span>
                      ) : null}
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
