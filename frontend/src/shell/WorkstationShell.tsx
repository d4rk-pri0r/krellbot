import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
} from "react";
import { createPortal } from "react-dom";
import type { Connection } from "@xyflow/react";
import type {
  PaperArmedRecord,
  PaperClient,
  PaperPosition,
  PaperRunsClient,
  PaperArmedClient,
} from "../features/paper/client";
import { StatusPanel } from "../features/paper/StatusPanel";
import { createHttpClient as createPaperHttpClient } from "../features/paper/client";
import { LastRunsPanel } from "../features/paper/LastRunsPanel";
import { createLastRunsHttpClient } from "../features/paper/client";
import { ArmedRecordsList } from "../features/paper/ArmedRecordsList";
import { ResearchView } from "../features/research/ResearchView";
import { createHttpClient as createResearchHttpClient } from "../features/research/client";
import type { ResearchClient } from "../features/research/client";
import { Editor } from "../features/strategies/Editor";
import { createHttpClient } from "../features/strategies/client";
import type { StrategyClient } from "../features/strategies/client";
import type { CopiedDraft, LoadedRevision } from "../features/strategies/Editor";
import { SavedStrategyLibrary } from "../features/strategies/SavedStrategyLibrary";
import type {
  LibraryClient,
  OwnedDraftSummary,
} from "../features/strategies/libraryClient";
import { createLibraryClient } from "../features/strategies/libraryClient";
import { buildOwnedDraftCopy } from "../features/strategies/ownedDraftCopy";
import { StrategyExplanation } from "../features/strategies/StrategyExplanation";
import {
  GraphCanvas,
  type GraphCanvasNode,
} from "../features/studio/GraphCanvas";
import { nodesFromPack } from "../features/studio/packNodes";
import { applyExecutionEdit } from "../features/studio/executionEdit";
import { StudioNode } from "../features/studio/StudioNode";
import { studioNodeLabel } from "../features/studio/studioNodeLabel";
import { StudioNodeInspector } from "../features/studio/StudioNodeInspector";
import { OperationsView } from "../features/operations/OperationsView";
import { LivePreflight } from "../features/deployments/LivePreflight";
import { createHttpClient as createOperationsHttpClient } from "../features/operations/client";
import type {
  AlertRow,
  OperationsClient,
} from "../features/operations/client";
import { PackLibrary } from "../features/packs/PackLibrary";
import { createPacksHttpClient } from "../features/packs/client";
import type { PackLibraryClient } from "../features/packs/client";
import { recoverCsrf, redeemBootstrap } from "../session";
import { Wordmark } from "../components/brand/Wordmark";
import { AppHome } from "./AppHome";
import { CommandPalette } from "./CommandPalette";
import {
  Inspector,
  selectionFromAlert,
  selectionFromDeployment,
  selectionFromPosition,
  type InspectorSelection,
} from "./Inspector";
import { JobsDrawer } from "./JobsDrawer";
import { Navigation, type View } from "./Navigation";
import {
  resolveViewFromSearch,
  syncViewToHistory,
} from "./route";
import { StatusStrip } from "./StatusStrip";
import { WorkstationAlerts } from "./WorkstationAlerts";

const BOOTSTRAP_META = "krellbot-bootstrap";
const WORKLOAD_NODE_COUNT = 200;
const STUDIO_SAVE_ERROR_MESSAGE =
  "save execution failed: see server response for status code";

type SearchParams = {
  workload: string | null;
  packParam: string | null;
};

function parseSearch(search: string): SearchParams {
  const params = new URLSearchParams(search);
  return {
    workload: params.get("workload"),
    packParam: params.get("pack"),
  };
}

function syntheticWorkloadNodes(): ReadonlyArray<GraphCanvasNode> {
  return Array.from({ length: WORKLOAD_NODE_COUNT }, (_, index) => {
    const id = `w${index}`;
    return {
      id,
      type: "default",
      position: { x: (index % 20) * 40, y: Math.floor(index / 20) * 40 },
      data: {
        timeframe: index % 2 === 0 ? "1h" : "4h",
        label: studioNodeLabel(id),
      },
    };
  });
}

function workloadOnlyNodes(): ReadonlyArray<GraphCanvasNode> {
  return syntheticWorkloadNodes();
}

const STUDIO_DEMO_NODES: ReadonlyArray<GraphCanvasNode> = [
  {
    id: "n0",
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe: "1h", label: studioNodeLabel("n0") },
  },
  {
    id: "n1",
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe: "4h", label: studioNodeLabel("n1") },
  },
  {
    id: "n2",
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe: "1h", label: studioNodeLabel("n2") },
  },
];

function consumeBootstrapToken(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const meta = document.querySelector(
    `meta[name="${BOOTSTRAP_META}"]`,
  );
  if (meta === null) {
    return null;
  }
  const token = meta.getAttribute("content") ?? "";
  meta.remove();
  return token;
}

export type WorkstationShellProps = {
  paperClient?: PaperClient;
  researchClient?: ResearchClient;
  strategyClient?: StrategyClient;
  operationsClient?: OperationsClient;
  libraryClient?: LibraryClient;
  packClient?: PackLibraryClient;
};

export function WorkstationShell({
  paperClient,
  researchClient,
  strategyClient,
  operationsClient,
  libraryClient,
  packClient,
}: WorkstationShellProps = {}): JSX.Element {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [searchRevision, setSearchRevision] = useState(0);
  // ``plainWorkload`` / ``workloadWithPack`` and the active view are
  // re-read from the URL whenever history changes (back/forward).
  const { workload, packParam } = parseSearch(
    typeof window === "undefined" ? "" : window.location.search,
  );
  // ``searchRevision`` is consumed to make this hook reactive to
  // popstate events.
  void searchRevision;
  // ``plainWorkload`` = the synthetic-only 200-node canvas (no pack
  // attached). ``workloadWithPack`` = the 200-node canvas layered on
  // top of a saved pack; editing still operates on the real pack.
  const plainWorkload = workload === "200" && packParam === null;
  const workloadWithPack = workload === "200" && packParam === "1";
  // View comes from ``?view=`` (or workload deep-link / home default).
  // Draft and selection state are not URL-encoded — see ``./route.ts``.
  const [active, setActiveState] = useState<View>(() =>
    resolveViewFromSearch(
      typeof window === "undefined" ? "" : window.location.search,
    ),
  );
  const setActive = useCallback((view: View): void => {
    setActiveState(view);
    // No-ops when the URL already encodes ``view`` (re-clicking the
    // active tab must not stack duplicate history entries).
    syncViewToHistory(view, "push");
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onPopState = (): void => {
      setSearchRevision((value) => value + 1);
      setActiveState(resolveViewFromSearch(window.location.search));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const [connections, setConnections] = useState<ReadonlyArray<Connection>>([]);
  const handleAddConnection = useCallback((connection: Connection): void => {
    setConnections((prev) => [...prev, connection]);
  }, []);
  const [savedRevision, setSavedRevision] = useState<LoadedRevision | null>(null);
  const [editedPack, setEditedPack] = useState<Record<string, unknown> | null>(
    null,
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [studioRevisionId, setStudioRevisionId] = useState<string | null>(null);
  const [studioSaveError, setStudioSaveError] = useState<string | null>(null);
  const [studioSaveOutcome, setStudioSaveOutcome] = useState<string | null>(null);
  const [studioLayoutError, setStudioLayoutError] = useState<string | null>(null);

  // Research lazy-mount + portal host lifecycle.
  // The first time the user visits Research we mark it visited. Once
  // visited, ResearchView stays mounted for the lifetime of this shell
  // instance so its in-flight state (form fields, job id, result,
  // selected bar, refusal alert) survives Studio/Strategies navigation.
  // A stable detached <div> is created once; we move it inside the main
  // pane only while Research is the active view. Off-document the
  // rendered controls are absent from document queries and the
  // accessibility tree, without unmounting their React state.
  const [hasEverVisitedResearch, setHasEverVisitedResearch] = useState(false);
  const researchHostRef = useRef<HTMLDivElement | null>(null);
  const researchDetachedRef = useRef<HTMLDivElement | null>(null);
  if (
    researchDetachedRef.current === null &&
    typeof document !== "undefined"
  ) {
    researchDetachedRef.current = document.createElement("div");
    researchDetachedRef.current.setAttribute("data-kbot-research-portal", "");
  }
  // Keep unsaved editor state just as Research keeps its in-flight form.
  // The stable portal is detached while inactive, so hidden editor controls
  // do not remain in the document, tab order or accessibility tree.
  const [hasEverVisitedEditor, setHasEverVisitedEditor] = useState(false);
  const editorHostRef = useRef<HTMLDivElement | null>(null);
  const pendingEditorReset = useRef(false);
  const editorDetachedRef = useRef<HTMLDivElement | null>(null);
  if (editorDetachedRef.current === null && typeof document !== "undefined") {
    editorDetachedRef.current = document.createElement("div");
  }
  useEffect(() => {
    const detached = editorDetachedRef.current;
    if (!detached) return;
    if (active === "strategies") {
      const host = editorHostRef.current;
      if (host && detached.parentNode !== host) host.appendChild(detached);
      setHasEverVisitedEditor(true);
      if (pendingEditorReset.current) {
        pendingEditorReset.current = false;
        setEditorEpoch((epoch) => epoch + 1);
      }
    } else if (detached.parentNode !== null) {
      detached.parentNode.removeChild(detached);
    }
  }, [active, savedRevision]);

  const researchRevisionKey = savedRevision?.revision_id ?? "__none__";
  const [openedResearchJob, setOpenedResearchJob] = useState<{
    id: string; revisionKey: string;
  } | null>(null);

  useEffect(() => {
    const detached = researchDetachedRef.current;
    const host = researchHostRef.current;
    if (!detached || typeof document === "undefined") {
      return;
    }
    if (active === "research") {
      if (host && detached.parentNode !== host) {
        host.appendChild(detached);
      }
      setHasEverVisitedResearch(true);
      return;
    }
    if (detached.parentNode !== null) {
      detached.parentNode.removeChild(detached);
    }
  }, [active]);

  const savedPack = useMemo(() => {
    if (!savedRevision) {
      return null;
    }
    try {
      const value = JSON.parse(savedRevision.bytes) as unknown;
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return value as Record<string, unknown>;
      }
    } catch {
      return null;
    }
    return null;
  }, [savedRevision]);

  const workingPack = useMemo<Record<string, unknown> | null>(() => {
    if (editedPack) {
      return editedPack;
    }
    return savedPack;
  }, [editedPack, savedPack]);

  const handleIndicatorChange = useCallback(
    (nextPack: Record<string, unknown>): void => {
      setEditedPack(nextPack);
    },
    [],
  );

  const studioNodes = useMemo<ReadonlyArray<GraphCanvasNode>>(() => {
    if (workloadWithPack && workingPack) {
      const packNodes = nodesFromPack(workingPack);
      const seen = new Set(packNodes.map((node) => node.id));
      const filler: GraphCanvasNode[] = [];
      let index = 0;
      while (packNodes.length + filler.length < WORKLOAD_NODE_COUNT) {
        const id = `w${index}`;
        if (!seen.has(id)) {
          filler.push({
            id,
            type: "default",
            position: {
              x: ((index + packNodes.length) % 20) * 40,
              y: Math.floor((index + packNodes.length) / 20) * 40,
            },
            data: {
              timeframe: index % 2 === 0 ? "1h" : "4h",
              label: studioNodeLabel(id),
            },
          });
        }
        index += 1;
      }
      return [...packNodes, ...filler];
    }
    if (plainWorkload) {
      return workloadOnlyNodes();
    }
    if (workingPack) {
      return nodesFromPack(workingPack);
    }
    return STUDIO_DEMO_NODES;
  }, [workloadWithPack, plainWorkload, workingPack]);

  const client = useMemo(
    () => strategyClient ?? createHttpClient(),
    [strategyClient],
  );
  const library = useMemo(
    () => libraryClient ?? createLibraryClient(),
    [libraryClient],
  );
  const [libraryOpen, setLibraryOpen] = useState(false);
  // True while Library Reopen/Copy is fetching revision bytes. The open
  // editor stays mounted but inert so mid-wait edits cannot be made and
  // then silently dropped when handleLibraryReopen remounts it.
  const [editorReplaceBusy, setEditorReplaceBusy] = useState(false);
  // The Editor reads ``initial`` at mount only and keeps its own save
  // outcome across its own ``onRevision`` saves, so a reopen remounts
  // it under a fresh key (the ResearchView portal pattern) instead of
  // mutating Editor internals. The key advances on an explicit library
  // reopen / new-strategy / copy-as-new only — never on the Editor's
  // own saves.
  const [editorEpoch, setEditorEpoch] = useState(0);
  // Seeds a NEW draft from a copied owned revision's bytes; remounts
  // the Editor with no revision identity so Save goes through create.
  const [copiedDraft, setCopiedDraft] = useState<CopiedDraft | null>(null);
  const handleLibraryReopen = useCallback(
    (summary: OwnedDraftSummary, bytes: string): void => {
      setCopiedDraft(null);
      setSavedRevision({
        revision_id: summary.revision_id,
        state: summary.state,
        bytes,
      });
      setEditedPack(null);
      setEditorEpoch((epoch: number) => epoch + 1);
    },
    [],
  );
  const handleLibraryNewStrategy = useCallback((): void => {
    setCopiedDraft(null);
    setSavedRevision(null);
    setEditedPack(null);
    setEditorEpoch((epoch: number) => epoch + 1);
  }, []);
  const handleLibraryCopyAsNew = useCallback(
    (summary: OwnedDraftSummary, bytes: string): void => {
      // Derive the copy from the real fetched bytes; the origin
      // revision's stored bytes/state stay untouched. A parse failure
      // keeps the previous editor contents instead of substituting an
      // empty draft.
      const copy = buildOwnedDraftCopy(bytes, {
        revision_id: summary.revision_id,
        state: summary.state,
        created_at: summary.created_at,
        strategy_id: summary.strategy_id,
        label: summary.label,
      });
      if (!copy) {
        return;
      }
      setSavedRevision(null);
      setEditedPack(null);
      setCopiedDraft({
        bytes: copy.bytes,
        origin: copy.origin,
        originLabel: copy.originLabel,
      });
      setEditorEpoch((epoch: number) => epoch + 1);
    },
    [],
  );
  const loadedEditorFor = useRef<string | null>(null);
  useEffect(() => {
    if (!savedRevision || !client.loadEditor) {
      return;
    }
    if (loadedEditorFor.current === savedRevision.revision_id) {
      return;
    }
    loadedEditorFor.current = savedRevision.revision_id;
    let cancelled = false;
    void client.loadEditor(savedRevision.revision_id).then((editor) => {
      if (cancelled || !Array.isArray(editor.edges) || editor.edges.length === 0) {
        return;
      }
      setConnections(
        editor.edges.flatMap((edge) => {
          if (!edge || typeof edge !== "object") {
            return [];
          }
          const row = edge as { source?: unknown; target?: unknown };
          if (typeof row.source !== "string" || typeof row.target !== "string") {
            return [];
          }
          return [
            {
              source: row.source,
              target: row.target,
              sourceHandle: null,
              targetHandle: null,
            },
          ];
        }),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [savedRevision, client]);
  const research = useMemo(
    () => researchClient ?? createResearchHttpClient(),
    [researchClient],
  );
  // The Editor's inline stop control needs a paper client in production
  // too, where <WorkstationShell /> is mounted with no props: fall back
  // to the same loopback default the Paper tab uses so the inline
  // Disarm/Pause/Resume is available without any caller-side wiring.
  const defaultWorkstationPaperClient = useMemo(
    () => paperClient ?? createPaperHttpClient(),
    [paperClient],
  );
  const paper = defaultWorkstationPaperClient;
  // LastRunsPanel needs listRuns guaranteed at the call site, even when
  // a bare PaperClient prop is injected: layer the runs client on top.
  const paperRuns = useMemo(
    () => Object.assign({}, paper, createLastRunsHttpClient()),
    [paper],
  );
  const operations = useMemo(
    () => operationsClient ?? createOperationsHttpClient(),
    [operationsClient],
  );
  const packs = useMemo(
    () => packClient ?? createPacksHttpClient(),
    [packClient],
  );
  const [packsOpen, setPacksOpen] = useState(false);

  const [bootstrapDone, setBootstrapDone] = useState(false);
  const [bootstrapFailed, setBootstrapFailed] = useState(false);
  const [inspectorSelection, setInspectorSelection] =
    useState<InspectorSelection | null>(null);

  const handleDeploymentSelection = useCallback(
    (record: PaperArmedRecord | null): void => {
      setInspectorSelection(
        record === null ? null : selectionFromDeployment(record),
      );
    },
    [],
  );

  const handlePositionSelect = useCallback(
    (position: PaperPosition | null): void => {
      setInspectorSelection(
        position === null ? null : selectionFromPosition(position),
      );
    },
    [],
  );

  const handleAlertSelect = useCallback((alert: AlertRow | null): void => {
    setInspectorSelection(alert === null ? null : selectionFromAlert(alert));
  }, []);

  const handleRecoverSession = useCallback(async (): Promise<{ ok: boolean; error?: string }> => {
    // Only existing-session recovery: never replay the consumed bootstrap token.
    try {
      const ok = await recoverCsrf();
      if (ok) {
        setBootstrapFailed(false);
        return { ok: true };
      }
      return {
        ok: false,
        error: navigator.onLine
          ? "recovery refused"
          : "recovery refused: browser is offline; reconnect and retry",
      };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  }, []);

  useEffect(() => {
    const token = consumeBootstrapToken();
    if (!token) {
      // Reload with a redeemed (or absent) bootstrap token: the
      // session cookie may still be valid, so try to recover the
      // CSRF before mounting. A refused or failed recovery is
      // surfaced honestly instead of silently presenting startup
      // as complete.
      let cancelled = false;
      void recoverCsrf()
        .catch(() => false)
        .then((ok: boolean) => {
          if (cancelled) {
            return;
          }
          setBootstrapDone(true);
          if (!ok) {
            setBootstrapFailed(true);
          }
        });
      return () => {
        cancelled = true;
      };
    }
    let cancelled = false;
    void redeemBootstrap(token)
      .then(() => {
        if (!cancelled) {
          setBootstrapDone(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          // Bootstrap failed: the shell still mounts so navigation
          // works, but the failure is surfaced on Home instead of
          // being presented silently as startup complete. The token
          // is consumed and never retried.
          setBootstrapDone(true);
          setBootstrapFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (
        event.key.toLowerCase() === "k" &&
        (event.ctrlKey || event.metaKey)
      ) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const studioHasPack = !!savedPack;
  // Studio controls (inspector + save buttons) are visible whenever
  // a saved pack is loaded. ``plainWorkload`` (no pack param) is the
  // synthetic-only mode and never shows them.
  const showStudioControls = studioHasPack && !plainWorkload;

  const handleSaveExecution = useCallback(async (): Promise<void> => {
    const acceptStudioRevision = (revision: LoadedRevision): void => {
      setSavedRevision(revision);
      // Apply explicit Studio replacements when the Editor is next visible,
      // avoiding hidden remounts and their optional catalogue/status reads.
      pendingEditorReset.current = true;
    };
    setStudioSaveError(null);
    setStudioSaveOutcome(null);
    if (!savedRevision || !workingPack) {
      return;
    }
    try {
      const outcome = await applyExecutionEdit(
        savedRevision.revision_id,
        workingPack,
      );
      if (!outcome.revisionId) {
        setStudioSaveError(STUDIO_SAVE_ERROR_MESSAGE);
        return;
      }
      setEditedPack(outcome.pack);
      if (outcome.outcome === "unchanged") {
        // F1 — no save happened; the parent revision id is kept, no
        // validate call, and the savedRevision bytes must not change.
        setStudioSaveOutcome(
          `No change: revision ${outcome.revisionId} kept`,
        );
        return;
      }
      if (outcome.outcome === "existing") {
        // F2 — the edit landed on a different, already-existing
        // revision. Use the server's stored state; do not force draft.
        const existingState =
          outcome.state === "validated" ||
          outcome.state === "deployed" ||
          outcome.state === "archived" ||
          outcome.state === "draft"
            ? outcome.state
            : "draft";
        const existingRevision: LoadedRevision = {
          revision_id: outcome.revisionId,
          state: existingState,
          bytes: JSON.stringify(outcome.pack),
        };
        acceptStudioRevision(existingRevision);
        setStudioRevisionId(outcome.revisionId);
        setStudioSaveOutcome(
          `Selected existing revision ${outcome.revisionId}`,
        );
        if (existingState === "draft") {
          try {
            const validated = await client.validate(outcome.revisionId);
            const validatedRevision: LoadedRevision = {
              revision_id: validated.revision_id,
              state: validated.state,
              bytes: JSON.stringify(validated.pack ?? outcome.pack),
            };
            acceptStudioRevision(validatedRevision);
          } catch {
            // best-effort
          }
        }
        return;
      }
      if (outcome.outcome === "created") {
        const nextRevision: LoadedRevision = {
          revision_id: outcome.revisionId,
          state: "draft",
          bytes: JSON.stringify(outcome.pack),
        };
        acceptStudioRevision(nextRevision);
        setStudioRevisionId(outcome.revisionId);
        setStudioSaveOutcome(`Saved new revision ${outcome.revisionId}`);
        try {
          const validated = await client.validate(outcome.revisionId);
          const validatedRevision: LoadedRevision = {
            revision_id: validated.revision_id,
            state: validated.state,
            bytes: JSON.stringify(validated.pack ?? outcome.pack),
          };
          acceptStudioRevision(validatedRevision);
        } catch {
          // validation is best-effort here; the new revision id is
          // surfaced either way so the e2e can drive the assertion.
        }
        return;
      }
      // W3: a missing server outcome must not be displayed as
      // "Saved new revision". Keep the created-style state handling
      // (select + validate) but render the neutral text. Only
      // outcome === "created" may render "Saved new revision".
      const nextRevision: LoadedRevision = {
        revision_id: outcome.revisionId,
        state: "draft",
        bytes: JSON.stringify(outcome.pack),
      };
      acceptStudioRevision(nextRevision);
      setStudioRevisionId(outcome.revisionId);
      setStudioSaveOutcome(`Saved revision ${outcome.revisionId}`);
      try {
        const validated = await client.validate(outcome.revisionId);
        const validatedRevision: LoadedRevision = {
          revision_id: validated.revision_id,
          state: validated.state,
          bytes: JSON.stringify(validated.pack ?? outcome.pack),
        };
        acceptStudioRevision(validatedRevision);
      } catch {
        // best-effort
      }
    } catch (err) {
      setStudioSaveError(
        err instanceof Error ? err.message : String(err),
      );
    }
  }, [savedRevision, workingPack, client]);

  return (
    <div className="kbot-shell" data-testid="kbot-shell" data-bootstrap-done={bootstrapDone ? "1" : "0"}>
      <header className="kbot-shell__header">
        <div className="kbot-shell__brandbar">
          <button
            type="button"
            className="kbot-shell__brand"
            data-testid="kbot-shell-brand"
            onClick={() => {
              setActive("home");
            }}
          >
            <Wordmark />
          </button>
          <Navigation active={active} onChange={setActive} />
          <div className="kbot-shell__head-utils">
            <StatusStrip live={bootstrapDone ? undefined : null} />
            <JobsDrawer onOpenResult={(id) => {
              setOpenedResearchJob({ id, revisionKey: researchRevisionKey });
              setActive("research");
            }} />
            <button
              type="button"
              className="kbot-shell__palette-hint"
              data-testid="kbot-shell-palette-hint"
              aria-keyshortcuts="Control+K Meta+K"
              onClick={() => {
                setPaletteOpen(true);
              }}
            >
              <span aria-hidden="true">Search</span>
              <span className="kbot-shell__palette-keys" aria-hidden="true">⌘K</span>
              <span className="kbot-palette__label">Open command palette</span>
            </button>
          </div>
        </div>
      </header>
      <main className="kbot-shell__main">
        {active === "home" ? (
          <AppHome
            onNavigate={setActive}
            sessionPending={!bootstrapDone}
            sessionFailed={bootstrapFailed}
            onRecoverSession={handleRecoverSession}
          />
        ) : null}
        {active === "workstation" ? (
          <>
            <div className="kbot-shell__pagehead">
              <div className="kbot-shell__pagehead-copy">
                <h1 className="kbot-shell__heading">Paper workstation</h1>
                <p className="kbot-shell__pagesub">
                  Arm a paper bot, watch last runs, and pause entries without
                  leaving this machine.
                </p>
              </div>
            </div>
            <div className="kbot-shell__workstation">
              <div className="kbot-shell__workstation-main">
                {bootstrapDone ? (
                  <>
                    <StatusPanel
                      client={paper}
                      onPositionSelect={handlePositionSelect}
                      positionSelected={
                        inspectorSelection?.kind === "position"
                      }
                    />
                    <LastRunsPanel client={paperRuns} />
                    {/* The shell factory returns PaperClient & PaperRunsClient & PaperArmedClient;
                        an injected legacy client without listArmed renders the
                        truthful unavailable state instead of crashing. */}
                    <ArmedRecordsList
                      client={
                        paper as PaperClient &
                          PaperRunsClient &
                          PaperArmedClient
                      }
                      onSelectionChange={handleDeploymentSelection}
                    />
                    <WorkstationAlerts
                      client={operations}
                      selectedId={
                        inspectorSelection?.kind === "alert"
                          ? inspectorSelection.id
                          : null
                      }
                      onSelect={handleAlertSelect}
                    />
                  </>
                ) : (
                  <p
                    className="kbot-paper-status__empty"
                    data-testid="status-panel-pending"
                  >
                    Connecting…
                  </p>
                )}
              </div>
              <aside className="kbot-shell__workstation-aside">
                <Inspector selection={inspectorSelection} />
              </aside>
            </div>
          </>
        ) : null}
        {active === "strategies" ? (
          <>
            <button
              type="button"
              className="kbot-shell__library-toggle"
              data-testid="library-toggle"
              aria-pressed={libraryOpen}
              onClick={() => {
                setLibraryOpen((open: boolean) => !open);
              }}
            >
              Library
            </button>
            {libraryOpen ? (
              <SavedStrategyLibrary
                client={library}
                onReopen={handleLibraryReopen}
                onNewStrategy={handleLibraryNewStrategy}
                onCopyAsNew={handleLibraryCopyAsNew}
                onEditorReplaceBusyChange={setEditorReplaceBusy}
              />
            ) : null}
            <div
              ref={editorHostRef}
              data-testid="editor-host"
              aria-busy={editorReplaceBusy || undefined}
            />
            {editorReplaceBusy ? (
              <p
                className="kbot-shell__hint"
                data-testid="editor-reopen-busy"
                role="status"
                aria-live="polite"
              >
                Loading saved revision…
              </p>
            ) : null}
            <StrategyExplanation
              bytes={savedRevision?.bytes ?? ""}
              revisionId={savedRevision?.revision_id ?? null}
            />
            <button
              type="button"
              className="kbot-shell__packs-toggle"
              data-testid="strategies-packs-toggle"
              aria-pressed={packsOpen}
              onClick={() => {
                setPacksOpen((open) => !open);
              }}
            >
              Packs
            </button>
            {packsOpen ? <PackLibrary client={packs} /> : null}
          </>
        ) : null}
        {active === "research" ? (
          <div
            ref={researchHostRef}
            className="kbot-research__host"
            data-testid="research-host"
          />
        ) : null}
        {active === "studio" ? (
          <>
            <GraphCanvas
              nodes={studioNodes as GraphCanvasNode[]}
              edges={connections.flatMap((connection, index) => {
                if (!connection.source || !connection.target) {
                  return [];
                }
                return [
                  {
                    id: `${connection.source}-${connection.target}-${index}`,
                    source: connection.source,
                    target: connection.target,
                  },
                ];
              })}
              onAddConnection={handleAddConnection}
              onSelectNode={setSelectedNodeId}
              nodeTypes={{ default: StudioNode }}
            />
            <p
              className="kbot-studio-debug"
              data-testid="studio-node-count"
            >
              {studioNodes.length}
            </p>
            {plainWorkload ? (
              <p
                className="app-home__note-copy kbot-shell__hint"
                data-testid="studio-synthetic-label"
              >
                Synthetic preview canvas — {WORKLOAD_NODE_COUNT} sample nodes
                for load testing, not a saved strategy.
              </p>
            ) : null}
            {savedPack && !plainWorkload ? (
              <p data-testid="studio-pack-id">{String(savedPack.id ?? "")}</p>
            ) : null}
            {studioRevisionId ? (
              <p data-testid="studio-revision-id">
                revision: {studioRevisionId}
              </p>
            ) : null}
            {studioSaveError ? (
              <p
                className="kbot-shell__error"
                role="alert"
                data-testid="studio-save-error"
              >
                {studioSaveError}
              </p>
            ) : null}
            {studioSaveOutcome ? (
              <p
                className="kbot-shell__outcome"
                data-testid="studio-save-outcome"
              >
                {studioSaveOutcome}
              </p>
            ) : null}
            {studioLayoutError ? (
              <p
                className="kbot-shell__error"
                role="alert"
                data-testid="studio-layout-error"
              >
                {studioLayoutError}
              </p>
            ) : null}
            {showStudioControls ? (
              <>
                <StudioNodeInspector
                  nodeId={selectedNodeId}
                  pack={workingPack ?? savedPack ?? {}}
                  onChange={handleIndicatorChange}
                />
                <button
                  type="button"
                  data-testid="studio-save-layout"
                  onClick={() => {
                    if (!savedRevision) {
                      return;
                    }
                    setStudioLayoutError(null);
                    const packNodeIds = new Set(
                      nodesFromPack(workingPack ?? savedPack ?? {}).map(
                        (node) => node.id,
                      ),
                    );
                    const layoutEntries = studioNodes
                      .filter((node) => packNodeIds.has(node.id))
                      .map((node) => [node.id, node.position] as const);
                    const layout = Object.fromEntries(layoutEntries);
                    const edges = connections.flatMap((connection) => {
                      if (!connection.source || !connection.target) {
                        return [];
                      }
                      return [{ source: connection.source, target: connection.target }];
                    });
                    void client.saveEditor
                      ?.(savedRevision.revision_id, { layout, edges })
                      .catch((err: unknown) => {
                        setStudioLayoutError(
                          err instanceof Error ? err.message : String(err),
                        );
                      });
                  }}
                >
                  Save layout
                </button>
                <button
                  type="button"
                  data-testid="studio-save-execution"
                  onClick={() => {
                    void handleSaveExecution();
                  }}
                >
                  Save execution
                </button>
              </>
            ) : null}
            <p
              className="kbot-studio-debug"
              data-testid="studio-connection-count"
            >
              Connections: {connections.length}
            </p>
            <p
              className="kbot-studio-debug"
              data-testid="studio-selected-node"
            >
              Selected: {selectedNodeId ?? "(none)"}
            </p>
          </>
        ) : null}
        {active === "operations" ? (
          bootstrapDone ? (
            <OperationsView client={operations} />
          ) : (
            <p
              className="kbot-paper-status__empty"
              data-testid="status-panel-pending"
            >
              Connecting…
            </p>
          )
        ) : null}
        {active === "deployments" ? <LivePreflight /> : null}
      </main>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={(view) => {
          setActive(view);
          setPaletteOpen(false);
        }}
      />
      {hasEverVisitedEditor && editorDetachedRef.current
        ? createPortal(
            <div
              data-testid="editor-portal-root"
              // Freeze the previous draft for the whole Library revision
              // read: inert blocks focus and edits so they cannot be made
              // and then silently dropped when editorEpoch remounts.
              inert={editorReplaceBusy || undefined}
              aria-hidden={editorReplaceBusy || undefined}
            >
              <Editor
                key={`editor-${editorEpoch}`}
                client={client}
                paperClient={defaultWorkstationPaperClient}
                initial={savedRevision ?? undefined}
                copiedDraft={copiedDraft ?? undefined}
                onRevision={(summary, bytes) => {
                  setSavedRevision({
                    revision_id: summary.revision_id,
                    state: summary.state,
                    bytes,
                  });
                  setEditedPack(null);
                }}
              />
            </div>,
            editorDetachedRef.current,
          )
        : null}
      {hasEverVisitedResearch && researchDetachedRef.current
        ? createPortal(
            <ResearchView
              key={researchRevisionKey}
              openedJob={openedResearchJob?.revisionKey === researchRevisionKey ? openedResearchJob : null}
              client={research}
              revisionId={savedRevision?.revision_id ?? null}
            />,
            researchDetachedRef.current,
          )
        : null}
    </div>
  );
}