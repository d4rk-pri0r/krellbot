import { useState, type ChangeEvent, type FormEvent, type JSX } from "react";
import { getCsrf } from "../../session";
import { summarizePreflightCode } from "./preflightCodeLabel";

export type LivePreflightResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  account_id?: string;
  revision_id?: string;
  stored_mode?: string;
};

type PreflightMode = "sandbox" | "live";

export function LivePreflight(): JSX.Element {
  const [accountId, setAccountId] = useState("");
  const [revisionId, setRevisionId] = useState("");
  const [mode, setMode] = useState<PreflightMode>("sandbox");
  const [result, setResult] = useState<LivePreflightResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [fieldProblems, setFieldProblems] = useState<{
    account: string | null;
    revision: string | null;
  }>({ account: null, revision: null });

  const handleAccountChange = (event: ChangeEvent<HTMLInputElement>): void => {
    setAccountId(event.target.value);
    if (fieldProblems.account !== null) {
      setFieldProblems((previous) => ({ ...previous, account: null }));
    }
  };

  const handleRevisionChange = (event: ChangeEvent<HTMLInputElement>): void => {
    setRevisionId(event.target.value);
    if (fieldProblems.revision !== null) {
      setFieldProblems((previous) => ({ ...previous, revision: null }));
    }
  };

  const handleModeChange = (event: ChangeEvent<HTMLSelectElement>): void => {
    setMode(event.target.value === "live" ? "live" : "sandbox");
  };

  // Preflight is a dry-run: the response always carries the verdict
  // (ok or a refusal code) with HTTP 200, so the refusal code and
  // message are rendered in the result panel, not as an error.
  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setPending(true);
    setErrorMessage(null);
    setFieldProblems({
      account: accountId.trim() === "" ? "Account ID is required" : null,
      revision: revisionId.trim() === "" ? "Revision ID is required" : null,
    });
    let succeeded = false;
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
            account_id: accountId,
            revision_id: revisionId,
            mode,
          },
        }),
      });
      if (!response.ok) {
        throw new Error(`live.preflight failed: ${response.status}`);
      }
      setResult((await response.json()) as LivePreflightResult);
      succeeded = true;
    } catch {
      setErrorMessage("Preflight request failed");
    } finally {
      if (succeeded) {
        setFieldProblems({ account: null, revision: null });
      }
      setPending(false);
    }
  };

  return (
    <section
      className="kbot-live-preflight"
      role="region"
      aria-label="Live preflight"
      data-testid="live-preflight-panel"
    >
      <header className="kbot-live-preflight__head">
        <h2 className="kbot-live-preflight__title">Live preflight</h2>
      </header>
      <form
        className="kbot-live-preflight__form"
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
      >
        <label
          className="kbot-live-preflight__field"
          htmlFor="live-preflight-account-input"
        >
          Account ID
          <input
            id="live-preflight-account-input"
            className="kbot-live-preflight__input"
            data-testid="live-preflight-account"
            aria-required="true"
            aria-invalid={fieldProblems.account !== null}
            aria-describedby={
              fieldProblems.account !== null ? "live-preflight-account-problem" : undefined
            }
            value={accountId}
            onChange={handleAccountChange}
          />
          {fieldProblems.account !== null ? (
            <p
              id="live-preflight-account-problem"
              data-testid="live-preflight-account-problem"
            >
              {fieldProblems.account}
            </p>
          ) : null}
        </label>
        <label
          className="kbot-live-preflight__field"
          htmlFor="live-preflight-revision-input"
        >
          Revision ID
          <input
            id="live-preflight-revision-input"
            className="kbot-live-preflight__input"
            data-testid="live-preflight-revision"
            aria-required="true"
            aria-invalid={fieldProblems.revision !== null}
            aria-describedby={
              fieldProblems.revision !== null ? "live-preflight-revision-problem" : undefined
            }
            value={revisionId}
            onChange={handleRevisionChange}
          />
          {fieldProblems.revision !== null ? (
            <p
              id="live-preflight-revision-problem"
              data-testid="live-preflight-revision-problem"
            >
              {fieldProblems.revision}
            </p>
          ) : null}
        </label>
        <label
          className="kbot-live-preflight__field"
          htmlFor="live-preflight-mode-select"
        >
          Mode
          <select
            id="live-preflight-mode-select"
            className="kbot-live-preflight__input"
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
          className="kbot-live-preflight__action"
          data-testid="live-preflight-submit"
          disabled={pending}
        >
          Run preflight
        </button>
      </form>
      {result !== null ? (
        <div
          className="kbot-live-preflight__result"
          data-testid="live-preflight-result"
        >
          <p className="kbot-live-preflight__result-line">
            code: {summarizePreflightCode(result.code).label}
          </p>
          <p className="kbot-live-preflight__result-line">
            ok: {result.ok === true ? "true" : "false"}
          </p>
          <p className="kbot-live-preflight__result-line">
            message: {result.message}
          </p>
          <p className="kbot-live-preflight__result-line">
            account_id: {result.account_id}
          </p>
          <p className="kbot-live-preflight__result-line">
            revision_id: {result.revision_id}
          </p>
        </div>
      ) : null}
      {errorMessage !== null ? (
        <p
          className="kbot-live-preflight__error"
          role="alert"
          data-testid="live-preflight-error"
        >
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}
