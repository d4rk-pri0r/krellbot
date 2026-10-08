import { describe, expect, it } from "vitest";
import {
  exportJobsCsvFilename,
  jobsCsvBody,
  jobsCsvField,
  jobsCsvHeader,
  jobsCsvRow,
} from "./jobsCsv";

describe("jobsCsvField", () => {
  it("returns the empty string unchanged", () => {
    expect(jobsCsvField("")).toBe("");
  });

  it("returns a plain field without quoting", () => {
    expect(jobsCsvField("a")).toBe("a");
  });

  it("quotes a field containing a comma", () => {
    expect(jobsCsvField("a,b")).toBe('"a,b"');
  });

  it("quotes a field containing a double quote and doubles the quote", () => {
    expect(jobsCsvField('a"b')).toBe('"a""b"');
  });

  it("quotes a field containing a newline", () => {
    expect(jobsCsvField("a\nb")).toBe('"a\nb"');
  });

  it("quotes a field containing a carriage return", () => {
    expect(jobsCsvField("a\rb")).toBe('"a\rb"');
  });
});

describe("jobsCsvHeader", () => {
  it("returns the deterministic column order id, kind, state", () => {
    expect(jobsCsvHeader()).toEqual(["id", "kind", "state"]);
  });
});

describe("jobsCsvRow", () => {
  it("passes the row fields through unchanged in column order", () => {
    expect(jobsCsvRow({ id: "job-1", kind: "research.backtest", state: "succeeded" })).toEqual([
      "job-1",
      "research.backtest",
      "succeeded",
    ]);
  });
});

describe("jobsCsvBody", () => {
  it("returns only the header row for an empty job list", () => {
    expect(jobsCsvBody([])).toBe("id,kind,state");
  });

  it("returns the header followed by each data row joined with LF", () => {
    expect(
      jobsCsvBody([
        { id: "job-1", kind: "research.backtest", state: "succeeded" },
        { id: "job-2", kind: "housekeeping.compact", state: "hibernating" },
      ]),
    ).toBe(
      "id,kind,state\njob-1,research.backtest,succeeded\njob-2,housekeeping.compact,hibernating",
    );
  });
});

describe("exportJobsCsvFilename", () => {
  it("concatenates the prefix, the timestamp, and the csv suffix", () => {
    expect(exportJobsCsvFilename("20261008T055500Z")).toBe(
      "krellbot-jobs-20261008T055500Z.csv",
    );
  });
});
