import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient, VersionInfo } from "../api/version";
import { AboutPanel } from "./AboutPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PREVIEW: VersionInfo = {
  schema_version: "1",
  version: "0.9.7",
  channel: "prerelease",
  artifacts_signed: false,
};

function fakeClient(over: Partial<VersionClient> = {}): VersionClient {
  return {
    getVersion: vi.fn().mockResolvedValue(PREVIEW),
    ...over,
  };
}

describe("AboutPanel version honesty", () => {
  it("surfaces version, prerelease channel, and unsigned signing state", async () => {
    render(<AboutPanel client={fakeClient()} />);

    expect((await screen.findByTestId("app-home-about-version")).textContent).toBe(
      "v0.9.7",
    );
    expect(screen.getByTestId("app-home-about-channel").textContent).toBe(
      "Prerelease",
    );
    expect(screen.getByTestId("app-home-about-signing").textContent).toBe(
      "Unsigned artifacts",
    );
  });

  it("refuses to render a dishonest GA claim while unsigned", async () => {
    const client = fakeClient({
      getVersion: vi.fn().mockResolvedValue({
        ...PREVIEW,
        channel: "ga",
        artifacts_signed: false,
      }),
    });
    render(<AboutPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("app-home-about-error").textContent).toMatch(
        /does not match signing/i,
      );
    });
    expect(screen.queryByTestId("app-home-about-facts")).toBeNull();
  });

  it("shows a load error when the version endpoint fails", async () => {
    const client = fakeClient({
      getVersion: vi.fn().mockRejectedValue(new Error("version request failed: 500")),
    });
    render(<AboutPanel client={client} />);

    expect((await screen.findByTestId("app-home-about-error")).textContent).toBe(
      "version request failed: 500",
    );
  });

  it("skips the network read when disabled", async () => {
    const client = fakeClient();
    render(<AboutPanel client={client} enabled={false} />);

    expect(screen.queryByTestId("app-home-about-loading")).toBeNull();
    expect(client.getVersion).not.toHaveBeenCalled();
  });

  it("shows digest and unsigned ARTIFACTS_SIGNED posture without claiming signed GA", async () => {
    render(<AboutPanel client={fakeClient()} />);

    expect(
      (await screen.findByTestId("app-home-about-digest")).textContent,
    ).toMatch(/HTTPS-pinned SHA-256/i);
    expect(screen.getByTestId("app-home-about-posture").textContent).toMatch(
      /ARTIFACTS_SIGNED is False/i,
    );
    expect(
      screen.getByTestId("app-home-about-signing-honesty").textContent,
    ).toMatch(/Do not treat this cut as signed GA/i);
    expect(screen.getByTestId("app-home-about-no-perf").textContent).toMatch(
      /not market performance/i,
    );
  });

  it("lists how to reproduce a starter pack and links signing docs", async () => {
    render(<AboutPanel client={fakeClient()} />);

    const steps = await screen.findByTestId("app-home-about-reproduce");
    expect(steps.textContent).toMatch(/Validate/i);
    expect(steps.textContent).toMatch(/kraken/i);
    expect(steps.textContent).toMatch(/1000/i);

    const links = screen.getByTestId("app-home-about-links");
    const hrefs = Array.from(links.querySelectorAll("a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs.some((h) => h?.includes("docs/evidence.md"))).toBe(true);
    expect(hrefs.some((h) => h?.includes("docs/signing.md"))).toBe(true);
    expect(hrefs.some((h) => h?.includes("krellbot.dev/docs/security"))).toBe(
      true,
    );
  });
});
