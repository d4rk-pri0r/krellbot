import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeExportPanel } from "./HomeExportPanel";
import type { HomeExportClient } from "./homeExportClient";

afterEach(() => {
  cleanup();
});

function makeClient(
  exportHome: HomeExportClient["exportHome"] = vi.fn().mockResolvedValue({
    blob: new Blob(["archive"], { type: "application/gzip" }),
    filename: "krellbot-home-1700000123.tar.gz",
  }),
): HomeExportClient {
  return { exportHome };
}

describe("HomeExportPanel", () => {
  it("downloads a local home backup archive on click", async () => {
    const exportHome = vi.fn().mockResolvedValue({
      blob: new Blob(["archive"], { type: "application/gzip" }),
      filename: "krellbot-home-1700000123.tar.gz",
    });
    const triggerDownload = vi.fn();
    render(
      <HomeExportPanel client={makeClient(exportHome)} triggerDownload={triggerDownload} />,
    );

    expect(screen.getByTestId("ops-home-export")).toBeTruthy();
    expect(screen.getByTestId("ops-home-export").textContent).toContain(
      "Export stays available when the store is down",
    );

    fireEvent.click(screen.getByTestId("ops-home-export-download"));
    await waitFor(() => expect(exportHome).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(triggerDownload).toHaveBeenCalledTimes(1));
    const [blob, filename] = triggerDownload.mock.calls[0];
    expect(filename).toBe("krellbot-home-1700000123.tar.gz");
    expect(blob).toBeInstanceOf(Blob);
    expect(
      (await screen.findByTestId("ops-home-export-feedback")).textContent,
    ).toBe("Backup downloaded.");
  });

  it("surfaces export failures without claiming success", async () => {
    const exportHome = vi
      .fn()
      .mockRejectedValue(new Error("home export failed: 400: secret_detected"));
    render(<HomeExportPanel client={makeClient(exportHome)} />);

    fireEvent.click(screen.getByTestId("ops-home-export-download"));
    const alert = await screen.findByTestId("ops-home-export-error");
    expect(alert.textContent).toContain("secret_detected");
    expect(screen.queryByTestId("ops-home-export-feedback")).toBeNull();
  });
});
