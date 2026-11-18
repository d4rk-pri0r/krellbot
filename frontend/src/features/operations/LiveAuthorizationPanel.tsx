import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./LiveAuthorizationPanel.signal.css";
import type {
  LiveAuthorizationState,
  LiveAuthorizationView,
  OperationsClient,
} from "./client";
import {
  COINBASE_BTC_USD_VENUE_SYMBOL,
  COINBASE_WAVE_PAIR_OPTIONS,
  coinbaseWavePairLabel,
} from "../../markets/coinbaseBtcUsd";
import {
  KRAKEN_BTC_USD_VENUE_SYMBOL,
  KRAKEN_WAVE_PAIR_OPTIONS,
  krakenWavePairLabel,
} from "../../markets/krakenBtcUsd";
import {
  QUALIFIED_LIVE_VENUES,
  type QualifiedLiveVenue,
} from "../../markets/qualifiedLiveVenues";

const PANEL_TITLE = "Live authorization";
const LOADING_TEXT = "Loading live authorization…";
const LOAD_ERROR_PREFIX = "Could not load live authorization — check the workstation is running.";
const RETRY_TEXT = "Retry";
const EMPTY_TEXT = "No live authorization on file.";
const CONFIRM_LABEL = "Type LIVE to confirm";
const VENUE_LABEL = "Venue";
const PAIR_LABEL = "Pair";
const EXPIRY_LABEL = "Expires in (hours)";
const GRANT_LABEL = "Grant authorization";
const REVOKE_LABEL = "Revoke authorization";
const PAPER_ONLY_HEADING = "Live authorization is disabled in this paper-only release.";
const HELPER_TEXT =
  "Authorizes one exact venue and pair until expiry. Replaces the CLI typed LIVE prompt. For Kraken BTC/USD grant XXBTZUSD (not BTC/USD, BTCUSD, or XBTUSD). For Coinbase BTC/USD grant BTC-USD. Binance is paper-only and is not a live grant venue.";
const DEFAULT_VENUE: QualifiedLiveVenue = "kraken";
const DEFAULT_PAIR = KRAKEN_BTC_USD_VENUE_SYMBOL;
const DEFAULT_HOURS = "24";

function isQualifiedLiveVenue(value: string): value is QualifiedLiveVenue {
  return (QUALIFIED_LIVE_VENUES as readonly string[]).includes(value);
}

function defaultPairForVenue(venue: QualifiedLiveVenue): string {
  return venue === "coinbase" ? COINBASE_BTC_USD_VENUE_SYMBOL : KRAKEN_BTC_USD_VENUE_SYMBOL;
}

type LiveAuthPairOption = {
  readonly venueSymbol: string;
  readonly label: string;
};

function pairOptionsForVenue(venue: QualifiedLiveVenue): readonly LiveAuthPairOption[] {
  if (venue === "coinbase") {
    return COINBASE_WAVE_PAIR_OPTIONS.map((option) => ({
      venueSymbol: option.venueSymbol,
      label: coinbaseWavePairLabel(option.venueSymbol),
    }));
  }
  return KRAKEN_WAVE_PAIR_OPTIONS.map((option) => ({
    venueSymbol: option.venueSymbol,
    label: krakenWavePairLabel(option.venueSymbol),
  }));
}

export type LiveAuthorizationPanelProps = {
  client: OperationsClient;
};

function formatExpiry(expiresAt: number | null): string {
  if (expiresAt === null || !Number.isFinite(expiresAt)) {
    return "—";
  }
  try {
    return new Date(expiresAt * 1000).toISOString();
  } catch {
    return "—";
  }
}

function describeAuthorization(auth: LiveAuthorizationState): string {
  if (!auth.active || auth.grants.length === 0) {
    return EMPTY_TEXT;
  }
  const grant = auth.grants[0];
  return `Authorized: ${grant.venue} ${grant.pair} until ${formatExpiry(auth.expires_at)}`;
}

export function LiveAuthorizationPanel({ client }: LiveAuthorizationPanelProps): JSX.Element {
  const [view, setView] = useState<LiveAuthorizationView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [venue, setVenue] = useState<QualifiedLiveVenue>(DEFAULT_VENUE);
  const [pair, setPair] = useState(DEFAULT_PAIR);
  const [hours, setHours] = useState(DEFAULT_HOURS);
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const requestRef = useRef(0);
  const inFlight = useRef(false);

  const load = useCallback(async (): Promise<void> => {
    if (typeof client.getLiveAuthorization !== "function") {
      setView({
        schema_version: "1",
        authorization: { active: false, expires_at: null, grants: [] },
        release_policy: "paper_only",
        release_policy_code: "live_disabled_paper_only_release",
        release_policy_message:
          "This release is a paper-only release: live order send is disabled regardless of environment, stored keys, or authorization. This is temporary; an owner-approved code change can re-enable live trading.",
        confirmation_required: "LIVE",
      });
      setError(null);
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.getLiveAuthorization();
      if (requestId !== requestRef.current) {
        return;
      }
      setView(next);
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
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const paperOnly = view?.release_policy === "paper_only";
  const requiredConfirm = view?.confirmation_required ?? "LIVE";
  const controlsDisabled = paperOnly || pending || loading;

  const handleGrant = useCallback(async (): Promise<void> => {
    if (
      inFlight.current ||
      paperOnly ||
      typeof client.grantLiveAuthorization !== "function" ||
      confirmation.trim() !== requiredConfirm
    ) {
      return;
    }
    const hoursNum = Number(hours);
    if (!Number.isFinite(hoursNum) || hoursNum <= 0) {
      setFeedback("Expires in (hours) must be a positive number.");
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    try {
      const expiresAt = Math.floor(Date.now() / 1000) + Math.floor(hoursNum * 3600);
      const result = await client.grantLiveAuthorization(venue, pair, expiresAt, confirmation);
      setFeedback(
        typeof result.message === "string"
          ? result.message
          : result.ok
            ? "Live authorization granted."
            : "Live authorization refused.",
      );
      await load();
    } catch (err) {
      setFeedback(`Grant failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [client, confirmation, hours, load, pair, paperOnly, requiredConfirm, venue]);

  const handleRevoke = useCallback(async (): Promise<void> => {
    if (inFlight.current || paperOnly || typeof client.revokeLiveAuthorization !== "function") {
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    try {
      const result = await client.revokeLiveAuthorization();
      setFeedback(
        typeof result.message === "string"
          ? result.message
          : result.ok
            ? "Live authorization revoked."
            : "Revoke refused.",
      );
      await load();
    } catch (err) {
      setFeedback(`Revoke failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [client, load, paperOnly]);

  return (
    <div className="kbot-ops__live-auth" data-testid="ops-live-authorization">
      <div className="kbot-ops__live-auth-head">
        <h3 className="kbot-ops__panel-title">{PANEL_TITLE}</h3>
        <button
          type="button"
          className="kbot-ops__live-auth-refresh"
          data-testid="ops-live-auth-refresh"
          disabled={pending || loading}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Loading…" : RETRY_TEXT}
        </button>
      </div>

      {loading && view === null ? (
        <p className="kbot-ops__live-auth-status" data-testid="ops-live-auth-loading">
          {LOADING_TEXT}
        </p>
      ) : null}

      {error !== null ? (
        <p className="kbot-ops__live-auth-error" role="alert" data-testid="ops-live-auth-error">
          {LOAD_ERROR_PREFIX} ({error})
        </p>
      ) : null}

      {view !== null ? (
        <>
          {paperOnly ? (
            <p
              className="kbot-ops__live-auth-paper-only"
              role="status"
              data-testid="ops-live-auth-paper-only"
            >
              <span data-testid="ops-live-auth-paper-only-heading">{PAPER_ONLY_HEADING}</span>{" "}
              <span data-testid="ops-live-auth-paper-only-reason">
                {view.release_policy_message ??
                  "Live order send is disabled in this paper-only release."}
              </span>
            </p>
          ) : null}

          <p className="kbot-ops__live-auth-status" data-testid="ops-live-auth-status">
            {describeAuthorization(view.authorization)}
          </p>

          <div className="kbot-ops__live-auth-form" data-testid="ops-live-auth-form">
            <div className="kbot-ops__live-auth-row">
              <label className="kbot-ops__live-auth-label" htmlFor="ops-live-auth-venue">
                {VENUE_LABEL}
              </label>
              <select
                id="ops-live-auth-venue"
                data-testid="ops-live-auth-venue"
                value={venue}
                disabled={controlsDisabled}
                onChange={(event) => {
                  const next = event.target.value;
                  if (!isQualifiedLiveVenue(next)) {
                    return;
                  }
                  setVenue(next);
                  setPair(defaultPairForVenue(next));
                }}
              >
                {QUALIFIED_LIVE_VENUES.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </div>
            <div className="kbot-ops__live-auth-row">
              <label className="kbot-ops__live-auth-label" htmlFor="ops-live-auth-pair">
                {PAIR_LABEL}
              </label>
              <select
                id="ops-live-auth-pair"
                data-testid="ops-live-auth-pair"
                value={pair}
                disabled={controlsDisabled}
                onChange={(event) => setPair(event.target.value)}
              >
                {pairOptionsForVenue(venue).map((option) => (
                  <option key={option.venueSymbol} value={option.venueSymbol}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="kbot-ops__live-auth-row">
              <label className="kbot-ops__live-auth-label" htmlFor="ops-live-auth-hours">
                {EXPIRY_LABEL}
              </label>
              <input
                id="ops-live-auth-hours"
                data-testid="ops-live-auth-hours"
                type="number"
                min={1}
                step={1}
                value={hours}
                disabled={controlsDisabled}
                onChange={(event) => setHours(event.target.value)}
              />
            </div>
            <div className="kbot-ops__live-auth-row">
              <label className="kbot-ops__live-auth-label" htmlFor="ops-live-auth-confirm">
                {CONFIRM_LABEL}
              </label>
              <input
                id="ops-live-auth-confirm"
                data-testid="ops-live-auth-confirm"
                type="text"
                value={confirmation}
                disabled={controlsDisabled}
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => setConfirmation(event.target.value)}
                placeholder={requiredConfirm}
              />
            </div>
            <div className="kbot-ops__live-auth-buttons">
              <button
                type="button"
                className="kbot-ops__live-auth-grant"
                data-testid="ops-live-auth-grant"
                disabled={
                  controlsDisabled ||
                  confirmation.trim() !== requiredConfirm ||
                  venue.trim() === "" ||
                  pair.trim() === ""
                }
                aria-busy={pending || undefined}
                onClick={() => {
                  void handleGrant();
                }}
              >
                {GRANT_LABEL}
              </button>
              <button
                type="button"
                className="kbot-ops__live-auth-revoke"
                data-testid="ops-live-auth-revoke"
                disabled={controlsDisabled || !view.authorization.active}
                aria-busy={pending || undefined}
                onClick={() => {
                  void handleRevoke();
                }}
              >
                {REVOKE_LABEL}
              </button>
            </div>
          </div>

          {feedback !== null ? (
            <p className="kbot-ops__live-auth-feedback" role="status" data-testid="ops-live-auth-feedback">
              {feedback}
            </p>
          ) : null}

          <p className="kbot-ops__live-auth-helper">{HELPER_TEXT}</p>
        </>
      ) : null}
    </div>
  );
}
