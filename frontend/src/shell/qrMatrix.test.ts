import { describe, expect, it } from "vitest";
import { encodeQrMatrix } from "./qrMatrix";

describe("encodeQrMatrix", () => {
  it("returns a square matrix with finder patterns for a short token", () => {
    const modules = encodeQrMatrix("reconnect-token-abc");
    expect(modules.length).toBeGreaterThanOrEqual(21);
    expect(modules[0].length).toBe(modules.length);
    // Top-left finder center is dark.
    expect(modules[3][3]).toBe(true);
    // Quiet separator just outside finder stays light.
    expect(modules[7][7]).toBe(false);
  });
});
