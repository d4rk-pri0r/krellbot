/**
 * Live guardrails surface (M20.3) — Deploy preflight.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Shows active rails before arm: stop required, max account pct, kill
 * switch, grant expiry, paper-only rail. Evaluate posts `live.guardrails`
 * (journals refusals). Read path uses GET live-guardrails.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type JSX,
} from "react";
import { getCsrf } from "../../session";
import "./LiveGuardrails.signal.css";

export type LiveGuardrailRail = {
  id?: string;
  active?: boolean;
  blocking?: boolean;
  code?: string | null;
  message?: string;
  detail?: Record<string, unknown>;
};

export type LiveGuardrailsView = {
  schema_version?: string;
  venue?: string;
  pair?: string | null;
  pack?: {
    pack_id?: string;
    stop_present?: boolean;
    stop_ok?: boolean;
    max_account_pct?: number | string | null;
    max_account_pct_ok?: boolean;
  } | null;
  rails?: LiveGuardrailRail[];
  blocking_codes?: string[];
  ok?: boolean;
  code?: string;
  effect?: string;
  message?: string;
  journaled_codes?: string[];
};

export type LiveGuardrailsClient = {
  getLiveGuardrails?(venue: string, revisionId: string): Promise<LiveGuardrailsView>;
  evaluateLiveGuardrails?(
    venue: string,
    revisionId: string,
    journal: boolean,
  ): Promise<LiveGuardrailsView>;
};

const PANEL_TITLE = "Live guardrails";
const HELPER_TEXT =
  "Active rails before live arm: stop required, max account percent, kill switch, grant expiry, and the paper-only rail when set. Evaluate journals refusals.";
const DEFAULT_VENUE = "kraken";

const RAIL_LABELS: Record<string, string> = {
  paper_only_rail: "Paper-only rail",
  kill_switch: "Kill switch",
  grant_expiry: "Grant expiry",
  stop_required: "Stop required",
  max_account_pct: "Max account percent",
};

export type LiveGuardrailsProps = {
  client?: LiveGuardrailsClient;
};

async function defaultGet(venue: string, revisionId: string): Promise<LiveGuardrailsView> {
  const params = new URLSearchParams({ venue });
  if (revisionId.trim() !== "") {
    params.set("revision_id", revisionId.trim());
  }
  const response = await fetch(`/api/v1/operations/live-guardrails?${params.toString()}`, {
    method: "GET",
    credentials: "include",
    headers: { "X-Krellbot-CSRF": getCsrf() },
  });
  if (!response.ok) {
    throw new Error(`live guardrails failed: ${response.status}`);
  }
  return (await response.json()) as LiveGuardrailsView;
}

async function defaultEvaluate(
  venue: string,
  revisionId: string,
  journal: boolean,
): Promise<LiveGuardrailsView> {
  const payload: Record<string, unknown> = {
    venue,
    journal,
  };
  if (revisionId.trim() !== "") {
    payload.revision_id = revisionId.trim();
  }
  const response = await fetch("/api/v1/commands", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({
      schema_version: "1",
      command: "live.guardrails",
      payload,
    }),
  });
  if (!response.ok) {
    throw new Error(`live.guardrails failed: ${response.status}`);
  }
  return (await response.json()) as LiveGuardrailsView;
}

function railLabel(id: string | undefined): string {
  if (!id) {
    return "Rail";
  }
  return RAIL_LABELS[id] ?? id;
}

export function LiveGuardrails({ client }: LiveGuardrailsProps): JSX.Element {
  const [revisionId, setRevisionId] = useState("");
  const [view, setView] = useState<LiveGuardrailsView | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const requestRef = useRef(0);
  const intent = useRef(0);

  const load = useCallback(
    async (revisionForLoad: string): Promise<void> => {
      const requestId = ++requestRef.current;
      setLoading(true);
      setLoadError(null);
      try {
        const getter =
          client?.getLiveGuardrails !== undefined
            ? client.getLiveGuardrails.bind(client)
            : defaultGet;
        const next = await getter(DEFAULT_VENUE, revisionForLoad);
        if (requestId !== requestRef.current) {
          return;
        }
        setView(next);
      } catch (err) {
        if (requestId !== requestRef.current) {
          return;
        }
        setLoadError(err instanceof Error ? err.message : String(err));
      } finally {
        if (requestId === requestRef.current) {
          setLoading(false);
        }
      }
    },
    [client],
  );

  useEffect(() => {
    void load("");
  }, [load]);

  const handleRevisionChange = (event: ChangeEvent<HTMLInputElement>): void => {
    intent.current += 1;
    setErrorMessage(null);
    setRevisionId(event.target.value);
  };

  const handleEvaluate = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const submittedIntent = ++intent.current;
    setPending(true);
    setErrorMessage(null);
    try {
      const evaluate =
        client?.evaluateLiveGuardrails !== undefined
          ? client.evaluateLiveGuardrails.bind(client)
          : defaultEvaluate;
      const next = await evaluate(DEFAULT_VENUE, revisionId, true);
      if (intent.current !== submittedIntent) {
        return;
      }
      setView(next);
    } catch (err) {
      if (intent.current !== submittedIntent) {
        return;
      }
      setErrorMessage(err instanceof Error ? err.message : String(err));
    } finally {
      if (intent.current === submittedIntent) {
        setPending(false);
      }
    }
  };

  const rails = view?.rails ?? [];
  const blocking = view?.blocking_codes ?? [];
  const journaled = view?.journaled_codes ?? [];

  return (
    <section
      className="kbot-feature__live-guardrails-root"
      role="region"
      aria-label="Live guardrails"
      data-testid="live-guardrails-panel"
    >
      <header className="kbot-feature__live-guardrails-root__head">
        <h2 className="kbot-feature__live-guardrails-root__title">{PANEL_TITLE}</h2>
        <button
          type="button"
          className="kbot-feature__live-guardrails-root__refresh"
          data-testid="live-guardrails-refresh"
          disabled={pending || loading}
          aria-busy={loading || undefined}
          onClick={() => {
            void load(revisionId);
          }}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </header>

      {loadError !== null ? (
        <p
          className="kbot-feature__live-guardrails-root__error"
          role="alert"
          data-testid="live-guardrails-load-error"
        >
          Could not load live guardrails — check the workstation is running. ({loadError})
        </p>
      ) : null}

      <form
        className="kbot-feature__live-guardrails-root__form"
        onSubmit={(event) => {
          void handleEvaluate(event);
        }}
      >
        <label
          className="kbot-feature__live-guardrails-root__field"
          htmlFor="live-guardrails-venue"
        >
          Venue
          <select
            id="live-guardrails-venue"
            className="kbot-feature__live-guardrails-root__input"
            data-testid="live-guardrails-venue"
            value={DEFAULT_VENUE}
            disabled={pending || loading}
            onChange={() => {
              /* Kraken-only for M20. */
            }}
          >
            <option value="kraken">kraken</option>
          </select>
        </label>
        <label
          className="kbot-feature__live-guardrails-root__field"
          htmlFor="live-guardrails-revision"
        >
          Revision ID
          <input
            id="live-guardrails-revision"
            className="kbot-feature__live-guardrails-root__input"
            data-testid="live-guardrails-revision"
            value={revisionId}
            disabled={pending || loading}
            onChange={handleRevisionChange}
            placeholder="optional — checks stop + max account pct"
          />
        </label>
        <button
          type="submit"
          className="kbot-feature__live-guardrails-root__action"
          data-testid="live-guardrails-evaluate"
          disabled={pending || loading}
          aria-busy={pending || undefined}
        >
          Evaluate &amp; journal
        </button>
      </form>

      {view !== null ? (
        <div
          className="kbot-feature__live-guardrails-root__result"
          data-testid="live-guardrails-result"
        >
          <p
            className={
              "kbot-feature__live-guardrails-root__result-line " +
              (view.ok === true
                ? "kbot-feature__live-guardrails-root__result-line--ok"
                : "kbot-feature__live-guardrails-root__result-line--refused")
            }
            data-testid="live-guardrails-ok"
          >
            ok: {view.ok === true ? "true" : "false"}
          </p>
          <p className="kbot-feature__live-guardrails-root__result-line">
            message: {view.message}
          </p>
          {blocking.length > 0 ? (
            <p
              className="kbot-feature__live-guardrails-root__result-line kbot-feature__live-guardrails-root__result-line--refused"
              data-testid="live-guardrails-blocking"
            >
              blocking: {blocking.join(", ")}
            </p>
          ) : null}
          {journaled.length > 0 ? (
            <p
              className="kbot-feature__live-guardrails-root__result-line"
              data-testid="live-guardrails-journaled"
            >
              journaled: {journaled.join(", ")}
            </p>
          ) : null}
          <ul
            className="kbot-feature__live-guardrails-root__rails"
            data-testid="live-guardrails-rails"
          >
            {rails.map((rail) => {
              const id = typeof rail.id === "string" ? rail.id : "rail";
              const blocked = rail.blocking === true;
              return (
                <li
                  key={id}
                  className={
                    "kbot-feature__live-guardrails-root__rail" +
                    (blocked
                      ? " kbot-feature__live-guardrails-root__rail--blocking"
                      : "")
                  }
                  data-testid={`live-guardrails-rail-${id}`}
                  data-blocking={blocked ? "true" : "false"}
                >
                  <span className="kbot-feature__live-guardrails-root__rail-label">
                    {railLabel(rail.id)}
                  </span>
                  <span className="kbot-feature__live-guardrails-root__rail-state">
                    {blocked ? "blocking" : rail.active === false ? "off" : "clear"}
                  </span>
                  <span className="kbot-feature__live-guardrails-root__rail-message">
                    {rail.message}
                  </span>
                  {rail.code ? (
                    <span
                      className="kbot-feature__live-guardrails-root__rail-code"
                      data-testid={`live-guardrails-code-${id}`}
                    >
                      {rail.code}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {errorMessage !== null ? (
        <p
          className="kbot-feature__live-guardrails-root__error"
          role="alert"
          data-testid="live-guardrails-error"
        >
          {errorMessage}
        </p>
      ) : null}

      <p className="kbot-feature__live-guardrails-root__helper">{HELPER_TEXT}</p>
    </section>
  );
}
