/**
 * One-click paper simulation start for the setup tour.
 *
 * Uses the existing starter catalogue and strategy client, then the real
 * Run arm control. Paper mode only — never a live order.
 */

import type { StrategyClient } from "../strategies/client";
import {
  fetchStarters,
  type StarterCatalogue,
} from "../strategies/StarterPicker.client";

const DEFAULT_STARTER_ID = "starter-dual-ma-crossover";

export async function prepareStarterRevision(
  strategyClient: Pick<StrategyClient, "create" | "validate">,
  loadStarters: () => Promise<StarterCatalogue> = fetchStarters,
  starterId: string = DEFAULT_STARTER_ID,
): Promise<string> {
  let catalogue: StarterCatalogue;
  try {
    catalogue = await loadStarters();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Could not load free strategies: ${detail}`);
  }
  const example =
    catalogue.examples.find((row) => row.id === starterId) ??
    catalogue.examples[0];
  if (!example) {
    throw new Error("No free paper strategy is available.");
  }
  try {
    const created = await strategyClient.create(example.pack);
    const validated = await strategyClient.validate(created.revision_id);
    if (validated.state !== "validated" && validated.state !== "deployed") {
      const detail =
        validated.errors
          .map((row) => row.message)
          .filter((message) => message.length > 0)
          .join("; ") || `validation left state ${validated.state}`;
      throw new Error(`Could not prepare that strategy: ${detail}`);
    }
    return validated.revision_id;
  } catch (error) {
    if (
      error instanceof Error &&
      error.message.startsWith("Could not prepare that strategy:")
    ) {
      throw error;
    }
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Could not prepare that strategy: ${detail}`);
  }
}

export type PaperArmSurface = "running" | "ready" | "pending";

/** What the Run page is showing right now, from the real controls. */
export function findPaperArmSurface(
  doc: Document = document,
): PaperArmSurface {
  if (
    doc.querySelector(
      '[data-testid="paper-status-entries"], [data-testid="paper-position"]',
    )
  ) {
    return "running";
  }
  const submit = doc.querySelector<HTMLButtonElement>(
    '[data-testid="paper-arm-submit"]',
  );
  if (submit && !submit.disabled) {
    return "ready";
  }
  return "pending";
}

/** Click the real paper-arm button when it is enabled. */
export function clickPaperArmSubmit(doc: Document = document): boolean {
  const submit = doc.querySelector<HTMLButtonElement>(
    '[data-testid="paper-arm-submit"]',
  );
  if (!submit || submit.disabled) {
    return false;
  }
  submit.click();
  return true;
}

export async function waitForPaperArmSurface(
  timeoutMs: number,
  doc: Document = document,
): Promise<PaperArmSurface> {
  const started = Date.now();
  let surface = findPaperArmSurface(doc);
  while (surface === "pending" && Date.now() - started < timeoutMs) {
    await new Promise((resolve) => {
      window.setTimeout(resolve, 50);
    });
    surface = findPaperArmSurface(doc);
  }
  return surface;
}
