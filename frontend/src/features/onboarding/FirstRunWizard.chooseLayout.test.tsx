/**
 * FirstRunWizard choose step blurbs, scrollable/responsive layout, and
 * navy-blended status mascot.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import {
  CONSUMER_STARTER_CARD_ORDER,
  CONSUMER_STARTER_CARDS,
} from "../strategies/consumerStarterCopy";
import { FirstRunWizard, writeFirstRunWizardState } from "./FirstRunWizard";
import { FIRST_RUN_WIZARD_STORAGE_KEY } from "./firstRunWizardPersistence";

const here = dirname(fileURLToPath(import.meta.url));
const STORAGE = FIRST_RUN_WIZARD_STORAGE_KEY;

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function readWizardCss(): string {
  return readFileSync(join(here, "FirstRunWizard.signal.css"), "utf8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );
}

describe("FirstRunWizard choose layout and plain-English blurbs", () => {
  it("shows a plain-English blurb on each starter tile without jargon or P&L", () => {
    writeFirstRunWizardState(
      { status: "active", stepId: "choose", selectedStarterId: null },
      STORAGE,
    );
    render(<FirstRunWizard />);

    const wizard = screen.getByTestId("first-run-wizard");
    expect(wizard.classList.contains("kbot-first-run-wizard--choose")).toBe(
      true,
    );

    for (const id of CONSUMER_STARTER_CARD_ORDER) {
      const card = CONSUMER_STARTER_CARDS[id]!;
      const blurb = screen.getByTestId(`first-run-wizard-blurb-${id}`);
      expect(blurb.textContent).toBe(card.description);
      expect(blurb.textContent).not.toMatch(/\$|%|P&L|JSON|XXBTZUSD/i);
    }
  });

  it("uses the navy-blended portrait visual on the status step", () => {
    writeFirstRunWizardState(
      {
        status: "active",
        stepId: "status",
        selectedStarterId: "starter-dual-ma-crossover",
      },
      STORAGE,
    );
    render(<FirstRunWizard />);

    expect(
      screen
        .getByTestId("first-run-wizard-visual")
        .getAttribute("data-wizard-visual"),
    ).toBe("krell_portrait.png");
  });

  it("keeps the full-screen overlay scrollable and lays out choose tiles responsively", () => {
    const css = readWizardCss();

    expect(css).toMatch(/\.kbot-first-run-wizard\s*\{[^}]*display:\s*flex/);
    expect(css).toMatch(
      /\.kbot-first-run-wizard\s*\{[^}]*overflow-y:\s*auto/,
    );
    expect(css).toMatch(
      /\.kbot-first-run-wizard__chrome\s*\{[^}]*margin:\s*auto/,
    );
    expect(css).toMatch(
      /\.kbot-first-run-wizard--choose\s+\.kbot-first-run-wizard__tiles\s*\{[^}]*repeat\(3,\s*minmax\(0,\s*1fr\)\)/,
    );
    expect(css).toMatch(
      /@media\s*\(max-width:\s*719px\)[\s\S]*\.kbot-first-run-wizard--choose\s+\.kbot-first-run-wizard__tile\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/,
    );
  });
});
