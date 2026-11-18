import { useEffect, useRef, useState, type JSX } from "react";
import {
  channelMatchesSigning,
  createVersionHttpClient,
  type VersionClient,
  type VersionInfo,
} from "../api/version";
import "./AboutPanel.signal.css";

export type AboutPanelProps = {
  /** Injectable version client; defaults to the loopback HTTP client. */
  client?: VersionClient;
  /** When false, skip the network read (session still starting). */
  enabled?: boolean;
};

const EVIDENCE_DOC_URL =
  "https://github.com/d4rkpr10r-Labs/krellbot/blob/main/docs/evidence.md";
const SIGNING_DOC_URL =
  "https://github.com/d4rkpr10r-Labs/krellbot/blob/main/docs/signing.md";
const SITE_SECURITY_URL = "https://krellbot.dev/docs/security.html";

function channelLabel(channel: VersionInfo["channel"]): string {
  return channel === "ga" ? "GA" : "Prerelease";
}

function signingLabel(signed: boolean): string {
  return signed ? "Signed artifacts" : "Unsigned artifacts";
}

/**
 * About / version + evidence surface (KRELL-SIGNAL-20261010).
 *
 * Surfaces the engine version string and release-channel honesty from
 * ``GET /api/v1/version``, plus the M19.2 install-evidence copy contract
 * (pinned digest, signing posture, reproduce a starter pack). Never invents
 * a GA claim while artifacts are unsigned.
 */
export function AboutPanel({
  client,
  enabled = true,
}: AboutPanelProps): JSX.Element {
  const fallbackRef = useRef<VersionClient | null>(null);
  if (fallbackRef.current === null && client === undefined) {
    fallbackRef.current = createVersionHttpClient();
  }
  const versionClient = client ?? fallbackRef.current!;
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void versionClient
      .getVersion()
      .then((payload) => {
        if (cancelled) return;
        if (!channelMatchesSigning(payload)) {
          setInfo(null);
          setError("Release channel claim does not match signing state");
          return;
        }
        setInfo(payload);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setInfo(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, versionClient]);

  const unsigned =
    info !== null ? info.artifacts_signed === false : true;

  return (
    <section
      className="kbot-about"
      aria-labelledby="kbot-about-title"
      data-testid="app-home-about"
    >
      <h2 className="kbot-about__title" id="kbot-about-title">
        About
      </h2>
      {loading ? (
        <p className="kbot-about__copy" data-testid="app-home-about-loading">
          Reading version…
        </p>
      ) : null}
      {error !== null ? (
        <p
          className="kbot-about__copy kbot-about__copy--caution"
          data-testid="app-home-about-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      {info !== null ? (
        <dl className="kbot-about__facts" data-testid="app-home-about-facts">
          <div className="kbot-about__row">
            <dt>Version</dt>
            <dd data-testid="app-home-about-version">v{info.version}</dd>
          </div>
          <div className="kbot-about__row">
            <dt>Channel</dt>
            <dd data-testid="app-home-about-channel">
              {channelLabel(info.channel)}
            </dd>
          </div>
          <div className="kbot-about__row">
            <dt>Signing</dt>
            <dd data-testid="app-home-about-signing">
              {signingLabel(info.artifacts_signed)}
            </dd>
          </div>
        </dl>
      ) : null}
      {!loading && error === null && info === null ? (
        <p className="kbot-about__copy" data-testid="app-home-about-empty">
          Version unavailable.
        </p>
      ) : null}
      <p className="kbot-about__copy">
        Public GA releases require signed artifacts. This surface reports the
        channel the engine claims, not a marketing label.
      </p>

      <section
        className="kbot-about__evidence"
        aria-labelledby="kbot-about-evidence-title"
        data-testid="app-home-about-evidence"
      >
        <h3
          className="kbot-about__subtitle"
          id="kbot-about-evidence-title"
        >
          Install evidence
        </h3>
        <dl className="kbot-about__facts">
          <div className="kbot-about__row">
            <dt>Digest</dt>
            <dd data-testid="app-home-about-digest">
              HTTPS-pinned SHA-256 before extract (pins zip bytes; not a
              publisher signature)
            </dd>
          </div>
          <div className="kbot-about__row">
            <dt>Posture</dt>
            <dd data-testid="app-home-about-posture">
              {unsigned
                ? "Unsigned prerelease — ARTIFACTS_SIGNED is False; Gatekeeper / SmartScreen may warn on first run"
                : "Signed artifacts claimed by this build — confirm release notes and docs/signing.md"}
            </dd>
          </div>
        </dl>
        <p
          className={
            unsigned
              ? "kbot-about__copy kbot-about__copy--caution"
              : "kbot-about__copy"
          }
          data-testid="app-home-about-signing-honesty"
        >
          {unsigned
            ? "Do not treat this cut as signed GA. A digest pin is integrity, not notarization or Authenticode."
            : "Signed channel claims still need the published cut’s notes; this rail does not invent market performance."}
        </p>

        <h3 className="kbot-about__subtitle" id="kbot-about-reproduce-title">
          Reproduce a starter pack
        </h3>
        <ol
          className="kbot-about__steps"
          data-testid="app-home-about-reproduce"
        >
          <li>
            Open <strong>Strategies</strong>, choose a free starter example,
            then <strong>Save</strong> and <strong>Validate</strong>.
          </li>
          <li>
            Paper-arm with venue <code>kraken</code> and starting balance{" "}
            <code>1000</code>, then <strong>Arm</strong> (simulated cash).
          </li>
          <li>
            Confirm <strong>Operations</strong> shows <code>paper</code> /{" "}
            <code>active</code> with live trading disabled. Optional: pin a
            Research backtest on fixed local data.
          </li>
        </ol>
        <p className="kbot-about__copy" data-testid="app-home-about-no-perf">
          Starter, fixture, and paper results are not market performance.
        </p>
        <p className="kbot-about__links" data-testid="app-home-about-links">
          <a href={EVIDENCE_DOC_URL} target="_blank" rel="noreferrer">
            Evidence contract
          </a>
          <span aria-hidden="true"> · </span>
          <a href={SIGNING_DOC_URL} target="_blank" rel="noreferrer">
            Signing posture
          </a>
          <span aria-hidden="true"> · </span>
          <a href={SITE_SECURITY_URL} target="_blank" rel="noreferrer">
            Site security
          </a>
        </p>
      </section>
    </section>
  );
}
