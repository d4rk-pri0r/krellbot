/**
 * Kraken live arm + confirm panel (M20.1).
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LiveArmConfirm,
  type LiveArmConfirmAuthView,
  type LiveArmConfirmClient,
} from "./LiveArmConfirm";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PAPER_ONLY_VIEW: LiveArmConfirmAuthView = {
  release_policy: "paper_only",
  release_policy_code: "live_disabled_paper_only_release",
  release_policy_message:
    "v0.9.7 is a paper-only release: live order send is disabled regardless of environment, stored keys, or authorization.",
  confirmation_required: "LIVE",
};

const LIVE_ALLOWED_VIEW: LiveArmConfirmAuthView = {
  release_policy: "live_allowed",
  release_policy_code: "ok",
  confirmation_required: "LIVE",
};

function makeClient(over: Partial<LiveArmConfirmClient> = {}): LiveArmConfirmClient {
  return {
    getLiveAuthorization: vi.fn().mockResolvedValue(PAPER_ONLY_VIEW),
    armLive: vi.fn(),
    ...over,
  };
}

describe("LiveArmConfirm paper-only state", () => {
  it("shows the panel disabled with the paper-only reason", async () => {
    const client = makeClient();
    render(<LiveArmConfirm client={client} />);

    expect(await screen.findByTestId("live-arm-confirm-panel")).toBeTruthy();
    const reason = await screen.findByTestId("live-arm-confirm-paper-only");
    expect(reason.textContent).toMatch(/paper-only release/i);
    expect(screen.getByTestId("live-arm-confirm-paper-only-reason").textContent).toMatch(
      /live order send is disabled/i,
    );

    expect((screen.getByTestId("live-arm-confirm-venue") as HTMLSelectElement).disabled).toBe(
      true,
    );
    expect((screen.getByTestId("live-arm-confirm-revision") as HTMLInputElement).disabled).toBe(
      true,
    );
    expect((screen.getByTestId("live-arm-confirm-live") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("live-arm-confirm-submit") as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.getByText(/Grant live authorization on Operations first/i)).toBeDefined();

    await waitFor(() => {
      expect(client.getLiveAuthorization).toHaveBeenCalled();
    });
  });
});

describe("LiveArmConfirm typed LIVE + arm", () => {
  it("requires typed LIVE before arming and posts live.arm for kraken", async () => {
    const armLive = vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "armed",
      ok: true,
      effect: "changed",
      message: "armed on kraken SUIUSD",
      venue: "kraken",
      pair: "SUIUSD",
    });
    const client = makeClient({
      getLiveAuthorization: vi.fn().mockResolvedValue(LIVE_ALLOWED_VIEW),
      armLive,
    });
    render(<LiveArmConfirm client={client} />);

    await screen.findByTestId("live-arm-confirm-revision");
    expect(screen.queryByTestId("live-arm-confirm-paper-only")).toBeNull();

    const submit = screen.getByTestId("live-arm-confirm-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("live-arm-confirm-revision"), {
      target: { value: "rev-kraken-1" },
    });
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("live-arm-confirm-live"), {
      target: { value: "LIVE" },
    });
    expect(submit.disabled).toBe(false);

    fireEvent.click(submit);

    await waitFor(() => {
      expect(armLive).toHaveBeenCalledWith("rev-kraken-1", "kraken", "LIVE");
    });

    const result = await screen.findByTestId("live-arm-confirm-result");
    expect(result.textContent).toMatch(/code: armed/);
    expect(result.textContent).toMatch(/ok: true/);
    expect(result.textContent).toMatch(/venue: kraken/);
  });

  it("renders an honest refusal when live.arm is refused", async () => {
    const client = makeClient({
      getLiveAuthorization: vi.fn().mockResolvedValue(LIVE_ALLOWED_VIEW),
      armLive: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "live_disabled_paper_only_release",
        ok: false,
        effect: "refused",
        message: "paper-only release",
      }),
    });
    render(<LiveArmConfirm client={client} />);

    await screen.findByTestId("live-arm-confirm-revision");
    fireEvent.change(screen.getByTestId("live-arm-confirm-revision"), {
      target: { value: "rev-refused" },
    });
    fireEvent.change(screen.getByTestId("live-arm-confirm-live"), {
      target: { value: "LIVE" },
    });
    fireEvent.click(screen.getByTestId("live-arm-confirm-submit"));

    const result = await screen.findByTestId("live-arm-confirm-result");
    expect(result.textContent).toMatch(/live_disabled_paper_only_release/);
    expect(result.textContent).toMatch(/ok: false/);
  });
});
