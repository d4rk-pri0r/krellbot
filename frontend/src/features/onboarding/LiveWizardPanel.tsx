import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import { KeysOnboardingPanel } from "../keys/KeysOnboardingPanel";
import type { KeysClient } from "../keys/client";
import type { LiveWizardHonesty, TrustClient } from "./client";
import "./LiveWizardPanel.signal.css";

type WizardStep = "welcome" | "security" | "exchange" | "live";

const STEPS: ReadonlyArray<{ id: WizardStep; label: string }> = [
  { id: "welcome", label: "Welcome" },
  { id: "security", label: "Security" },
  { id: "exchange", label: "Exchange" },
  { id: "live", label: "Live state" },
];

const PANEL_TITLE = "Live-ready path";
const HELPER =
  "Local path toward live: trust posture, trade-only key probe, then honest paper-only release versus live grant. No license ask. Keys stay on this machine.";

const WELCOME_TRUTHS: ReadonlyArray<string> = [
  "The engine is free and open-source.",
  "Exchange keys are stored locally in the OS keychain and are not sent to krellbot.dev.",
  "Official packs are optional and recommended; this path never asks for a license token.",
];

const KEY_PERM_REQUIREMENT =
  "Trade-only permission required, withdraw permission never granted. No exchange key is probed from the Security step.";

export type LiveWizardPanelProps = {
  trustClient: TrustClient;
  keysClient: KeysClient;
  enabled?: boolean;
};

function describeGrant(view: LiveWizardHonesty): string {
  if (!view.live_grant_active || view.live_grant.grants.length === 0) {
    return "No live grant on file.";
  }
  const grant = view.live_grant.grants[0];
  const until =
    view.live_grant.expires_at != null
      ? new Date(view.live_grant.expires_at * 1000).toISOString()
      : "unknown expiry";
  return `Grant on file: ${grant.venue} ${grant.pair} until ${until}. A grant is not live order send.`;
}

export function LiveWizardPanel({
  trustClient,
  keysClient,
  enabled = true,
}: LiveWizardPanelProps): JSX.Element {
  const [step, setStep] = useState<WizardStep>("welcome");
  const [view, setView] = useState<LiveWizardHonesty | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(async (): Promise<void> => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await trustClient.getTrust();
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
  }, [enabled, trustClient]);

  useEffect(() => {
    void load();
  }, [load]);

  const stepIndex = STEPS.findIndex((s) => s.id === step);
  const trust = view?.trust;

  return (
    <section
      className="kbot-live-wizard"
      aria-labelledby="live-wizard-title"
      data-testid="live-wizard"
    >
      <h3 className="kbot-live-wizard__title" id="live-wizard-title">
        {PANEL_TITLE}
      </h3>
      <p className="kbot-live-wizard__helper">{HELPER}</p>

      <ul className="kbot-live-wizard__steps" aria-label="Wizard steps">
        {STEPS.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="kbot-live-wizard__step-btn"
              data-testid={`live-wizard-step-${item.id}`}
              aria-current={step === item.id ? "step" : undefined}
              onClick={() => {
                setStep(item.id);
              }}
            >
              {item.label}
            </button>
          </li>
        ))}
      </ul>

      {step === "welcome" ? (
        <div
          className="kbot-live-wizard__panel"
          data-testid="live-wizard-welcome"
        >
          <h4 className="kbot-live-wizard__panel-title">Welcome</h4>
          <p className="kbot-live-wizard__panel-copy">
            Read-only orientation. Nothing posts a preference from this step.
          </p>
          <ul className="kbot-live-wizard__list">
            {WELCOME_TRUTHS.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p
            className="kbot-live-wizard__panel-copy"
            data-testid="live-wizard-no-license"
          >
            No license token is collected on this path.
          </p>
        </div>
      ) : null}

      {step === "security" ? (
        <div
          className="kbot-live-wizard__panel"
          data-testid="live-wizard-security"
        >
          <h4 className="kbot-live-wizard__panel-title">Security posture</h4>
          <p className="kbot-live-wizard__panel-copy">
            Local trust snapshot from this machine. No venue probe and no
            credential read on this step.
          </p>
          {loading ? (
            <p className="kbot-live-wizard__loading" data-testid="live-wizard-loading">
              Reading trust snapshot…
            </p>
          ) : null}
          {error ? (
            <p className="kbot-live-wizard__error" data-testid="live-wizard-error">
              {error}
            </p>
          ) : null}
          {trust ? (
            <>
              <p
                className={
                  trust.posture_ok
                    ? "kbot-live-wizard__banner kbot-live-wizard__banner--ok"
                    : "kbot-live-wizard__banner"
                }
                data-testid="live-wizard-posture"
              >
                {trust.posture_ok
                  ? "Aggregate posture looks private on this machine."
                  : `${trust.posture_warning ?? "Posture issue detected"}. Run krellbot doctor.`}
              </p>
              <ul className="kbot-live-wizard__rows">
                <li className="kbot-live-wizard__row">
                  <span className="kbot-live-wizard__row-label">Keychain backend</span>
                  <span
                    className="kbot-live-wizard__row-value"
                    data-testid="live-wizard-keychain"
                  >
                    {trust.keychain_backend ?? "(none)"}
                    {trust.keychain_ok ? "" : " — not persistent"}
                  </span>
                </li>
                <li className="kbot-live-wizard__row">
                  <span className="kbot-live-wizard__row-label">Home</span>
                  <span
                    className="kbot-live-wizard__row-value"
                    data-testid="live-wizard-home"
                  >
                    {trust.home}
                  </span>
                </li>
                <li className="kbot-live-wizard__row">
                  <span className="kbot-live-wizard__row-label">Home mode</span>
                  <span
                    className="kbot-live-wizard__row-value"
                    data-testid="live-wizard-home-mode"
                  >
                    {trust.home_mode ?? "unknown / not readable"}
                    {trust.home_mode_ok ? "" : " (expected 0o700)"}
                  </span>
                </li>
                <li className="kbot-live-wizard__row">
                  <span className="kbot-live-wizard__row-label">Bind</span>
                  <span
                    className="kbot-live-wizard__row-value"
                    data-testid="live-wizard-bind"
                  >
                    {trust.bind}
                  </span>
                </li>
                <li className="kbot-live-wizard__row">
                  <span className="kbot-live-wizard__row-label">Live arm UI</span>
                  <span
                    className="kbot-live-wizard__row-value"
                    data-testid="live-wizard-arm-ui"
                  >
                    {trust.live_arm_ui_allowed ? "allowed" : "not allowed"}
                  </span>
                </li>
                <li className="kbot-live-wizard__row">
                  <span className="kbot-live-wizard__row-label">Key permissions</span>
                  <span
                    className="kbot-live-wizard__row-value"
                    data-testid="live-wizard-key-requirement"
                  >
                    {KEY_PERM_REQUIREMENT}
                  </span>
                </li>
              </ul>
            </>
          ) : null}
        </div>
      ) : null}

      {step === "exchange" ? (
        <div
          className="kbot-live-wizard__panel"
          data-testid="live-wizard-exchange"
        >
          <h4 className="kbot-live-wizard__panel-title">Exchange</h4>
          <p className="kbot-live-wizard__panel-copy">
            One credentialed trade-only probe-and-store. Status is stored-key
            history, never a live connection claim. No license field.
          </p>
          <KeysOnboardingPanel
            client={keysClient}
            venue="kraken"
            enabled={enabled}
          />
        </div>
      ) : null}

      {step === "live" ? (
        <div className="kbot-live-wizard__panel" data-testid="live-wizard-live">
          <h4 className="kbot-live-wizard__panel-title">Paper-only vs live grant</h4>
          <p className="kbot-live-wizard__panel-copy">
            These are separate rails. A stored key or a grant file does not
            make this workstation live-ready while the paper-only release is
            active.
          </p>
          {loading ? (
            <p className="kbot-live-wizard__loading">Reading live state…</p>
          ) : null}
          {error ? (
            <p className="kbot-live-wizard__error">{error}</p>
          ) : null}
          {view ? (
            <div className="kbot-live-wizard__state">
              <p
                className="kbot-live-wizard__state-chip"
                data-testid="live-wizard-paper-only"
              >
                <strong>Paper-only release:</strong>{" "}
                {view.paper_only_release
                  ? view.release_policy_message ||
                    "Live order send is disabled in this paper-only release."
                  : "Release policy allows live (owner flip)."}
              </p>
              <p
                className="kbot-live-wizard__state-chip"
                data-testid="live-wizard-grant"
              >
                <strong>Live grant:</strong> {describeGrant(view)}
              </p>
              <p
                className="kbot-live-wizard__state-chip"
                data-testid="live-wizard-live-ready"
              >
                Live-ready claim: no
              </p>
              <p
                className="kbot-live-wizard__state-chip"
                data-testid="live-wizard-keys-local"
              >
                Keys leave this machine:{" "}
                {view.keys_leave_machine ? "yes" : "no"}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="kbot-live-wizard__nav">
        <button
          type="button"
          className="kbot-live-wizard__nav-btn"
          data-testid="live-wizard-back"
          disabled={stepIndex <= 0}
          onClick={() => {
            if (stepIndex > 0) {
              setStep(STEPS[stepIndex - 1].id);
            }
          }}
        >
          Back
        </button>
        <button
          type="button"
          className="kbot-live-wizard__nav-btn kbot-live-wizard__nav-btn--primary"
          data-testid="live-wizard-next"
          disabled={stepIndex >= STEPS.length - 1}
          onClick={() => {
            if (stepIndex < STEPS.length - 1) {
              setStep(STEPS[stepIndex + 1].id);
            }
          }}
        >
          Next
        </button>
      </div>
    </section>
  );
}
