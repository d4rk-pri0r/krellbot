import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * Detail-request race regressions for the Operations deployment history.
 *
 * Every client below is an in-memory fake whose list/detail calls return
 * manually settled deferred promises, so the pending window of the real
 * component is deterministic. This file pins that only the still-selected
 * row's current request may update the detail panel: obsolete successes,
 * failures, and finalizers are ignored when another row is selected, the
 * row is collapsed/reopened, history is refreshed, or the client is
 * replaced. These are component-level regressions with synthetic data —
 * they are not real-browser or real-backend acceptance.
 */

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: Error) => void;
};

type DetailCall = { deploymentId: string; request: Deferred<DeploymentRecordRow> };

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((settle, refuse) => {
    resolve = settle;
    reject = refuse;
  });
  return { promise, resolve, reject };
}

async function settle(settleFn: () => void): Promise<void> {
  await act(async () => {
    settleFn();
  });
}

function record(over: Partial<DeploymentRecordRow> = {}): DeploymentRecordRow {
  return {
    deployment_id: "dep-a",
    venue: "kraken",
    pair: "SUIUSD",
    created_at_ms: 1_700_000_010_000,
    state: "paper",
    config: { pack_id: "dep-a-pack" },
    schedule: { timeframe: "dep-a-timeframe" },
    last_execution_summary: "dep-a execution summary",
    ...over,
  };
}

const ROW_A = record();
const ROW_B = record({
  deployment_id: "dep-b",
  venue: "coinbase",
  pair: "BTC-USD",
  config: { pack_id: "dep-b-pack" },
  schedule: { timeframe: "dep-b-timeframe" },
  last_execution_summary: "dep-b execution summary",
});

function makeClient(
  list: () => Promise<DeploymentRecordRow[]>,
  detail: (deploymentId: string) => Promise<DeploymentRecordRow>,
): OperationsClient {
  return {
    getOperations: vi.fn(),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
    listDeploymentRecords: list,
    getDeploymentRecord: detail,
  };
}

function listWithRows(
  rows: DeploymentRecordRow[],
  laterLoads: Deferred<DeploymentRecordRow[]>[],
): () => Promise<DeploymentRecordRow[]> {
  let firstLoad = true;
  return (): Promise<DeploymentRecordRow[]> => {
    if (firstLoad) {
      firstLoad = false;
      return Promise.resolve(rows);
    }
    const pending = deferred<DeploymentRecordRow[]>();
    laterLoads.push(pending);
    return pending.promise;
  };
}

function detailQueue(calls: DetailCall[]): (deploymentId: string) => Promise<DeploymentRecordRow> {
  return (deploymentId: string): Promise<DeploymentRecordRow> => {
    const request = deferred<DeploymentRecordRow>();
    calls.push({ deploymentId, request });
    return request.promise;
  };
}

function detailPanel(deploymentId: string): HTMLElement | null {
  return screen.queryByTestId(`ops-history-detail-${deploymentId}`);
}

function detailConfigText(): string | null {
  return screen.queryByTestId("ops-history-detail-config")?.textContent ?? null;
}

async function openHistory(
  calls: DetailCall[],
  rows: DeploymentRecordRow[] = [ROW_A, ROW_B],
): Promise<OperationsClient> {
  const client = makeClient(() => Promise.resolve(rows), detailQueue(calls));
  render(<DeploymentHistory client={client} />);
  await screen.findByTestId(`ops-history-row-${rows[0]?.deployment_id ?? "dep-a"}`);
  return client;
}

describe("DeploymentHistory detail request races", () => {
  it("keeps row B's detail when the older row A request settles after B (B completes first)", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-b"));
    expect(calls.map((call) => call.deploymentId)).toEqual(["dep-a", "dep-b"]);
    expect(screen.getByTestId("ops-history-detail-loading")).toBeTruthy();
    await settle(() => calls[1].request.resolve(ROW_B));
    await settle(() => calls[0].request.resolve(ROW_A));
    expect(detailPanel("dep-b")).not.toBeNull();
    expect(detailPanel("dep-a")).toBeNull();
    expect(detailConfigText()).toContain("dep-b-pack");
    expect(detailConfigText()).not.toContain("dep-a-pack");
    expect(screen.queryByTestId("ops-history-detail-loading")).toBeNull();
    expect(screen.queryByTestId("ops-history-detail-error")).toBeNull();
  });

  it("keeps row B pending until it settles when the obsolete row A request resolves first (A completes first)", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-b"));
    await settle(() => calls[0].request.resolve(ROW_A));
    expect(screen.getByTestId("ops-history-detail-loading")).toBeTruthy();
    expect(detailConfigText()).toBeNull();
    expect(screen.queryByTestId("ops-history-detail-error")).toBeNull();
    await settle(() => calls[1].request.resolve(ROW_B));
    expect(detailPanel("dep-b")).not.toBeNull();
    expect(detailConfigText()).toContain("dep-b-pack");
    expect(detailConfigText()).not.toContain("dep-a-pack");
  });

  it("does not let an obsolete row A failure hide row B's loaded detail (obsolete rejection)", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-b"));
    await settle(() => calls[1].request.resolve(ROW_B));
    expect(detailConfigText()).toContain("dep-b-pack");
    await settle(() => calls[0].request.reject(new Error("dep-a stale refusal 503")));
    expect(detailPanel("dep-b")).not.toBeNull();
    expect(detailConfigText()).toContain("dep-b-pack");
    expect(screen.queryByTestId("ops-history-detail-error")).toBeNull();
  });

  it("does not let an obsolete row A failure clear row B's loading indicator (obsolete finalizer)", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-b"));
    await settle(() => calls[0].request.reject(new Error("dep-a stale refusal 500")));
    expect(screen.getByTestId("ops-history-detail-loading")).toBeTruthy();
    expect(screen.queryByTestId("ops-history-detail-error")).toBeNull();
    expect(detailConfigText()).toBeNull();
    await settle(() => calls[1].request.resolve(ROW_B));
    expect(detailConfigText()).toContain("dep-b-pack");
    expect(screen.queryByTestId("ops-history-detail-loading")).toBeNull();
  });

  it("discards the first request when row A is collapsed and reopened before it settles", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls, [ROW_A]);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    expect(calls.map((call) => call.deploymentId)).toEqual(["dep-a", "dep-a"]);
    await settle(() => calls[0].request.resolve(record({ last_execution_summary: "first view" })));
    expect(screen.getByTestId("ops-history-detail-loading")).toBeTruthy();
    expect(
      screen.queryByTestId("ops-history-detail-summary")?.textContent.includes("first view") ??
        false,
    ).toBe(false);
    await settle(() =>
      calls[1].request.resolve(record({ last_execution_summary: "reopened view" })),
    );
    expect(screen.getByTestId("ops-history-detail-summary").textContent).toContain("reopened view");
    expect(screen.queryByTestId("ops-history-detail-loading")).toBeNull();
  });

  it("invalidates an outstanding detail request when history is refreshed", async () => {
    const calls: DetailCall[] = [];
    const refreshes: Deferred<DeploymentRecordRow[]>[] = [];
    const client = makeClient(listWithRows([ROW_A, ROW_B], refreshes), detailQueue(calls));
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-row-dep-a");
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    fireEvent.click(screen.getByTestId("ops-history-refresh"));
    await settle(() => refreshes[0].resolve([ROW_A, ROW_B]));
    expect(detailPanel("dep-a")).toBeNull();
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    expect(calls.map((call) => call.deploymentId)).toEqual(["dep-a", "dep-a"]);
    await settle(() => calls[0].request.resolve(record({ last_execution_summary: "stale view" })));
    expect(screen.getByTestId("ops-history-detail-loading")).toBeTruthy();
    expect(
      screen.queryByTestId("ops-history-detail-summary")?.textContent.includes("stale view") ??
        false,
    ).toBe(false);
    await settle(() =>
      calls[1].request.resolve(record({ last_execution_summary: "post-refresh view" })),
    );
    expect(screen.getByTestId("ops-history-detail-summary").textContent).toContain(
      "post-refresh view",
    );
  });

  it("collapses the stale detail and ignores the old client's late settlement when the client is replaced", async () => {
    const oldCalls: DetailCall[] = [];
    const oldClient = makeClient(() => Promise.resolve([ROW_A]), detailQueue(oldCalls));
    const nextLoads: Deferred<DeploymentRecordRow[]>[] = [];
    const nextCalls: DetailCall[] = [];
    const nextClient = makeClient(
      (): Promise<DeploymentRecordRow[]> => {
        const pending = deferred<DeploymentRecordRow[]>();
        nextLoads.push(pending);
        return pending.promise;
      },
      detailQueue(nextCalls),
    );
    const view = render(<DeploymentHistory client={oldClient} />);
    fireEvent.click(await screen.findByTestId("ops-history-row-dep-a"));
    view.rerender(<DeploymentHistory client={nextClient} />);
    await settle(() => nextLoads[0].resolve([ROW_A]));
    expect(detailPanel("dep-a")).toBeNull();
    await settle(() =>
      oldCalls[0].request.resolve(record({ last_execution_summary: "old client view" })),
    );
    expect(detailPanel("dep-a")).toBeNull();
    expect(
      screen.queryByTestId("ops-history-detail-summary")?.textContent.includes("old client view") ??
        false,
    ).toBe(false);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    await settle(() =>
      nextCalls[0].request.resolve(record({ last_execution_summary: "new client view" })),
    );
    expect(screen.getByTestId("ops-history-detail-summary").textContent).toContain(
      "new client view",
    );
  });

  it("still loads details in order when selections never overlap (in-order control)", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    await settle(() => calls[0].request.resolve(ROW_A));
    expect(detailPanel("dep-a")).not.toBeNull();
    expect(detailConfigText()).toContain("dep-a-pack");
    fireEvent.click(screen.getByTestId("ops-history-row-dep-b"));
    await settle(() => calls[1].request.resolve(ROW_B));
    expect(detailPanel("dep-b")).not.toBeNull();
    expect(detailPanel("dep-a")).toBeNull();
    expect(detailConfigText()).toContain("dep-b-pack");
    expect(screen.queryByTestId("ops-history-detail-error")).toBeNull();
  });

  it("still reports the current row's detail failure truthfully (current-error control)", async () => {
    const calls: DetailCall[] = [];
    await openHistory(calls, [ROW_A]);
    fireEvent.click(screen.getByTestId("ops-history-row-dep-a"));
    await settle(() =>
      calls[0].request.reject(new Error("deployment history failed: 404 deployment_not_found")),
    );
    const error = screen.getByTestId("ops-history-detail-error");
    expect(error.textContent).toContain("deployment history failed: 404 deployment_not_found");
    expect(screen.queryByTestId("ops-history-detail-loading")).toBeNull();
    expect(detailConfigText()).toBeNull();
  });

  it("ignores a settlement that lands after unmount without throwing", async () => {
    const calls: DetailCall[] = [];
    const client = makeClient(() => Promise.resolve([ROW_A]), detailQueue(calls));
    const view = render(<DeploymentHistory client={client} />);
    fireEvent.click(await screen.findByTestId("ops-history-row-dep-a"));
    view.unmount();
    await settle(() => calls[0].request.reject(new Error("post-unmount refusal")));
    expect(document.querySelector(".kbot-ops__history")).toBeNull();
  });
});
