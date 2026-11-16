export type ReleaseChannel = "prerelease" | "ga";

export type VersionInfo = {
  schema_version: string;
  version: string;
  channel: ReleaseChannel;
  artifacts_signed: boolean;
};

export type VersionClient = {
  getVersion(): Promise<VersionInfo>;
};

export function adaptVersionInfo(raw: unknown): VersionInfo {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const channelRaw = obj.channel;
  const channel: ReleaseChannel =
    channelRaw === "ga" ? "ga" : "prerelease";
  return {
    schema_version:
      typeof obj.schema_version === "string" ? obj.schema_version : "1",
    version: typeof obj.version === "string" ? obj.version : "",
    channel,
    artifacts_signed: obj.artifacts_signed === true,
  };
}

/** Refuse a GA claim when artifacts are unsigned (client-side honesty). */
export function channelMatchesSigning(info: VersionInfo): boolean {
  if (!info.artifacts_signed) {
    return info.channel === "prerelease";
  }
  return info.channel === "prerelease" || info.channel === "ga";
}

export function createVersionHttpClient(): VersionClient {
  return {
    async getVersion(): Promise<VersionInfo> {
      const response = await fetch("/api/v1/version", {
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error(`version request failed: ${response.status}`);
      }
      return adaptVersionInfo(await response.json());
    },
  };
}
