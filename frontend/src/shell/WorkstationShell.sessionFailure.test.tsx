/**
 * Failed local session bootstrap must stay visible on application Home
 * (APP-BONES-SESSION-ERROR-01). A rejected one-time bootstrap token is
 * never silently presented as "startup complete": the failure is
 * displayed with a recovery action that re-reads the CSRF token for the
 * existing session cookie only. A consumed bootstrap token is never
 * replayed and no token value is rendered or retained.
 */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { JSX } from "react";
import type { PaperClient } from "../features/paper/client";
import type { ResearchClient } from "../features/research/client";
import type { StrategyClient } from "../features/strategies/client";
import { recoverCsrf, redeemBootstrap } from "../session";
import { AppHome } from "./AppHome";
import { WorkstationShell } from "./WorkstationShell";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

vi.mock("../session", () => ({
  redeemBootstrap: vi.fn(
    (): Promise<void> => Promise.reject(new Error("bootstrap failed: 401")),
  ),
  recoverCsrf: vi.fn((): Promise<boolean> => Promise.resolve(false)),
}));

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn(async () => ({ schema_version: "1", armed: false })),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
    }),
  };
}

function makeResearchClient(): ResearchClient {
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-1", state: "queued" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-1", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
    } as unknown as Response),
  };
}

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-2",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function setBootstrapMeta(content: string): void {
  const meta = document.createElement("meta");
  meta.setAttribute("name", "krellbot-bootstrap");
  meta.setAttribute("content", content);
  document.head.appendChild(meta);
}

function renderShell(): ReturnType<typeof render> {
  return render(
    <WorkstationShell
      paperClient={makePaperClient()}
      researchClient={makeResearchClient()}
      strategyClient={makeStrategyClient()}
    />,
  );
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
  vi.clearAllMocks();
});

describe("WorkstationShell — failed session bootstrap", () => {
  it("shows a failed-session alert on Home after the bootstrap token is rejected", async () => {
    setBootstrapMeta("token-secret-value-1");
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    expect(
      screen.getByTestId("app-home-session-failure").getAttribute("role"),
    ).toBe("alert");
    // The bootstrap attempt is settled (not silently "startup complete").
    expect(
      document.querySelector('[data-testid="kbot-shell"]')?.getAttribute(
        "data-bootstrap-done",
      ),
    ).toBe("1");
    // The one-time token was consumed exactly once and never replayed.
    expect(redeemBootstrap).toHaveBeenCalledTimes(1);
    expect(redeemBootstrap).toHaveBeenCalledWith("token-secret-value-1");
    // The token value must never be rendered or otherwise surfaced.
    expect(document.body.innerHTML.includes("token-secret-value-1")).toBe(
      false,
    );
  });

  it("keeps the pending note while the bootstrap is in flight and only then swaps to the failure", async () => {
    let rejectBootstrap: ((err: Error) => void) | null = null;
    vi.mocked(redeemBootstrap).mockImplementationOnce(
      (): Promise<void> =>
        new Promise<void>((_resolve, reject) => {
          rejectBootstrap = reject;
        }),
    );
    setBootstrapMeta("token-secret-value-2");
    renderShell();
    expect(screen.getByTestId("app-home-session").textContent).toMatch(
      /starting the local session/i,
    );
    expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
    await act(async () => {
      rejectBootstrap?.(new Error("bootstrap failed: 503"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    expect(document.body.innerHTML.includes("token-secret-value-2")).toBe(
      false,
    );
  });

  it("never re-attacks the consumed bootstrap token, even when the user re-enters Home", async () => {
    setBootstrapMeta("token-secret-value-3");
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    vi.clearAllMocks();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    fireEvent.click(screen.getByRole("button", { name: /^Home$/ }));
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    // No second bootstrap attempt: the token was already consumed once.
    expect(redeemBootstrap).not.toHaveBeenCalled();
    expect(document.body.innerHTML.includes("token-secret-value-3")).toBe(
      false,
    );
  });

  it("offers the existing-session recovery action and clears the failure when it succeeds", async () => {
    setBootstrapMeta("token-secret-value-4");
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    // Recovery is available before it is used.
    expect(recoverCsrf).not.toHaveBeenCalled();
    vi.mocked(recoverCsrf).mockResolvedValueOnce(true);
    fireEvent.click(
      within(screen.getByTestId("app-home-session-failure")).getByRole(
        "button",
        { name: /recover the local session/i },
      ),
    );
    await waitFor(() => {
      expect(recoverCsrf).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
    });
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    // Recovery used the existing session only — never a bootstrap retry.
    expect(redeemBootstrap).toHaveBeenCalledTimes(1);
    expect(document.body.innerHTML.includes("token-secret-value-4")).toBe(
      false,
    );
  });

  it("persists the failure when the existing session cannot be recovered, without bootstrapping again", async () => {
    setBootstrapMeta("token-secret-value-5");
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    fireEvent.click(
      within(screen.getByTestId("app-home-session-failure")).getByRole(
        "button",
        { name: /recover the local session/i },
      ),
    );
    await waitFor(() => {
      expect(recoverCsrf).toHaveBeenCalledTimes(1);
    });
    // recoverCsrf defaults to false: the session cookie is gone.
    expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    expect(redeemBootstrap).toHaveBeenCalledTimes(1);
    expect(document.body.innerHTML.includes("token-secret-value-5")).toBe(
      false,
    );
  });

  it("keeps offline navigation available while the session failure is displayed", async () => {
    setBootstrapMeta("token-secret-value-6");
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    const home = within(screen.getByTestId("app-home"));
    for (const name of [
      /create or open a strategy/i,
      /explore research/i,
      /open studio/i,
      /paper workstation/i,
      /operations/i,
    ]) {
      const card = home.getByRole("button", { name });
      expect((card as HTMLButtonElement).disabled).toBe(false);
    }
    home.getByRole("button", { name: /open studio/i }).click();
    await waitFor(() => {
      expect(screen.queryByTestId("app-home")).toBeNull();
    });
    expect(document.body.innerHTML.includes("token-secret-value-6")).toBe(
      false,
    );
  });
});

describe("WorkstationShell — reload without bootstrap metadata (APP-BONES-SESSION-RELOAD-01)", () => {
  it("treats an absent-meta reload with a valid session cookie as success", async () => {
    vi.mocked(recoverCsrf).mockResolvedValueOnce(true);
    renderShell();
    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="kbot-shell"]')?.getAttribute(
          "data-bootstrap-done",
        ),
      ).toBe("1");
    });
    // Recovered from the existing session: no failure alert, no pending note.
    expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    // The reload path never touches the one-time bootstrap token.
    expect(redeemBootstrap).not.toHaveBeenCalled();
  });

  it("surfaces the failure alert when an absent-meta reload has no recoverable session", async () => {
    // recoverCsrf defaults to resolving false: the session cookie is
    // gone or expired, so the reload cannot recover the CSRF token.
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    expect(
      screen.getByTestId("app-home-session-failure").getAttribute("role"),
    ).toBe("alert");
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    // Settled (not silently "startup complete") but honestly failed.
    expect(
      document.querySelector('[data-testid="kbot-shell"]')?.getAttribute(
        "data-bootstrap-done",
      ),
    ).toBe("1");
    expect(redeemBootstrap).not.toHaveBeenCalled();
  });

  it("keeps the failure when recovery from the existing session is refused or throws", async () => {
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    // First recovery attempt: recoverCsrf resolves false again.
    fireEvent.click(
      within(screen.getByTestId("app-home-session-failure")).getByRole(
        "button",
        { name: /recover the local session/i },
      ),
    );
    await waitFor(() => {
      expect(recoverCsrf).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    // Second recovery attempt: the recovery request itself rejects.
    vi.mocked(recoverCsrf).mockImplementationOnce(
      (): Promise<boolean> => Promise.reject(new Error("csrf failed: 403")),
    );
    fireEvent.click(
      within(screen.getByTestId("app-home-session-failure")).getByRole(
        "button",
        { name: /recover the local session/i },
      ),
    );
    await waitFor(() => {
      expect(recoverCsrf).toHaveBeenCalledTimes(3);
    });
    // The rejection is swallowed, never rendered as success.
    expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    expect(redeemBootstrap).not.toHaveBeenCalled();
  });

  it("recovers from the failed reload state when the existing session becomes available again", async () => {
    renderShell();
    await waitFor(() => {
      expect(screen.getByTestId("app-home-session-failure")).toBeDefined();
    });
    vi.mocked(recoverCsrf).mockResolvedValueOnce(true);
    fireEvent.click(
      within(screen.getByTestId("app-home-session-failure")).getByRole(
        "button",
        { name: /recover the local session/i },
      ),
    );
    await waitFor(() => {
      expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
    });
    expect(screen.queryByTestId("app-home-session")).toBeNull();
    expect(redeemBootstrap).not.toHaveBeenCalled();
  });
});

describe("AppHome — failed-session prop contract", () => {
  it("renders the failed-session alert only when sessionFailed is set", () => {
    const { rerender } = render(<AppHome onNavigate={() => {}} />);
    expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
    rerender(<AppHome onNavigate={() => {}} sessionFailed />);
    expect(
      screen.getByTestId("app-home-session-failure").getAttribute("role"),
    ).toBe("alert");
    expect(
      screen.getByTestId("app-home-session-failure").textContent,
    ).toMatch(/local session could not start/i);
    expect(document.body.innerHTML.includes("bootstrap failed")).toBe(false);
    rerender(<AppHome onNavigate={() => {}} sessionFailed={false} />);
    expect(screen.queryByTestId("app-home-session-failure")).toBeNull();
  });

  it("shows the recovery control only on failure and only when a handler is provided", () => {
    const onRecoverSession = vi.fn();
    const first = render(
      <AppHome onNavigate={() => {}} sessionFailed />,
    );
    expect(
      screen.queryByRole("button", { name: /recover the local session/i }),
    ).toBeNull();
    first.unmount();
    const second = render(
      <AppHome
        onNavigate={() => {}}
        sessionFailed
        onRecoverSession={onRecoverSession}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /recover the local session/i }),
    );
    expect(onRecoverSession).toHaveBeenCalledTimes(1);
    second.unmount();
  });
});
