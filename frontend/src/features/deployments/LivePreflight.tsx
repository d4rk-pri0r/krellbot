import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type JSX } from "react";
import { getCsrf } from "../../session";
import { summarizePreflightCode } from "./preflightCodeLabel";
import "./LivePreflight.signal.css";

export type LivePreflightPermissions = {
  can_trade?: boolean;
  can_withdraw?: boolean;
};

export type LivePreflightResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  account_id?: string;
  revision_id?: string;
  stored_mode?: string;
  balances?: Record<string, string | number> | null;
  permissions?: LivePreflightPermissions | null;
};

type PreflightMode = "sandbox" | "live";
type PreflightVenue = "kraken";

export function LivePreflight(): JSX.Element {
  const [venue, setVenue] = useState<PreflightVenue>("kraken");
  const [revisionId, setRevisionId] = useState("");
  const [mode, setMode] = useState<PreflightMode>("sandbox");
  const [result, setResult] = useState<LivePreflightResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const intent = useRef(0);
  useEffect(() => () => { intent.current += 1; }, []);

  const invalidate = (): void => {
    intent.current += 1;
    setResult(null);
    setErrorMessage(null);
    setPending(false);
  };

  const handleVenueChange = (_event: ChangeEvent<HTMLSelectElement>): void => {
    invalidate();
    setVenue("kraken");
  };

  const handleRevisionChange = (event: ChangeEvent<HTMLInputElement>): void => {
    invalidate();
    setRevisionId(event.target.value);
  };

  const handleModeChange = (event: ChangeEvent<HTMLSelectElement>): void => {
    invalidate();
    setMode(event.target.value === "live" ? "live" : "sandbox");
  };

  // Preflight is a dry-run: the response always carries the verdict
  // (ok or a refusal code) with HTTP 200, so the refusal code and
  // message are rendered in the result panel, not as an error.
  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const submittedIntent = ++intent.current;
    setPending(true);
    setResult(null);
    setErrorMessage(null);
    try {
      const response = await fetch("/api/v1/commands", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: JSON.stringify({
          schema_version: "1",
          command: "live.preflight",
          payload: {
            venue,
            account_id: venue,
            revision_id: revisionId,
            mode,
          },
        }),
      });
      if (intent.current !== submittedIntent) return;
      if (!response.ok) {
        throw new Error(`live.preflight failed: ${response.status}`);
      }
      const verdict = (await response.json()) as LivePreflightResult;
      if (intent.current === submittedIntent) setResult(verdict);
    } catch {
      if (intent.current === submittedIntent) setErrorMessage("Preflight request failed");
    } finally {
      if (intent.current === submittedIntent) setPending(false);
    }
  };

  // Verdict reinforcement only: sage for an ok verdict, coral-derived
  // for a refusal. The verbatim code label and ok flag carry the state.
  const verdictModifier =
    result?.ok === true
      ? "kbot-feature__live-preflight-root__result-line--ok"
      : "kbot-feature__live-preflight-root__result-line--refused";

  const balanceEntries =
    result?.balances !== null && result?.balances !== undefined
      ? Object.entries(result.balances)
      : null;
  const permissions = result?.permissions ?? null;

  return (
    <section
      className="kbot-feature__live-preflight-root"
      role="region"
      aria-label="Live preflight"
      data-testid="live-preflight-panel"
    >
      <header className="kbot-feature__live-preflight-root__head">
        <h2 className="kbot-feature__live-preflight-root__title">
          Live preflight
        </h2>
      </header>
      <form
        className="kbot-feature__live-preflight-root__form"
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
      >
        <label
          className="kbot-feature__live-preflight-root__field"
          htmlFor="live-preflight-venue-select"
        >
          Venue
          <select
            id="live-preflight-venue-select"
            className="kbot-feature__live-preflight-root__input"
            data-testid="live-preflight-account"
            value={venue}
            onChange={handleVenueChange}
          >
            <option value="kraken">kraken</option>
          </select>
        </label>
        <p
          className="kbot-feature__live-preflight-root__hint"
          data-testid="live-preflight-paper-only-venues"
        >
          This paper-only release does not offer qualified Binance live. Use
          paper arm for binance / BTCUSDT; live preflight stays Kraken-only.
        </p>
        <label
          className="kbot-feature__live-preflight-root__field"
          htmlFor="live-preflight-revision-input"
        >
          Revision ID
          <input
            id="live-preflight-revision-input"
            className="kbot-feature__live-preflight-root__input"
            data-testid="live-preflight-revision"
            value={revisionId}
            onChange={handleRevisionChange}
          />
        </label>
        <label
          className="kbot-feature__live-preflight-root__field"
          htmlFor="live-preflight-mode-select"
        >
          Mode
          <select
            id="live-preflight-mode-select"
            className="kbot-feature__live-preflight-root__input"
            data-testid="live-preflight-mode"
            value={mode}
            onChange={handleModeChange}
          >
            <option value="sandbox">sandbox</option>
            <option value="live">live</option>
          </select>
        </label>
        <button
          type="submit"
          className="kbot-feature__live-preflight-root__action"
          data-testid="live-preflight-submit"
          disabled={pending}
        >
          Run preflight
        </button>
      </form>
      {result !== null ? (
        <div
          className="kbot-feature__live-preflight-root__result"
          data-testid="live-preflight-result"
        >
          <p
            className={
              "kbot-feature__live-preflight-root__result-line " +
              verdictModifier
            }
          >
            code: {summarizePreflightCode(result.code).label}
          </p>
          <p
            className={
              "kbot-feature__live-preflight-root__result-line " +
              verdictModifier
            }
          >
            ok: {result.ok === true ? "true" : "false"}
          </p>
          <p className="kbot-feature__live-preflight-root__result-line">
            message: {result.message}
          </p>
          <p
            className={
              "kbot-feature__live-preflight-root__result-line kbot-feature__live-preflight-root__result-line--tech"
            }
          >
            account_id: {result.account_id}
          </p>
          <p
            className={
              "kbot-feature__live-preflight-root__result-line kbot-feature__live-preflight-root__result-line--tech"
            }
          >
            revision_id: {result.revision_id}
          </p>
          {permissions !== null ? (
            <p
              className="kbot-feature__live-preflight-root__result-line"
              data-testid="live-preflight-permissions"
            >
              permissions: trade {permissions.can_trade === true ? "on" : "off"},
              withdraw {permissions.can_withdraw === true ? "on" : "off"}
            </p>
          ) : null}
          {balanceEntries !== null ? (
            <div
              className="kbot-feature__live-preflight-root__balances"
              data-testid="live-preflight-balances"
            >
              <p className="kbot-feature__live-preflight-root__result-line">
                balances
              </p>
              {balanceEntries.length === 0 ? (
                <p
                  className="kbot-feature__live-preflight-root__result-line kbot-feature__live-preflight-root__result-line--tech"
                  data-testid="live-preflight-balances-empty"
                >
                  (none)
                </p>
              ) : (
                <ul className="kbot-feature__live-preflight-root__balances-list">
                  {balanceEntries.map(([asset, free]) => (
                    <li
                      key={asset}
                      className="kbot-feature__live-preflight-root__result-line kbot-feature__live-preflight-root__result-line--tech"
                      data-testid={`live-preflight-balance-${asset}`}
                    >
                      {asset}: {String(free)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
      {errorMessage !== null ? (
        <p
          className="kbot-feature__live-preflight-root__error"
          role="alert"
          data-testid="live-preflight-error"
        >
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}
