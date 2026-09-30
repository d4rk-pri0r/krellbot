export type RevisionPack = Record<string, unknown>;

export const EXECUTION_FIELDS: readonly string[] = [
  "schema_version",
  "id",
  "timeframe",
  "indicators",
  "entry",
  "exit",
  "risk",
  "markets",
];

function hasOwn(obj: RevisionPack, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) {
    return true;
  }
  if (typeof a !== typeof b) {
    return false;
  }
  if (a === null || b === null) {
    return a === b;
  }
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) {
      return false;
    }
    for (let i = 0; i < a.length; i += 1) {
      if (!deepEqual(a[i], b[i])) {
        return false;
      }
    }
    return true;
  }
  if (Array.isArray(b)) {
    return false;
  }
  if (typeof a === "object" && typeof b === "object") {
    const aKeys = Object.keys(a as object);
    const bKeys = Object.keys(b as object);
    if (aKeys.length !== bKeys.length) {
      return false;
    }
    for (const key of aKeys) {
      if (!Object.prototype.hasOwnProperty.call(b, key)) {
        return false;
      }
      if (
        !deepEqual(
          (a as Record<string, unknown>)[key],
          (b as Record<string, unknown>)[key],
        )
      ) {
        return false;
      }
    }
    return true;
  }
  return false;
}

export function semanticChanges(
  before: RevisionPack,
  after: RevisionPack,
): string[] {
  const changed: string[] = [];
  for (const field of EXECUTION_FIELDS) {
    const beforeHas = hasOwn(before, field);
    const afterHas = hasOwn(after, field);
    if (beforeHas !== afterHas) {
      changed.push(field);
      continue;
    }
    if (!beforeHas) {
      continue;
    }
    if (!deepEqual(before[field], after[field])) {
      changed.push(field);
    }
  }
  return changed.sort();
}