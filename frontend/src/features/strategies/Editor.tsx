import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent, type JSX } from "react";
import "./Editor.signal.css";
import "./Editor.saveKeyboard.signal.css";
import { EditorCsvExport } from "./EditorCsvExport";
import { EditorInlineStopControl, type PaperClient } from "./EditorInlineStopControl";
import { summarizeDraftState } from "./draftStateLabel";
import type {
  DraftState,
  DraftSummary,
  Pack,
  StrategyClient,
  ValidationError,
} from "./client";
import { OwnedStrategyForm } from "./OwnedStrategyForm";
import { StarterPicker } from "./StarterPicker";
import type { StarterExample } from "./StarterPicker.client";
import {
  readOwnedStrategy,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
  type OwnedStrategyFormState,
} from "./ownedStrategy";
import {
  copyOriginLabel,
  type OwnedCopyOrigin,
} from "./ownedDraftCopy";
import { summarizeSaveOutcome } from "./saveOutcomeSummary";

export type { DraftState, DraftSummary, Pack, StrategyClient, ValidationError };

export type LoadedRevision = {
  revision_id: string;
  state: DraftState;
  bytes: string;
};

/** A new, unsaved draft seeded from a copied owned revision's real bytes. */
export type CopiedDraft = {
  bytes: string;
  origin: OwnedCopyOrigin;
  originLabel?: string | null;
};

export type EditorProps = {
  client: StrategyClient;
  /** Paper command surface for the inline stop control; optional so hosts without one render unchanged. */
  paperClient?: PaperClient;
  initial?: LoadedRevision;
  /** Mount-only: seed a fresh draft from copied owned bytes (create path). */
  copiedDraft?: CopiedDraft;
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

export function Editor({ client, paperClient, initial, copiedDraft, onRevision }: EditorProps): JSX.Element {
  const initialRawJson = initial?.bytes ?? copiedDraft?.bytes ?? "";
  const [rawJson, setRawJson] = useState<string>(initialRawJson);
  const [ownedForm, setOwnedForm] = useState<OwnedStrategyFormState | null>(() =>
    readOwnedStrategy(parsePack(initialRawJson)),
  );
  const [lastSummary, setLastSummary] = useState<DraftSummary | null>(() => {
    if (!initial) {
      // A copied draft is a NEW draft: no revision identity, no state,
      // no forged validation. Saving it goes through client.create.
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
  const [fileImportInFlight, setFileImportInFlight] = useState(false);
  const fileImportInFlightRef = useRef(false);
  const [fileImportFileName, setFileImportFileName] = useState("");
  const [fileImportStatusMessage, setFileImportStatusMessage] = useState<string | null>(null);
  // True after a starter example seeded the draft: the next Save must
  // create a fresh revision even when an `initial` revision was
  // previously loaded (a starter pick is never a reopen/edit).
  const [seededFresh, setSeededFresh] = useState(false);
  const [saveOutcome, setSaveOutcome] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const saveInFlight = useRef(false);
  const [validateError, setValidateError] = useState<string | null>(null);
  const [armError, setArmError] = useState<string | null>(null);
  const [arming, setArming] = useState(false);
  // Bumped only after a confirmed arm success: drives the inline stop
  // control's refreshSignal so it reconciles status without a manual refresh.
  const [armCounter, setArmCounter] = useState(0);

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

  const handleStarterPick = (example: StarterExample): void => {
    // A starter is a seed for a NEW owned copy, never a reopen: the
    // previous revision identity is dropped so the next Save creates a
    // fresh revision through client.create (never edit on the loaded
    // parent), and transient errors from the prior draft do not leak
    // into the seeded one.
    setRawJson(JSON.stringify(example.pack, null, 2));
    setLastSummary(null);
    setSeededFresh(true);
    setImportError(null);
    setSaveOutcome(null);
    setSaveError(null);
    setValidateError(null);
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
    if (saveInFlight.current) {
      return;
    }
    const pack = requireValidPack();
    if (!pack) {
      return;
    }
    saveInFlight.current = true;
    setSaving(true);
    setSaveOutcome(null);
    setSaveError(null);
    const parentId = seededFresh
      ? null
      : lastSummary?.revision_id ?? initial?.revision_id;
    try {
      const summary = parentId
        ? await client.edit(parentId, pack)
        : await client.create(pack);
      setSeededFresh(false);
      if (summary.outcome === "unchanged") {
        setSaveOutcome(summarizeSaveOutcome("unchanged", summary.revision_id).label);
        return;
      }
      if (summary.outcome === "existing") {
        setSaveOutcome(summarizeSaveOutcome("existing", summary.revision_id).label);
      } else if (summary.outcome === "created") {
        setSaveOutcome(summarizeSaveOutcome("created", summary.revision_id).label);
      } else {
        // W3: missing server outcome must not render "Saved new".
        setSaveOutcome(summarizeSaveOutcome("other", summary.revision_id).label);
      }
      setLastSummary(summary);
      onRevision?.(summary, rawJson);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      saveInFlight.current = false;
      setSaving(false);
    }
  };

  const handleSaveKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    if (
      event.defaultPrevented ||
      !(event.ctrlKey || event.metaKey) ||
      (event.key !== "s" && event.key !== "S")
    ) {
      return;
    }
    const target = event.target;
    if (
      target instanceof Element &&
      (target.id === "kbot-strategy-editor-json" ||
        target.closest(".kbot-owned-strategy-form input"))
    ) {
      return;
    }
    event.preventDefault();
    if (!event.repeat && !saveInFlight.current) {
      void handleSave();
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
    if (fileImportInFlightRef.current) {
      return;
    }
    fileImportInFlightRef.current = true;
    setFileImportInFlight(true);
    const fileImportFileName = file.name;
    setFileImportFileName(fileImportFileName);
    setFileImportStatusMessage(null);
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = typeof reader.result === "string" ? reader.result : "";
        const pack = parsePack(text);
        if (!pack) {
          setImportError("Invalid JSON");
          setFileImportStatusMessage(`Invalid JSON in ${fileImportFileName}`);
          return;
        }
        // An imported file is a seed for a NEW draft, exactly like a starter
        // pick: the previously-loaded revision identity is dropped so the
        // next Save creates a fresh revision through client.create instead
        // of silently editing the reopened one, and stale outcome/error
        // surfaces from that revision do not leak into the imported draft.
        setOwnedForm(readOwnedStrategy(pack));
        setLastSummary(null);
        setSeededFresh(true);
        setImportError(null);
        setSaveOutcome(null);
        setSaveError(null);
        setValidateError(null);
        setArmError(null);
        setRawJson(text);
        setFileImportStatusMessage(`Loaded pack from ${fileImportFileName}`);
      } finally {
        fileImportInFlightRef.current = false;
        setFileImportInFlight(false);
      }
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
      // Arm confirmed by the backend: nudge the inline stop control to
      // re-read paper status so its Disarm/Pause/Resume reflect the new
      // armed state without a manual "Refresh status" click.
      setArmCounter((c) => c + 1);
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

  // Progressive disclosure: the technical JSON section stays collapsed while
  // the readable form covers the pack. It opens itself exactly when the user
  // needs the raw bytes — an imported unsupported pack (the form will not
  // rewrite it) or a JSON error. Opening is one-way per trigger: a manual
  // collapse afterwards is respected until a new trigger arrives.
  const technicalRef = useRef<HTMLDetailsElement | null>(null);
  useEffect(() => {
    if ((!formSupported || importError !== null) && technicalRef.current) {
      technicalRef.current.open = true;
    }
  }, [formSupported, importError]);

  return (
    <section
      className="kbot-strategy-editor"
      role="region"
      aria-label="Strategy editor"
      onKeyDown={handleSaveKeyDown}
    >
      <div
        className="kbot-editor-save-status"
        data-testid="editor-save-status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {saving ? "Saving…" : importError !== null ? (
          <>Invalid <span>JSON</span>; save blocked</>
        ) : saveError !== null ? `Save failed: ${saveError}` : saveOutcome !== null ? "Saved" : ""}
      </div>
      <header className="kbot-strategy-editor__head">
        <div className="kbot-strategy-editor__head-copy">
          <h2 className="kbot-strategy-editor__title">Strategy draft</h2>
          <p className="kbot-strategy-editor__intro">
            Read the rules first, then save and validate the revision. Nothing
            saves, validates or arms by itself.
          </p>
        </div>
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
      <div className="kbot-strategy-editor__layout">
        <div className="kbot-strategy-editor__primary">
          <section
            className="kbot-strategy-editor__group"
            aria-labelledby="kbot-strategy-editor-identity-title"
          >
            <header className="kbot-strategy-editor__group-head">
              <h3
                className="kbot-strategy-editor__group-title"
                id="kbot-strategy-editor-identity-title"
              >
                <span className="kbot-strategy-editor__step" aria-hidden="true">
                  1
                </span>
                Strategy identity and readable rules
              </h3>
              <span className="kbot-strategy-editor__group-note">
                Readable fields write the real pack bytes
              </span>
            </header>
            <div className="kbot-strategy-editor__group-body">
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
              {copiedDraft ? (
                <p
                  className="kbot-strategy-editor__copy-origin"
                  data-testid="editor-copy-origin"
                >
                  {lastSummary
                    ? `Copied from revision ${copiedDraft.origin.revision_id}`
                    : `${copyOriginLabel(copiedDraft.origin)} — unsaved draft; Save creates a new revision`}
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
              <StarterPicker onPick={handleStarterPick} />
            </div>
          </section>

          <details
            className="kbot-strategy-editor__group kbot-strategy-editor__technical"
            data-testid="editor-technical-section"
            role="region"
            aria-labelledby="kbot-strategy-editor-technical-title"
            ref={technicalRef}
          >
            <summary className="kbot-strategy-editor__technical-summary">
              <span
                className="kbot-strategy-editor__group-title"
                id="kbot-strategy-editor-technical-title"
              >
                <span className="kbot-strategy-editor__chevron" aria-hidden="true" />
                <span className="kbot-strategy-editor__step" aria-hidden="true">
                  2
                </span>
                Technical JSON, import and export
              </span>
              <span className="kbot-strategy-editor__group-note">
                Raw bytes stay byte-preserved
              </span>
            </summary>
            <div className="kbot-strategy-editor__technical-body">
              <p className="kbot-strategy-editor__hint">
                The raw pack is the source of truth. Imported packs that use
                unsupported features are never converted or stripped — edit them
                here as JSON only.
              </p>
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
                  aria-invalid={importError !== null ? "true" : undefined}
                  aria-describedby={importError !== null ? "editor-import-error" : undefined}
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
                  aria-label="Import pack file"
                  aria-busy={fileImportInFlight ? "true" : undefined}
                />
              </label>
              {fileImportInFlight || fileImportStatusMessage !== null ? (
                <p
                  data-testid="editor-file-import-busy-status"
                  id="editor-file-import-busy-status"
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  className="kbot-strategy-editor__hint"
                >
                  {fileImportInFlight ? `Reading pack file ${fileImportFileName}` : fileImportStatusMessage}
                </p>
              ) : null}
              <div className="kbot-strategy-editor__actions">
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
              </div>
            </div>
          </details>
          {importError !== null ? (
            <p
              id="editor-import-error"
              className="kbot-strategy-editor__error"
              role="alert"
              data-testid="editor-import-error"
            >
              {importError}
            </p>
          ) : null}
        </div>

        <aside className="kbot-strategy-editor__rail">
          <section
            className="kbot-strategy-editor__group"
            aria-labelledby="kbot-strategy-editor-save-title"
          >
            <header className="kbot-strategy-editor__group-head">
              <h3
                className="kbot-strategy-editor__group-title"
                id="kbot-strategy-editor-save-title"
              >
                <span className="kbot-strategy-editor__step" aria-hidden="true">
                  3
                </span>
                Save and validation
              </h3>
              <span className="kbot-strategy-editor__group-note">
                Explicit actions only
              </span>
            </header>
            <div className="kbot-strategy-editor__group-body">
              {lastSummary ? (
                <p
                  className="kbot-strategy-editor__revision"
                  data-testid="editor-revision-id"
                >
                  revision: {lastSummary.revision_id} (state:{" "}
                  {summarizeDraftState(lastSummary.state).label})
                </p>
              ) : (
                <p className="kbot-strategy-editor__revision kbot-strategy-editor__revision--empty">
                  No saved revision yet — Save creates one.
                </p>
              )}
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
              {lastSummary?.errors.map((err, index) => (
                <ErrorBlock key={`${err.field ?? "root"}-${index}`} error={err} />
              ))}
              <div className="kbot-strategy-editor__actions">
                <button
                  type="button"
                  className="kbot-strategy-editor__action kbot-strategy-editor__action--primary"
                  aria-keyshortcuts="Control+S Meta+S"
                  onClick={() => {
                    void handleSave();
                  }}
                >
                  Save
                </button>
                <button
                  type="button"
                  className="kbot-strategy-editor__action kbot-strategy-editor__action--secondary"
                  onClick={() => {
                    void handleValidate();
                  }}
                  disabled={!lastSummary}
                >
                  Validate
                </button>
              </div>
              <p className="kbot-strategy-editor__hint">
                Save creates a new revision or edits the loaded one; Validate
                asks the backend to check the saved revision. Neither runs on
                navigation.
              </p>
            </div>
          </section>

          <section
            className="kbot-strategy-editor__group"
            aria-labelledby="kbot-strategy-editor-run-title"
          >
            <header className="kbot-strategy-editor__group-head">
              <h3
                className="kbot-strategy-editor__group-title"
                id="kbot-strategy-editor-run-title"
              >
                <span className="kbot-strategy-editor__step" aria-hidden="true">
                  4
                </span>
                Paper run and risk reduction
              </h3>
              <span className="kbot-strategy-editor__group-note">
                Arm needs a validated revision
              </span>
            </header>
            <div className="kbot-strategy-editor__group-body">
              <div className="kbot-strategy-editor__run-fields">
                <label
                  className="kbot-strategy-editor__field"
                  htmlFor="kbot-strategy-editor-venue"
                >
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
                <label
                  className="kbot-strategy-editor__field"
                  htmlFor="kbot-strategy-editor-balance"
                >
                  <span className="kbot-strategy-editor__field-label">
                    Paper balance
                  </span>
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
              </div>
              <p className="kbot-strategy-editor__hint">
                The paper balance is a starting input for this draft, not a read
                of any account. Arm is a deliberate action and never runs by
                itself.
              </p>
              <div className="kbot-strategy-editor__actions">
                <button
                  type="button"
                  className="kbot-strategy-editor__action kbot-strategy-editor__action--arm"
                  onClick={() => {
                    void handleArm();
                  }}
                  disabled={armDisabled}
                >
                  Arm
                </button>
              </div>
              {armError !== null ? (
                <p
                  className="kbot-strategy-editor__error"
                  role="alert"
                  data-testid="editor-arm-error"
                >
                  {armError}
                </p>
              ) : null}
              {paperClient ? (
                <EditorInlineStopControl
                  paperClient={paperClient}
                  refreshSignal={armCounter}
                />
              ) : null}
            </div>
          </section>
        </aside>
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