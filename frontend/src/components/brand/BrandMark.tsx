import type { JSX } from "react";

/**
 * Supplied outlined Krellbot mark (Signal + Krell Asset Pack v2,
 * contract KRELL-SIGNAL-20261010). Path data copied verbatim from
 * `src/assets/brand/krellbot-mark-mint.svg`.
 */
export function BrandMark(): JSX.Element {
  return (
    <svg
      className="kbot-brandmark"
      width="20"
      height="16"
      viewBox="0 0 79 64"
      aria-hidden="true"
      data-testid="kbot-brandmark"
    >
      <g transform="translate(0 0) scale(1)" fill="#A8D8D1">
        <path d="M0 0H14V64H0Z M23 32L51 0H79L47 32L79 64H51Z" />
      </g>
    </svg>
  );
}
