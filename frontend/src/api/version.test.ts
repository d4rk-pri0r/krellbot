import { afterEach, describe, expect, it, vi } from "vitest";
import {
  adaptVersionInfo,
  channelMatchesSigning,
  createVersionHttpClient,
  type VersionInfo,
} from "./version";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("adaptVersionInfo", () => {
  it("adapts a closed version payload", () => {
    expect(
      adaptVersionInfo({
        schema_version: "1",
        version: "0.9.7",
        channel: "prerelease",
        artifacts_signed: false,
      }),
    ).toEqual({
      schema_version: "1",
      version: "0.9.7",
      channel: "prerelease",
      artifacts_signed: false,
    });
  });

  it("defaults unknown channel to prerelease and unsigned", () => {
    expect(adaptVersionInfo({ version: "1.0.0", channel: "stable" })).toEqual({
      schema_version: "1",
      version: "1.0.0",
      channel: "prerelease",
      artifacts_signed: false,
    });
  });
});

describe("channelMatchesSigning", () => {
  const base: VersionInfo = {
    schema_version: "1",
    version: "0.9.7",
    channel: "prerelease",
    artifacts_signed: false,
  };

  it("allows prerelease while unsigned", () => {
    expect(channelMatchesSigning(base)).toBe(true);
  });

  it("refuses GA while unsigned", () => {
    expect(
      channelMatchesSigning({ ...base, channel: "ga", artifacts_signed: false }),
    ).toBe(false);
  });

  it("allows GA when signed", () => {
    expect(
      channelMatchesSigning({ ...base, channel: "ga", artifacts_signed: true }),
    ).toBe(true);
  });
});

describe("createVersionHttpClient", () => {
  it("GETs /api/v1/version with credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: "1",
        version: "0.9.7",
        channel: "prerelease",
        artifacts_signed: false,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const info = await createVersionHttpClient().getVersion();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/version", {
      credentials: "include",
    });
    expect(info.version).toBe("0.9.7");
    expect(info.channel).toBe("prerelease");
    expect(info.artifacts_signed).toBe(false);
  });
});
