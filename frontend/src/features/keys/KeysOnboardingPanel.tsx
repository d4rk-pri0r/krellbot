import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./KeysOnboardingPanel.signal.css";
import type { KeysClient, KeysStatus, KeysVenue } from "./client";
import { KEYS_VENUE } from "./client";

type VenueCopy = {
  title: string;
  helper: string;
  loading: string;
  loadErrorPrefix: string;
  keyLabel: string;
  secretLabel: string;
  absent: string;
  secretMultiline: boolean;
};

const VENUE_COPY: Record<KeysVenue, VenueCopy> = {
  kraken: {
    title: "Kraken exchange key",
    helper:
      "Probe a trade-only Kraken key (withdraw off; unknown permissions fail closed), store it in this machine’s OS keychain, then review stored status and free holdings. Status here is not a live connection claim. Live order send stays disabled in this paper-only release.",
    loading: "Reading Kraken key status…",
    loadErrorPrefix:
      "Could not read Kraken key status — check the workstation is running.",
    keyLabel: "Public key",
    secretLabel: "Private key",
    absent:
      "No Kraken key is stored on this machine yet. Enter trade-only key material below.",
    secretMultiline: false,
  },
  coinbase: {
    title: "Coinbase exchange key",
    helper:
      "Probe a trade-only Coinbase Advanced Trade key (withdraw/transfer off), store it in this machine’s OS keychain, then review stored status and free holdings. Status here is not a live connection claim. Live order send stays disabled in this paper-only release.",
    loading: "Reading Coinbase key status…",
    loadErrorPrefix:
      "Could not read Coinbase key status — check the workstation is running.",
    keyLabel: "API key name",
    secretLabel: "Private key (PEM)",
    absent:
      "No Coinbase key is stored on this machine yet. Enter trade-only key material below.",
    secretMultiline: true,
  },
};

const STORE_LABEL = "Probe and store";
const REMOVE_LABEL = "Remove key";
const REFRESH_LABEL = "Refresh";
const PAPER_ONLY_NOTE =
  "Storing a key does not enable live trading in this paper-only release.";

export type KeysOnboardingPanelProps = {
  client: KeysClient;
  /** Venue this panel manages. Defaults to Kraken for single-panel callers. */
  venue?: KeysVenue;
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
  venue = KEYS_VENUE,
  enabled = true,
}: KeysOnboardingPanelProps): JSX.Element {
  const copy = VENUE_COPY[venue];
  const [status, setStatus] = useState<KeysStatus | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const requestRef = useRef(0);
  const inFlight = useRef(false);

  const publicId = `keys-public-${venue}`;
  const privateId = `keys-private-${venue}`;
  const titleId = `keys-onboarding-title-${venue}`;

  const load = useCallback(async (): Promise<void> => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.getStatus(venue);
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
  }, [client, enabled, venue]);

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
      setFeedback(
        venue === "coinbase"
          ? "Enter both the API key name and the private key."
          : "Enter both the public key and the private key.",
      );
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    try {
      const result = await client.probeAndStore(trimmedKey, trimmedSecret, venue);
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
  }, [client, enabled, key, load, secret, venue]);

  const handleRemove = useCallback(async (): Promise<void> => {
    if (inFlight.current || !enabled) {
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    try {
      const result = await client.remove(venue);
      setFeedback(result.message);
      await load();
    } catch (err) {
      setFeedback(`Remove failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [client, enabled, load, venue]);

  const controlsDisabled = !enabled || pending || loading;
  const present = status?.present === true && status.corrupt !== true;

  return (
    <section
      className="kbot-keys"
      data-testid={`keys-onboarding-${venue}`}
      data-venue={venue}
      aria-labelledby={titleId}
    >
      <div className="kbot-keys__head">
        <h2 className="kbot-keys__title" id={titleId}>
          {copy.title}
        </h2>
        <button
          type="button"
          className="kbot-keys__refresh"
          data-testid={`keys-refresh-${venue}`}
          disabled={controlsDisabled}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Loading…" : REFRESH_LABEL}
        </button>
      </div>

      <p className="kbot-keys__helper">{copy.helper}</p>
      <p className="kbot-keys__paper-only" data-testid={`keys-paper-only-${venue}`}>
        {PAPER_ONLY_NOTE}
      </p>

      {!enabled ? (
        <p
          className="kbot-keys__status"
          data-testid={`keys-waiting-session-${venue}`}
          role="status"
        >
          Waiting for the local session before reading key status.
        </p>
      ) : null}

      {enabled && loading && status === null ? (
        <p className="kbot-keys__status" data-testid={`keys-loading-${venue}`} role="status">
          {copy.loading}
        </p>
      ) : null}

      {error !== null ? (
        <p className="kbot-keys__error" role="alert" data-testid={`keys-error-${venue}`}>
          {copy.loadErrorPrefix} ({error})
        </p>
      ) : null}

      {status !== null ? (
        <>
          <p className="kbot-keys__status" data-testid={`keys-status-${venue}`} role="status">
            {describeStatus(status)}
            {status.backend_label ? ` · ${status.backend_label}` : ""}
          </p>

          {present ? (
            <div className="kbot-keys__stored" data-testid={`keys-stored-${venue}`}>
              {status.balances_available && status.balances !== null ? (
                <div data-testid={`keys-balances-${venue}`}>
                  <h3 className="kbot-keys__balances-title">Free holdings</h3>
                  {status.balances.length === 0 ? (
                    <p
                      className="kbot-keys__status"
                      data-testid={`keys-balances-empty-${venue}`}
                    >
                      No free holdings reported.
                    </p>
                  ) : (
                    <ul className="kbot-keys__balances-list">
                      {status.balances.map((row) => (
                        <li
                          key={row.asset}
                          className="kbot-keys__balance-row"
                          data-testid={`keys-balance-${venue}-${row.asset}`}
                        >
                          <span className="kbot-keys__balance-asset">{row.asset}</span>
                          <span className="kbot-keys__balance-free">{row.free}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <p
                  className="kbot-keys__status"
                  data-testid={`keys-balances-unavailable-${venue}`}
                >
                  Holdings are unavailable right now.
                </p>
              )}
              <button
                type="button"
                className="kbot-keys__remove"
                data-testid={`keys-remove-${venue}`}
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
            <div className="kbot-keys__form" data-testid={`keys-form-${venue}`}>
              <p className="kbot-keys__absent" data-testid={`keys-absent-${venue}`}>
                {copy.absent}
              </p>
              <div className="kbot-keys__row">
                <label className="kbot-keys__label" htmlFor={publicId}>
                  {copy.keyLabel}
                </label>
                <input
                  id={publicId}
                  data-testid={`keys-public-${venue}`}
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  value={key}
                  disabled={controlsDisabled}
                  onChange={(event) => setKey(event.target.value)}
                />
              </div>
              <div className="kbot-keys__row">
                <label className="kbot-keys__label" htmlFor={privateId}>
                  {copy.secretLabel}
                </label>
                {copy.secretMultiline ? (
                  <textarea
                    id={privateId}
                    data-testid={`keys-private-${venue}`}
                    className="kbot-keys__secret-area"
                    autoComplete="off"
                    spellCheck={false}
                    rows={4}
                    value={secret}
                    disabled={controlsDisabled}
                    onChange={(event) => setSecret(event.target.value)}
                  />
                ) : (
                  <input
                    id={privateId}
                    data-testid={`keys-private-${venue}`}
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={secret}
                    disabled={controlsDisabled}
                    onChange={(event) => setSecret(event.target.value)}
                  />
                )}
              </div>
              <button
                type="button"
                className="kbot-keys__store"
                data-testid={`keys-store-${venue}`}
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
        <p
          className="kbot-keys__feedback"
          role="status"
          data-testid={`keys-feedback-${venue}`}
        >
          {feedback}
        </p>
      ) : null}
    </section>
  );
}
