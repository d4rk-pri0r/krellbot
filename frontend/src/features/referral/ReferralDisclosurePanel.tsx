import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import {
  REFERRAL_DISCLOSURE_BODY,
  REFERRAL_DISCLOSURE_HEADLINE,
} from "./copy";
import type { ReferralClient, ReferralStatus } from "./client";
import "./ReferralDisclosurePanel.signal.css";

export type ReferralDisclosurePanelProps = {
  client: ReferralClient;
  /** When false, skip network reads (session still starting or failed). */
  enabled?: boolean;
};

/**
 * Settings disclosure for exchange fee share / referral (M23.1).
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Status is fetched only while the Settings disclosure body is open (or
 * when mounted outside a disclosure). Collapsed mount must not hit the
 * network — shell bootstrap tests stub a closed allow-list of routes.
 */
export function ReferralDisclosurePanel({
  client,
  enabled = true,
}: ReferralDisclosurePanelProps): JSX.Element {
  const rootRef = useRef<HTMLElement | null>(null);
  // Start closed; open after we see no disclosure parent (standalone) or
  // the Settings body is un-hidden — avoids bootstrap fetches while collapsed.
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const [status, setStatus] = useState<ReferralStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [venue, setVenue] = useState<"kraken" | "coinbase">("kraken");
  const requestRef = useRef(0);
  const inFlight = useRef(false);

  useEffect(() => {
    const node = rootRef.current;
    const body = node?.closest(".kbot-disclosure__body") as HTMLElement | null;
    if (!body) {
      setDisclosureOpen(true);
      return;
    }
    const sync = (): void => {
      setDisclosureOpen(!body.hasAttribute("hidden"));
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(body, { attributes: true, attributeFilter: ["hidden"] });
    return () => {
      observer.disconnect();
    };
  }, []);

  const load = useCallback(async (): Promise<void> => {
    if (!enabled || !disclosureOpen) {
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.getStatus();
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
  }, [client, disclosureOpen, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  const attributeSignup = useCallback(async (): Promise<void> => {
    if (!enabled || !disclosureOpen || inFlight.current) {
      return;
    }
    inFlight.current = true;
    setPending(true);
    setFeedback(null);
    setError(null);
    try {
      const result = await client.attribute({
        kind: "exchange_signup",
        venue,
      });
      setFeedback(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [client, disclosureOpen, enabled, load, venue]);

  const headline = status?.headline || REFERRAL_DISCLOSURE_HEADLINE;
  const body = status?.body || REFERRAL_DISCLOSURE_BODY;
  const busy = pending || loading;

  return (
    <div
      ref={(node) => {
        rootRef.current = node;
      }}
      className="kbot-referral"
      data-testid="referral-disclosure-panel"
    >
      <h3 className="kbot-referral__title" id="referral-disclosure-title">
        {headline}
      </h3>
      <p className="kbot-referral__body" data-testid="referral-disclosure-body">
        {body}
      </p>
      <p className="kbot-referral__note">
        Recording attribution leaves a local receipt on this machine and may
        notify the disclosed fee-share path. Exchange credentials never leave
        the OS keychain.
      </p>

      <label className="kbot-referral__label" htmlFor="referral-venue">
        Exchange referral path
      </label>
      <select
        id="referral-venue"
        className="kbot-referral__select"
        data-testid="referral-venue"
        value={venue}
        disabled={busy || !enabled || !disclosureOpen}
        onChange={(event) => {
          const next = event.target.value;
          if (next === "kraken" || next === "coinbase") {
            setVenue(next);
          }
        }}
      >
        <option value="kraken">Kraken</option>
        <option value="coinbase">Coinbase</option>
      </select>

      <button
        type="button"
        className="kbot-referral__action"
        data-testid="referral-attribute-exchange"
        disabled={busy || !enabled || !disclosureOpen}
        onClick={() => {
          void attributeSignup();
        }}
      >
        {pending ? "Recording…" : "Record disclosed referral attribution"}
      </button>

      {loading && status === null ? (
        <p
          className="kbot-referral__status"
          role="status"
          data-testid="referral-loading"
        >
          Loading referral status…
        </p>
      ) : null}

      {error !== null ? (
        <p
          className="kbot-referral__error"
          role="alert"
          data-testid="referral-error"
        >
          {error}
        </p>
      ) : null}

      {feedback !== null ? (
        <p
          className="kbot-referral__status"
          role="status"
          data-testid="referral-feedback"
        >
          {feedback}
        </p>
      ) : null}

      {status !== null ? (
        <p
          className="kbot-referral__count"
          data-testid="referral-receipt-count"
        >
          Local receipts: {status.receipt_count}
        </p>
      ) : null}
    </div>
  );
}
