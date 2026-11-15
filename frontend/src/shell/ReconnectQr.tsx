import { useMemo, type JSX } from "react";
import { encodeQrMatrix } from "./qrMatrix";

type ReconnectQrProps = {
  /** Short payload encoded into the QR (the reconnect token). */
  payload: string;
  label?: string;
};

/**
 * Local reconnect QR (KRELL-SIGNAL-20261010). Renders an SVG matrix for
 * the short-lived token — no network fetch, no third-party widget.
 */
export function ReconnectQr({
  payload,
  label = "Reconnect QR code",
}: ReconnectQrProps): JSX.Element {
  const modules = useMemo(() => encodeQrMatrix(payload), [payload]);
  const size = modules.length;
  const cells: JSX.Element[] = [];
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (!modules[r][c]) continue;
      cells.push(
        <rect
          key={`${r}-${c}`}
          x={c}
          y={r}
          width={1}
          height={1}
          fill="currentColor"
        />,
      );
    }
  }
  return (
    <svg
      className="app-home__reconnect-qr"
      data-testid="app-home-reconnect-qr"
      viewBox={`0 0 ${size} ${size}`}
      width={128}
      height={128}
      role="img"
      aria-label={label}
    >
      <rect width={size} height={size} fill="#E9F0F5" />
      <g color="#0E1C29">
        {cells}
      </g>
    </svg>
  );
}
