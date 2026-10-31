import { useEffect, useRef, useState, type JSX } from "react";
import "../styles/fonts.css";
import "../styles/shell.css";
import "./StatusStrip.signal.css";
import { createHttpClient, type LiveStatus } from "../features/operations/client";
import { useOperationsRefresh } from "../features/operations/useOperationsRefresh";

const ORDERS_UNAVAILABLE_TEXT = "Live orders unavailable";
const KILL_ENGAGED_PREFIX = "Kill switch: engaged";
const KILL_ENGAGED_RULE = "Kill switch engaged";
const NO_REASON_TEXT = "(no reason)";
const VENUES_SUFFIX = " live venues authorized";
const ONE_VENUE_SUFFIX = " live venue authorized";
const PROMOTION_TEXT = "Promotion available";
const NO_VENUES_TEXT = "No live venues authorized";
const ENGAGED_AT_SUFFIX = " UTC";

export type StatusStripProps = {
  /**
   * Live status to reflect. Omitted (or undefined) means the strip owns its
   * read: it performs the same bounded, read-only refresh OperationsView
   * already uses — never a tighter loop, never a state-changing command.
   * `null` means "no successful read yet" and renders the honest
   * unavailable placeholder rather than invented state.
   */
  live?: LiveStatus | null;
};

// A read-only view onto the operations model: the strip needs only the live
// block, so it narrows the full OperationsViewModel the shared refresh hook
// produces instead of declaring a parallel shape. The hook only ever calls
// getOperations; engage/release stay unreachable from this surface.
function SelfReadStatusStripBody(): JSX.Element {
  // The client is a stable read-only adapter; keep one per mount so the
  // refresh effect does not restart on every render.
  const clientRef = useRef(createHttpClient());
  const refresh = useOperationsRefresh(clientRef.current);
  return <StatusStripBody live={refresh.view?.live ?? null} />;
}

// Mounts the read one macrotask after first paint: the shell's synchronous
// first render (and the zero-fetch-on-mount contracts its tests pin) is never
// raced by the strip, while the periodic cadence afterwards is exactly the
// hook's existing interval — no tighter loop is introduced.
function DeferredSelfReadStatusStrip(): JSX.Element {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    const tick = window.setTimeout(() => {
      setArmed(true);
    }, 0);
    return () => {
      window.clearTimeout(tick);
    };
  }, []);
  return armed ? <SelfReadStatusStripBody /> : <StatusStripBody live={null} />;
}

// Largest magnitude Date can represent (±8.64e15 ms); beyond this the
// time value clips to NaN and toISOString would throw RangeError.
const MAX_EPOCH_MS = 8.64e15;

function engagedAtText(engagedAt: number | null): string | null {
  if (engagedAt === null) {
    return null;
  }
  const epochMs = engagedAt * 1000;
  // A NaN/±Infinity or Date-out-of-range engaged_at has no truthful
  // timestamp to show: render without the suffix rather than throw the
  // whole strip away or fabricate a time.
  if (!Number.isFinite(epochMs) || Math.abs(epochMs) > MAX_EPOCH_MS) {
    return null;
  }
  // The server reports epoch seconds; surface it explicitly in UTC so the
  // strip never implies a local-clock claim it cannot verify.
  return (
    new Date(epochMs).toISOString().replace("T", " ").slice(0, 19) +
    ENGAGED_AT_SUFFIX
  );
}

function modeLabel(live: LiveStatus): string {
  // Paper is only honest when the kill switch is released AND nothing is
  // authorized for live; any live authorization or an engaged switch is Live.
  return live.kill_switch.engaged || live.authorized.length > 0 ? "Live" : "Paper";
}

function ordersText(live: LiveStatus): string {
  const { kill_switch: kill, authorized } = live;
  if (kill.engaged) {
    return `${KILL_ENGAGED_PREFIX} — ${kill.reason ?? NO_REASON_TEXT}`;
  }
  if (authorized.length === 1) {
    return `1${ONE_VENUE_SUFFIX}`;
  }
  return authorized.length > 0
    ? `${authorized.length}${VENUES_SUFFIX}`
    : NO_VENUES_TEXT;
}

/**
 * Self-contained top-of-shell status surface. Reflects the operations
 * client's LiveStatus — kill-switch engagement (with reason and timestamp),
 * authorized venue count and promotion availability — without duplicating
 * OperationsView: it renders state only and exposes no engage/release
 * control.
 */
export function StatusStrip({ live }: StatusStripProps = {}): JSX.Element {
  if (live !== undefined) {
    return <StatusStripBody live={live} />;
  }
  return <DeferredSelfReadStatusStrip />;
}

function StatusStripBody({ live }: { live: LiveStatus | null }): JSX.Element {
  const engaged = live?.kill_switch.engaged === true;
  const mode = live ? modeLabel(live) : "Paper";
  const engagedAt = engaged ? engagedAtText(live?.kill_switch.engaged_at ?? null) : null;
  const view = live;
  return (
    <div
      className={engaged ? "kbot-status kbot-status--engaged" : "kbot-status"}
      role="region"
      aria-label={engaged ? "Status — kill switch engaged" : "Status"}
    >
      <span
        className={
          engaged ? "kbot-status__dot kbot-status__dot--engaged" : "kbot-status__dot"
        }
        aria-hidden="true"
      />
      <span className="kbot-status__mode" aria-label={`Mode ${mode}`}>
        {mode}
      </span>
      <span className="kbot-status__divider" aria-hidden="true">·</span>
      {view === null ? (
        <span className="kbot-status__orders" data-testid="live-orders-status">
          {ORDERS_UNAVAILABLE_TEXT}
        </span>
      ) : (
        <>
          <span className="kbot-status__orders" data-testid="live-orders-status">
            {ordersText(view)}
          </span>
          {view.authorized.length > 0 ? (
            <span
              className="kbot-status__venues"
              data-testid="statusstrip-venues"
              title={view.authorized
                .map((grant) => `${grant.venue} ${grant.pair}`)
                .join(", ")}
            >
              {view.authorized.map((grant) => (
                <span
                  key={`${grant.venue}-${grant.pair}`}
                  className="kbot-status__venue"
                  data-testid="statusstrip-venue"
                >
                  {grant.venue}{" "}
                  <span className="kbot-status__pair">{grant.pair}</span>
                </span>
              ))}
            </span>
          ) : null}
          {view.promotion_available ? (
            <span
              className="kbot-status__promotion"
              data-testid="statusstrip-promotion"
            >
              {PROMOTION_TEXT}
            </span>
          ) : null}
        </>
      )}
      {engaged ? (
        <span className="kbot-status__kill" data-testid="statusstrip-kill">
          <span className="kbot-status__kill-label">{KILL_ENGAGED_RULE}</span>
          <span className="kbot-status__kill-reason">
            {view?.kill_switch.reason ?? NO_REASON_TEXT}
          </span>
          {engagedAt !== null ? (
            <span className="kbot-status__kill-at">{engagedAt}</span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
