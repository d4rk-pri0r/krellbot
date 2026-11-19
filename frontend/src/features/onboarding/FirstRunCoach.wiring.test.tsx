/**
 * M25.3 — coach wires to home CTA → chooser → Run arm → status.
 * Does not rewrite starter cards (M25.5).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KeysClient, KeysStatus } from "../keys/client";
import type { LiveWizardHonesty, TrustClient } from "./client";
import type { PaperClient } from "../paper/client";
import { StatusPanel } from "../paper/StatusPanel";
import type { StrategyClient } from "../strategies/client";
import type { StarterCatalogue, StarterExample } from "../strategies/StarterPicker.client";
import { AppHome } from "../../shell/AppHome";
import {
  advanceFirstRunCoachTo,
  FirstRunCoach,
  FIRST_RUN_COACH_STORAGE_KEY,
  readFirstRunCoachState,
  writeFirstRunCoachState,
} from "./FirstRunCoach";

const STORAGE = FIRST_RUN_COACH_STORAGE_KEY;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

const ABSENT_KEYS: KeysStatus = {
  schema_version: "1",
  venue: "kraken",
  present: false,
  corrupt: false,
  message: "no key stored",
  backend_label: null,
  balances: null,
  balances_available: false,
};

const HONEST_TRUST: LiveWizardHonesty = {
  schema_version: "1",
  trust: {
    home: "/tmp/krellbot-home",
    home_mode: "0o700",
    home_mode_ok: true,
    keychain_backend: "FakeKeyring",
    keychain_ok: false,
    posture_ok: false,
    posture_warning: "keychain backend is FakeKeyring (not persistent)",
    bind: "127.0.0.1",
    live_arm_ui_allowed: false,
    trade_only_required: true,
  },
  paper_only_release: true,
  release_policy: "paper_only",
  release_policy_code: "live_disabled_paper_only_release",
  release_policy_message: "paper-only release",
  live_grant_active: false,
  live_grant: { active: false, expires_at: null, grants: [] },
  live_ready: false,
  live_arm_ui_allowed: false,
  trade_only_required: true,
  license_required_for_exchange: false,
  keys_leave_machine: false,
};

function fakeKeys(): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue(ABSENT_KEYS),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
  };
}

function fakeTrust(): TrustClient {
  return {
    getTrust: vi.fn().mockResolvedValue(HONEST_TRUST),
  };
}

const example: StarterExample = {
  id: "starter-dual-ma-crossover",
  label: "Dual moving-average crossover",
  description: "Educational example for paper.",
  pack: {
    schema_version: 1,
    id: "starter-dual-ma-crossover",
    label: "Dual MA crossover (educational example)",
    timeframe: "1h",
  },
};

const catalogue: StarterCatalogue = {
  schema_version: "1",
  catalogue_version: "1",
  examples: [example],
};

function fakeStrategy(over: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-starter-1",
      state: "draft",
      pack: example.pack,
      errors: [],
    }),
    edit: vi.fn(),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-starter-1",
      state: "validated",
      pack: example.pack,
      errors: [],
    }),
    arm: vi.fn(),
    ...over,
  };
}

describe("home paper CTA opens the starter chooser without a spotlight anchor", () => {
  it("does not mark the home CTA as a coach spotlight target", () => {
    render(
      <AppHome onNavigate={vi.fn()} keysClient={fakeKeys()} trustClient={fakeTrust()} />,
    );
    expect(
      screen.getByTestId("app-home-cta-paper").hasAttribute("data-coach-anchor"),
    ).toBe(false);
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.queryByTestId("first-run-coach")).toBeNull();
  });

  it("opens the starter chooser from the home paper CTA", async () => {
    render(
      <AppHome
        onNavigate={vi.fn()}
        strategyClient={fakeStrategy()}
        loadStarters={async () => catalogue}
        keysClient={fakeKeys()}
        trustClient={fakeTrust()}
      />,
    );
    expect(screen.queryByTestId("paper-starter-chooser")).toBeNull();
    fireEvent.click(screen.getByTestId("app-home-cta-paper"));
    expect(await screen.findByTestId("paper-starter-chooser")).toBeTruthy();
  });
});

describe("FirstRunCoach wiring — starter ready advances to arm_paper", () => {
  it("syncKey picks up an external advance to arm_paper after starter handoff", () => {
    writeFirstRunCoachState(
      { status: "active", stepId: "choose_starter" },
      STORAGE,
    );
    const { rerender } = render(<FirstRunCoach syncKey={0} />);
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "choose_starter",
    );
    advanceFirstRunCoachTo("arm_paper", STORAGE);
    rerender(<FirstRunCoach syncKey={1} />);
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "arm_paper",
    );
    expect(readFirstRunCoachState(STORAGE)).toEqual({
      status: "active",
      stepId: "arm_paper",
    });
  });
});

describe("FirstRunCoach wiring — Run arm and status anchors", () => {
  function fakePaper(over: Partial<PaperClient> = {}): PaperClient {
    return {
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: false,
        pack_id: null,
        venue: null,
        pair: null,
        entries_paused: false,
      }),
      pause: vi.fn(),
      resume: vi.fn(),
      disarm: vi.fn(),
      raiseStop: vi.fn(),
      arm: vi.fn().mockResolvedValue({
        ok: true,
        code: "armed",
        message: "armed",
      }),
      listOwnedDrafts: vi.fn().mockResolvedValue([
        {
          revision_id: "rev-starter-1",
          label: "starter",
          pair: "XBT/USD",
          runnable: true,
        },
      ]),
      getPosition: vi.fn(),
      ...over,
    } as PaperClient;
  }

  it("starts a paper run from the arm control and reports onPaperArmed", async () => {
    const onPaperArmed = vi.fn();
    const client = fakePaper();
    render(
      <StatusPanel
        client={client}
        preferredRevisionId="rev-starter-1"
        onPaperArmed={onPaperArmed}
      />,
    );
    await screen.findByTestId("paper-arm-form");
    const submit = await screen.findByTestId("paper-arm-submit");
    expect(submit.hasAttribute("data-coach-anchor")).toBe(false);
    expect(
      screen.getByTestId("paper-status-panel").hasAttribute("data-coach-anchor"),
    ).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalled();
      expect(onPaperArmed).toHaveBeenCalledTimes(1);
    });
  });
});

describe("FirstRunCoach wiring — Open starters primary opens path without skipping step", () => {
  it("keeps choose_starter when primary asks the host to open the chooser", () => {
    writeFirstRunCoachState(
      { status: "active", stepId: "choose_starter" },
      STORAGE,
    );
    const open = vi.fn(() => false as const);
    render(
      <FirstRunCoach
        onPrimaryAction={(stepId) => {
          if (stepId === "choose_starter") {
            open();
            return false;
          }
        }}
      />,
    );
    fireEvent.click(screen.getByTestId("first-run-coach-primary"));
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("first-run-coach").getAttribute("data-coach-step")).toBe(
      "choose_starter",
    );
  });
});
