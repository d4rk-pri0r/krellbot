import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppHome } from "./AppHome";
import { WorkstationShell } from "./WorkstationShell";
import { recoverCsrf, redeemBootstrap } from "../session";

// Exercise defensive caller failures without changing recoverCsrf's boolean contract.
vi.mock("../session", () => ({
  recoverCsrf: vi.fn(),
  redeemBootstrap: vi.fn(),
}));

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.resetAllMocks();
  vi.restoreAllMocks();
});

describe("Home session recovery", () => {
  it("shows each click's cause, clears it on retry, and keeps retry enabled", async () => {
    let finish: (result: { ok: boolean; error?: string }) => void = () => {};
    const recover = vi.fn(() => new Promise<{ ok: boolean; error?: string }>(resolve => { finish = resolve; }));
    render(<AppHome onNavigate={() => {}} sessionFailed onRecoverSession={recover} />);
    const button = screen.getByTestId("app-home-recover-session") as HTMLButtonElement;
    expect(screen.queryByTestId("apphome-recover-error")).toBeNull();
    fireEvent.click(button);
    await act(async () => { finish({ ok: false, error: "recovery refused" }); });
    expect(screen.getByTestId("apphome-recover-error").textContent).toContain("recovery refused");
    expect(screen.getByTestId("apphome-recover-error").getAttribute("role")).toBe("alert");
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(screen.queryByTestId("apphome-recover-error")).toBeNull();
    await act(async () => { finish({ ok: false, error: "network unavailable" }); });
    expect(screen.getByTestId("apphome-recover-error").textContent).toContain("network unavailable");
    expect(screen.getByTestId("apphome-recover-error").textContent).not.toContain("recovery refused");
    fireEvent.click(button);
    await act(async () => { finish({ ok: true }); });
    expect(screen.queryByTestId("apphome-recover-error")).toBeNull();
    expect(button.disabled).toBe(false);
  });

  it("supplies a useful fallback for a false result without an error", async () => {
    render(<AppHome onNavigate={() => {}} sessionFailed onRecoverSession={async () => ({ ok: false })} />);
    fireEvent.click(screen.getByTestId("app-home-recover-session"));
    expect((await screen.findByTestId("apphome-recover-error")).textContent).toContain("recovery refused");
  });

  it("passes false and defensive thrown causes from the shell, then clears both surfaces on success", async () => {
    vi.mocked(recoverCsrf).mockResolvedValueOnce(false).mockResolvedValueOnce(false)
      .mockRejectedValueOnce(new Error("local service unreachable")).mockResolvedValueOnce(true);
    render(<WorkstationShell />);
    await screen.findByTestId("app-home-session-failure");
    fireEvent.click(screen.getByTestId("app-home-recover-session"));
    expect((await screen.findByTestId("apphome-recover-error")).textContent).toContain("recovery refused");
    fireEvent.click(screen.getByTestId("app-home-recover-session"));
    await waitFor(() => expect(screen.getByTestId("apphome-recover-error").textContent).toContain("local service unreachable"));
    fireEvent.click(screen.getByTestId("app-home-recover-session"));
    await waitFor(() => expect(screen.queryByTestId("app-home-session-failure")).toBeNull());
    expect(screen.queryByTestId("apphome-recover-error")).toBeNull();
    expect(redeemBootstrap).not.toHaveBeenCalled();
  });

  it("adds observed offline context without pretending to know the swallowed transport error", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    vi.mocked(recoverCsrf).mockResolvedValue(false);
    render(<WorkstationShell />);
    await screen.findByTestId("app-home-session-failure");
    fireEvent.click(screen.getByTestId("app-home-recover-session"));
    expect((await screen.findByTestId("apphome-recover-error")).textContent).toMatch(/recovery refused.*offline/i);
  });
});
