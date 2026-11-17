import { useEffect, useState, type JSX } from "react";
import type { Pack } from "../strategies/client";
import {
  fetchModePacks,
  type ModePackCatalogue,
  type ModePackRow,
} from "./modePackClient";
import "./ModePackPicker.signal.css";

export type ModePackPickerProps = {
  onPick: (pack: Pack) => void;
  loadModes?: () => Promise<ModePackCatalogue>;
};

/**
 * Studio control to open a built-in trading-mode pack as a real graph.
 * Selecting a mode replaces demo nodes with ``nodesFromPack`` output.
 */
export function ModePackPicker({
  onPick,
  loadModes = fetchModePacks,
}: ModePackPickerProps): JSX.Element {
  const [rows, setRows] = useState<ModePackRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    void loadModes()
      .then((doc) => {
        if (cancelled) {
          return;
        }
        setRows(doc.modes);
        setBusy(false);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setRows(null);
        setError(err instanceof Error ? err.message : String(err));
        setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadModes]);

  return (
    <div className="kbot-mode-pack-picker" data-testid="studio-mode-pack-picker">
      <p className="kbot-mode-pack-picker__eyebrow">Built-in modes</p>
      <p className="kbot-mode-pack-picker__hint">
        Open DCA, grid, or rebalance as a readable graph. Save execution still
        validates. Not live market performance.
      </p>
      {busy ? (
        <p data-testid="studio-mode-pack-loading">Loading modes…</p>
      ) : null}
      {error ? (
        <p
          className="kbot-shell__error"
          role="alert"
          data-testid="studio-mode-pack-error"
        >
          {error}
        </p>
      ) : null}
      {rows && rows.length === 0 ? (
        <p data-testid="studio-mode-pack-empty">No built-in mode packs shipped.</p>
      ) : null}
      {rows && rows.length > 0 ? (
        <ul className="kbot-mode-pack-picker__list">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className="kbot-mode-pack-picker__button"
                data-testid={`studio-mode-pack-${row.id}`}
                onClick={() => {
                  onPick(row.pack);
                }}
              >
                {row.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
