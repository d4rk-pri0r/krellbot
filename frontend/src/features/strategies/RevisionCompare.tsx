import { useRef, useState, type JSX } from "react";
import type { LibraryClient, OwnedDraftSummary } from "./libraryClient";

/**
 * Read-only comparison of two actual saved owned revisions. Both packs are
 * fetched through the same authenticated read client the library already
 * uses; nothing is rewritten, validated, or armed here, and no value is
 * invented — differences are computed from the stored bytes only.
 */

export type RevisionCompareChange = {
  /** Dotted path with [index] segments, rooted at the pack. */
  path: string;
  kind: "added" | "removed" | "changed";
  /** Value in the earlier revision; null when the path was added. */
  previous: string | null;
  /** Value in the later revision; null when the path was removed. */
  next: string | null;
};

export type RevisionCompareProps = {
  client: LibraryClient;
  /** The already-listed revisions this surface can choose between. */
  rows: ReadonlyArray<OwnedDraftSummary>;
  /** The row whose Compare control opened this surface. */
  row: OwnedDraftSummary;
  onClose?: () => void;
};

type ComparePhase = "idle" | "loading" | "done" | "error";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    const text = JSON.stringify(value);
    if (typeof text === "string") {
      return text;
    }
  } catch {
    // Circular or otherwise unserializable; fall through to String().
  }
  return String(value);
}

function childPath(path: string, key: string): string {
  return path === "" ? key : `${path}.${key}`;
}

function elementPath(path: string, index: number): string {
  return `${path}[${index}]`;
}

function diffValue(
  previous: unknown,
  next: unknown,
  path: string,
  out: RevisionCompareChange[],
): void {
  if (previous === next) {
    return;
  }
  if (isRecord(previous) && isRecord(next)) {
    const keys = Array.from(
      new Set([...Object.keys(previous), ...Object.keys(next)]),
    ).sort();
    for (const key of keys) {
      const inPrevious = Object.prototype.hasOwnProperty.call(previous, key);
      const inNext = Object.prototype.hasOwnProperty.call(next, key);
      const child = childPath(path, key);
      if (inPrevious && inNext) {
        diffValue(previous[key], next[key], child, out);
      } else if (inNext) {
        out.push({
          path: child,
          kind: "added",
          previous: null,
          next: formatValue(next[key]),
        });
      } else {
        out.push({
          path: child,
          kind: "removed",
          previous: formatValue(previous[key]),
          next: null,
        });
      }
    }
    return;
  }
  if (Array.isArray(previous) && Array.isArray(next)) {
    const shared = Math.min(previous.length, next.length);
    for (let index = 0; index < shared; index += 1) {
      diffValue(previous[index], next[index], elementPath(path, index), out);
    }
    for (let index = shared; index < next.length; index += 1) {
      out.push({
        path: elementPath(path, index),
        kind: "added",
        previous: null,
        next: formatValue(next[index]),
      });
    }
    for (let index = shared; index < previous.length; index += 1) {
      out.push({
        path: elementPath(path, index),
        kind: "removed",
        previous: formatValue(previous[index]),
        next: null,
      });
    }
    return;
  }
  const previousText = formatValue(previous);
  const nextText = formatValue(next);
  if (previousText !== nextText) {
    out.push({
      path,
      kind: "changed",
      previous: previousText,
      next: nextText,
    });
  }
}

function diffRevisionPacks(
  previous: unknown,
  next: unknown,
): RevisionCompareChange[] {
  const out: RevisionCompareChange[] = [];
  diffValue(previous, next, "", out);
  return out;
}

function parseRevisionBytes(bytes: string, revisionId: string): unknown {
  try {
    return JSON.parse(bytes) as unknown;
  } catch (err: unknown) {
    throw new Error(
      `revision ${revisionId} is not readable JSON: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

function optionLabel(row: OwnedDraftSummary): string {
  const name = row.label || row.strategy_id || row.id || "(untitled)";
  return `${row.revision_id} — ${name} (${row.created_at || "unknown date"})`;
}

const KIND_TEXT: Record<RevisionCompareChange["kind"], string> = {
  added: "added",
  removed: "removed",
  changed: "changed",
};

export function RevisionCompare({
  client,
  rows,
  row,
  onClose,
}: RevisionCompareProps): JSX.Element {
  const parentInRows =
    row.parent_revision_id !== null &&
    rows.some((candidate) => candidate.revision_id === row.parent_revision_id);
  const [leftId, setLeftId] = useState<string>(
    parentInRows ? (row.parent_revision_id as string) : row.revision_id,
  );
  const [rightId, setRightId] = useState<string>(
    parentInRows ? row.revision_id : "",
  );
  const [phase, setPhase] = useState<ComparePhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [changes, setChanges] = useState<ReadonlyArray<RevisionCompareChange>>([]);
  const [compared, setCompared] = useState<{ left: string; right: string } | null>(
    null,
  );
  const requestSeq = useRef(0);

  const readyToCompare = leftId !== "" && rightId !== "" && leftId !== rightId;

  const runCompare = (): void => {
    if (!readyToCompare) {
      return;
    }
    const left = leftId;
    const right = rightId;
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    setPhase("loading");
    setError(null);
    setChanges([]);
    setCompared({ left, right });
    Promise.all([client.getJson(left), client.getJson(right)])
      .then(([earlier, later]) => {
        // Ignore superseded responses: only the newest selection counts.
        if (seq !== requestSeq.current) {
          return;
        }
        const previous = parseRevisionBytes(earlier.bytes, left);
        const next = parseRevisionBytes(later.bytes, right);
        setChanges(diffRevisionPacks(previous, next));
        setPhase("done");
      })
      .catch((err: unknown) => {
        if (seq !== requestSeq.current) {
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
        setPhase("error");
      });
  };

  return (
    <section
      className="kbot-revision-compare"
      role="region"
      aria-label="Compare saved revisions"
      data-testid="revision-compare"
    >
      <header className="kbot-revision-compare__head">
        <h3 className="kbot-revision-compare__title">
          Compare saved revisions
        </h3>
        {onClose ? (
          <button
            type="button"
            className="kbot-revision-compare__close"
            data-testid="revision-compare-close"
            onClick={onClose}
          >
            Close
          </button>
        ) : null}
      </header>
      <p className="kbot-revision-compare__note" data-testid="revision-compare-note">
        Read-only comparison: both revisions are fetched as stored and neither is
        changed, validated, or armed. Values are shown exactly as saved; nothing
        about performance is implied.
      </p>
      <div className="kbot-revision-compare__picks">
        <label htmlFor="revision-compare-left">Earlier revision</label>
        <select
          id="revision-compare-left"
          data-testid="revision-compare-left"
          value={leftId}
          onChange={(event) => {
            setLeftId(event.target.value);
          }}
        >
          <option value="">(choose a revision)</option>
          {rows.map((candidate) => (
            <option
              key={candidate.revision_id}
              value={candidate.revision_id}
            >
              {optionLabel(candidate)}
            </option>
          ))}
        </select>
        <label htmlFor="revision-compare-right">Later revision</label>
        <select
          id="revision-compare-right"
          data-testid="revision-compare-right"
          value={rightId}
          onChange={(event) => {
            setRightId(event.target.value);
          }}
        >
          <option value="">(choose a revision)</option>
          {rows.map((candidate) => (
            <option
              key={candidate.revision_id}
              value={candidate.revision_id}
            >
              {optionLabel(candidate)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="kbot-revision-compare__run"
          data-testid="revision-compare-run"
          onClick={runCompare}
          disabled={!readyToCompare}
        >
          Compare revisions
        </button>
      </div>
      {leftId !== "" && rightId !== "" && leftId === rightId ? (
        <p className="kbot-revision-compare__hint" data-testid="revision-compare-hint">
          Pick two different revisions to compare.
        </p>
      ) : null}
      {phase === "loading" ? (
        <p
          className="kbot-revision-compare__loading"
          role="status"
          data-testid="revision-compare-loading"
        >
          Comparing revisions…
        </p>
      ) : null}
      {phase === "error" && error !== null ? (
        <p
          className="kbot-revision-compare__error"
          role="alert"
          data-testid="revision-compare-error"
        >
          Comparison failed: {error}
        </p>
      ) : null}
      {phase === "done" && compared !== null ? (
        changes.length === 0 ? (
          <p
            className="kbot-revision-compare__identical"
            data-testid="revision-compare-identical"
          >
            No differences between {compared.left} and {compared.right}: the
            compared rule values are identical.
          </p>
        ) : (
          <>
            <p
              className="kbot-revision-compare__summary"
              data-testid="revision-compare-summary"
            >
              {changes.length} difference{changes.length === 1 ? "" : "s"} between{" "}
              {compared.left} and {compared.right}:
            </p>
            <table className="kbot-revision-compare__table">
              <thead>
                <tr>
                  <th scope="col">Path</th>
                  <th scope="col">Change</th>
                  <th scope="col">Earlier value ({compared.left})</th>
                  <th scope="col">Later value ({compared.right})</th>
                </tr>
              </thead>
              <tbody data-testid="revision-compare-changes">
                {changes.map((change) => (
                  <tr
                    key={`${change.kind}:${change.path}`}
                    data-testid="revision-compare-change"
                    data-kind={change.kind}
                  >
                    <td>
                      <code>{change.path}</code>
                    </td>
                    <td>{KIND_TEXT[change.kind]}</td>
                    <td>
                      <code>{change.previous ?? "— (not present)"}</code>
                    </td>
                    <td>
                      <code>{change.next ?? "— (not present)"}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )
      ) : null}
    </section>
  );
}
