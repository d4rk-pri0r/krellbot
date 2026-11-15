import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./KeysOnboardingPanel.signal.css";
import type { KeysClient, KeysStatus } from "./client";
import { KEYS_VENUE } from "./client";

const PANEL_TITLE = "Kraken exchange key";
const HELPER_TEXT =
  "Probe a trade-only Kraken key, store it in this machine’s OS keychain, then review status and free holdings. Live order send stays disabled in this paper-only release.";
const LOADING_TEXT = "Reading Kraken key status…";
const LOAD_ERROR_PREFIX =
  "Could not read Kraken key status — check the workstation is running.";
const KEY_LABEL = "Public key";
const SECRET_LABEL = "Private key";
const STORE_LABEL = "Probe and store";
const REMOVE_LABEL = "Remove key";
const REFRESH_LABEL = "Refresh";
const ABSENT_COPY =
  "No Kraken key is stored on this machine yet. Enter trade-only key material below.";
const PAPER_ONLY_NOTE =
  "Storing a key does not enable live trading in this paper-only release.";

export type KeysOnboardingPanelProps = {
  client: KeysClient;
  /** When false, skip network reads (session still starting or failed). */
  enabled?: boolean;
};

function describeStatus(status: KeysStatus): string {
  if (status.corrupt) {
    return status.message || "keyring pair is corrupt; refused";
  }
  if (!status.present) {
    return status.message || "no key stored";
  }
  return status.message || "key present";
}

export function KeysOnboardingPanel({
  client,
  enabled = true,
}: KeysOnboardingPanelProps): JSX.Element {
  const [status, setStatus] = useState<KeysStatus | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const requestRef = useRef(0);
  const inFlight = useRef(false);

  const load = useCallback(async (): Promise<void> => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.getStatus(KEYS_VENUE);
      if (requestId !== requestRef.current) {
        return;
      }
      setStatus(next);
    } catch (err) {
      if (requestId !== requestRef.current) {
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === requestRef.current) {
        setLoading(false);
      }
    }
  }, [client, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleStore = useCallback(async (): Promise<void> => {
    if (inFlight.current || !enabled) {
      return;
    }
    const trimmedKey = key.trim();
    const trimmedSecret = secret.trim();
    if (trimmedKey === "" || trimmedSecret === "") {
      setFeedback("Enter both the public key and the private key.");
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    try {
      const result = await client.probeAndStore(trimmedKey, trimmedSecret, KEYS_VENUE);
      setFeedback(result.message);
      if (result.ok) {
        setKey("");
        setSecret("");
      }
      await load();
    } catch (err) {
      setFeedback(
        `Probe and store failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [client, enabled, key, load, secret]);

  const handleRemove = useCallback(async (): Promise<void> => {
    if (inFlight.current || !enabled) {
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    try {
      const result = await client.remove(KEYS_VENUE);
      setFeedback(result.message);
      await load();
    } catch (err) {
      setFeedback(`Remove failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [client, enabled, load]);

  const controlsDisabled = !enabled || pending || loading;
  const present = status?.present === true && status.corrupt !== true;

  return (
    <section
      className="kbot-keys"
      data-testid="keys-onboarding"
      aria-labelledby="keys-onboarding-title"
    >
      <div className="kbot-keys__head">
        <h2 className="kbot-keys__title" id="keys-onboarding-title">
          {PANEL_TITLE}
        </h2>
        <button
          type="button"
          className="kbot-keys__refresh"
          data-testid="keys-refresh"
          disabled={controlsDisabled}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Loading…" : REFRESH_LABEL}
        </button>
      </div>

      <p className="kbot-keys__helper">{HELPER_TEXT}</p>
      <p className="kbot-keys__paper-only" data-testid="keys-paper-only">
        {PAPER_ONLY_NOTE}
      </p>

      {!enabled ? (
        <p className="kbot-keys__status" data-testid="keys-waiting-session" role="status">
          Waiting for the local session before reading key status.
        </p>
      ) : null}

      {enabled && loading && status === null ? (
        <p className="kbot-keys__status" data-testid="keys-loading" role="status">
          {LOADING_TEXT}
        </p>
      ) : null}

      {error !== null ? (
        <p className="kbot-keys__error" role="alert" data-testid="keys-error">
          {LOAD_ERROR_PREFIX} ({error})
        </p>
      ) : null}

      {status !== null ? (
        <>
          <p className="kbot-keys__status" data-testid="keys-status" role="status">
            {describeStatus(status)}
            {status.backend_label ? ` · ${status.backend_label}` : ""}
          </p>

          {present ? (
            <div className="kbot-keys__connected" data-testid="keys-connected">
              {status.balances_available && status.balances !== null ? (
                <div data-testid="keys-balances">
                  <h3 className="kbot-keys__balances-title">Free holdings</h3>
                  {status.balances.length === 0 ? (
                    <p className="kbot-keys__status" data-testid="keys-balances-empty">
                      No free holdings reported.
                    </p>
                  ) : (
                    <ul className="kbot-keys__balances-list">
                      {status.balances.map((row) => (
                        <li
                          key={row.asset}
                          className="kbot-keys__balance-row"
                          data-testid={`keys-balance-${row.asset}`}
                        >
                          <span className="kbot-keys__balance-asset">{row.asset}</span>
                          <span className="kbot-keys__balance-free">{row.free}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <p className="kbot-keys__status" data-testid="keys-balances-unavailable">
                  Holdings are unavailable right now.
                </p>
              )}
              <button
                type="button"
                className="kbot-keys__remove"
                data-testid="keys-remove"
                disabled={controlsDisabled}
                aria-busy={pending || undefined}
                onClick={() => {
                  void handleRemove();
                }}
              >
                {REMOVE_LABEL}
              </button>
            </div>
          ) : (
            <div className="kbot-keys__form" data-testid="keys-form">
              <p className="kbot-keys__absent" data-testid="keys-absent">
                {ABSENT_COPY}
              </p>
              <div className="kbot-keys__row">
                <label className="kbot-keys__label" htmlFor="keys-public">
                  {KEY_LABEL}
                </label>
                <input
                  id="keys-public"
                  data-testid="keys-public"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  value={key}
                  disabled={controlsDisabled}
                  onChange={(event) => setKey(event.target.value)}
                />
              </div>
              <div className="kbot-keys__row">
                <label className="kbot-keys__label" htmlFor="keys-private">
                  {SECRET_LABEL}
                </label>
                <input
                  id="keys-private"
                  data-testid="keys-private"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={secret}
                  disabled={controlsDisabled}
                  onChange={(event) => setSecret(event.target.value)}
                />
              </div>
              <button
                type="button"
                className="kbot-keys__store"
                data-testid="keys-store"
                disabled={controlsDisabled || key.trim() === "" || secret.trim() === ""}
                aria-busy={pending || undefined}
                onClick={() => {
                  void handleStore();
                }}
              >
                {STORE_LABEL}
              </button>
            </div>
          )}
        </>
      ) : null}

      {feedback !== null ? (
        <p className="kbot-keys__feedback" role="status" data-testid="keys-feedback">
          {feedback}
        </p>
      ) : null}
    </section>
  );
}
