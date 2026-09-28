import { useMemo, useState, type JSX } from "react";
import type {
  DraftState,
  DraftSummary,
  Pack,
  StrategyClient,
  ValidationError,
} from "./client";

export type { DraftState, DraftSummary, Pack, StrategyClient, ValidationError };

export type LoadedRevision = {
  revision_id: string;
  state: DraftState;
  bytes: string;
};

export type EditorProps = {
  client: StrategyClient;
  initial?: LoadedRevision;
};

function parsePack(text: string): Pack | null {
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as Pack;
    }
    return null;
  } catch {
    return null;
  }
}

function readLabel(pack: Pack | null): string {
  if (!pack) {
    return "";
  }
  const value = pack.label;
  return typeof value === "string" ? value : "";
}

export function Editor({ client, initial }: EditorProps): JSX.Element {
  const initialRawJson = initial?.bytes ?? "";
  const [rawJson, setRawJson] = useState<string>(initialRawJson);
  const [lastSummary, setLastSummary] = useState<DraftSummary | null>(() => {
    if (!initial) {
      return null;
    }
    const pack = parsePack(initial.bytes);
    return {
      revision_id: initial.revision_id,
      state: initial.state,
      pack: pack ?? {},
      errors: [],
    };
  });
  const [venue, setVenue] = useState("kraken");
  const [paperBalance, setPaperBalance] = useState("1000");
  const [importError, setImportError] = useState<string | null>(null);

  const currentPack = useMemo(() => parsePack(rawJson), [rawJson]);
  const labelValue = readLabel(currentPack);

  const handleLabelChange = (nextLabel: string): void => {
    if (currentPack) {
      const merged: Pack = { ...currentPack, label: nextLabel };
      setRawJson(JSON.stringify(merged, null, 2));
    } else {
      const seed: Pack = { label: nextLabel };
      setRawJson(JSON.stringify(seed, null, 2));
    }
  };

  const handleRawJsonChange = (text: string): void => {
    setRawJson(text);
    if (importError !== null) {
      setImportError(null);
    }
  };

  const requireValidPack = (): Pack | null => {
    const pack = parsePack(rawJson);
    if (!pack) {
      setImportError("Invalid JSON");
      return null;
    }
    if (importError !== null) {
      setImportError(null);
    }
    return pack;
  };

  const handleImport = (): void => {
    requireValidPack();
  };

  const handleSave = async (): Promise<void> => {
    const pack = requireValidPack();
    if (!pack) {
      return;
    }
    const parentId = lastSummary?.revision_id ?? initial?.revision_id;
    const summary = parentId
      ? await client.edit(parentId, pack)
      : await client.create(pack);
    setLastSummary(summary);
  };

  const handleValidate = async (): Promise<void> => {
    if (!lastSummary) {
      return;
    }
    const summary = await client.validate(lastSummary.revision_id);
    setLastSummary(summary);
  };

  const handleArm = async (): Promise<void> => {
    if (!lastSummary || lastSummary.state !== "validated") {
      return;
    }
    await client.arm(lastSummary.revision_id, venue, paperBalance);
  };

  const armDisabled = !lastSummary || lastSummary.state !== "validated";

  return (
    <section
      className="kbot-strategy-editor"
      role="region"
      aria-label="Strategy editor"
    >
      <header className="kbot-strategy-editor__head">
        <h2 className="kbot-strategy-editor__title">Strategy draft</h2>
      </header>
      <div className="kbot-strategy-editor__body">
        <label
          className="kbot-strategy-editor__field"
          htmlFor="kbot-strategy-editor-label"
        >
          <span className="kbot-strategy-editor__field-label">Label</span>
          <input
            id="kbot-strategy-editor-label"
            className="kbot-strategy-editor__input"
            type="text"
            value={labelValue}
            onChange={(event) => handleLabelChange(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-strategy-editor__field" htmlFor="kbot-strategy-editor-venue">
          <span className="kbot-strategy-editor__field-label">Venue</span>
          <input
            id="kbot-strategy-editor-venue"
            className="kbot-strategy-editor__input"
            type="text"
            value={venue}
            onChange={(event) => setVenue(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-strategy-editor__field" htmlFor="kbot-strategy-editor-balance">
          <span className="kbot-strategy-editor__field-label">Paper balance</span>
          <input
            id="kbot-strategy-editor-balance"
            className="kbot-strategy-editor__input"
            type="text"
            value={paperBalance}
            onChange={(event) => setPaperBalance(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label
          className="kbot-strategy-editor__field"
          htmlFor="kbot-strategy-editor-json"
        >
          <span className="kbot-strategy-editor__field-label">Raw JSON</span>
          <textarea
            id="kbot-strategy-editor-json"
            className="kbot-strategy-editor__textarea"
            value={rawJson}
            onChange={(event) => handleRawJsonChange(event.target.value)}
            spellCheck={false}
            rows={12}
          />
        </label>
        {importError !== null ? (
          <p
            className="kbot-strategy-editor__error"
            role="alert"
            data-testid="editor-import-error"
          >
            {importError}
          </p>
        ) : null}
        {lastSummary?.errors.map((err, index) => (
          <ErrorBlock key={`${err.field ?? "root"}-${index}`} error={err} />
        ))}
        <div className="kbot-strategy-editor__actions">
          <button
            type="button"
            className="kbot-strategy-editor__action"
            onClick={() => {
              void handleSave();
            }}
          >
            Save
          </button>
          <button
            type="button"
            className="kbot-strategy-editor__action"
            onClick={handleImport}
          >
            Import
          </button>
          <button
            type="button"
            className="kbot-strategy-editor__action"
            onClick={() => {
              void handleValidate();
            }}
            disabled={!lastSummary}
          >
            Validate
          </button>
          <button
            type="button"
            className="kbot-strategy-editor__action"
            onClick={() => {
              void handleArm();
            }}
            disabled={armDisabled}
          >
            Arm
          </button>
        </div>
        {lastSummary ? (
          <p
            className="kbot-strategy-editor__revision"
            data-testid="editor-revision-id"
          >
            revision: {lastSummary.revision_id} (state: {lastSummary.state})
          </p>
        ) : null}
      </div>
    </section>
  );
}

function ErrorBlock({ error }: { error: ValidationError }): JSX.Element {
  const field = error.field ?? "<root>";
  const testId = `editor-error-${field.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  return (
    <p
      className="kbot-strategy-editor__error"
      role="alert"
      data-testid={testId}
    >
      <span className="kbot-strategy-editor__error-field">{field}</span>
      <span className="kbot-strategy-editor__error-sep">: </span>
      <span className="kbot-strategy-editor__error-message">
        {error.message}
      </span>
    </p>
  );
}