import { useMemo, useState, type ChangeEvent, type JSX } from "react";
import { EditorCsvExport } from "./EditorCsvExport";
import { summarizeDraftState } from "./draftStateLabel";
import type {
  DraftState,
  DraftSummary,
  Pack,
  StrategyClient,
  ValidationError,
} from "./client";
import { OwnedStrategyForm } from "./OwnedStrategyForm";
import {
  readOwnedStrategy,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
  type OwnedStrategyFormState,
} from "./ownedStrategy";

export type { DraftState, DraftSummary, Pack, StrategyClient, ValidationError };

export type LoadedRevision = {
  revision_id: string;
  state: DraftState;
  bytes: string;
};

export type EditorProps = {
  client: StrategyClient;
  initial?: LoadedRevision;
  onRevision?: (summary: DraftSummary, bytes: string) => void;
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

export function Editor({ client, initial, onRevision }: EditorProps): JSX.Element {
  const initialRawJson = initial?.bytes ?? "";
  const [rawJson, setRawJson] = useState<string>(initialRawJson);
  const [ownedForm, setOwnedForm] = useState<OwnedStrategyFormState | null>(() =>
    readOwnedStrategy(parsePack(initialRawJson)),
  );
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
  const [saveOutcome, setSaveOutcome] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validateError, setValidateError] = useState<string | null>(null);
  const [armError, setArmError] = useState<string | null>(null);
  const [arming, setArming] = useState(false);

  const currentPack = useMemo(() => parsePack(rawJson), [rawJson]);
  const labelValue = readLabel(currentPack);
  // The form is offered only when the current pack is exactly the supported
  // subset. Anything else (imported, nested, extra indicators) keeps its
  // bytes untouched; the user is told instead of the pack being rewritten.
  const formSupported = useMemo(
    () => (rawJson.trim() === "" ? true : readOwnedStrategy(currentPack) !== null),
    [rawJson, currentPack],
  );

  const handleStartOwnedStrategy = (): void => {
    const form = seedOwnedStrategyForm();
    const pack = seedOwnedStrategyPack(form.name);
    setOwnedForm({ ...form, id: pack.id as string });
    setRawJson(JSON.stringify(pack, null, 2));
    setImportError(null);
  };

  const handleOwnedApply = (pack: Pack | null): void => {
    if (!pack) {
      // Invalid form state: keep the last good payload in the JSON view so
      // Save still sends a pack the schema accepts.
      return;
    }
    setRawJson(JSON.stringify(pack, null, 2));
  };

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
    setSaveOutcome(null);
    setSaveError(null);
    const parentId = lastSummary?.revision_id ?? initial?.revision_id;
    try {
      const summary = parentId
        ? await client.edit(parentId, pack)
        : await client.create(pack);
      if (summary.outcome === "unchanged") {
        setSaveOutcome(`No change: revision ${summary.revision_id} kept`);
        return;
      }
      if (summary.outcome === "existing") {
        setSaveOutcome(`Selected existing revision ${summary.revision_id}`);
      } else if (summary.outcome === "created") {
        setSaveOutcome(`Saved new revision ${summary.revision_id}`);
      } else {
        // W3: missing server outcome must not render "Saved new".
        setSaveOutcome(`Saved revision ${summary.revision_id}`);
      }
      setLastSummary(summary);
      onRevision?.(summary, rawJson);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleValidate = async (): Promise<void> => {
    if (!lastSummary) {
      return;
    }
    setValidateError(null);
    try {
      const summary = await client.validate(lastSummary.revision_id);
      setLastSummary(summary);
      onRevision?.(summary, rawJson);
    } catch (err) {
      // Keep the last known revision/state; never imply validation succeeded.
      setValidateError(
        `Validation failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      const pack = parsePack(text);
      if (!pack) {
        setImportError("Invalid JSON");
        return;
      }
      setImportError(null);
      setRawJson(text);
    };
    reader.readAsText(file);
  };

  const handleExport = (): void => {
    const blob = new Blob([rawJson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "pack.json";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  };

  const handleArm = async (): Promise<void> => {
    if (arming || !lastSummary || lastSummary.state !== "validated") {
      return;
    }
    setArmError(null);
    setArming(true);
    try {
      await client.arm(lastSummary.revision_id, venue, paperBalance);
    } catch (err) {
      // Keep the validated revision; never imply a deployment from stale local state.
      setArmError(
        `Arm failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setArming(false);
    }
  };

  const armDisabled = !lastSummary || lastSummary.state !== "validated" || arming;

  return (
    <section
      className="kbot-strategy-editor"
      role="region"
      aria-label="Strategy editor"
    >
      <header className="kbot-strategy-editor__head">
        <h2 className="kbot-strategy-editor__title">Strategy draft</h2>
        <div className="kbot-strategy-editor__head-actions">
          <button
            type="button"
            className="kbot-strategy-editor__action"
            onClick={handleStartOwnedStrategy}
          >
            Create new owned strategy
          </button>
        </div>
      </header>
      <div className="kbot-strategy-editor__body">
        {ownedForm && formSupported ? (
          <OwnedStrategyForm
            state={ownedForm}
            basePack={currentPack}
            onStateChange={setOwnedForm}
            onApply={(pack) => handleOwnedApply(pack)}
          />
        ) : null}
        {!formSupported ? (
          <p
            className="kbot-strategy-editor__unsupported"
            data-testid="owned-strategy-form-unsupported"
          >
            This pack is not supported by the form (it uses features outside
            the supported moving-average subset). Edit it as JSON below; the
            form will not rewrite it. Imported pack ownership is not verified.
          </p>
        ) : null}
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
        <label
          className="kbot-strategy-editor__field"
          htmlFor="kbot-strategy-editor-file"
        >
          <span className="kbot-strategy-editor__field-label">
            Import pack file
          </span>
          <input
            id="kbot-strategy-editor-file"
            className="kbot-strategy-editor__input"
            type="file"
            accept="application/json,.json"
            onChange={handleFileChange}
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
        {saveOutcome !== null ? (
          <p
            className="kbot-strategy-editor__outcome"
            data-testid="editor-save-outcome"
          >
            {saveOutcome}
          </p>
        ) : null}
        {saveError !== null ? (
          <p
            className="kbot-strategy-editor__error"
            role="alert"
            data-testid="editor-save-error"
          >
            {saveError}
          </p>
        ) : null}
        {validateError !== null ? (
          <p
            className="kbot-strategy-editor__error"
            role="alert"
            data-testid="editor-validate-error"
          >
            {validateError}
          </p>
        ) : null}
        {armError !== null ? (
          <p
            className="kbot-strategy-editor__error"
            role="alert"
            data-testid="editor-arm-error"
          >
            {armError}
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
            onClick={handleExport}
          >
            Export pack
          </button>
          <EditorCsvExport
            lastSummary={lastSummary}
            currentPack={currentPack}
          />
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
            revision: {lastSummary.revision_id} (state: {summarizeDraftState(lastSummary.state).label})
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