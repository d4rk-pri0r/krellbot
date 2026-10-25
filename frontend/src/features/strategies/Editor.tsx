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

/** A visible import refusal. `fromFile` marks refusals produced by a
 * chosen pack file: those are sticky against the Import button and are
 * cleared only by a new file choice or an edit to the raw JSON box. */
type ImportRefusal = {
  message: string;
  fromFile: boolean;
};

/** The draft, client and revision identity an asynchronous Save or
 * Validate started against. Its completion may apply a summary, outcome
 * or error only while that exact scope is still the editor's current
 * one; otherwise the result belongs to a replaced draft and is dropped,
 * never reattached. */
type DraftOpScope = {
  client: StrategyClient;
  lifetime: number;
  revisionId: string | null;
  validateSeq: number | null;
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
  const [importError, setImportError] = useState<ImportRefusal | null>(null);
  // True after a starter example seeded the draft: the next Save must
  // create a fresh revision even when an `initial` revision was
  // previously loaded (a starter pick is never a reopen/edit).
  const [seededFresh, setSeededFresh] = useState(false);
  const [saveOutcome, setSaveOutcome] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const saveInFlight = useRef(false);
  // Draft lifetime: bumped by every fresh-draft seed (a chosen pack file,
  // a starter pick), so an asynchronous Save/Validate completion for the
  // replaced draft cannot reattach its revision, outcome, errors or
  // fresh-create identity, and cannot invoke a stale onRevision. Text
  // edits deliberately do NOT bump it: saving the currently edited draft
  // keeps applying its result (existing policy).
  const draftLifetime = useRef(0);
  const seedFreshDraft = (): void => {
    draftLifetime.current += 1;
  };
  // Latest-value mirrors readable from promise continuations after awaits.
  const clientRef = useRef(client);
  clientRef.current = client;
  const lastSummaryRef = useRef(lastSummary);
  const setTrackedLastSummary = (next: DraftSummary | null): void => {
    lastSummaryRef.current = next;
    setLastSummary(next);
  };
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  // Validates have no single-flight lock (existing behavior); each start
  // supersedes any still-pending older attempt's right to apply.
  const validateSeq = useRef(0);
  // Race guard for asynchronous pack-file reads: every draft replacement
  // (a new file read, a textarea edit, a starter pick, the owned form)
  // bumps this token, so a stale read's onload can never overwrite the
  // newer draft content.
  const fileReadToken = useRef(0);
  const invalidatePendingFileRead = (): void => {
    fileReadToken.current += 1;
  };
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
    invalidatePendingFileRead();
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
    invalidatePendingFileRead();
    setRawJson(JSON.stringify(pack, null, 2));
  };

  const handleLabelChange = (nextLabel: string): void => {
    invalidatePendingFileRead();
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
    invalidatePendingFileRead();
    seedFreshDraft();
    setRawJson(JSON.stringify(example.pack, null, 2));
    setTrackedLastSummary(null);
    setSeededFresh(true);
    setImportError(null);
    setSaveOutcome(null);
    setSaveError(null);
    setValidateError(null);
  };

  const handleRawJsonChange = (text: string): void => {
    invalidatePendingFileRead();
    setRawJson(text);
    if (importError !== null) {
      setImportError(null);
    }
  };

  const requireValidPack = (): Pack | null => {
    const pack = parsePack(rawJson);
    if (!pack) {
      setImportError({ message: "Invalid JSON", fromFile: false });
      return null;
    }
    if (importError !== null) {
      setImportError(null);
    }
    return pack;
  };

  const handleImport = (): void => {
    // Import validates only the raw JSON box; it never reads a file. A
    // refusal that came from a chosen file is sticky against Import:
    // only a new file choice or a textarea edit clears it, so pressing
    // Import preserves the refusal and imports/saves nothing.
    if (importError?.fromFile) {
      return;
    }
    requireValidPack();
  };

  const captureDraftOpScope = (): DraftOpScope => ({
    client,
    lifetime: draftLifetime.current,
    revisionId: lastSummaryRef.current?.revision_id ?? null,
    validateSeq: null,
  });

  const draftOpScopeIsCurrent = (scope: DraftOpScope): boolean =>
    mountedRef.current &&
    clientRef.current === scope.client &&
    draftLifetime.current === scope.lifetime &&
    (lastSummaryRef.current?.revision_id ?? null) === scope.revisionId &&
    (scope.validateSeq === null || validateSeq.current === scope.validateSeq);

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
    const scope = captureDraftOpScope();
    const parentId = seededFresh
      ? null
      : lastSummary?.revision_id ?? initial?.revision_id;
    try {
      const summary = parentId
        ? await client.edit(parentId, pack)
        : await client.create(pack);
      if (!draftOpScopeIsCurrent(scope)) {
        // A newer fresh draft, revision, client or component lifetime
        // superseded this Save: its result stays out of the current
        // editor instead of republishing the replaced draft's revision.
        return;
      }
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
      setTrackedLastSummary(summary);
      onRevision?.(summary, rawJson);
    } catch (err) {
      if (!draftOpScopeIsCurrent(scope)) {
        return;
      }
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      // Always releases the single-flight lock and the Saving… surface:
      // the replacement must not block the next explicit Save.
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
    const scope: DraftOpScope = {
      ...captureDraftOpScope(),
      validateSeq: ++validateSeq.current,
    };
    setValidateError(null);
    try {
      const summary = await client.validate(lastSummary.revision_id);
      if (!draftOpScopeIsCurrent(scope)) {
        // A newer draft, revision, client, component lifetime or newer
        // validate attempt superseded this one: its result is not
        // reattached to the current editor.
        return;
      }
      setTrackedLastSummary(summary);
      onRevision?.(summary, rawJson);
    } catch (err) {
      if (!draftOpScopeIsCurrent(scope)) {
        return;
      }
      // Keep the last known revision/state; never imply validation succeeded.
      setValidateError(
        `Validation failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Reads and seeds the draft from a chosen pack file. The Import button
  // never calls this: only an explicit file selection does. A file that
  // does not parse refuses with "Invalid JSON" on the import-error
  // surface and leaves the current draft untouched; that refusal is
  // sticky against Import until another file is chosen or the raw JSON
  // is edited. After every completed read (success, refusal or read
  // error) the picker's value is cleared so choosing the same file
  // again is a real second read, and a stale read whose draft was
  // replaced meanwhile (new file, textarea edit, starter pick) is
  // discarded by the token guard instead of overwriting it.
  const importPackFile = (file: File): void => {
    const token = ++fileReadToken.current;
    const clearPicker = (): void => {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    };
    const reader = new FileReader();
    reader.onload = () => {
      clearPicker();
      if (token !== fileReadToken.current) {
        return;
      }
      const text = typeof reader.result === "string" ? reader.result : "";
      const pack = parsePack(text);
      if (!pack) {
        setImportError({ message: "Invalid JSON", fromFile: true });
        return;
      }
      // An imported file is a seed for a NEW draft, exactly like a starter
      // pick: the previously-loaded revision identity is dropped so the
      // next Save creates a fresh revision through client.create instead
      // of silently editing the reopened one, and stale outcome/error
      // surfaces from that revision do not leak into the imported draft.
      // Seeding also bumps the draft lifetime, so Save/Validate
      // completions still in flight for the replaced draft are dropped
      // rather than reattaching its revision here.
      seedFreshDraft();
      setOwnedForm(readOwnedStrategy(pack));
      setTrackedLastSummary(null);
      setSeededFresh(true);
      setImportError(null);
      setSaveOutcome(null);
      setSaveError(null);
      setValidateError(null);
      setArmError(null);
      setRawJson(text);
    };
    reader.onerror = () => {
      clearPicker();
      if (token !== fileReadToken.current) {
        return;
      }
      setImportError({ message: "Could not read pack file", fromFile: true });
    };
    reader.readAsText(file);
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    importPackFile(file);
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
                  ref={fileInputRef}
                  className="kbot-strategy-editor__input"
                  type="file"
                  accept="application/json,.json"
                  onChange={handleFileChange}
                />
              </label>
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
              {importError.message}
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