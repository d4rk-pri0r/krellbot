import { useEffect, useState, type JSX } from "react";
import type {
  LibraryClient,
  OwnedDraftSummary,
} from "./libraryClient";

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
};

type LoadPhase = "loading" | "ready" | "error";

export function SavedStrategyLibrary({
  client,
  onReopen,
  onNewStrategy,
}: SavedStrategyLibraryProps): JSX.Element {
  const [rows, setRows] = useState<ReadonlyArray<OwnedDraftSummary>>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [reopenError, setReopenError] = useState<string | null>(null);
  const [openingRevision, setOpeningRevision] = useState<string | null>(null);

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

  return (
    <section
      className="kbot-strategy-library"
      role="region"
      aria-label="Saved strategy library"
      data-testid="saved-strategy-library"
    >
      <header className="kbot-strategy-library__head">
        <h2 className="kbot-strategy-library__title">
          Saved strategy library
        </h2>
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
      {phase === "ready" && rows.length > 0 ? (
        <ul className="kbot-strategy-library__list">
          {rows.map((row) => (
            <li
              key={row.revision_id}
              className="kbot-strategy-library__row"
              data-testid="library-row"
              data-revision-id={row.revision_id}
            >
              <span className="kbot-strategy-library__cell">
                {row.strategy_id || row.id || "(untitled)"}
              </span>
              <span className="kbot-strategy-library__cell">
                {row.label || "(no label)"}
              </span>
              <span className="kbot-strategy-library__cell">
                {row.pair || "(no pair)"}
              </span>
              <span className="kbot-strategy-library__cell">
                {row.timeframe || "(no timeframe)"}
              </span>
              <span className="kbot-strategy-library__cell">
                {row.state}
              </span>
              <span className="kbot-strategy-library__cell">
                {row.created_at || "(unknown date)"}
              </span>
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
            </li>
          ))}
        </ul>
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
    </section>
  );
}
