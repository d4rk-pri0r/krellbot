import { afterEach, expect, it, vi } from "vitest";
import { buildOwnedDraftCopy } from "./ownedDraftCopy";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(() => vi.restoreAllMocks());

it.each([23, 32])("keeps %i-character origins independent even when copying in the same millisecond", (length) => {
  vi.spyOn(Date, "now").mockReturnValue(1700000000000);
  const source: Record<string, unknown> = { ...seedOwnedStrategyPack("Synthetic long identity"), id: "a".repeat(length) };
  const bytes = JSON.stringify(source);
  const origin = { revision_id: "synthetic-revision", state: "draft" };
  const ids = new Set<string>();
  for (let i = 0; i < 50; i++) {
    const copy = buildOwnedDraftCopy(bytes, origin)!;
    const parsed = JSON.parse(copy.bytes);
    expect(parsed.id).toMatch(/^[a-z0-9][a-z0-9-]{0,31}$/);
    expect(parsed.id).not.toBe(source.id);
    const { id: _id, label: _label, ...settings } = parsed;
    const { id: _sourceId, label: _sourceLabel, ...originalSettings } = source;
    expect(settings).toEqual(originalSettings);
    expect(JSON.parse(bytes)).toEqual(source);
    ids.add(parsed.id);
  }
  expect(ids.size).toBe(50);
});
