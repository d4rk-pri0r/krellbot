import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndicatorSpecJsonExport } from "./IndicatorSpecJsonExport";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

type AnchorSpy = {
  href: string;
  download: string;
  click: ReturnType<typeof vi.fn<() => void>>;
};

function stubDownloadEnvironment() {
  const objectUrls: string[] = [];
  const revokedUrls: string[] = [];
  const anchors: AnchorSpy[] = [];
  const blobs: Blob[] = [];

  const revokeObjectURL = vi.fn((url: string) => {
    revokedUrls.push(url);
  });

  const createElement = vi
    .spyOn(document, "createElement")
    .mockImplementation((tagName: string) => {
      const element = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tagName,
      ) as HTMLAnchorElement;
      if (tagName.toLowerCase() === "a") {
        const anchor: AnchorSpy = {
          href: "",
          download: "",
          click: vi.fn(),
        };
        anchors.push(anchor);
        Object.defineProperty(element, "href", {
          get: () => anchor.href,
          set: (value: string) => {
            anchor.href = value;
          },
          configurable: true,
        });
        Object.defineProperty(element, "download", {
          get: () => anchor.download,
          set: (value: string) => {
            anchor.download = value;
          },
          configurable: true,
        });
        element.click = anchor.click;
      }
      return element;
    });

  const createObjectURL = vi.fn((blob: Blob) => {
    blobs.push(blob);
    const url = `blob:mock-${objectUrls.length + 1}`;
    objectUrls.push(url);
    return url;
  });
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

  return {
    anchors,
    revokeObjectURL,
    createObjectURL,
    objectUrls,
    firstBlob: () => blobs[0],
  };
}

describe("IndicatorSpecJsonExport", () => {
  it("renders nothing when spec is null", () => {
    const { container } = render(<IndicatorSpecJsonExport spec={null} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("studio-indicator-spec-export")).toBeNull();
  });

  it("renders exactly one export button with the expected label", () => {
    render(<IndicatorSpecJsonExport spec={{ name: "rsi", len: 14 }} />);
    const button = screen.getByTestId("studio-indicator-spec-export");
    expect(screen.getAllByTestId("studio-indicator-spec-export")).toHaveLength(1);
    expect(button.getAttribute("type")).toBe("button");
    expect(button.textContent).toBe("Export spec JSON");
    expect(button.className).toBe("kbot-studio-node-inspector__export");
  });

  it("downloads a JSON blob and revokes the object URL on click", async () => {
    const env = stubDownloadEnvironment();
    render(
      <IndicatorSpecJsonExport
        spec={{ name: "rsi", len: 14 }}
        timestamp="20261008T055500Z"
      />,
    );
    fireEvent.click(screen.getByTestId("studio-indicator-spec-export"));

    expect(env.anchors).toHaveLength(1);
    expect(env.anchors[0].click).toHaveBeenCalledTimes(1);
    expect(env.revokeObjectURL).toHaveBeenCalledTimes(1);

    expect(env.createObjectURL).toHaveBeenCalledTimes(1);
    const blob = env.firstBlob();
    expect(blob.type).toBe("application/json;charset=utf-8");
    expect(await blob.text()).toBe('{\n  "name": "rsi",\n  "len": 14\n}\n');
    expect(env.anchors[0].download).toBe(
      "krellbot-indicator-rsi-20261008T055500Z.json",
    );
    expect(env.anchors[0].href).toBe(env.objectUrls[0]);
    expect(env.revokeObjectURL).toHaveBeenCalledWith(env.objectUrls[0]);
  });

  it("uses the provided spec name and len exactly", async () => {
    const env = stubDownloadEnvironment();
    render(
      <IndicatorSpecJsonExport
        spec={{ name: "ema 200/fast", len: 200 }}
        timestamp="20261008T055500Z"
      />,
    );
    fireEvent.click(screen.getByTestId("studio-indicator-spec-export"));

    const blob = env.firstBlob();
    expect(await blob.text()).toBe(
      '{\n  "name": "ema 200/fast",\n  "len": 200\n}\n',
    );
    expect(env.anchors[0].download).toBe(
      "krellbot-indicator-ema_200_fast-20261008T055500Z.json",
    );
  });
});
