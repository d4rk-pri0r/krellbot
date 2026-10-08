import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeploymentsCsvExport } from "./DeploymentsCsvExport";
import type { DeploymentRow } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeDeployment(over: Partial<DeploymentRow> = {}): DeploymentRow {
  return {
    venue: "kraken",
    pair: "XBT/USD",
    pack_id: "alpha",
    pack_version: "1",
    mode: "paper",
    entries_paused: false,
    promotion: { available: false, code: "live_promotion_owner_deferred" },
    ...over,
  };
}

describe("DeploymentsCsvExport", () => {
  it("renders a disabled button when deployments is empty", () => {
    render(<DeploymentsCsvExport deployments={[]} />);
    const button = screen.getByTestId(
      "ops-deployments-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("renders an enabled button labelled Export deployments when non-empty", () => {
    render(<DeploymentsCsvExport deployments={[makeDeployment()]} />);
    const button = screen.getByTestId(
      "ops-deployments-csv-export",
    ) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(button.textContent).toBe("Export deployments");
  });

  it("downloads a UTF-8 CSV blob of the deployment rows on click", async () => {
    render(
      <DeploymentsCsvExport
        deployments={[
          makeDeployment({ pack_id: "alpha" }),
          makeDeployment({ pack_id: "beta", entries_paused: true }),
        ]}
      />,
    );

    const originalCreateElement = document.createElement.bind(document);
    const createObjectURLSpy = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test-url");
    const revokeObjectURLSpy = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const createElementSpy = vi.spyOn(document, "createElement");
    const capturedAnchors: HTMLAnchorElement[] = [];
    createElementSpy.mockImplementation(((tag: string) => {
      const element = originalCreateElement(tag);
      if (tag === "a" && element instanceof HTMLAnchorElement) {
        capturedAnchors.push(element);
      }
      return element;
    }) as typeof document.createElement);

    fireEvent.click(screen.getByTestId("ops-deployments-csv-export"));

    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("text/csv;charset=utf-8");
    expect(await blob.text()).toBe(
      "pack_id,venue,pair,mode,entries\r\n" +
        "alpha,kraken,XBT/USD,paper,active\r\n" +
        "beta,kraken,XBT/USD,paper,paused",
    );

    const downloadAnchors = capturedAnchors.filter((a) =>
      a.download.startsWith("krellbot-deployments-"),
    );
    expect(downloadAnchors.length).toBeGreaterThan(0);
    expect(downloadAnchors[0].download).toMatch(/^krellbot-deployments-.*\.csv$/);

    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLSpy).toHaveBeenCalledTimes(1);

    clickSpy.mockRestore();
    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
    createElementSpy.mockRestore();
  });
});
