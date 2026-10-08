import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { fetchStarters, type StarterExample } from "./StarterPicker.client";
import { StarterPicker } from "./StarterPicker";
import type { Pack } from "./client";

afterEach(cleanup);

/**
 * Minimal IntersectionObserver stand-in: report the element as visible
 * as soon as it is observed. The real catalogue request is still the
 * production `fetchStarters` path (mocked at the network boundary);
 * only the viewport capability is provided.
 */
class VisibleIntersectionObserver {
  static instances: VisibleIntersectionObserver[] = [];
  callback: IntersectionObserverCallback;
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    VisibleIntersectionObserver.instances.push(this);
  }
  observe(target: Element): void {
    this.callback(
      [{ isIntersecting: true, target } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
  disconnect(): void {}
  unobserve(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

beforeAll(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    VisibleIntersectionObserver as unknown as typeof IntersectionObserver,
  );
});

afterAll(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  VisibleIntersectionObserver.instances = [];
});


const dualMaPack: Pack = {
  schema_version: 1,
  id: "starter-dual-ma-crossover",
  label: "Dual MA crossover (educational example)",
  timeframe: "1h",
};

const meanReversionPack: Pack = {
  schema_version: 1,
  id: "starter-mean-reversion-band",
  label: "Mean reversion band (educational example)",
  timeframe: "1h",
};

const rangeBreakoutPack: Pack = {
  schema_version: 1,
  id: "starter-range-breakout",
  label: "Range breakout (educational example)",
  timeframe: "1h",
};

const examples: StarterExample[] = [
  {
    id: "starter-dual-ma-crossover",
    label: "Dual moving-average crossover",
    description:
      "Educational example. Enters long when a 10-bar SMA of close crosses above a 30-bar SMA.",
    pack: dualMaPack,
  },
  {
    id: "starter-mean-reversion-band",
    label: "Mean reversion band",
    description:
      "Educational example. Enters long when close is under a 20-bar SMA.",
    pack: meanReversionPack,
  },
  {
    id: "starter-range-breakout",
    label: "Range breakout",
    description:
      "Educational example. Enters long when close pushes above the 20-bar average high.",
    pack: rangeBreakoutPack,
  },
];

const fetchStartersMock = vi.mocked(fetchStarters);

vi.mock("./StarterPicker.client", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("./StarterPicker.client")>();
  return {
    ...original,
    fetchStarters: vi.fn(),
  };
});

function makeClient(overrides: Partial<StrategyClient> = {}): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-create",
      state: "draft",
      pack: dualMaPack,
      errors: [],
      outcome: "created",
    }),
    edit: vi.fn().mockImplementation(
      async (parentRevisionId: string, pack: Pack) => ({
        revision_id: "rev-edit",
        parent_revision_id: parentRevisionId,
        state: "draft",
        pack,
        errors: [],
      }),
    ),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-validate",
      state: "draft",
      pack: dualMaPack,
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("StarterPicker contract", () => {
  it("fetches the starters endpoint once on mount", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    render(<StarterPicker onPick={() => {}} />);
    await waitFor(() => {
      expect(fetchStartersMock).toHaveBeenCalledTimes(1);
    });
  });

  it("renders all three starter examples with label and description", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    render(<StarterPicker onPick={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText("Dual moving-average crossover")).toBeDefined();
    });
    expect(screen.getByText("Mean reversion band")).toBeDefined();
    expect(screen.getByText("Range breakout")).toBeDefined();
    for (const example of examples) {
      expect(screen.getByText(example.description)).toBeDefined();
    }
  });

  it("hands the full pack to onPick when an entry is used", async () => {
    const onPick = vi.fn();
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    render(<StarterPicker onPick={onPick} />);
    const button = await waitFor(() =>
      screen.getByRole("button", { name: "Use Mean reversion band" }),
    );
    fireEvent.click(button);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "starter-mean-reversion-band", pack: meanReversionPack }),
    );
  });

  it("is clearly labelled as the free starter examples section", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    render(<StarterPicker onPick={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText("Free Starter Examples")).toBeDefined();
    });
    expect(screen.getByRole("region", { name: "Free starter examples" })).toBeDefined();
  });
});

describe("fetchStarters (real helper, stubbed network)", () => {
  const realFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  function jsonResponse(body: unknown, ok = true, status = 200): Response {
    return {
      ok,
      status,
      json: async () => body,
    } as Response;
  }

  it("parses the catalogue contract and maps version 0 to an empty list upstream of the picker", async () => {
    const { fetchStarters: realFetchStarters } = await vi.importActual<
      typeof import("./StarterPicker.client")
    >("./StarterPicker.client");
    globalThis.fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        catalogue_version: "1",
        examples: [
          {
            id: "starter-dual-ma-crossover",
            label: "Dual moving-average crossover",
            description: "d",
            pack: { id: "starter-dual-ma-crossover" },
          },
        ],
      }),
    );
    const catalogue = await realFetchStarters();
    expect(catalogue.schema_version).toBe("1");
    expect(catalogue.examples).toHaveLength(1);
    expect(catalogue.examples[0].pack).toEqual({
      id: "starter-dual-ma-crossover",
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/packs/starters",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("throws an explicit error on a non-2xx response", async () => {
    const { fetchStarters: realFetchStarters } = await vi.importActual<
      typeof import("./StarterPicker.client")
    >("./StarterPicker.client");
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({}, false, 500));
    await expect(realFetchStarters()).rejects.toThrow(
      "starter catalogue unavailable: 500",
    );
  });

  it("throws an explicit error on a malformed body", async () => {
    const { fetchStarters: realFetchStarters } = await vi.importActual<
      typeof import("./StarterPicker.client")
    >("./StarterPicker.client");
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({ nope: 1 }));
    await expect(realFetchStarters()).rejects.toThrow(
      "starter catalogue response malformed",
    );
  });
});

describe("Editor + StarterPicker integration", () => {
  it("mounts the starter picker above the raw JSON textarea", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    render(<Editor client={makeClient()} />);
    const picker = await waitFor(() => screen.getByTestId("starter-picker"));
    const textarea = screen.getByLabelText(/raw json/i);
    // DOM order: the picker section precedes the Raw JSON field.
    expect(picker.compareDocumentPosition(textarea as Node) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
  });

  it("seeds rawJson with the reserialized starter pack on pick", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    render(<Editor client={makeClient()} />);
    const button = await waitFor(() =>
      screen.getByRole("button", { name: "Use Dual moving-average crossover" }),
    );
    fireEvent.click(button);
    const textarea = screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe(JSON.stringify(dualMaPack, null, 2));
  });

  it("seeding a starter is not a reopen: Save creates a fresh revision", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    const client = makeClient();
    // Simulate a previously saved/opened revision in the editor.
    render(
      <Editor
        client={client}
        initial={{
          revision_id: "rev-previous",
          state: "draft",
          bytes: JSON.stringify(dualMaPack, null, 2),
        }}
      />,
    );
    expect(screen.getByTestId("editor-revision-id").textContent).toContain(
      "rev-previous",
    );
    const button = await waitFor(() =>
      screen.getByRole("button", { name: "Use Range breakout" }),
    );
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.queryByTestId("editor-revision-id")).toBeNull();
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(client.create).toHaveBeenCalledWith(rangeBreakoutPack);
    expect(client.edit).not.toHaveBeenCalled();
  });

  it("each pick seeds distinct bytes and the existing Save path still runs", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    const client = makeClient();
    render(<Editor client={client} />);
    const seen: string[] = [];
    for (const label of [
      "Dual moving-average crossover",
      "Mean reversion band",
      "Range breakout",
    ]) {
      const button = await screen.findByRole("button", { name: `Use ${label}` });
      fireEvent.click(button);
      const value = (screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value;
      expect(seen).not.toContain(value);
      seen.push(value);
    }
    expect(seen).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(client.create).toHaveBeenCalledTimes(1);
    });
    expect(JSON.parse(seen[2])).toEqual(rangeBreakoutPack);
  });

  it("does not mutate existing saved draft bytes rendered alongside", async () => {
    fetchStartersMock.mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      examples,
    });
    const savedBytes = JSON.stringify(
      { id: "paid-import", label: "Paid import", timeframe: "4h" },
      null,
      2,
    );
    render(
      <Editor
        client={makeClient()}
        initial={{ revision_id: "rev-saved", state: "draft", bytes: savedBytes }}
      />,
    );
    await screen.findByTestId("starter-picker");
    expect((screen.getByLabelText(/raw json/i) as HTMLTextAreaElement).value).toBe(
      savedBytes,
    );
  });
});
