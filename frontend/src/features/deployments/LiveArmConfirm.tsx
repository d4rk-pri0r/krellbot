/**
 * Kraken live arm + confirm (M20.1) — Deploy/Operations.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * End-to-end workstation live arm for Kraken: typed LIVE confirm, then
 * `live.arm`. Honest paper-only refusals leave controls disabled. No CLI
 * stdin path. Fake-transport CI covers the command; this panel never
 * places a real order by itself.
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
import "./LiveArmConfirm.signal.css";

export type LiveArmConfirmResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  detail?: string;
  venue?: string;
  pair?: string;
};

export type LiveArmConfirmAuthView = {
  release_policy?: string;
  release_policy_code?: string;
  release_policy_message?: string | null;
  confirmation_required?: string;
};

export type LiveArmConfirmClient = {
  getLiveAuthorization?(): Promise<LiveArmConfirmAuthView>;
  armLive?(
    revisionId: string,
    venue: string,
    confirmation: string,
  ): Promise<LiveArmConfirmResult>;
};

const PANEL_TITLE = "Kraken live arm";
const PAPER_ONLY_HEADING = "Live arm is disabled in this paper-only release.";
const HELPER_TEXT =
  "Arms one Kraken pack after typed LIVE confirm. Grant live authorization on Operations first. No CLI Type LIVE prompt.";
const CONFIRM_LABEL = "Type LIVE to confirm";
const DEFAULT_VENUE = "kraken";
const REQUIRED_CONFIRM = "LIVE";

export type LiveArmConfirmProps = {
  client?: LiveArmConfirmClient;
};

async function defaultLoadAuth(): Promise<LiveArmConfirmAuthView> {
  const response = await fetch("/api/v1/operations/live-authorization", {
    method: "GET",
    credentials: "include",
    headers: { "X-Krellbot-CSRF": getCsrf() },
  });
  if (!response.ok) {
    throw new Error(`live authorization failed: ${response.status}`);
  }
  return (await response.json()) as LiveArmConfirmAuthView;
}

async function defaultArmLive(
  revisionId: string,
  venue: string,
  confirmation: string,
): Promise<LiveArmConfirmResult> {
  const response = await fetch("/api/v1/commands", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({
      schema_version: "1",
      command: "live.arm",
      payload: {
        venue,
        revision_id: revisionId,
        mode: "live",
        confirmation,
      },
    }),
  });
  let body: LiveArmConfirmResult = {};
  try {
    body = (await response.json()) as LiveArmConfirmResult;
  } catch {
    body = {};
  }
  if (!response.ok) {
    return {
      schema_version: typeof body.schema_version === "string" ? body.schema_version : "1",
      code: typeof body.code === "string" ? body.code : `http_${response.status}`,
      ok: false,
      effect: typeof body.effect === "string" ? body.effect : "refused",
      message:
        typeof body.message === "string"
          ? body.message
          : typeof body.detail === "string"
            ? body.detail
            : `live.arm refused: ${response.status}`,
      detail: typeof body.detail === "string" ? body.detail : undefined,
      venue: typeof body.venue === "string" ? body.venue : undefined,
      pair: typeof body.pair === "string" ? body.pair : undefined,
    };
  }
  return body;
}

export function LiveArmConfirm({ client }: LiveArmConfirmProps): JSX.Element {
  const [auth, setAuth] = useState<LiveArmConfirmAuthView | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [revisionId, setRevisionId] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<LiveArmConfirmResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const requestRef = useRef(0);
  const intent = useRef(0);

  const load = useCallback(async (): Promise<void> => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const loader =
        client?.getLiveAuthorization !== undefined
          ? client.getLiveAuthorization.bind(client)
          : defaultLoadAuth;
      const next = await loader();
      if (requestId !== requestRef.current) {
        return;
      }
      setAuth(next);
    } catch (err) {
      if (requestId !== requestRef.current) {
        return;
      }
      setLoadError(err instanceof Error ? err.message : String(err));
      setAuth({
        release_policy: "paper_only",
        release_policy_code: "live_disabled_paper_only_release",
        release_policy_message:
          "This release is a paper-only release: live order send is disabled regardless of environment, stored keys, or authorization.",
        confirmation_required: REQUIRED_CONFIRM,
      });
    } finally {
      if (requestId === requestRef.current) {
        setLoading(false);
      }
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const paperOnly = auth?.release_policy === "paper_only";
  const requiredConfirm = auth?.confirmation_required ?? REQUIRED_CONFIRM;
  const confirmReady = confirmation.trim() === requiredConfirm;
  const controlsDisabled = paperOnly || pending || loading;

  const invalidate = (): void => {
    intent.current += 1;
    setResult(null);
    setErrorMessage(null);
  };

  const handleRevisionChange = (event: ChangeEvent<HTMLInputElement>): void => {
    invalidate();
    setRevisionId(event.target.value);
  };

  const handleConfirmChange = (event: ChangeEvent<HTMLInputElement>): void => {
    invalidate();
    setConfirmation(event.target.value);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (controlsDisabled || !confirmReady || revisionId.trim() === "") {
      return;
    }
    const submittedIntent = ++intent.current;
    setPending(true);
    setResult(null);
    setErrorMessage(null);
    try {
      const arm =
        client?.armLive !== undefined ? client.armLive.bind(client) : defaultArmLive;
      const verdict = await arm(revisionId.trim(), DEFAULT_VENUE, confirmation.trim());
      if (intent.current !== submittedIntent) {
        return;
      }
      setResult(verdict);
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

  const verdictModifier =
    result?.ok === true
      ? "kbot-feature__live-arm-confirm-root__result-line--ok"
      : "kbot-feature__live-arm-confirm-root__result-line--refused";

  return (
    <section
      className="kbot-feature__live-arm-confirm-root"
      role="region"
      aria-label="Kraken live arm"
      data-testid="live-arm-confirm-panel"
    >
      <header className="kbot-feature__live-arm-confirm-root__head">
        <h2 className="kbot-feature__live-arm-confirm-root__title">{PANEL_TITLE}</h2>
        <button
          type="button"
          className="kbot-feature__live-arm-confirm-root__refresh"
          data-testid="live-arm-confirm-refresh"
          disabled={pending || loading}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Loading…" : "Retry"}
        </button>
      </header>

      {paperOnly ? (
        <p
          className="kbot-feature__live-arm-confirm-root__paper-only"
          role="status"
          data-testid="live-arm-confirm-paper-only"
        >
          <span data-testid="live-arm-confirm-paper-only-heading">{PAPER_ONLY_HEADING}</span>{" "}
          <span data-testid="live-arm-confirm-paper-only-reason">
            {auth?.release_policy_message ??
              "Live order send is disabled in this paper-only release."}
          </span>
        </p>
      ) : null}

      {loadError !== null ? (
        <p
          className="kbot-feature__live-arm-confirm-root__error"
          role="alert"
          data-testid="live-arm-confirm-load-error"
        >
          Could not load live authorization — check the workstation is running. ({loadError})
        </p>
      ) : null}

      <form
        className="kbot-feature__live-arm-confirm-root__form"
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
      >
        <label
          className="kbot-feature__live-arm-confirm-root__field"
          htmlFor="live-arm-confirm-venue"
        >
          Venue
          <select
            id="live-arm-confirm-venue"
            className="kbot-feature__live-arm-confirm-root__input"
            data-testid="live-arm-confirm-venue"
            value={DEFAULT_VENUE}
            disabled={controlsDisabled}
            onChange={() => {
              /* Kraken-only; keep the select honest and fixed. */
            }}
          >
            <option value="kraken">kraken</option>
          </select>
        </label>
        <label
          className="kbot-feature__live-arm-confirm-root__field"
          htmlFor="live-arm-confirm-revision"
        >
          Revision ID
          <input
            id="live-arm-confirm-revision"
            className="kbot-feature__live-arm-confirm-root__input"
            data-testid="live-arm-confirm-revision"
            value={revisionId}
            disabled={controlsDisabled}
            onChange={handleRevisionChange}
          />
        </label>
        <label
          className="kbot-feature__live-arm-confirm-root__field"
          htmlFor="live-arm-confirm-live"
        >
          {CONFIRM_LABEL}
          <input
            id="live-arm-confirm-live"
            className="kbot-feature__live-arm-confirm-root__input"
            data-testid="live-arm-confirm-live"
            type="text"
            value={confirmation}
            disabled={controlsDisabled}
            autoComplete="off"
            spellCheck={false}
            placeholder={requiredConfirm}
            onChange={handleConfirmChange}
          />
        </label>
        <button
          type="submit"
          className="kbot-feature__live-arm-confirm-root__action"
          data-testid="live-arm-confirm-submit"
          disabled={controlsDisabled || !confirmReady || revisionId.trim() === ""}
          aria-busy={pending || undefined}
        >
          Arm live
        </button>
      </form>

      {result !== null ? (
        <div
          className="kbot-feature__live-arm-confirm-root__result"
          data-testid="live-arm-confirm-result"
        >
          <p
            className={
              "kbot-feature__live-arm-confirm-root__result-line " + verdictModifier
            }
          >
            code: {result.code ?? "unknown"}
          </p>
          <p
            className={
              "kbot-feature__live-arm-confirm-root__result-line " + verdictModifier
            }
          >
            ok: {result.ok === true ? "true" : "false"}
          </p>
          <p className="kbot-feature__live-arm-confirm-root__result-line">
            message: {result.message}
          </p>
          {result.venue !== undefined ? (
            <p className="kbot-feature__live-arm-confirm-root__result-line kbot-feature__live-arm-confirm-root__result-line--tech">
              venue: {result.venue}
            </p>
          ) : null}
          {result.pair !== undefined ? (
            <p className="kbot-feature__live-arm-confirm-root__result-line kbot-feature__live-arm-confirm-root__result-line--tech">
              pair: {result.pair}
            </p>
          ) : null}
        </div>
      ) : null}

      {errorMessage !== null ? (
        <p
          className="kbot-feature__live-arm-confirm-root__error"
          role="alert"
          data-testid="live-arm-confirm-error"
        >
          {errorMessage}
        </p>
      ) : null}

      <p className="kbot-feature__live-arm-confirm-root__helper">{HELPER_TEXT}</p>
    </section>
  );
}
