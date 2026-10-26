/**
 * RehearsalFillsCsvExport — failure-recovery regressions (issue 189).
 *
 * The ordinary "Export visible fills" click owns every temporary download
 * artifact it creates: the attached anchor and the allocated object URL
 * must be released through every preparation/activation path, each
 * cleanup attempted independently of the other, cleanup refusals
 * contained, and the in-flight guard always released so the next
 * ordinary click works on the same mount without reset.
 *
 * Distinctions these tests pin down:
 * - an actual preactivation failure (URL allocation / attachment
 *   refusal) never attempts a browser delivery;
 * - an activation refusal (anchor click throws) has already attached
 *   the anchor — that attached anchor must be removed and its URL
 *   revoked before the accessible failure alert is shown;
 * - a refused cleanup after a delivered activation never retracts the
 *   delivered file and never disables the next ordinary export.
 *
 * Transport note: synthetic JSDOM fault injection with in-memory fakes
 * standing in for the browser download machinery. No real browser, OS
 * file-persistence or backend claim — the guarded browser journey
 * covers the real download path.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RehearsalFillsCsvExport, toRehearsalFillsCsv } from "./RehearsalFillsCsvExport";
import type { RehearsalFill } from "./rehearsalClient";

const EXPORT_ID = "rehearsal-fills-csv-export";
const ERROR_ID = "rehearsal-fills-csv-export-error";
const BUSY_ID = "rehearsal-fills-csv-export-busy-status";

function fill(extra: Partial<RehearsalFill> = {}): RehearsalFill {
  return {
    coid: "coid-entry-1",
    side: "buy",
    qty: "1.50000000",
    price: "0.00004500",
    ts_ms: 1760121005000,
    kind: "fill",
    ...extra,
  };
}

type RecordedAnchor = { href: string | null; download: string | null };

function downloadAnchors(): NodeListOf<HTMLAnchorElement> {
  return document.querySelectorAll<HTMLAnchorElement>("a[download]");
}

function mountDownloadHarness() {
  const blobs: Blob[] = [];
  const allocatedUrls: string[] = [];
  const revokedUrls: string[] = [];
  const activations: RecordedAnchor[] = [];
  const attachedAnchors: RecordedAnchor[] = [];
  const removedAnchors: RecordedAnchor[] = [];
  let callSequence = 0;

  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const originalAppendChild = document.body.appendChild;
  const originalRemoveChild = document.body.removeChild;

  const createObjectURL = vi.fn((blob: Blob): string => {
    callSequence += 1;
    const url = `blob:rehearsal-${callSequence}`;
    blobs.push(blob);
    allocatedUrls.push(url);
    return url;
  });
  const revokeObjectURL = vi.fn((url: string): void => {
    revokedUrls.push(url);
  });

  URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
  URL.revokeObjectURL = revokeObjectURL as typeof URL.revokeObjectURL;

  const anchorClick = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function recordActivation(this: HTMLAnchorElement) {
      activations.push({
        href: this.getAttribute("href"),
        download: this.getAttribute("download"),
      });
    });

  const appendChild = vi
    .spyOn(document.body, "appendChild")
    .mockImplementation(function recordAppend(this: HTMLBodyElement, node: Node) {
      if (node instanceof HTMLAnchorElement && node.hasAttribute("download")) {
        attachedAnchors.push({
          href: node.getAttribute("href"),
          download: node.getAttribute("download"),
        });
      }
      return originalAppendChild.call(document.body, node);
    });

  const removeChild = vi
    .spyOn(document.body, "removeChild")
    .mockImplementation(function recordRemove(this: HTMLBodyElement, node: Node) {
      if (node instanceof HTMLAnchorElement && node.hasAttribute("download")) {
        removedAnchors.push({
          href: node.getAttribute("href"),
          download: node.getAttribute("download"),
        });
      }
      return originalRemoveChild.call(document.body, node);
    });

  return {
    blobs,
    allocatedUrls,
    revokedUrls,
    activations,
    attachedAnchors,
    removedAnchors,
    anchorClick,
    appendChild,
    removeChild,
    revokeObjectURL,
    failNextAllocation(reason = "synthetic allocation refusal") {
      createObjectURL.mockImplementationOnce(() => {
        throw new Error(reason);
      });
    },
    failNextActivation(reason = "synthetic activation refusal") {
      anchorClick.mockImplementationOnce(function recordFailingActivation(
        this: HTMLAnchorElement,
      ) {
        activations.push({
          href: this.getAttribute("href"),
          download: this.getAttribute("download"),
        });
        throw new Error(reason);
      });
    },
    failNextAttachment(reason = "synthetic attachment refusal") {
      appendChild.mockImplementationOnce(() => {
        throw new Error(reason);
      });
    },
    failNextRemoval(reason = "synthetic removal refusal") {
      removeChild.mockImplementationOnce(() => {
        throw new Error(reason);
      });
    },
    failNextRevoke(reason = "synthetic revoke refusal") {
      revokeObjectURL.mockImplementationOnce(() => {
        throw new Error(reason);
      });
    },
    restore() {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      anchorClick.mockRestore();
      appendChild.mockRestore();
      removeChild.mockRestore();
    },
  };
}

describe("RehearsalFillsCsvExport failure recovery", () => {
  let windowErrors: string[];

  function recordWindowError(event: ErrorEvent) {
    windowErrors.push(event.message);
    event.preventDefault();
  }

  beforeEach(() => {
    windowErrors = [];
    window.addEventListener("error", recordWindowError);
  });

  afterEach(() => {
    window.removeEventListener("error", recordWindowError);
    cleanup();
    vi.restoreAllMocks();
    document
      .querySelectorAll("a[download]")
      .forEach((anchor) => anchor.remove());
  });

  it("delivers the exact CSV bytes with the CSV MIME type and timestamped filename, then releases both owned resources", async () => {
    const env = mountDownloadHarness();
    try {
      const fills = [
        fill(),
        fill({ coid: "coid-exit-2", side: "sell", ts_ms: 1760123700000 }),
      ];
      render(<RehearsalFillsCsvExport fills={fills} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(windowErrors).toEqual([]);
      expect(env.blobs).toHaveLength(1);
      expect(env.blobs[0].type).toBe("text/csv;charset=utf-8");
      expect(await env.blobs[0].text()).toBe(toRehearsalFillsCsv(fills));
      expect(env.activations).toHaveLength(1);
      expect(env.activations[0].href).toBe("blob:rehearsal-1");
      expect(env.activations[0].download ?? "").toMatch(
        /^krellbot-rehearsal-fills-\d{14}\.csv$/,
      );
      expect(env.revokedUrls).toEqual(["blob:rehearsal-1"]);
      expect(env.removedAnchors).toHaveLength(1);
      expect(downloadAnchors()).toHaveLength(0);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
    } finally {
      env.restore();
    }
  });

  it("keeps the export disabled and touches no download machinery while no fills are visible", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[]} />);
      const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
      expect(button.disabled).toBe(true);

      fireEvent.click(button);
      expect(env.blobs).toHaveLength(0);
      expect(env.activations).toHaveLength(0);
      expect(env.attachedAnchors).toHaveLength(0);
      expect(env.revokedUrls).toEqual([]);
      expect(downloadAnchors()).toHaveLength(0);
      expect(screen.getByTestId(BUSY_ID).textContent).not.toMatch(/complete/i);
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    } finally {
      env.restore();
    }
  });

  it("an activation refusal removes the already attached anchor, revokes its URL, alerts accessibly and allows the next ordinary click on the same mount", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      env.failNextActivation();

      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(env.activations).toHaveLength(1);
      expect(env.attachedAnchors).toHaveLength(1);
      expect(env.attachedAnchors[0].href).toBe("blob:rehearsal-1");
      expect(env.removedAnchors).toHaveLength(1);
      expect(env.removedAnchors[0].href).toBe("blob:rehearsal-1");
      expect(env.revokedUrls).toEqual(["blob:rehearsal-1"]);
      expect(downloadAnchors()).toHaveLength(0);
      expect(windowErrors).toEqual([]);
      const alert = screen.getByTestId(ERROR_ID);
      expect(alert.getAttribute("role")).toBe("alert");
      expect(alert.textContent).toMatch(/failed/i);
      expect(screen.getByTestId(BUSY_ID).textContent).not.toMatch(/complete/i);

      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(env.activations).toHaveLength(2);
      expect(env.revokedUrls).toEqual(["blob:rehearsal-1", "blob:rehearsal-2"]);
      expect(downloadAnchors()).toHaveLength(0);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    } finally {
      env.restore();
    }
  });

  it("an object URL allocation refusal attempts no delivery and no cleanup, and still allows an ordinary retry", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      env.failNextAllocation();

      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(env.activations).toHaveLength(0);
      expect(env.attachedAnchors).toHaveLength(0);
      expect(env.removedAnchors).toHaveLength(0);
      expect(env.revokedUrls).toEqual([]);
      expect(env.anchorClick).not.toHaveBeenCalled();
      expect(downloadAnchors()).toHaveLength(0);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(ERROR_ID).textContent).toMatch(/failed/i);
      expect(screen.getByTestId(BUSY_ID).textContent).not.toMatch(/complete/i);

      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(env.activations).toHaveLength(1);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    } finally {
      env.restore();
    }
  });

  it("a preparation failure after allocation revokes the allocated URL and removes no never-attached anchor", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      env.failNextAttachment();

      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(env.activations).toHaveLength(0);
      expect(env.attachedAnchors).toHaveLength(0);
      expect(env.removedAnchors).toHaveLength(0);
      expect(env.revokedUrls).toEqual(["blob:rehearsal-1"]);
      expect(downloadAnchors()).toHaveLength(0);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(ERROR_ID).textContent).toMatch(/failed/i);

      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(env.activations).toHaveLength(1);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
    } finally {
      env.restore();
    }
  });

  it("a refused anchor removal still revokes the URL, does not retract the delivered file and keeps ordinary retries working", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      env.failNextRemoval();

      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(windowErrors).toEqual([]);
      expect(env.activations).toHaveLength(1);
      expect(env.revokedUrls).toEqual(["blob:rehearsal-1"]);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();

      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(env.activations).toHaveLength(2);
      expect(env.revokedUrls).toEqual(["blob:rehearsal-1", "blob:rehearsal-2"]);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
    } finally {
      env.restore();
    }
  });

  it("a refused URL revoke still removes the attached anchor and cannot disable the next ordinary export", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      env.failNextRevoke();

      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(windowErrors).toEqual([]);
      expect(env.activations).toHaveLength(1);
      expect(env.removedAnchors).toHaveLength(1);
      expect(env.removedAnchors[0].href).toBe("blob:rehearsal-1");
      expect(downloadAnchors()).toHaveLength(0);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();

      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(env.activations).toHaveLength(2);
      expect(env.revokedUrls).toEqual(["blob:rehearsal-2"]);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
    } finally {
      env.restore();
    }
  });

  it("an activation refusal with both cleanups refused stays contained and the next ordinary export still works", () => {
    const env = mountDownloadHarness();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      env.failNextActivation();
      env.failNextRemoval();
      env.failNextRevoke();

      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(env.activations).toHaveLength(1);
      expect(env.attachedAnchors).toHaveLength(1);
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(ERROR_ID).textContent).toMatch(/failed/i);
      expect(screen.getByTestId(BUSY_ID).textContent).not.toMatch(/complete/i);

      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(env.activations).toHaveLength(2);
      expect(env.removedAnchors).toHaveLength(1);
      expect(env.removedAnchors[0].href).toBe("blob:rehearsal-2");
      expect(env.revokedUrls).toEqual(["blob:rehearsal-2"]);
      // Only the anchor whose removal was synthetically refused remains.
      expect(downloadAnchors()).toHaveLength(1);
      expect(downloadAnchors()[0].getAttribute("href")).toBe("blob:rehearsal-1");
      expect(windowErrors).toEqual([]);
      expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    } finally {
      env.restore();
    }
  });
});
