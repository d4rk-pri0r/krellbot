/**
 * StrategyExplanation nested Boolean group rendering — issue 163 regression.
 *
 * Saved rule explanations must keep nested all/any group boundaries: every
 * group owns one labelled <li> whose nested <ul> contains ONLY that group's
 * children, recursively. The two differently scoped trees
 * {all:[{any:[A,B]},C]} and {all:[{any:[A,B,C]}]} previously rendered
 * identical entry DOM and text; these tests pin the structural difference
 * while preserving leaf order, supplied values, joiner labels,
 * unsupported/malformed/depth disclosures, single-leaf content, revision
 * binding, metadata, indicators, markets and the CSV export bytes.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { explainPack } from "./explainPack";
import { StrategyExplanation } from "./StrategyExplanation";

afterEach(cleanup);

const supportedPack = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "krellbot tests",
  origin: "Test fixture.",
  timeframe: "1h",
  indicators: { sma20: { fn: "sma", src: "close", len: 20 } },
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
};

const leaf10 = "the close price is greater than the fixed number 10";
const leaf20 = "the close price is greater than the fixed number 20";
const leaf30 = "the close price is greater than the fixed number 30";
const exitLeaf10 = "the close price is less than the fixed number 10";
const exitLeaf20 = "the close price is less than the fixed number 20";
const exitLeaf30 = "the close price is less than the fixed number 30";

const requiredSiblingEntry = {
  all: [{ any: [["close", ">", 10], ["close", ">", 20]] }, ["close", ">", 30]],
};
const alternativeEntry = {
  all: [{ any: [["close", ">", 10], ["close", ">", 20], ["close", ">", 30]] }],
};

type Joiner = "all" | "any";

const joinerLabel = (joiner: Joiner): string =>
  joiner === "all" ? "All of these are true:" : "Any of these is true:";

function listItems(list: Element): HTMLLIElement[] {
  return Array.from(list.children).filter(
    (child): child is HTMLLIElement => child instanceof HTMLLIElement,
  );
}

function nestedList(group: HTMLLIElement): HTMLUListElement {
  const list = Array.from(group.children).find(
    (child) => child instanceof HTMLUListElement,
  );
  if (!(list instanceof HTMLUListElement)) {
    throw new Error("Expected the group <li> to own a nested <ul> of only its children.");
  }
  return list;
}

function leafTexts(list: Element): string[] {
  return listItems(list)
    .filter(
      (li) => !Array.from(li.children).some((child) => child instanceof HTMLUListElement),
    )
    .map((li) => li.textContent ?? "");
}

function owningGroupItem(label: HTMLElement): HTMLLIElement {
  const li = label.closest("li");
  if (!(li instanceof HTMLLIElement)) {
    throw new Error(`Expected a group <li> owning the "${label.textContent}" label.`);
  }
  return li;
}

function groupItem(scope: HTMLElement, joiner: Joiner): HTMLLIElement {
  return owningGroupItem(within(scope).getByText(joinerLabel(joiner)));
}

function groupItems(scope: HTMLElement, joiner: Joiner): HTMLLIElement[] {
  return within(scope)
    .getAllByText(joinerLabel(joiner))
    .map((label) => owningGroupItem(label));
}

describe("StrategyExplanation nested Boolean group structure", () => {
  it("renders differently scoped all/any trees as different entry DOM", () => {
    const required = render(
      <StrategyExplanation
        bytes={JSON.stringify({ ...supportedPack, entry: requiredSiblingEntry })}
        revisionId="rev-scope-a"
      />,
    );
    const entryA = screen.getByTestId("strategy-explanation-entry");
    const textA = entryA.textContent ?? "";
    required.unmount();

    render(
      <StrategyExplanation
        bytes={JSON.stringify({ ...supportedPack, entry: alternativeEntry })}
        revisionId="rev-scope-b"
      />,
    );
    const entryB = screen.getByTestId("strategy-explanation-entry");

    expect(entryA.innerHTML).not.toBe(entryB.innerHTML);
    for (const text of [leaf10, leaf20, leaf30]) {
      expect(textA).toContain(text);
      expect(entryB.textContent).toContain(text);
    }
  });

  it("keeps a nested any-group's children inside its own list and the following required sibling outside it", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({ ...supportedPack, entry: requiredSiblingEntry })}
        revisionId="rev-own"
      />,
    );
    const entry = screen.getByTestId("strategy-explanation-entry");

    expect(listItems(entry)).toHaveLength(1);
    const outer = groupItem(entry, "all");
    const outerList = nestedList(outer);
    const outerItems = listItems(outerList);
    expect(outerItems).toHaveLength(2);

    const anyGroup = groupItem(entry, "any");
    expect(outerItems).toContain(anyGroup);
    expect(leafTexts(nestedList(anyGroup))).toEqual([leaf10, leaf20]);
    expect(anyGroup.textContent).not.toContain(leaf30);

    const requiredSibling = outerItems.find((li) => li !== anyGroup);
    expect(requiredSibling?.textContent).toBe(leaf30);
  });

  it("renders the alternative scope with all three leaves inside the any-group", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({ ...supportedPack, entry: alternativeEntry })}
        revisionId="rev-alt"
      />,
    );
    const entry = screen.getByTestId("strategy-explanation-entry");

    expect(listItems(entry)).toHaveLength(1);
    const outer = groupItem(entry, "all");
    const outerList = nestedList(outer);
    expect(listItems(outerList)).toHaveLength(1);

    const anyGroup = groupItem(entry, "any");
    expect(leafTexts(nestedList(anyGroup))).toEqual([leaf10, leaf20, leaf30]);
  });

  it("renders nested groups in both the entry and the exit lists", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          entry: requiredSiblingEntry,
          exit: {
            all: [{ any: [["close", "<", 10], ["close", "<", 20]] }, ["close", "<", 30]],
          },
        })}
        revisionId="rev-both"
      />,
    );
    for (const testId of ["strategy-explanation-entry", "strategy-explanation-exit"]) {
      const list = screen.getByTestId(testId);
      expect(listItems(list)).toHaveLength(1);
      const outer = groupItem(list, "all");
      const outerItems = listItems(nestedList(outer));
      expect(outerItems).toHaveLength(2);
      const anyGroup = groupItem(list, "any");
      const expected = testId.endsWith("entry") ? [leaf10, leaf20] : [exitLeaf10, exitLeaf20];
      expect(leafTexts(nestedList(anyGroup))).toEqual(expected);
      const sibling = outerItems.find((li) => li !== anyGroup);
      expect(sibling?.textContent).toBe(
        testId.endsWith("entry") ? leaf30 : exitLeaf30,
      );
    }
  });

  it("supports both operator nesting directions", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          entry: {
            any: [{ all: [["close", ">", 10], ["close", ">", 20]] }, ["close", ">", 30]],
          },
          exit: {
            all: [{ any: [["close", "<", 10], ["close", "<", 20]] }, ["close", "<", 30]],
          },
        })}
        revisionId="rev-dirs"
      />,
    );

    const entry = screen.getByTestId("strategy-explanation-entry");
    const entryAny = groupItem(entry, "any");
    const entryAnyItems = listItems(nestedList(entryAny));
    expect(entryAnyItems).toHaveLength(2);
    const entryAll = groupItem(entry, "all");
    expect(leafTexts(nestedList(entryAll))).toEqual([leaf10, leaf20]);
    expect(entryAll.textContent).not.toContain(leaf30);
    const entrySibling = entryAnyItems.find((li) => li !== entryAll);
    expect(entrySibling?.textContent).toBe(leaf30);

    const exit = screen.getByTestId("strategy-explanation-exit");
    const exitAll = groupItem(exit, "all");
    const exitAllItems = listItems(nestedList(exitAll));
    expect(exitAllItems).toHaveLength(2);
    const exitAny = groupItem(exit, "any");
    expect(leafTexts(nestedList(exitAny))).toEqual([exitLeaf10, exitLeaf20]);
    expect(exitAny.textContent).not.toContain(exitLeaf30);
    const exitSibling = exitAllItems.find((li) => li !== exitAny);
    expect(exitSibling?.textContent).toBe(exitLeaf30);
  });

  it("keeps sibling groups each owning only their own children in stored order", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          entry: {
            all: [
              { any: [["close", ">", 10]] },
              { any: [["close", ">", 20]] },
              ["close", ">", 30],
            ],
          },
        })}
        revisionId="rev-siblings"
      />,
    );
    const entry = screen.getByTestId("strategy-explanation-entry");
    const outer = groupItem(entry, "all");
    const outerList = nestedList(outer);
    const outerItems = listItems(outerList);
    expect(outerItems).toHaveLength(3);

    const anyGroups = groupItems(entry, "any");
    expect(anyGroups).toHaveLength(2);
    expect(outerItems[0]).toBe(anyGroups[0]);
    expect(outerItems[1]).toBe(anyGroups[1]);
    expect(leafTexts(nestedList(anyGroups[0]))).toEqual([leaf10]);
    expect(leafTexts(nestedList(anyGroups[1]))).toEqual([leaf20]);
    expect(anyGroups[0].textContent).not.toContain(leaf20);
    expect(anyGroups[1].textContent).not.toContain(leaf10);
    expect(outerItems[2].textContent).toBe(leaf30);
    for (const group of anyGroups) {
      expect(group.textContent).not.toContain(leaf30);
    }
  });
});

describe("StrategyExplanation nested groups at the DSL depth limits", () => {
  it("nests the DSL maximum supported group depth fully without inventing unknowns", () => {
    const maxDepthEntry = {
      all: [{ any: [{ all: [["close", ">", 10]] }] }],
    };
    const bytes = JSON.stringify({ ...supportedPack, entry: maxDepthEntry });
    const pack = explainPack(bytes, "rev-max");
    expect(pack.entry.kind).toBe("group");
    expect(pack.hasUnknowns).toBe(false);

    render(<StrategyExplanation bytes={bytes} revisionId="rev-max" />);
    const entry = screen.getByTestId("strategy-explanation-entry");

    expect(listItems(entry)).toHaveLength(1);
    const allGroups = groupItems(entry, "all");
    expect(allGroups).toHaveLength(2);
    const anyGroups = groupItems(entry, "any");
    expect(anyGroups).toHaveLength(1);

    expect(listItems(nestedList(allGroups[0]))).toEqual([anyGroups[0]]);
    expect(listItems(nestedList(anyGroups[0]))).toEqual([allGroups[1]]);
    expect(leafTexts(nestedList(allGroups[1]))).toEqual([leaf10]);

    expect(entry.textContent).not.toContain("nested deeper");
    expect(screen.queryByTestId("strategy-explanation-unknowns")).toBeNull();
  });

  it("keeps an over-depth group disclosed as an unknown inside its owning group", () => {
    const overDepthEntry = {
      all: [{ any: [{ all: [{ any: [["close", ">", 10]] }] }] }],
    };
    render(
      <StrategyExplanation
        bytes={JSON.stringify({ ...supportedPack, entry: overDepthEntry })}
        revisionId="rev-deep"
      />,
    );
    const entry = screen.getByTestId("strategy-explanation-entry");

    const allGroups = groupItems(entry, "all");
    expect(allGroups).toHaveLength(2);
    const anyGroups = groupItems(entry, "any");
    expect(anyGroups).toHaveLength(1);
    expect(listItems(nestedList(allGroups[0]))).toEqual([anyGroups[0]]);
    expect(listItems(nestedList(anyGroups[0]))).toEqual([allGroups[1]]);

    const disclosureItems = leafTexts(nestedList(allGroups[1]));
    expect(disclosureItems).toHaveLength(1);
    expect(disclosureItems[0]).toContain('a "any" grouping nested deeper than the DSL allows');
    expect(screen.getByTestId("strategy-explanation-unknowns")).toBeTruthy();
  });
});

describe("StrategyExplanation grouping preserved behavior", () => {
  it("keeps a single leaf condition as one plain list item in entry and exit", () => {
    render(
      <StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId="rev-leaf" />,
    );
    const entry = screen.getByTestId("strategy-explanation-entry");
    expect(listItems(entry)).toHaveLength(1);
    expect(listItems(entry)[0].textContent).toBe(
      'the close price is greater than the indicator "sma20"',
    );
    expect(entry.querySelectorAll("ul")).toHaveLength(0);

    const exit = screen.getByTestId("strategy-explanation-exit");
    expect(listItems(exit)).toHaveLength(1);
    expect(listItems(exit)[0].textContent).toBe(
      'the close price is less than the indicator "sma20"',
    );
    expect(exit.querySelectorAll("ul")).toHaveLength(0);
  });

  it("keeps unknown and malformed descendants inside their owning group's list", () => {
    render(
      <StrategyExplanation
        bytes={JSON.stringify({
          ...supportedPack,
          entry: { all: [{ any: [["close", "!=", 10]] }, [], {}] },
        })}
        revisionId="rev-unknowns"
      />,
    );
    const entry = screen.getByTestId("strategy-explanation-entry");

    expect(listItems(entry)).toHaveLength(1);
    const outer = groupItem(entry, "all");
    const outerItems = listItems(nestedList(outer));
    expect(outerItems).toHaveLength(3);

    const anyGroup = groupItem(entry, "any");
    const anyLeaves = leafTexts(nestedList(anyGroup));
    expect(anyLeaves).toHaveLength(1);
    expect(anyLeaves[0]).toContain("a comparison with an unsupported operator");
    expect(anyGroup.textContent).not.toContain("an unsupported grouping");

    expect(outerItems[1].textContent).toContain("an unsupported condition");
    expect(outerItems[2].textContent).toContain("an unsupported grouping");
    expect(screen.getByTestId("strategy-explanation-unknowns")).toBeTruthy();
  });

  it("keeps revision binding, metadata, indicators, markets and CSV bytes unchanged by nesting", async () => {
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test-url");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    try {
      const nested = render(
        <StrategyExplanation
          bytes={JSON.stringify({ ...supportedPack, entry: requiredSiblingEntry })}
          revisionId="rev-163"
        />,
      );
      expect(screen.getByTestId("strategy-explanation-revision").textContent).toBe(
        "Saved revision rev-163",
      );
      const metadata = screen.getByTestId("strategy-explanation-metadata").textContent ?? "";
      expect(metadata).toContain("Label: Trend follow");
      expect(metadata).toContain("Pack id: trend-follow");
      expect(metadata).toContain("Version: 1.0.0");
      expect(metadata).toContain("Author: krellbot tests");
      expect(screen.getByTestId("strategy-explanation-indicators").textContent).toContain(
        '"sma20" = sma of close over the last 20 bars',
      );
      expect(screen.getByTestId("strategy-explanation-markets").textContent).toContain(
        "kraken: SUIUSD",
      );
      const button = screen.getByTestId(
        "strategies-explanation-csv-export",
      ) as HTMLButtonElement;
      expect(button.disabled).toBe(false);
      fireEvent.click(button);
      nested.unmount();

      render(
        <StrategyExplanation bytes={JSON.stringify(supportedPack)} revisionId="rev-7" />,
      );
      fireEvent.click(screen.getByTestId("strategies-explanation-csv-export"));

      expect(createObjectURL).toHaveBeenCalledTimes(2);
      const nestedCsv = await (createObjectURL.mock.calls[0][0] as Blob).text();
      const flatCsv = await (createObjectURL.mock.calls[1][0] as Blob).text();
      expect(nestedCsv).toContain("section,key,value");
      expect(nestedCsv).toContain("metadata,label,Trend follow");
      expect(nestedCsv).toContain("indicator,sma20,");
      expect(nestedCsv).toContain("market,kraken SUIUSD,SUIUSD");
      expect(nestedCsv).toBe(flatCsv);
    } finally {
      click.mockRestore();
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });
});
