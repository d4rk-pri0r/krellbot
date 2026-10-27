import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { JSX } from "react";
import type { PaperClient } from "../paper/client";
import type { ResearchClient } from "../research/client";
import type { StrategyClient } from "../strategies/client";
import type { Pack } from "../strategies/client";
import { WorkstationShell } from "../../shell/WorkstationShell";

// The REAL applyExecutionEdit module drives every save in this file:
// only global fetch is stubbed. There is deliberately no vi.mock of
// ../features/studio/executionEdit — these tests pin the module's own
// bounded read behavior (read-deadline-20261027) as the shell consumes
// it through the existing studio-save-error / studio-save-outcome rows.

// The coordinator contract fixes the total read deadline (response
// headers AND JSON body) at exactly 10000ms. The literal is repeated
// here on purpose so a module regression cannot silently retime it.
const READ_DEADLINE_MS = 10000;

// jsdom cannot measure the real canvas; render the same captured
// ReactFlow stub the WorkstationShell studio suite uses so the Studio
// view mounts exactly as it does there.
vi.mock("@xyflow/react", async () => {
  const actual =
    await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  function StubReactFlow(props: { children?: React.ReactNode }): JSX.Element {
    return (
      <div
        data-testid="react-flow-stub"
        className="react-flow"
        role="application"
      >
        {props.children}
      </div>
    );
  }
  return {
    ...actual,
    ReactFlow: StubReactFlow,
  };
});

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

const CSRF_TOKEN = "deadline-csrf";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function stalledBodyResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: () => new Promise<never>(() => {}),
  } as unknown as Response;
}

type DraftsHandler = (init: RequestInit) => Response | Promise<Response>;

let draftsHandler: DraftsHandler;
let draftsCalls: RequestInit[];

function stubFetch(): void {
  draftsHandler = () => new Promise<Response>(() => {});
  draftsCalls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/v1/session/csrf") {
        return jsonResponse({ csrf_token: CSRF_TOKEN });
      }
      if (url.startsWith("/api/v1/strategies/drafts/")) {
        draftsCalls.push(init ?? {});
        return draftsHandler(init ?? {});
      }
      return jsonResponse({}, 403);
    }),
  );
}

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    }),
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
      revision_id: "rev-deadline-1",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-deadline-2",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-deadline-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function savedPackFixture(): Pack {
  return {
    id: "trend-follow",
    timeframe: "1h",
    indicators: { sma20: { fn: "sma" } },
    entry: ["close", ">", "sma20"],
    exit: ["close", "<", "sma20"],
  };
}

// Same user journey the WorkstationShell studio suite drives: save a
// pack through Strategies (injected strategy client, no fetch), then
// open Studio so the Save execution button is shown.
async function savePackAndOpenStudio(
  strategyClient?: StrategyClient,
): Promise<void> {
  render(
    <WorkstationShell
      paperClient={makePaperClient()}
      researchClient={makeResearchClient()}
      strategyClient={strategyClient ?? makeStrategyClient()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
  fireEvent.change(screen.getByLabelText(/raw json/i), {
    target: { value: JSON.stringify(savedPackFixture()) },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await screen.findByTestId("editor-revision-id");
  fireEvent.click(screen.getByRole("button", { name: "Studio" }));
  // Settle the shell's real-clock mount effects (notably the status
  // strip's deferred self-read arm and its refresh intervals) BEFORE a
  // test switches to fake timers, so the fake clock only ever owns the
  // deadline timer under test.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 25));
  });
}

function clickSaveExecution(): void {
  fireEvent.click(screen.getByRole("button", { name: /save execution/i }));
}

async function flushMicrotasks(ticks = 16): Promise<void> {
  for (let i = 0; i < ticks; i += 1) {
    await Promise.resolve();
  }
}

afterEach(() => {
  // Real timers must be restored BEFORE the unmount: the shell mounts
  // real-clock refresh intervals, and clearing them through a faked
  // clearInterval would silently leak them into later tests.
  vi.useRealTimers();
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WorkstationShell studio save — applyExecutionEdit healthy reads", () => {
  beforeEach(() => {
    stubFetch();
  });

  it("a healthy created read renders 'Saved new revision <id>' and keeps the exact PUT request shape", async () => {
    const strategy = makeStrategyClient();
    await savePackAndOpenStudio(strategy);
    draftsHandler = () =>
      jsonResponse({
        revision_id: "rev-created-9",
        pack: savedPackFixture(),
        outcome: "created",
        state: "draft",
      });
    clickSaveExecution();
    const outcome = await screen.findByTestId("studio-save-outcome");
    expect(outcome.textContent).toMatch(/Saved new revision rev-created-9/);
    expect(screen.queryByTestId("studio-save-error")).toBeNull();
    // Request shape through the real module: same endpoint, method,
    // credentials, CSRF header and body key as before the deadline fix.
    expect(draftsCalls.length).toBe(1);
    expect(
      (draftsCalls[0] as { method?: string }).method,
    ).toBe("PUT");
    expect((draftsCalls[0] as { credentials?: string }).credentials).toBe(
      "include",
    );
    const headers = (draftsCalls[0] as { headers?: Record<string, string> })
      .headers;
    expect(headers?.["Content-Type"]).toBe("application/json");
    expect(headers?.["X-Krellbot-CSRF"]).toBe(CSRF_TOKEN);
    const body = JSON.parse(
      String((draftsCalls[0] as { body?: unknown }).body),
    ) as { pack?: unknown };
    expect(body.pack).toEqual(savedPackFixture());
    // Best-effort validate still runs for a created revision.
    await vi.waitFor(() => {
      expect(strategy.validate).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("studio-revision-id").textContent).toContain(
      "rev-created-9",
    );
  });

  it("a healthy unchanged read renders 'No change: revision <id> kept' and skips validate", async () => {
    const strategy = makeStrategyClient();
    await savePackAndOpenStudio(strategy);
    draftsHandler = () =>
      jsonResponse({
        revision_id: "rev-deadline-1",
        pack: savedPackFixture(),
        outcome: "unchanged",
        state: "validated",
      });
    clickSaveExecution();
    const outcome = await screen.findByTestId("studio-save-outcome");
    expect(outcome.textContent).toMatch(
      /No change: revision rev-deadline-1 kept/,
    );
    expect(strategy.validate).not.toHaveBeenCalled();
    expect(screen.queryByTestId("studio-save-error")).toBeNull();
  });

  it("a healthy existing read renders 'Selected existing revision <id>' and skips validate for a non-draft state", async () => {
    const strategy = makeStrategyClient();
    await savePackAndOpenStudio(strategy);
    draftsHandler = () =>
      jsonResponse({
        revision_id: "rev-existing-3",
        pack: savedPackFixture(),
        outcome: "existing",
        state: "validated",
      });
    clickSaveExecution();
    const outcome = await screen.findByTestId("studio-save-outcome");
    expect(outcome.textContent).toMatch(
      /Selected existing revision rev-existing-3/,
    );
    expect(strategy.validate).not.toHaveBeenCalled();
    expect(screen.queryByTestId("studio-save-error")).toBeNull();
  });

  it("a non2xx response with a server message surfaces the existing truthful error through the studio-save-error row", async () => {
    await savePackAndOpenStudio();
    draftsHandler = () =>
      jsonResponse({ code: "edit_refused", message: "engine busy" }, 500);
    clickSaveExecution();
    const error = await screen.findByTestId("studio-save-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(
      /execution edit failed: 500 engine busy/,
    );
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
  });

  it("a non2xx response with a malformed body keeps the status-code-only truthful error", async () => {
    await savePackAndOpenStudio();
    draftsHandler = () =>
      ({
        ok: false,
        status: 503,
        json: async () => {
          throw new SyntaxError("unexpected token");
        },
      }) as unknown as Response;
    clickSaveExecution();
    const error = await screen.findByTestId("studio-save-error");
    expect(error.textContent).toMatch(/execution edit failed: 503$/);
  });

  it("a 2xx response with a malformed body surfaces the raw parse error through the same row", async () => {
    await savePackAndOpenStudio();
    draftsHandler = () =>
      ({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error("malformed-json-body");
        },
      }) as unknown as Response;
    clickSaveExecution();
    const error = await screen.findByTestId("studio-save-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(/malformed-json-body/);
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
  });
});

describe("WorkstationShell studio save — applyExecutionEdit read deadline", () => {
  beforeEach(() => {
    stubFetch();
  });

  it("a stalled response-header read settles by the fixed 10000ms deadline with the honest studio-save-error row", async () => {
    await savePackAndOpenStudio();
    // Fake timers only from here: the mount journey (csrf recovery,
    // editor save) already settled on the real clock.
    vi.useFakeTimers();
    draftsHandler = () => new Promise<Response>(() => {});
    clickSaveExecution();
    expect(draftsCalls.length).toBe(1);
    const signal = (draftsCalls[0] as { signal?: AbortSignal }).signal;
    await act(async () => {
      vi.advanceTimersByTime(READ_DEADLINE_MS - 1);
    });
    // Before the deadline the save is still pending: no terminal feedback.
    expect(screen.queryByTestId("studio-save-error")).toBeNull();
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    // After the deadline the user must learn the save never completed
    // instead of watching an indefinitely pending save. Today (BASE)
    // this row never appears and the test fails here.
    const error = screen.getByTestId("studio-save-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(/read timed out/i);
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
    // The stalled attempt's owned request is aborted by the deadline.
    expect(signal?.aborted).toBe(true);
  });

  it("a stalled JSON-body read (headers ok) settles by the same total deadline and aborts the owned request", async () => {
    await savePackAndOpenStudio();
    vi.useFakeTimers();
    draftsHandler = () => stalledBodyResponse();
    clickSaveExecution();
    const signal = (draftsCalls[0] as { signal?: AbortSignal }).signal;
    await act(async () => {
      vi.advanceTimersByTime(READ_DEADLINE_MS);
    });
    const error = screen.getByTestId("studio-save-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toMatch(/read timed out/i);
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
    expect(signal?.aborted).toBe(true);
  });

  it("a late response-header arrival after the deadline never settles the original save", async () => {
    await savePackAndOpenStudio();
    vi.useFakeTimers();
    let lateResolve: (response: Response) => void = () => {};
    draftsHandler = () =>
      new Promise<Response>((resolve) => {
        lateResolve = resolve;
      });
    clickSaveExecution();
    await act(async () => {
      vi.advanceTimersByTime(READ_DEADLINE_MS);
    });
    expect(screen.getByTestId("studio-save-error").textContent).toMatch(
      /read timed out/i,
    );
    // The stalled headers finally arrive long after the deadline with a
    // perfectly healthy created outcome...
    await act(async () => {
      lateResolve(
        jsonResponse({
          revision_id: "rev-late-created",
          pack: savedPackFixture(),
          outcome: "created",
          state: "draft",
        }),
      );
      await flushMicrotasks();
      vi.advanceTimersByTime(60000);
      await flushMicrotasks();
    });
    // ...but the expired attempt must not settle the original save.
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
    expect(screen.getByTestId("studio-save-error").textContent).toMatch(
      /read timed out/i,
    );
  });

  it("a late JSON-body resolution after the deadline never settles the original save", async () => {
    await savePackAndOpenStudio();
    vi.useFakeTimers();
    let lateBody: (body: unknown) => void = () => {};
    draftsHandler = () =>
      ({
        ok: true,
        status: 200,
        json: () =>
          new Promise<unknown>((resolve) => {
            lateBody = resolve;
          }),
      }) as unknown as Response;
    clickSaveExecution();
    await act(async () => {
      vi.advanceTimersByTime(READ_DEADLINE_MS);
    });
    expect(screen.getByTestId("studio-save-error").textContent).toMatch(
      /read timed out/i,
    );
    await act(async () => {
      lateBody({
        revision_id: "rev-late-body",
        pack: savedPackFixture(),
        outcome: "created",
        state: "draft",
      });
      await flushMicrotasks();
      vi.advanceTimersByTime(60000);
      await flushMicrotasks();
    });
    expect(screen.queryByTestId("studio-save-outcome")).toBeNull();
    expect(screen.getByTestId("studio-save-error").textContent).toMatch(
      /read timed out/i,
    );
  });

  it("retry after the timeout performs a fresh bounded read and renders its exact outcome", async () => {
    await savePackAndOpenStudio();
    vi.useFakeTimers();
    draftsHandler = () => new Promise<Response>(() => {});
    clickSaveExecution();
    await act(async () => {
      vi.advanceTimersByTime(READ_DEADLINE_MS);
    });
    expect(screen.getByTestId("studio-save-error").textContent).toMatch(
      /read timed out/i,
    );
    const firstSignal = (draftsCalls[0] as { signal?: AbortSignal }).signal;
    // The user retries: the second attempt is a fresh bounded read.
    draftsHandler = () =>
      jsonResponse({
        revision_id: "rev-after-retry",
        pack: savedPackFixture(),
        outcome: "created",
        state: "draft",
      });
    clickSaveExecution();
    expect(draftsCalls.length).toBe(2);
    const retrySignal = (draftsCalls[1] as { signal?: AbortSignal }).signal;
    expect(retrySignal).not.toBe(firstSignal);
    await act(async () => {
      await flushMicrotasks();
    });
    const outcome = screen.getByTestId("studio-save-outcome");
    expect(outcome.textContent).toMatch(/Saved new revision rev-after-retry/);
    expect(screen.queryByTestId("studio-save-error")).toBeNull();
  });

  it("a healthy read clears its deadline timer: no late abort, no late error, no leftover timer", async () => {
    await savePackAndOpenStudio();
    vi.useFakeTimers();
    const timersBefore = vi.getTimerCount();
    draftsHandler = () =>
      jsonResponse({
        revision_id: "rev-healthy",
        pack: savedPackFixture(),
        outcome: "created",
        state: "draft",
      });
    clickSaveExecution();
    expect(vi.getTimerCount()).toBe(timersBefore + 1);
    const signal = (draftsCalls[0] as { signal?: AbortSignal }).signal;
    await act(async () => {
      await flushMicrotasks();
    });
    expect(screen.getByTestId("studio-save-outcome").textContent).toMatch(
      /Saved new revision rev-healthy/,
    );
    // The timer was cleared on the success exit: no deadline timer is
    // left pending over the rendered outcome.
    expect(vi.getTimerCount()).toBe(timersBefore);
    await act(async () => {
      vi.advanceTimersByTime(600000);
      await flushMicrotasks();
    });
    // Long after the deadline: no late abort of the completed request
    // and no late error over the rendered outcome.
    expect(signal?.aborted).toBe(false);
    expect(screen.queryByTestId("studio-save-error")).toBeNull();
    expect(screen.getByTestId("studio-save-outcome").textContent).toMatch(
      /Saved new revision rev-healthy/,
    );
  });

  it("unmounting mid-read leaves no runaway timer: the bounded deadline still fires, clears itself, and aborts the owned request", async () => {
    await savePackAndOpenStudio();
    vi.useFakeTimers();
    const timersBefore = vi.getTimerCount();
    draftsHandler = () => new Promise<Response>(() => {});
    clickSaveExecution();
    expect(vi.getTimerCount()).toBe(timersBefore + 1);
    const signal = (draftsCalls[0] as { signal?: AbortSignal }).signal;
    cleanup();
    // Exactly the one bounded deadline timer remains pending after the
    // unmount — nothing else may keep the attempt alive.
    expect(vi.getTimerCount()).toBe(timersBefore + 1);
    await act(async () => {
      vi.advanceTimersByTime(READ_DEADLINE_MS);
      await flushMicrotasks();
    });
    // The deadline cleared itself on its exit path and aborted the
    // owned request; the expired attempt surfaces no unhandled error.
    expect(vi.getTimerCount()).toBe(timersBefore);
    expect(signal?.aborted).toBe(true);
  });
});
