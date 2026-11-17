/**
 * Community pack open → Strategies validate → paper.arm (M17.6).
 * Contract: KRELL-SIGNAL-20261010. Fake fetch only — no network.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient as createPacksClient } from "./client";
import { createHttpClient as createStrategiesClient } from "../strategies/client";
import { createHttpClient as createPaperClient } from "../paper/client";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const COMMUNITY_PACK = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "community-example",
  origin: "Community pack. Unverified. No guarantee.",
  timeframe: "1h",
  indicators: { sma20: { fn: "sma", src: "close", len: 20 } },
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
};

describe("community pack open → validate → paper-arm", () => {
  it("opens a community pack, refuses unvalidated arm, then arms after validate", async () => {
    const revisionId = "a".repeat(64);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url === "/api/v1/community/packs/trend-follow" && method === "GET") {
        return jsonResponse({
          schema_version: "1",
          source: "community",
          path: "packs/community/trend-follow.json",
          pack: COMMUNITY_PACK,
        });
      }
      if (url === "/api/v1/strategies/drafts" && method === "POST") {
        return jsonResponse({
          schema_version: "1",
          strategy_id: "trend-follow",
          revision_id: revisionId,
          state: "draft",
          runnable: false,
        });
      }
      if (
        url === `/api/v1/strategies/drafts/${revisionId}/validate` &&
        method === "POST"
      ) {
        return jsonResponse({
          schema_version: "1",
          strategy_id: "trend-follow",
          revision_id: revisionId,
          state: "validated",
          runnable: true,
        });
      }
      if (url === "/api/v1/commands" && method === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}")) as {
          command?: string;
          payload?: { revision_id?: string };
        };
        expect(body.command).toBe("paper.arm");
        expect(body.payload?.revision_id).toBe(revisionId);
        // First arm attempt in this test is after validate → success.
        return jsonResponse({
          schema_version: "1",
          ok: true,
          code: "armed",
          message: "armed",
          effect: "applied",
          revision_before: null,
          revision_after: "1",
        });
      }
      throw new Error(`unexpected fetch ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const packs = createPacksClient();
    const strategies = createStrategiesClient();
    const paper = createPaperClient();
    expect(paper.arm).toBeTypeOf("function");
    const arm = paper.arm!;

    const opened = await packs.openCommunityPack("trend-follow");
    expect(opened.source).toBe("community");
    expect(opened.path).toBe("packs/community/trend-follow.json");
    expect(opened.pack.id).toBe("trend-follow");
    expect(opened.pack.author).toBe("community-example");

    const draft = await strategies.create(opened.pack);
    expect(draft.state).toBe("draft");
    expect(draft.revision_id).toBe(revisionId);

    // Unvalidated arm refusal (typed backend words).
    const refuseMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          schema_version: "1",
          ok: false,
          code: "draft_not_runnable",
          message: `draft ${revisionId} is not runnable`,
          effect: "refused",
        },
        403,
      ),
    );
    vi.stubGlobal("fetch", refuseMock);
    await expect(
      arm({
        revision_id: revisionId,
        venue: "kraken",
        mode: "paper",
        paper_balance: "1000",
      }),
    ).rejects.toMatchObject({ code: "draft_not_runnable" });

    vi.stubGlobal("fetch", fetchMock);
    const validated = await strategies.validate(revisionId);
    expect(validated.state).toBe("validated");

    const armed = await arm({
      revision_id: revisionId,
      venue: "kraken",
      mode: "paper",
      paper_balance: "1000",
    });
    expect(armed.ok).toBe(true);
    expect(armed.code).toBe("armed");
  });

  it("GETs /api/v1/community/packs/{id} with credentials and CSRF", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        source: "community",
        path: "packs/community/trend-follow.json",
        pack: COMMUNITY_PACK,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createPacksClient().openCommunityPack("trend-follow");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/community/packs/trend-follow",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });
});
