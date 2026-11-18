/**
 * Live guardrails surface (M20.3).
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LiveGuardrails,
  type LiveGuardrailsClient,
  type LiveGuardrailsView,
} from "./LiveGuardrails";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PAPER_ONLY_VIEW: LiveGuardrailsView = {
  schema_version: "1",
  venue: "kraken",
  pair: null,
  pack: null,
  ok: false,
  code: "live_disabled_paper_only_release",
  effect: "refused",
  message: "live guardrails blocking: live_disabled_paper_only_release",
  blocking_codes: ["live_disabled_paper_only_release", "live_not_authorized"],
  rails: [
    {
      id: "paper_only_rail",
      active: true,
      blocking: true,
      code: "live_disabled_paper_only_release",
      message: "paper-only release",
      detail: { release_policy: "paper_only" },
    },
    {
      id: "kill_switch",
      active: true,
      blocking: false,
      code: null,
      message: "kill switch clear",
      detail: { engaged: false },
    },
    {
      id: "grant_expiry",
      active: true,
      blocking: true,
      code: "live_not_authorized",
      message: "no live grant on file",
      detail: { present: false, expired: false, expires_at: null },
    },
    {
      id: "stop_required",
      active: true,
      blocking: false,
      code: null,
      message: "live arm requires a pack stop (provide revision to check)",
      detail: { checked: false },
    },
    {
      id: "max_account_pct",
      active: true,
      blocking: false,
      code: null,
      message: "live arm requires max_account_pct > 0 (provide revision to check)",
      detail: { checked: false },
    },
  ],
};

function makeClient(over: Partial<LiveGuardrailsClient> = {}): LiveGuardrailsClient {
  return {
    getLiveGuardrails: vi.fn().mockResolvedValue(PAPER_ONLY_VIEW),
    evaluateLiveGuardrails: vi.fn().mockResolvedValue({
      ...PAPER_ONLY_VIEW,
      journaled_codes: ["live_disabled_paper_only_release", "live_not_authorized"],
    }),
    ...over,
  };
}

describe("LiveGuardrails surface", () => {
  it("shows active rails including paper-only, kill switch, grant expiry, stop, max pct", async () => {
    const client = makeClient();
    render(<LiveGuardrails client={client} />);

    expect(await screen.findByTestId("live-guardrails-panel")).toBeTruthy();
    expect(await screen.findByTestId("live-guardrails-rail-paper_only_rail")).toBeTruthy();
    expect(screen.getByTestId("live-guardrails-rail-kill_switch")).toBeTruthy();
    expect(screen.getByTestId("live-guardrails-rail-grant_expiry")).toBeTruthy();
    expect(screen.getByTestId("live-guardrails-rail-stop_required")).toBeTruthy();
    expect(screen.getByTestId("live-guardrails-rail-max_account_pct")).toBeTruthy();

    expect(screen.getByTestId("live-guardrails-code-paper_only_rail").textContent).toBe(
      "live_disabled_paper_only_release",
    );
    expect(screen.getByTestId("live-guardrails-ok").textContent).toMatch(/false/);
    expect(screen.getByTestId("live-guardrails-blocking").textContent).toMatch(
      /live_disabled_paper_only_release/,
    );

    await waitFor(() => {
      expect(client.getLiveGuardrails).toHaveBeenCalled();
    });
  });

  it("evaluate journals refusals via live.guardrails", async () => {
    const client = makeClient();
    render(<LiveGuardrails client={client} />);
    await screen.findByTestId("live-guardrails-rails");
    await waitFor(() => {
      expect(client.getLiveGuardrails).toHaveBeenCalled();
    });

    fireEvent.change(screen.getByTestId("live-guardrails-revision"), {
      target: { value: "rev-1" },
    });
    const submit = screen.getByTestId("live-guardrails-evaluate") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);

    await waitFor(() => {
      expect(client.evaluateLiveGuardrails).toHaveBeenCalledWith("kraken", "rev-1", true);
    });
    expect(await screen.findByTestId("live-guardrails-journaled")).toBeTruthy();
    expect(screen.getByTestId("live-guardrails-journaled").textContent).toMatch(
      /live_disabled_paper_only_release/,
    );
  });
});
