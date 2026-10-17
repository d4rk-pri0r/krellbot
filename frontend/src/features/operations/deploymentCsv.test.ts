import { describe, expect, it } from "vitest";
import {
  deploymentCsvBody,
  deploymentCsvField,
  deploymentCsvHeader,
  deploymentCsvRow,
} from "./deploymentCsv";
import type { DeploymentRow } from "./client";

function makeDeployment(over: Partial<DeploymentRow> = {}): DeploymentRow {
  return {
    venue: "kraken",
    pair: "XBT/USD",
    pack_id: "p",
    pack_version: "1",
    mode: "paper",
    entries_paused: false,
    promotion: { available: false, code: "live_promotion_owner_deferred" },
    ...over,
  };
}

describe("deploymentCsvField (RFC 4180 quote-only-when-needed)", () => {
  it("returns the empty string unchanged", () => {
    expect(deploymentCsvField("")).toBe("");
  });

  it("returns a plain field without quoting", () => {
    expect(deploymentCsvField("a")).toBe("a");
  });

  it("quotes a field containing a comma", () => {
    expect(deploymentCsvField("a,b")).toBe('"a,b"');
  });

  it("quotes a field containing a quote and doubles the quote", () => {
    expect(deploymentCsvField('a"b')).toBe('"a""b"');
  });

  it("quotes a field containing a newline and preserves the newline", () => {
    expect(deploymentCsvField("a\nb")).toBe('"a\nb"');
  });
});

describe("deploymentCsvHeader", () => {
  it("returns the deterministic column order without controls", () => {
    expect(deploymentCsvHeader()).toEqual([
      "pack_id",
      "venue",
      "pair",
      "mode",
      "entries",
    ]);
  });
});

describe("deploymentCsvRow", () => {
  it("maps entries_paused false to active", () => {
    expect(
      deploymentCsvRow(
        makeDeployment({ pack_id: "p", entries_paused: false }),
      ),
    ).toEqual(["p", "kraken", "XBT/USD", "paper", "active"]);
  });

  it("maps entries_paused true to paused", () => {
    expect(
      deploymentCsvRow(
        makeDeployment({ pack_id: "p", entries_paused: true }),
      ),
    ).toEqual(["p", "kraken", "XBT/USD", "paper", "paused"]);
  });

  it("maps entries_paused undefined to active", () => {
    const row = makeDeployment({ pack_id: "p" });
    expect(deploymentCsvRow({ ...row, entries_paused: undefined })).toEqual([
      "p",
      "kraken",
      "XBT/USD",
      "paper",
      "active",
    ]);
  });
});

describe("deploymentCsvBody", () => {
  it("returns an empty string for an empty list", () => {
    expect(deploymentCsvBody([])).toBe("");
  });

  it("returns the header and rows joined by CRLF", () => {
    const first = makeDeployment({ pack_id: "alpha" });
    const second = makeDeployment({ pack_id: "beta", entries_paused: true });
    expect(deploymentCsvBody([first, second])).toBe(
      "pack_id,venue,pair,mode,entries\r\n" +
        "alpha,kraken,XBT/USD,paper,active\r\n" +
        "beta,kraken,XBT/USD,paper,paused",
    );
  });

  it("escapes commas and quotes inside fields", () => {
    const row = makeDeployment({ pack_id: 'a,b"c' });
    expect(deploymentCsvBody([row])).toBe(
      'pack_id,venue,pair,mode,entries\r\n"a,b""c",kraken,XBT/USD,paper,active',
    );
  });
});
