import {
  useCallback,
  useId,
  useRef,
  useState,
  type FormEvent,
  type JSX,
} from "react";
import type {
  ActivationRedeemResult,
  PackLibraryClient,
  RefundResult,
} from "./client";
import { PackLibraryHttpError } from "./client";
import "./PackLibrary.signal.css";

export type PackBillingClient = Pick<PackLibraryClient, "redeemActivation"> & {
  requestRefund?(sku: string): Promise<RefundResult>;
};

export type PackBillingFormsProps = {
  client: PackBillingClient;
  /** Optional callback fired after a successful redeem or refund. */
  onUpdated?: () => void;
};

function isRedeemSuccess(result: ActivationRedeemResult): boolean {
  return result.status === "paid" || result.status === "grace";
}

/**
 * Activation key redemption and paid pack refund request forms.
 * Mounted under Settings → Trust & billing so Packs stays catalogue-first.
 */
export function PackBillingForms({
  client,
  onUpdated,
}: PackBillingFormsProps): JSX.Element {
  const [activationKey, setActivationKey] = useState("");
  const [redeemPending, setRedeemPending] = useState(false);
  const [redeemFeedback, setRedeemFeedback] = useState<string | null>(null);
  const [redeemError, setRedeemError] = useState<string | null>(null);
  const [refundSku, setRefundSku] = useState("");
  const [refundPending, setRefundPending] = useState(false);
  const [refundFeedback, setRefundFeedback] = useState<string | null>(null);
  const [refundError, setRefundError] = useState<string | null>(null);
  const redeemInFlight = useRef(false);
  const refundInFlight = useRef(false);
  const redeemKeyId = useId();
  const refundSkuId = useId();
  const canRequestRefund = typeof client.requestRefund === "function";

  const handleRedeem = useCallback(
    async (event: FormEvent<HTMLFormElement>): Promise<void> => {
      event.preventDefault();
      if (redeemInFlight.current) {
        return;
      }
      const trimmed = activationKey.trim();
      if (trimmed === "") {
        setRedeemFeedback(null);
        setRedeemError("Enter an activation key to redeem.");
        return;
      }
      redeemInFlight.current = true;
      setRedeemPending(true);
      setRedeemFeedback(null);
      setRedeemError(null);
      try {
        const result = await client.redeemActivation(trimmed);
        // Never surface the submitted key; only the closed server message.
        if (isRedeemSuccess(result)) {
          setActivationKey("");
          setRedeemFeedback(result.message);
          onUpdated?.();
        } else {
          setRedeemError(result.message);
        }
      } catch (err: unknown) {
        if (err instanceof PackLibraryHttpError) {
          setRedeemError(`Activation redeem failed (HTTP ${err.status})`);
        } else {
          setRedeemError("Activation redeem failed");
        }
      } finally {
        redeemInFlight.current = false;
        setRedeemPending(false);
      }
    },
    [activationKey, client, onUpdated],
  );

  const handleRefund = useCallback(
    async (event: FormEvent<HTMLFormElement>): Promise<void> => {
      event.preventDefault();
      if (!canRequestRefund || refundInFlight.current) {
        return;
      }
      const trimmed = refundSku.trim();
      if (trimmed === "") {
        setRefundFeedback(null);
        setRefundError("Enter a catalogue SKU to request a refund.");
        return;
      }
      refundInFlight.current = true;
      setRefundPending(true);
      setRefundFeedback(null);
      setRefundError(null);
      try {
        const result = await client.requestRefund!(trimmed);
        if (result.status === "refunded") {
          setRefundSku("");
          setRefundFeedback(
            "Entitlement revoked · refund recorded. Trading and export stay available.",
          );
          onUpdated?.();
        } else if (result.status === "failed") {
          setRefundError(
            "Refund refused. Entitlement unchanged; trading and export stay available.",
          );
        } else if (result.status === "refused") {
          setRefundError(
            result.message === "sku not entitled"
              ? "That SKU is not entitled on this machine."
              : "Refund refused.",
          );
        } else {
          setRefundError(
            "Refund unreachable. Entitlement unchanged; trading and export stay available.",
          );
        }
      } catch (err: unknown) {
        if (err instanceof PackLibraryHttpError) {
          setRefundError(`Refund request failed (HTTP ${err.status})`);
        } else {
          setRefundError("Refund request failed");
        }
      } finally {
        refundInFlight.current = false;
        setRefundPending(false);
      }
    },
    [canRequestRefund, client, refundSku, onUpdated],
  );

  return (
    <div
      className="kbot-pack-library"
      data-testid="pack-billing-forms"
    >
      <form
        className="kbot-pack-library__redeem"
        data-testid="pack-library-redeem"
        onSubmit={(event) => {
          void handleRedeem(event);
        }}
      >
        <div className="kbot-pack-library__redeem-copy">
          <h3 className="kbot-pack-library__redeem-title">Redeem activation key</h3>
          <p className="kbot-pack-library__redeem-helper">
            Redeem a signed activation key to refresh entitlements and the pack
            library on this machine. The key is never stored or echoed.
          </p>
        </div>
        <label className="kbot-pack-library__redeem-label" htmlFor={redeemKeyId}>
          <span className="kbot-pack-library__redeem-caption">Activation key</span>
          <input
            id={redeemKeyId}
            type="password"
            className="kbot-pack-library__redeem-input"
            data-testid="pack-library-redeem-input"
            autoComplete="off"
            spellCheck={false}
            value={activationKey}
            disabled={redeemPending}
            onChange={(event) => {
              setActivationKey(event.target.value);
            }}
          />
        </label>
        <button
          type="submit"
          className="kbot-pack-library__redeem-submit"
          data-testid="pack-library-redeem-submit"
          disabled={redeemPending}
          aria-disabled={redeemPending}
          aria-busy={redeemPending}
        >
          {redeemPending ? "Redeeming…" : "Redeem"}
        </button>
        {redeemFeedback !== null ? (
          <p
            className="kbot-pack-library__redeem-feedback"
            role="status"
            data-testid="pack-library-redeem-feedback"
          >
            {redeemFeedback}
          </p>
        ) : null}
        {redeemError !== null ? (
          <p
            className="kbot-pack-library__redeem-error"
            role="alert"
            data-testid="pack-library-redeem-error"
          >
            {redeemError}
          </p>
        ) : null}
      </form>

      {canRequestRefund ? (
        <form
          className="kbot-pack-library__refund"
          data-testid="pack-library-refund"
          onSubmit={(event) => {
            void handleRefund(event);
          }}
        >
          <div className="kbot-pack-library__refund-copy">
            <h3 className="kbot-pack-library__refund-title">Request pack refund</h3>
            <p className="kbot-pack-library__refund-helper">
              Request a refund for a paid catalogue SKU. On success the local
              entitlement is revoked and journaled. Billing failure cannot block
              exits or export. See docs/refunds.md.
            </p>
          </div>
          <label className="kbot-pack-library__refund-label" htmlFor={refundSkuId}>
            <span className="kbot-pack-library__refund-caption">Catalogue SKU</span>
            <input
              id={refundSkuId}
              type="text"
              className="kbot-pack-library__refund-input"
              data-testid="pack-library-refund-input"
              autoComplete="off"
              spellCheck={false}
              value={refundSku}
              disabled={refundPending}
              onChange={(event) => {
                setRefundSku(event.target.value);
              }}
            />
          </label>
          <button
            type="submit"
            className="kbot-pack-library__refund-submit"
            data-testid="pack-library-refund-submit"
            disabled={refundPending}
            aria-disabled={refundPending}
            aria-busy={refundPending}
          >
            {refundPending ? "Requesting…" : "Request refund"}
          </button>
          {refundFeedback !== null ? (
            <p
              className="kbot-pack-library__refund-feedback"
              role="status"
              data-testid="pack-library-refund-feedback"
            >
              {refundFeedback}
            </p>
          ) : null}
          {refundError !== null ? (
            <p
              className="kbot-pack-library__refund-error"
              role="alert"
              data-testid="pack-library-refund-error"
            >
              {refundError}
            </p>
          ) : null}
        </form>
      ) : null}
    </div>
  );
}
