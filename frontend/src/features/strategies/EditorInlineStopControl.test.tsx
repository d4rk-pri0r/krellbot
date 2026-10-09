import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";
import { summarizePaperCommandRefusal } from "../paper/paperCommandRefusalSummary";

afterEach(cleanup);

const validPack = {
  id: "trend-follow",
  label: "Trend follow",
  timeframe: "1h",
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
};

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-edit",
      state: "draft",
      pack: validPack,
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: validPack,
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
}

function okResult(code: string): PaperCommandResult {
  return {
    schema_version: "1",
    code,
    ok: true,
    message: `${code}: kraken SUIUSD`,
    effect: "changed",
  };
}

function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi
      .fn()
      .mockResolvedValue(okResult("entries_paused")),
    resumeEntries: vi
      .fn()
      .mockResolvedValue(okResult("entries_resumed")),
    disarm: vi.fn().mockResolvedValue(okResult("disarmed")),
    ...overrides,
  };
}

function disarmButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^disarm$/i,
  }) as HTMLButtonElement;
}

function pauseButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /pause entries/i,
  }) as HTMLButtonElement;
}

function resumeButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /resume entries/i,
  }) as HTMLButtonElement;
}

describe("Editor inline stop control mount", () => {
  it("renders the inline stop buttons inside the Editor view after the summary line when status says armed", async () => {
    const paperClient = makePaperClient();
    render(
      <Editor
        client={makeStrategyClient()}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    const summary = await screen.findByTestId("editor-revision-id");
    expect(summary.textContent).toMatch(/rev-1 \(state: Validated\)/);

    const control = await screen.findByTestId("editor-inline-stop");
    expect(control).toBeDefined();
    // Mounted immediately after the summary line, inside the Editor region.
    expect(summary.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(pauseButton().disabled).toBe(false);
    expect(resumeButton().disabled).toBe(false);
  });

  it("keeps the three stop buttons disabled until getStatus confirms armed=true", async () => {
    const paperClient = makePaperClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: false,
      }),
    });
    render(
      <Editor
        client={makeStrategyClient()}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(true);
    });
    expect(pauseButton().disabled).toBe(true);
    expect(resumeButton().disabled).toBe(true);
    expect(paperClient.disarm).not.toHaveBeenCalled();
  });

  it("Disarm click calls paperClient.disarm once with the armed venue/pair and disables the controls after confirmed ok", async () => {
    const paperClient = makePaperClient();
    render(
      <Editor
        client={makeStrategyClient()}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    fireEvent.click(disarmButton());

    await waitFor(() => {
      expect(paperClient.disarm).toHaveBeenCalledTimes(1);
    });
    expect(paperClient.disarm).toHaveBeenCalledWith("kraken", "SUIUSD");

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(true);
    });
    expect(pauseButton().disabled).toBe(true);
    expect(resumeButton().disabled).toBe(true);
    expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
      /No pack armed/,
    );
  });

  it("a refused disarm keeps the confirmed armed state and surfaces the summarizePaperCommandRefusal label", async () => {
    const refusal: PaperCommandResult = {
      schema_version: "1",
      code: "not_armed",
      ok: false,
    };
    const paperClient = makePaperClient({
      disarm: vi.fn().mockResolvedValue(refusal),
    });
    render(
      <Editor
        client={makeStrategyClient()}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    fireEvent.click(disarmButton());

    const error = await screen.findByTestId("editor-inline-stop-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe(
      summarizePaperCommandRefusal("Disarm", refusal).label,
    );
    // Refused: still armed, control stays usable.
    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
  });

  it("Pause entries click calls paperClient.pauseEntries once and shows the paused sentence", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(armedStatus({ entries_paused: false }))
      .mockResolvedValueOnce(armedStatus({ entries_paused: true }));
    const paperClient = makePaperClient({ getStatus });
    render(
      <Editor
        client={makeStrategyClient()}
        paperClient={paperClient}
        initial={{
          revision_id: "rev-1",
          state: "validated",
          bytes: JSON.stringify(validPack, null, 2),
        }}
      />,
    );

    await waitFor(() => {
      expect(pauseButton().disabled).toBe(false);
    });
    fireEvent.click(pauseButton());

    await waitFor(() => {
      expect(paperClient.pauseEntries).toHaveBeenCalledTimes(1);
    });
    expect(paperClient.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
    expect(
      (await screen.findByTestId("editor-inline-stop-entries")).textContent,
    ).toMatch(/Entries paused/);
  });
});
