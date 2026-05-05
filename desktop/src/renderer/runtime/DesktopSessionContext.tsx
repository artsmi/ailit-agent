import React from "react";

import {
  resolveRegistryProjectChain,
  supervisorCreateOrGetBrokerParamsFromChain
} from "@shared/brokerHandshakePayload";
import type { DesktopConfigSnapshot, ProjectRegistryEntry, RuntimeResponseEnvelope } from "@shared/ipc";

import { DEFAULT_AGENT_MANIFEST_V1 } from "../state/agentManifest";
import {
  loadPersistedUi,
  newChatSession,
  type LastAgentPairV1,
  type ChatSessionRecordV1,
  type MemoryPanelTabV1,
  type ChatToolDisplayV1,
  normalizeMemorySplitRatio,
  savePersistedUi,
  type PersistedUiStateV1
} from "../state/persistedUi";
import {
  buildPermModeChoiceRequest,
  buildRuntimeCancelActiveTurnRequest,
  buildToolApprovalResolveRequest,
  buildUserPromptAction
} from "./envelopeFactory";
import {
  buildAgentDialogueMessages,
  deriveAgentLinkKeysFromTrace,
  type AgentDialogueMessage
} from "./agentDialogueProjection";
import {
  chatLineId,
  projectChatTraceRows,
  type ChatLine,
  type ContextFillState,
  type ToolApprovalPending
} from "./chatTraceProjector";
import { projectBrokerMemoryRecallActive } from "./chatTraceAmPhase";
import {
  buildBrokerMemoryRecallUiPhase,
  recallPhraseIdAtIndex,
  RECALL_PHRASE_ROTATION_MS,
  type BrokerMemoryRecallUiPhase
} from "./memoryRecallUiPhaseProjection";
import { buildMemoryRecallUiPhaseTraceRow } from "./memoryRecallUiObservability";
import {
  createEmptyPagGraphSessionSnapshot,
  PagGraphSessionFullLoad,
  PagGraphSessionTraceMerge,
  PagGraphWorkspaceNamespaces,
  type PagGraphSessionSnapshot,
  type PagGraphTraceMergeEmitHooks
} from "./pagGraphSessionStore";
import { dedupKeyForRow, type NormalizedTraceProjection } from "./traceNormalize";
import { newMessageId } from "./uuid";
import { BrokerTraceUserTurnResolver } from "./userTurnIdFromTrace";

const GOAL: string = "g-desktop";

type ConnState = "idle" | "connecting" | "ready" | "error";
export type { ChatLine } from "./chatTraceProjector";

export type DesktopSessionValue = {
  readonly chatId: string;
  readonly sessions: readonly ChatSessionRecordV1[];
  readonly activeSessionId: string;
  readonly setActiveSessionId: (id: string) => void;
  /** Рабочие проекты активной сессии: минимум один. */
  readonly setActiveSessionProjectIds: (ids: readonly string[]) => void;
  /** Переключить проект в workspace; не снимет последний. */
  readonly toggleProject: (projectId: string) => void;
  readonly createNewChatSession: (projectIds: readonly string[], label: string) => void;
  readonly renameSession: (sessionId: string, label: string) => void;
  readonly removeSession: (sessionId: string) => void;
  readonly toolDisplay: ChatToolDisplayV1;
  readonly setToolDisplay: (mode: ChatToolDisplayV1) => void;
  readonly lastAgentPair: LastAgentPairV1 | null;
  readonly setLastAgentPair: (pair: LastAgentPairV1 | null) => void;
  readonly connection: ConnState;
  /** Домашний каталог (пути вне runtime_dir, например ~/.ailit/agent-memory/chat_logs). */
  readonly homeDir: string | null;
  /** OR-009: снимок desktop config из main по IPC (один fetch при старте). */
  readonly desktopConfig: DesktopConfigSnapshot | null;
  readonly runtimeDir: string | null;
  readonly supervisorSummary: string | null;
  readonly brokerEndpoint: string | null;
  readonly lastError: string | null;
  readonly registry: readonly ProjectRegistryEntry[];
  readonly selectedProjectIds: readonly string[];
  readonly rawTraceRows: readonly Record<string, unknown>[];
  readonly normalizedRows: readonly NormalizedTraceProjection[];
  readonly agentDialogueMessages: readonly AgentDialogueMessage[];
  readonly agentLinkKeys: ReturnType<typeof deriveAgentLinkKeysFromTrace>;
  readonly chatLines: readonly ChatLine[];
  readonly reconnectAttempt: number;
  readonly refreshStatus: () => Promise<void>;
  readonly loadProjects: () => Promise<void>;
  readonly connectToBroker: () => Promise<void>;
  readonly sendUserPrompt: (text: string) => Promise<void>;
  readonly resubscribeTrace: () => Promise<void>;
  /** Модель/рантайм обрабатывают ход (до assistant.final / стопа). */
  readonly agentTurnInProgress: boolean;
  /** UC-06: фаза recall в строке чата (trace + ротация фраз ≥1.5s). */
  readonly brokerMemoryRecallPhase: BrokerMemoryRecallUiPhase;
  readonly requestStopAgent: () => Promise<void>;
  /** Текущий perm-режим после ``session.perm_mode.settled`` (сокращение для поля ввода). */
  readonly permModeLabel: string | null;
  /** Открыть модалку: gate_id с ``session.perm_mode.need_user_choice``. */
  readonly permModeGateId: string | null;
  readonly submitPermModeChoice: (mode: string, rememberProject: boolean) => Promise<void>;
  /** ASK: ``session.waiting_approval`` — показать модалку и вызвать ``work.approval_resolve``. */
  readonly toolApproval: { readonly callId: string; readonly tool: string } | null;
  readonly submitToolApproval: (approved: boolean) => Promise<void>;
  readonly contextFill: ContextFillState | null;
  readonly memoryPanelOpen: boolean;
  readonly memoryPanelTab: MemoryPanelTabV1;
  readonly memorySplitRatio: number;
  readonly setMemoryPanelOpen: (open: boolean) => void;
  readonly setMemoryPanelTab: (tab: MemoryPanelTabV1) => void;
  readonly setMemorySplitRatio: (ratio: number) => void;
  /**
   * Единый PAG graph store на session (G13.6): 2D/3D читают `activeSnapshot`,
   * не держат отдельный source of truth для rev/merge.
   */
  readonly pagGraph: {
    readonly activeSnapshot: PagGraphSessionSnapshot | null;
    /** Полная перезагрузка из БД (как Refresh 3D) + reconcile с trace. */
    readonly refreshPagGraph: () => void;
  };
};

const Ctx = React.createContext<DesktopSessionValue | null>(null);

/** Тот же контекст, что у `DesktopSessionProvider` — для unit-тестов без spy на `useDesktopSession`. */
export const desktopSessionReactContext: React.Context<DesktopSessionValue | null> = Ctx;

function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function getRuntimeDirFromStatus(st: unknown): string | null {
  const o: Record<string, unknown> | null = asDict(st);
  if (!o) {
    return null;
  }
  if (o["ok"] === true) {
    const r: Record<string, unknown> | null = asDict(o["result"]);
    const rd: unknown = r?.["runtime_dir"];
    return typeof rd === "string" ? rd : null;
  }
  return null;
}

function extractBroker(
  r: unknown
): { readonly endpoint: string; readonly project_root: string; readonly namespace: string } | null {
  const o: Record<string, unknown> | null = asDict(r);
  if (!o || o["ok"] !== true) {
    return null;
  }
  const b: Record<string, unknown> | null = asDict(o["result"]);
  if (!b) {
    return null;
  }
  const ep: unknown = b["endpoint"];
  const pr: unknown = b["project_root"];
  const ns: unknown = b["namespace"];
  if (typeof ep === "string" && typeof pr === "string" && typeof ns === "string") {
    return { endpoint: ep, project_root: pr, namespace: ns };
  }
  return null;
}

function buildSessionCancelledTraceRow(params: {
  readonly chatId: string;
  readonly namespace: string;
  readonly userTurnId?: string;
}): Record<string, unknown> {
  const traceId: string = newMessageId();
  const messageId: string = newMessageId();
  const cancelledPayload: Record<string, unknown> = {
    reason: "user_stop",
    source: "desktop"
  };
  const ut: string | undefined = params.userTurnId?.trim();
  if (ut && ut.length > 0) {
    cancelledPayload["user_turn_id"] = ut;
  }
  return {
    contract_version: "ailit_agent_runtime_v1",
    runtime_id: "ailit-desktop",
    chat_id: params.chatId,
    broker_id: `broker-${params.chatId}`,
    trace_id: traceId,
    message_id: messageId,
    parent_message_id: null,
    goal_id: GOAL,
    namespace: params.namespace,
    from_agent: "User:desktop",
    to_agent: `AgentWork:${params.chatId}`,
    created_at: new Date().toISOString(),
    type: "topic.publish",
    payload: {
      type: "topic.publish",
      topic: "chat",
      event_name: "session.cancelled",
      payload: cancelledPayload
    }
  };
}

function buildPagGraphTraceMergeHooks(p: {
  readonly runtimeDir: string;
  readonly chatId: string;
  readonly sessionId: string;
  readonly graphRevBeforeByNamespace: Readonly<Record<string, number>>;
  readonly pagDefaultNamespace: string;
  readonly reconciledEmitRevByNs: Map<string, number>;
  readonly fullLoad?: PagGraphTraceMergeEmitHooks["fullLoad"];
  readonly traceOnlyPagModeSentKeys: Set<string>;
}): PagGraphTraceMergeEmitHooks | undefined {
  const rd: string = p.runtimeDir;
  const canTrace: boolean = typeof window.ailitDesktop?.appendTraceRow === "function";
  const canDiag: boolean = typeof window.ailitDesktop?.appendSessionDiagnostic === "function";
  if (!canTrace && !canDiag) {
    return undefined;
  }
  // Сигнатура совпадает с appendTraceRow; при отсутствии IPC строки не уходят, но emitPagGraphObservability обновляет rev-map.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- параметр требуется типом PagGraphTraceMergeEmitHooks
  const noopEmit: (row: Record<string, unknown>) => void = (_row: Record<string, unknown>): void => {};
  return {
    chatId: p.chatId,
    sessionId: p.sessionId,
    graphRevBeforeByNamespace: { ...p.graphRevBeforeByNamespace },
    defaultNamespace: p.pagDefaultNamespace,
    reconciledEmitRevByNs: p.reconciledEmitRevByNs,
    fullLoad: p.fullLoad,
    emitTraceRow: canTrace
      ? (row: Record<string, unknown>): void => {
          void window.ailitDesktop.appendTraceRow({ runtimeDir: rd, chatId: p.chatId, row });
        }
      : canDiag
        ? noopEmit
        : undefined,
    appendDiagnosticLines: canDiag
      ? (lines: readonly string[]): void => {
          void window.ailitDesktop.appendSessionDiagnostic({
            runtimeDir: rd,
            chatId: p.chatId,
            lines: [...lines]
          });
        }
      : undefined,
    traceOnlyPagModeSentKeys: p.traceOnlyPagModeSentKeys
  };
}

function validateSessions(
  reg: readonly ProjectRegistryEntry[],
  p: PersistedUiStateV1
): PersistedUiStateV1 {
  if (reg.length === 0) {
    return p;
  }
  const allowed: Set<string> = new Set(reg.map((e) => e.projectId));
  const dft: string = reg[0]!.projectId;
  const sessions: ChatSessionRecordV1[] = p.sessions.map((s) => {
    const next: string[] = s.projectIds.map((x) => x).filter((id) => allowed.has(id));
    if (next.length === 0) {
      return { ...s, projectIds: [dft] };
    }
    return { ...s, projectIds: next as unknown as readonly string[] };
  });
  return { ...p, sessions };
}

export function DesktopSessionProvider({ children }: { readonly children: React.ReactNode }): React.JSX.Element {
  const [ui, setUi] = React.useState<PersistedUiStateV1>(loadPersistedUi);
  const [connection, setConnection] = React.useState<ConnState>("idle");
  const [homeDir, setHomeDir] = React.useState<string | null>(null);
  const [desktopConfig, setDesktopConfig] = React.useState<DesktopConfigSnapshot | null>(null);
  const [runtimeDir, setRuntimeDir] = React.useState<string | null>(null);
  const [supervisorSummary, setSupervisorSummary] = React.useState<string | null>(null);
  const [brokerEndpoint, setBrokerEndpoint] = React.useState<string | null>(null);
  const [lastError, setLastError] = React.useState<string | null>(null);
  const [registry, setRegistry] = React.useState<readonly ProjectRegistryEntry[]>([]);
  const [rawTraceRows, setRawTraceRows] = React.useState<Record<string, unknown>[]>([]);
  const rawTraceRowsRef: React.MutableRefObject<Record<string, unknown>[]> = React.useRef<Record<string, unknown>[]>([]);
  const [pagGraphBySession, setPagGraphBySession] = React.useState<Record<string, PagGraphSessionSnapshot>>({});
  const pagGraphBySessionRef: React.MutableRefObject<Record<string, PagGraphSessionSnapshot>> =
    React.useRef<Record<string, PagGraphSessionSnapshot>>({});
  React.useEffect((): void => {
    pagGraphBySessionRef.current = pagGraphBySession;
  }, [pagGraphBySession]);
  const pagGraphRefreshIntentRef: React.MutableRefObject<"none" | "user" | "poll"> = React.useRef<"none" | "user" | "poll">(
    "none"
  );
  const pagGraphLastEmittedReconcileRevRef: React.MutableRefObject<Map<string, number>> = React.useRef<
    Map<string, number>
  >(new Map());
  const traceOnlyPagModeSentKeysRef: React.MutableRefObject<Set<string>> = React.useRef<Set<string>>(new Set());
  const [pagLoadTick, setPagLoadTick] = React.useState(0);
  const [optimisticChatLines, setOptimisticChatLines] = React.useState<ChatLine[]>([]);
  const [reconnectAttempt, setReconnectAttempt] = React.useState(0);
  const seenRowKeys: React.MutableRefObject<Set<string>> = React.useRef<Set<string>>(new Set());
  const registryWasEmpty: React.MutableRefObject<boolean> = React.useRef(true);
  const subChatIdRef: React.MutableRefObject<string | null> = React.useRef(null);
  const activeChatIdRef: React.MutableRefObject<string> = React.useRef("");
  const [suppressedToolApprovalCallId, setSuppressedToolApprovalCallId] = React.useState<string | null>(null);
  const toolApprovalRef: React.MutableRefObject<ToolApprovalPending | null> = React.useRef<ToolApprovalPending | null>(null);
  const stopAgentInFlightRef: React.MutableRefObject<boolean> = React.useRef<boolean>(false);

  const setUiAndSave: (next: PersistedUiStateV1 | ((prev: PersistedUiStateV1) => PersistedUiStateV1)) => void = React.useCallback(
    (next) => {
      setUi((prev) => {
        const resolved: PersistedUiStateV1 = typeof next === "function" ? (next as (p: PersistedUiStateV1) => PersistedUiStateV1)(prev) : next;
        savePersistedUi(resolved);
        return resolved;
      });
    },
    []
  );

  const activeSession: ChatSessionRecordV1 = React.useMemo((): ChatSessionRecordV1 => {
    return ui.sessions.find((s) => s.id === ui.activeSessionId) ?? ui.sessions[0]!;
  }, [ui.sessions, ui.activeSessionId]);

  activeChatIdRef.current = activeSession.chatId;

  React.useEffect((): void => {
    pagGraphLastEmittedReconcileRevRef.current = new Map();
    pagGraphRefreshIntentRef.current = "none";
    traceOnlyPagModeSentKeysRef.current = new Set();
  }, [activeSession.id]);

  React.useEffect((): void => {
    rawTraceRowsRef.current = rawTraceRows;
  }, [rawTraceRows]);

  const pagNamespaces: readonly string[] = React.useMemo(
    (): readonly string[] => PagGraphWorkspaceNamespaces.list(registry, activeSession.projectIds),
    [registry, activeSession.projectIds]
  );

  const pagDefaultNamespace: string = React.useMemo(
    (): string => PagGraphWorkspaceNamespaces.defaultNamespace(registry, activeSession.projectIds),
    [registry, activeSession.projectIds]
  );

  const awaitingPagSqlite: boolean = React.useMemo((): boolean => {
    const cur: PagGraphSessionSnapshot | undefined = pagGraphBySession[activeSession.id];
    return cur != null && cur.loadState === "ready" && !cur.pagDatabasePresent;
  }, [pagGraphBySession, activeSession.id]);

  const traceProjection = React.useMemo(
    () => projectChatTraceRows(rawTraceRows, { suppressedToolApprovalCallId }),
    [rawTraceRows, suppressedToolApprovalCallId]
  );
  const normalizedRows: readonly NormalizedTraceProjection[] = traceProjection.normalizedRows;
  const chatLines: readonly ChatLine[] = React.useMemo((): readonly ChatLine[] => {
    const projectedIds: Set<string> = new Set(traceProjection.chatLines.map((line) => line.id));
    return [
      ...traceProjection.chatLines,
      ...optimisticChatLines.filter((line) => !projectedIds.has(line.id))
    ].sort((a, b) => {
      const d: number = a.order - b.order;
      if (d !== 0) {
        return d;
      }
      return a.atIso.localeCompare(b.atIso);
    });
  }, [optimisticChatLines, traceProjection.chatLines]);
  const agentTurnInProgress: boolean = traceProjection.agentTurnInProgress || optimisticChatLines.length > 0;
  const brokerMemoryRecallActive: boolean = React.useMemo(
    (): boolean => projectBrokerMemoryRecallActive(rawTraceRows, activeSession.chatId),
    [rawTraceRows, activeSession.chatId]
  );
  const [brokerMemoryRecallPhraseIndex, setBrokerMemoryRecallPhraseIndex] = React.useState<number>(0);
  React.useEffect((): void => {
    setBrokerMemoryRecallPhraseIndex(0);
  }, [activeSession.id]);
  React.useEffect((): void | (() => void) => {
    if (!brokerMemoryRecallActive) {
      setBrokerMemoryRecallPhraseIndex(0);
      return;
    }
    const id: number = window.setInterval((): void => {
      setBrokerMemoryRecallPhraseIndex((i: number): number => i + 1);
    }, RECALL_PHRASE_ROTATION_MS);
    return (): void => {
      window.clearInterval(id);
    };
  }, [brokerMemoryRecallActive]);
  const brokerMemoryRecallPhase: BrokerMemoryRecallUiPhase = React.useMemo(
    (): BrokerMemoryRecallUiPhase =>
      buildBrokerMemoryRecallUiPhase(brokerMemoryRecallActive, brokerMemoryRecallPhraseIndex),
    [brokerMemoryRecallActive, brokerMemoryRecallPhraseIndex]
  );
  const memoryRecallEmitSigRef: React.MutableRefObject<string | null> = React.useRef<string | null>(null);
  React.useEffect((): void => {
    memoryRecallEmitSigRef.current = null;
  }, [activeSession.id]);
  React.useEffect((): void => {
    const rd: string | null = runtimeDir;
    if (rd == null || typeof window.ailitDesktop?.appendTraceRow !== "function") {
      return;
    }
    const chatId0: string = activeSession.chatId;
    const sessionId0: string = activeSession.id;
    const phase: BrokerMemoryRecallUiPhase = brokerMemoryRecallPhase;
    const sig: string = phase.active
      ? `a:${recallPhraseIdAtIndex(phase.phraseIndex)}`
      : "idle";
    const prev: string | null = memoryRecallEmitSigRef.current;
    if (sig === "idle" && prev === "idle") {
      return;
    }
    if (sig === "idle" && prev === null) {
      memoryRecallEmitSigRef.current = "idle";
      return;
    }
    if (phase.active && prev === sig) {
      return;
    }
    memoryRecallEmitSigRef.current = sig;
    const nsOpt: string | undefined =
      pagDefaultNamespace.length > 0 ? pagDefaultNamespace : undefined;
    const row: Record<string, unknown> = phase.active
      ? buildMemoryRecallUiPhaseTraceRow({
          chatId: chatId0,
          sessionId: sessionId0,
          phase_code: "recall_active",
          phrase_id: recallPhraseIdAtIndex(phase.phraseIndex),
          namespace: nsOpt
        })
      : buildMemoryRecallUiPhaseTraceRow({
          chatId: chatId0,
          sessionId: sessionId0,
          phase_code: "idle",
          namespace: nsOpt
        });
    void window.ailitDesktop.appendTraceRow({ runtimeDir: rd, chatId: chatId0, row });
  }, [
    brokerMemoryRecallPhase,
    runtimeDir,
    activeSession.chatId,
    activeSession.id,
    pagDefaultNamespace
  ]);
  const permModeLabel: string | null = traceProjection.permModeLabel;
  const permModeGateId: string | null = traceProjection.permModeGateId;
  const toolApproval: ToolApprovalPending | null = traceProjection.toolApproval;
  const contextFill: ContextFillState | null = traceProjection.contextFill;

  React.useEffect(() => {
    toolApprovalRef.current = toolApproval;
    if (!toolApproval) {
      setSuppressedToolApprovalCallId(null);
    }
  }, [toolApproval]);

  React.useEffect(() => {
    const projectedIds: Set<string> = new Set(traceProjection.chatLines.map((line) => line.id));
    setOptimisticChatLines((cur) => cur.filter((line) => !projectedIds.has(line.id)));
  }, [traceProjection.chatLines]);

  const setActiveSessionId: (id: string) => void = React.useCallback(
    (id) => {
      if (!id) {
        return;
      }
      setUiAndSave((p) => {
        if (!p.sessions.some((s) => s.id === id)) {
          return p;
        }
        return { ...p, activeSessionId: id };
      });
    },
    [setUiAndSave]
  );

  const setLastAgentPair: (pair: LastAgentPairV1 | null) => void = React.useCallback(
    (pair) => {
      setUiAndSave((p) => ({ ...p, lastAgentPair: pair }));
    },
    [setUiAndSave]
  );

  const setActiveSessionProjectIds: (ids: readonly string[]) => void = React.useCallback(
    (ids) => {
      if (ids.length === 0) {
        return;
      }
      setUiAndSave((p) => ({
        ...p,
        sessions: p.sessions.map((s) => (s.id === p.activeSessionId ? { ...s, projectIds: [...ids] } : s))
      }));
    },
    [setUiAndSave]
  );

  const toggleProject: (projectId: string) => void = React.useCallback(
    (projectId) => {
      setUiAndSave((p) => {
        const cur: ChatSessionRecordV1 | undefined = p.sessions.find((s) => s.id === p.activeSessionId);
        if (!cur) {
          return p;
        }
        const set0: Set<string> = new Set(cur.projectIds);
        if (set0.has(projectId)) {
          if (set0.size <= 1) {
            return p;
          }
          set0.delete(projectId);
        } else {
          set0.add(projectId);
        }
        const next: readonly string[] = [...set0];
        return {
          ...p,
          sessions: p.sessions.map((s) => (s.id === cur.id ? { ...s, projectIds: next } : s))
        };
      });
    },
    [setUiAndSave]
  );

  const createNewChatSession: (projectIds: readonly string[], label: string) => void = React.useCallback(
    (projectIds, label) => {
      if (projectIds.length === 0) {
        return;
      }
      const s: ChatSessionRecordV1 = newChatSession(projectIds, label);
      setUiAndSave((p) => ({
        ...p,
        sessions: [...p.sessions, s],
        activeSessionId: s.id
      }));
    },
    [setUiAndSave]
  );

  const renameSession: (sessionId: string, label: string) => void = React.useCallback(
    (sessionId, t) => {
      const next: string = t.trim();
      if (!next) {
        return;
      }
      setUiAndSave((p) => {
        if (!p.sessions.some((x) => x.id === sessionId)) {
          return p;
        }
        return {
          ...p,
          sessions: p.sessions.map((s) => (s.id === sessionId ? { ...s, label: next } : s))
        };
      });
    },
    [setUiAndSave]
  );

  const removeSession: (sessionId: string) => void = React.useCallback(
    (sessionId) => {
      setPagGraphBySession((pg) => {
        if (!(sessionId in pg)) {
          return pg;
        }
        const n: Record<string, PagGraphSessionSnapshot> = { ...pg };
        delete n[sessionId];
        return n;
      });
      setUiAndSave((p) => {
        if (p.sessions.length <= 1) {
          const one: ChatSessionRecordV1 = p.sessions[0]!;
          const rep: ChatSessionRecordV1 = newChatSession(
            one.projectIds.length > 0 ? [...one.projectIds] : [],
            "Session 1"
          );
          return { ...p, sessions: [rep], activeSessionId: rep.id };
        }
        const nextSess: ChatSessionRecordV1[] = p.sessions.filter((s) => s.id !== sessionId);
        if (nextSess.length === p.sessions.length) {
          return p;
        }
        const nextActive: string = p.activeSessionId === sessionId ? nextSess[0]!.id : p.activeSessionId;
        return { ...p, sessions: nextSess, activeSessionId: nextActive };
      });
    },
    [setUiAndSave]
  );

  const setToolDisplay: (m: ChatToolDisplayV1) => void = React.useCallback(
    (m) => {
      setUiAndSave((p) => ({ ...p, toolDisplay: m }));
    },
    [setUiAndSave]
  );

  const setMemoryPanelOpen: (open: boolean) => void = React.useCallback(
    (open) => {
      setUiAndSave((p) => ({ ...p, memoryPanelOpen: open }));
    },
    [setUiAndSave]
  );

  const setMemoryPanelTab: (tab: MemoryPanelTabV1) => void = React.useCallback(
    (tab) => {
      setUiAndSave((p) => ({ ...p, memoryPanelTab: tab }));
    },
    [setUiAndSave]
  );

  const setMemorySplitRatio: (ratio: number) => void = React.useCallback(
    (ratio) => {
      setUiAndSave((p) => ({
        ...p,
        memorySplitRatio: normalizeMemorySplitRatio(ratio)
      }));
    },
    [setUiAndSave]
  );

  const mergeRows: (rows: readonly Record<string, unknown>[]) => void = React.useCallback((rows) => {
    setRawTraceRows((prev) => {
      const next: Record<string, unknown>[] = [...prev];
      const byKey: Map<string, number> = new Map();
      next.forEach((r, i) => {
        byKey.set(dedupKeyForRow(r), i);
      });
      for (const r of rows) {
        const k: string = dedupKeyForRow(r);
        if (seenRowKeys.current.has(k)) {
          const idx: number | undefined = byKey.get(k);
          if (idx !== undefined) {
            next[idx] = r;
          }
        } else {
          seenRowKeys.current.add(k);
          next.push(r);
          byKey.set(k, next.length - 1);
        }
      }
      return next;
    });
  }, []);

  const selectedProjectIds: readonly string[] = activeSession.projectIds;

  const agentDialogueMessages: readonly AgentDialogueMessage[] = React.useMemo(
    () => buildAgentDialogueMessages(rawTraceRows, DEFAULT_AGENT_MANIFEST_V1, selectedProjectIds),
    [rawTraceRows, selectedProjectIds]
  );

  const agentLinkKeys = React.useMemo(() => deriveAgentLinkKeysFromTrace(rawTraceRows), [rawTraceRows]);

  const pickWorkspace: () => {
    namespace: string;
    projectRoot: string;
    pids: string[];
    roots: readonly string[];
  } | null = React.useCallback((): { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null => {
    const chain = resolveRegistryProjectChain(
      registry,
      selectedProjectIds,
      desktopConfig?.highlight_namespace_policy
    );
    if (!chain?.length) {
      return null;
    }
    const first = chain[0];
    if (!first) {
      return null;
    }
    return {
      namespace: first.namespace,
      projectRoot: first.projectRoot,
      pids: chain.map((r) => r.projectId),
      roots: chain.map((r) => r.projectRoot)
    };
  }, [desktopConfig?.highlight_namespace_policy, registry, selectedProjectIds]);

  const refreshStatus: () => Promise<void> = React.useCallback(async () => {
    const st: unknown = await window.ailitDesktop.supervisorStatus();
    setRuntimeDir(getRuntimeDirFromStatus(st));
    setSupervisorSummary(JSON.stringify(st, null, 0).slice(0, 2000));
  }, []);

  const loadProjects: () => Promise<void> = React.useCallback(async () => {
    const res: Awaited<ReturnType<typeof window.ailitDesktop.projectRegistryList>> = await window.ailitDesktop.projectRegistryList(
      {}
    );
    if (res.ok) {
      setRegistry(res.entries);
      setUiAndSave((p) => validateSessions(res.entries, p));
    }
  }, [setUiAndSave]);

  const resubscribeTrace: () => Promise<void> = React.useCallback(async () => {
    if (!brokerEndpoint || !runtimeDir) {
      return;
    }
    const cid: string = activeChatIdRef.current;
    await window.ailitDesktop.traceUnsubscribe({ chatId: cid });
    const dur: Awaited<ReturnType<typeof window.ailitDesktop.traceReadDurable>> = await window.ailitDesktop.traceReadDurable({
      runtimeDir,
      chatId: cid
    });
    if (dur.ok) {
      mergeRows(dur.rows);
    }
    const sub: { readonly ok: true } | { readonly ok: false; readonly error: string } = await window.ailitDesktop.traceSubscribe({
      chatId: cid,
      endpoint: brokerEndpoint
    });
    if (!sub.ok) {
      setLastError(sub.error);
      setConnection("error");
    } else {
      setConnection("ready");
    }
  }, [brokerEndpoint, mergeRows, runtimeDir]);

  const connectToBroker: () => Promise<void> = React.useCallback(async () => {
    const cid: string = activeSession.chatId;
    setConnection("connecting");
    setLastError(null);
    if (subChatIdRef.current && subChatIdRef.current !== cid) {
      try {
        await window.ailitDesktop.traceUnsubscribe({ chatId: subChatIdRef.current });
      } catch {
        /* non-fatal */
      }
    }
    await refreshStatus();
    const st0: unknown = await window.ailitDesktop.supervisorStatus();
    const rd0: string | null = getRuntimeDirFromStatus(st0);
    if (rd0) {
      setRuntimeDir(rd0);
    }
    const chain = resolveRegistryProjectChain(
      registry,
      selectedProjectIds,
      desktopConfig?.highlight_namespace_policy
    );
    if (!chain?.length) {
      setLastError("Нет выбранных проектов. Добавьте проекты (CLI) и создайте диалог.");
      setConnection("error");
      return;
    }
    const created: unknown = await window.ailitDesktop.supervisorCreateOrGetBroker(
      supervisorCreateOrGetBrokerParamsFromChain(cid, chain)
    );
    const br: { readonly endpoint: string } | null = extractBroker(created);
    if (!br) {
      setLastError(JSON.stringify(created, null, 0).slice(0, 800));
      setConnection("error");
      return;
    }
    setBrokerEndpoint(br.endpoint);
    const st1: unknown = await window.ailitDesktop.supervisorStatus();
    const rd1: string | null = getRuntimeDirFromStatus(st1);
    if (!rd1) {
      setConnection("error");
      setLastError("runtime_dir not available from status.");
      return;
    }
    setRuntimeDir(rd1);
    void window.ailitDesktop.appendSessionDiagnostic({
      runtimeDir: rd1,
      chatId: cid,
      lines: [
        `=== ailit-desktop broker connect ${new Date().toISOString()} chatId=${cid} sessionUi=${activeSession.id} ===`
      ]
    });
    const dur1: Awaited<ReturnType<typeof window.ailitDesktop.traceReadDurable>> = await window.ailitDesktop.traceReadDurable({
      runtimeDir: rd1,
      chatId: cid
    });
    if (dur1.ok) {
      mergeRows(dur1.rows);
    }
    const sub1: { readonly ok: true } | { readonly ok: false; readonly error: string } = await window.ailitDesktop.traceSubscribe({
      chatId: cid,
      endpoint: br.endpoint
    });
    if (!sub1.ok) {
      setLastError(sub1.error);
      setConnection("error");
      return;
    }
    subChatIdRef.current = cid;
    setConnection("ready");
  }, [
    activeSession.chatId,
    activeSession.id,
    desktopConfig?.highlight_namespace_policy,
    mergeRows,
    refreshStatus,
    registry,
    selectedProjectIds
  ]);

  React.useEffect(() => {
    void refreshStatus();
    void loadProjects();
  }, [loadProjects, refreshStatus]);

  React.useEffect(() => {
    void (async () => {
      try {
        const h: string = await window.ailitDesktop.homeDir();
        setHomeDir(h);
      } catch {
        setHomeDir(null);
      }
    })();
  }, []);

  React.useEffect(() => {
    void (async () => {
      try {
        const snap: DesktopConfigSnapshot = await window.ailitDesktop.getDesktopConfigSnapshot();
        setDesktopConfig(snap);
      } catch {
        setDesktopConfig(null);
      }
    })();
  }, []);

  React.useEffect(() => {
    if (registry.length > 0 && registryWasEmpty.current) {
      registryWasEmpty.current = false;
    }
  }, [registry.length]);

  const projKey: string = activeSession.projectIds.join("|");

  React.useEffect(() => {
    if (activeSession.projectIds.length === 0) {
      return;
    }
    if (registry.length === 0) {
      return;
    }
    seenRowKeys.current = new Set();
    setRawTraceRows([]);
    setOptimisticChatLines([]);
    setSuppressedToolApprovalCallId(null);
    setBrokerEndpoint(null);
    void connectToBroker();
  }, [
    activeSession.chatId,
    activeSession.id,
    activeSession.projectIds.length,
    connectToBroker,
    projKey,
    registry.length
  ]);

  const sendUserPrompt: (text: string) => Promise<void> = React.useCallback(
    async (text) => {
      const t: string = text.trim();
      if (!t) {
        return;
      }
      const ep: string | null = brokerEndpoint;
      if (!ep) {
        setLastError("Broker endpoint not ready.");
        return;
      }
      const chatId0: string = activeSession.chatId;
      const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null = pickWorkspace();
      if (!ws0) {
        setLastError("No workspace projects selected.");
        return;
      }
      const built: ReturnType<typeof buildUserPromptAction> = buildUserPromptAction({
        chatId: chatId0,
        brokerId: `broker-${chatId0}`,
        namespace: ws0.namespace,
        goalId: GOAL,
        traceId: newMessageId(),
        prompt: t,
        workspace: { projectIds: ws0.pids, projectRoots: [...ws0.roots] }
      });
      const userId: string = chatLineId("user", built.messageId);
      const userOrder: number = rawTraceRows.length + optimisticChatLines.length + 1;
      setOptimisticChatLines((cur) => [
        ...cur.filter((line) => line.id !== userId),
        {
          id: userId,
          from: "user",
          text: t,
          atIso: new Date().toISOString(),
          order: userOrder
        }
      ]);
      const r: { readonly ok: true; readonly response: RuntimeResponseEnvelope } | { readonly ok: false; readonly error: string } =
        await window.ailitDesktop.brokerRequest({ endpoint: ep, request: built.envelope });
      if (!r.ok) {
        setOptimisticChatLines((cur) => cur.filter((line) => line.id !== userId));
        setLastError(r.error);
        return;
      }
      if (!r.response.ok) {
        const err0: { readonly code: string; readonly message: string } | null = r.response.error;
        if (err0?.code === "agent_busy") {
          setOptimisticChatLines((cur) => cur.filter((line) => line.id !== userId));
          setLastError(
            err0.message.length > 0
              ? err0.message
              : "Агент занят: дождитесь окончания текущего ответа."
          );
          return;
        }
        const asstIdErr: string = r.response.message_id;
        const errId: string = chatLineId("system", asstIdErr);
        setOptimisticChatLines((cur) => [
          ...cur.filter((line) => line.id !== userId && line.id !== errId),
          {
            id: errId,
            from: "system",
            text: `Broker: ${JSON.stringify(r.response.error)}`,
            atIso: r.response.created_at,
            order: userOrder + 1
          }
        ]);
      }
    },
    [activeSession.chatId, brokerEndpoint, optimisticChatLines.length, pickWorkspace, rawTraceRows.length]
  );

  const submitToolApproval: (approved: boolean) => Promise<void> = React.useCallback(
    async (approved) => {
      const req: ToolApprovalPending | null = toolApprovalRef.current;
      if (!req) {
        return;
      }
      const finishUi: (reason: string | null) => void = (reason) => {
        setSuppressedToolApprovalCallId(req.callId);
        setLastError(reason);
      };
      const ep: string | null = brokerEndpoint;
      const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null =
        pickWorkspace();
      if (!ep) {
        finishUi(
          "Нет подключения к брокеру — ответ на ASK не отправлен. Модалка скрыта; переподключите broker при необходимости."
        );
        return;
      }
      if (!ws0) {
        finishUi(
          "Нет привязки сессии к проекту в registry — ответ на ASK не отправлен. Модалка скрыта; выберите проект или обновите registry."
        );
        return;
      }
      const chatId0: string = activeSession.chatId;
      const built: ReturnType<typeof buildToolApprovalResolveRequest> = buildToolApprovalResolveRequest({
        chatId: chatId0,
        brokerId: `broker-${chatId0}`,
        namespace: ws0.namespace,
        goalId: GOAL,
        traceId: newMessageId(),
        callId: req.callId,
        approved
      });
      const r: { readonly ok: true; readonly response: RuntimeResponseEnvelope } | { readonly ok: false; readonly error: string } =
        await window.ailitDesktop.brokerRequest({ endpoint: ep, request: built.envelope });
      if (!r.ok) {
        finishUi(r.error);
        return;
      }
      if (!r.response.ok) {
        const msg: string = r.response.error?.message ?? "work.approval_resolve failed";
        finishUi(msg);
        return;
      }
      finishUi(null);
    },
    [activeSession.chatId, brokerEndpoint, pickWorkspace]
  );

  const submitPermModeChoice: (mode: string, rememberProject: boolean) => Promise<void> = React.useCallback(
    async (mode, rememberProject) => {
      const ep: string | null = brokerEndpoint;
      const gid: string | null = permModeGateId;
      if (!ep || !gid) {
        return;
      }
      const chatId0: string = activeSession.chatId;
      const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null =
        pickWorkspace();
      if (!ws0) {
        return;
      }
      const built: ReturnType<typeof buildPermModeChoiceRequest> = buildPermModeChoiceRequest({
        chatId: chatId0,
        brokerId: `broker-${chatId0}`,
        namespace: ws0.namespace,
        goalId: GOAL,
        traceId: newMessageId(),
        gateId: gid,
        mode,
        rememberProject
      });
      const r: { readonly ok: true; readonly response: RuntimeResponseEnvelope } | { readonly ok: false; readonly error: string } =
        await window.ailitDesktop.brokerRequest({ endpoint: ep, request: built.envelope });
      if (!r.ok) {
        setLastError(r.error);
        return;
      }
      if (!r.response.ok) {
        setLastError(r.response.error?.message ?? "perm mode choice failed");
      }
    },
    [activeSession.chatId, brokerEndpoint, permModeGateId, pickWorkspace]
  );

  const requestStopAgent: () => Promise<void> = React.useCallback(async () => {
    if (stopAgentInFlightRef.current) {
      return;
    }
    stopAgentInFlightRef.current = true;
    try {
      const cid: string = activeSession.chatId;
      const rd: string | null = runtimeDir;
      const ep: string | null = brokerEndpoint;
      const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null =
        pickWorkspace();
      const userTurnId: string = BrokerTraceUserTurnResolver.latestForChat(rawTraceRows, cid);
      if (ep && ws0) {
        const builtCancel: ReturnType<typeof buildRuntimeCancelActiveTurnRequest> = buildRuntimeCancelActiveTurnRequest({
          chatId: cid,
          brokerId: `broker-${cid}`,
          namespace: ws0.namespace,
          goalId: GOAL,
          traceId: newMessageId(),
          userTurnId
        });
        const cr: { readonly ok: true; readonly response: RuntimeResponseEnvelope } | { readonly ok: false; readonly error: string } =
          await window.ailitDesktop.brokerRequest({ endpoint: ep, request: builtCancel.envelope });
        if (!cr.ok) {
          setLastError(cr.error);
        } else if (!cr.response.ok) {
          const msg: string = cr.response.error?.message ?? JSON.stringify(cr.response.error);
          setLastError(msg.length > 0 ? msg : "runtime.cancel_active_turn rejected");
        }
      }
      const stopRow: Record<string, unknown> = buildSessionCancelledTraceRow({
        chatId: cid,
        namespace: ws0?.namespace ?? "",
        userTurnId: userTurnId.length > 0 ? userTurnId : undefined
      });
      mergeRows([stopRow]);
      if (rd) {
        const appended: Awaited<ReturnType<typeof window.ailitDesktop.appendTraceRow>> =
          await window.ailitDesktop.appendTraceRow({
            runtimeDir: rd,
            chatId: cid,
            row: stopRow
          });
        if (!appended.ok) {
          setLastError(appended.error);
        }
      }
      setBrokerEndpoint(null);
      try {
        await window.ailitDesktop.supervisorStopBroker({ chatId: cid });
      } catch (e) {
        setLastError(e instanceof Error ? e.message : String(e));
      }
      setConnection("connecting");
      try {
        await connectToBroker();
      } catch (e) {
        setLastError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      stopAgentInFlightRef.current = false;
    }
  }, [activeSession.chatId, brokerEndpoint, connectToBroker, mergeRows, pickWorkspace, rawTraceRows, runtimeDir]);

  React.useEffect(() => {
    const offRow: (() => void) | void = window.ailitDesktop.onTraceRow((evt) => {
      if (evt.chatId !== activeChatIdRef.current) {
        return;
      }
      mergeRows([evt.row]);
    });
    const offCh: (() => void) | void = window.ailitDesktop.onTraceChannel((ch) => {
      if (ch.chatId !== activeChatIdRef.current) {
        return;
      }
      if (ch.kind === "error" || ch.kind === "end") {
        void (async () => {
          const delayMs: number = desktopConfig?.trace_reconnect_min_ms ?? 800;
          setReconnectAttempt((a) => a + 1);
          await new Promise((r) => {
            setTimeout(r, delayMs);
          });
          try {
            await resubscribeTrace();
          } catch (e) {
            setLastError(e instanceof Error ? e.message : String(e));
            setConnection("error");
          }
        })();
      }
    });
    return () => {
      if (typeof offRow === "function") {
        offRow();
      }
      if (typeof offCh === "function") {
        offCh();
      }
    };
  }, [desktopConfig?.trace_reconnect_min_ms, mergeRows, resubscribeTrace]);

  const refreshPagGraph: () => void = React.useCallback((): void => {
    pagGraphRefreshIntentRef.current = "user";
    setPagLoadTick((t) => t + 1);
  }, []);

  React.useEffect((): (() => void) | void => {
    const sessionId: string = activeSession.id;
    const chatIdForPag: string = activeSession.chatId;
    const slice: unknown = window.ailitDesktop?.pagGraphSlice;
    if (!runtimeDir || typeof slice !== "function" || pagNamespaces.length === 0) {
      return;
    }
    const sliceFn: typeof window.ailitDesktop.pagGraphSlice = slice as typeof window.ailitDesktop.pagGraphSlice;
    let cancelled: boolean = false;
    setPagGraphBySession((prev) => {
      const cur: PagGraphSessionSnapshot | undefined = prev[sessionId];
      if (cur != null) {
        return {
          ...prev,
          [sessionId]: {
            ...cur,
            loadState: "loading",
            loadError: null
          }
        };
      }
      return {
        ...prev,
        [sessionId]: createEmptyPagGraphSessionSnapshot({ loadState: "loading" })
      };
    });
    void (async () => {
      const r: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
        (p) => sliceFn(p),
        pagNamespaces
      );
      if (cancelled) {
        return;
      }
      if (!r.ok) {
        setPagGraphBySession((p0) => ({
          ...p0,
          [sessionId]: {
            ...createEmptyPagGraphSessionSnapshot({ loadState: "error" }),
            loadState: "error" as const,
            loadError: r.error
          }
        }));
        return;
      }
      const pagDatabasePresent: boolean = r.pagSqliteMissing !== true;
      const rows: readonly Record<string, unknown>[] = rawTraceRowsRef.current;
      const rd0: string | null = runtimeDir;
      const prevRevsFull: Readonly<Record<string, number>> =
        pagGraphBySessionRef.current[sessionId]?.graphRevByNamespace ?? {};
      const intentFl: "none" | "user" | "poll" = pagGraphRefreshIntentRef.current;
      pagGraphRefreshIntentRef.current = "none";
      const fullLoadKind: "user_refresh" | "poll_retry" | "initial_load" =
        intentFl === "user" ? "user_refresh" : intentFl === "poll" ? "poll_retry" : "initial_load";
      const prevHighlights = pagGraphBySessionRef.current[sessionId]?.searchHighlightsByNamespace ?? {};
      const hooks: PagGraphTraceMergeEmitHooks | undefined =
        rd0 != null
          ? buildPagGraphTraceMergeHooks({
              runtimeDir: rd0,
              chatId: chatIdForPag,
              sessionId,
              graphRevBeforeByNamespace: { ...prevRevsFull },
              pagDefaultNamespace,
              reconciledEmitRevByNs: pagGraphLastEmittedReconcileRevRef.current,
              fullLoad: { kind: fullLoadKind, namespaces: [...pagNamespaces] },
              traceOnlyPagModeSentKeys: traceOnlyPagModeSentKeysRef.current
            })
          : undefined;
      const snap: PagGraphSessionSnapshot = PagGraphSessionTraceMerge.afterFullLoad(
        r.merged,
        r.graphRevByNamespace,
        rows,
        pagNamespaces,
        pagDefaultNamespace,
        pagDatabasePresent,
        hooks,
        chatIdForPag,
        prevHighlights
      );
      if (cancelled) {
        return;
      }
      setPagGraphBySession((p0) => {
        if (p0[sessionId]?.loadState === "loading" || p0[sessionId] == null) {
          return { ...p0, [sessionId]: snap };
        }
        // concurrent refresh: только если тот же load tick-контур; упрощённо перезаписываем
        return { ...p0, [sessionId]: snap };
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [activeSession.chatId, activeSession.id, pagDefaultNamespace, pagLoadTick, pagNamespaces, projKey, registry, runtimeDir]);

  /**
   * Пока `store.sqlite3` ещё не создан, `pag-slice` даёт `missing_db`; после `ready`+trace
   * периодически повторяем полный load — при появлении БД **подмена** merged срезом + `afterFullLoad`.
   */
  React.useEffect((): (() => void) | void => {
    if (!awaitingPagSqlite) {
      return;
    }
    const sessionId: string = activeSession.id;
    const chatIdPoll: string = activeSession.chatId;
    const slice: unknown = window.ailitDesktop?.pagGraphSlice;
    if (!runtimeDir || typeof slice !== "function" || pagNamespaces.length === 0) {
      return;
    }
    const pollMs: number = desktopConfig?.pag_sqlite_poll_interval_ms ?? 2500;
    const sliceFn: typeof window.ailitDesktop.pagGraphSlice = slice as typeof window.ailitDesktop.pagGraphSlice;
    let cancelled: boolean = false;
    const h: ReturnType<typeof setInterval> = setInterval((): void => {
      void (async (): Promise<void> => {
        const r: Awaited<ReturnType<typeof PagGraphSessionFullLoad.run>> = await PagGraphSessionFullLoad.run(
          (p) => sliceFn(p),
          pagNamespaces
        );
        if (cancelled) {
          return;
        }
        if (!r.ok) {
          setPagGraphBySession((p0) => ({
            ...p0,
            [sessionId]: {
              ...createEmptyPagGraphSessionSnapshot({ loadState: "error" }),
              loadState: "error" as const,
              loadError: r.error
            }
          }));
          return;
        }
        if (r.pagSqliteMissing) {
          return;
        }
        const rows: readonly Record<string, unknown>[] = rawTraceRowsRef.current;
        const rdPoll: string | null = runtimeDir;
        const prevRevsPoll: Readonly<Record<string, number>> =
          pagGraphBySessionRef.current[sessionId]?.graphRevByNamespace ?? {};
        const prevHighlightsPoll = pagGraphBySessionRef.current[sessionId]?.searchHighlightsByNamespace ?? {};
        const hooksPoll: PagGraphTraceMergeEmitHooks | undefined =
          rdPoll != null
            ? buildPagGraphTraceMergeHooks({
                runtimeDir: rdPoll,
                chatId: chatIdPoll,
                sessionId,
                graphRevBeforeByNamespace: { ...prevRevsPoll },
                pagDefaultNamespace,
                reconciledEmitRevByNs: pagGraphLastEmittedReconcileRevRef.current,
                fullLoad: { kind: "poll_retry", namespaces: [...pagNamespaces] },
                traceOnlyPagModeSentKeys: traceOnlyPagModeSentKeysRef.current
              })
            : undefined;
        const snap: PagGraphSessionSnapshot = PagGraphSessionTraceMerge.afterFullLoad(
          r.merged,
          r.graphRevByNamespace,
          rows,
          pagNamespaces,
          pagDefaultNamespace,
          true,
          hooksPoll,
          chatIdPoll,
          prevHighlightsPoll
        );
        if (cancelled) {
          return;
        }
        setPagGraphBySession((p0) => ({ ...p0, [sessionId]: snap }));
      })();
    }, pollMs);
    return (): void => {
      cancelled = true;
      clearInterval(h);
    };
  }, [
    awaitingPagSqlite,
    activeSession.chatId,
    activeSession.id,
    desktopConfig?.pag_sqlite_poll_interval_ms,
    pagDefaultNamespace,
    pagNamespaces,
    projKey,
    registry,
    runtimeDir
  ]);

  React.useEffect((): void => {
    const sessionId: string = activeSession.id;
    const chatIdInc: string = activeSession.chatId;
    const rdInc: string | null = runtimeDir;
    setPagGraphBySession((prev) => {
      const cur: PagGraphSessionSnapshot | undefined = prev[sessionId];
      if (!cur || cur.loadState !== "ready") {
        return prev;
      }
      const hooksInc: PagGraphTraceMergeEmitHooks | undefined =
        rdInc != null
          ? buildPagGraphTraceMergeHooks({
              runtimeDir: rdInc,
              chatId: chatIdInc,
              sessionId,
              graphRevBeforeByNamespace: { ...cur.graphRevByNamespace },
              pagDefaultNamespace,
              reconciledEmitRevByNs: pagGraphLastEmittedReconcileRevRef.current,
              traceOnlyPagModeSentKeys: traceOnlyPagModeSentKeysRef.current
            })
          : undefined;
      const nxt: PagGraphSessionSnapshot = PagGraphSessionTraceMerge.applyIncremental(
        cur,
        rawTraceRows,
        pagNamespaces,
        pagDefaultNamespace,
        hooksInc,
        chatIdInc
      );
      if (nxt === cur) {
        return prev;
      }
      return { ...prev, [sessionId]: nxt };
    });
  }, [
    activeSession.chatId,
    activeSession.id,
    pagDefaultNamespace,
    pagNamespaces,
    rawTraceRows,
    runtimeDir
  ]);

  const pagGraphActive: PagGraphSessionSnapshot | null =
    pagGraphBySession[activeSession.id] ?? null;

  const v: DesktopSessionValue = {
    chatId: activeSession.chatId,
    sessions: ui.sessions,
    activeSessionId: ui.activeSessionId,
    setActiveSessionId,
    setActiveSessionProjectIds,
    toggleProject,
    createNewChatSession,
    renameSession,
    removeSession,
    toolDisplay: ui.toolDisplay,
    setToolDisplay,
    lastAgentPair: ui.lastAgentPair,
    setLastAgentPair,
    connection,
    homeDir,
    desktopConfig,
    runtimeDir,
    supervisorSummary,
    brokerEndpoint,
    lastError,
    registry,
    selectedProjectIds,
    rawTraceRows,
    normalizedRows,
    agentDialogueMessages,
    agentLinkKeys,
    chatLines,
    reconnectAttempt,
    refreshStatus,
    loadProjects,
    connectToBroker,
    sendUserPrompt,
    resubscribeTrace,
    agentTurnInProgress,
    brokerMemoryRecallPhase,
    requestStopAgent,
    permModeLabel,
    permModeGateId,
    submitPermModeChoice,
    toolApproval,
    submitToolApproval,
    contextFill,
    memoryPanelOpen: ui.memoryPanelOpen,
    memoryPanelTab: ui.memoryPanelTab,
    memorySplitRatio: ui.memorySplitRatio,
    setMemoryPanelOpen,
    setMemoryPanelTab,
    setMemorySplitRatio,
    pagGraph: { activeSnapshot: pagGraphActive, refreshPagGraph }
  };

  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export function useOptionalDesktopSession(): DesktopSessionValue | null {
  return React.useContext(Ctx);
}

export function useDesktopSession(): DesktopSessionValue {
  const x: DesktopSessionValue | null = React.useContext(Ctx);
  if (x) {
    return x;
  }
  throw new Error("useDesktopSession: provider missing");
}
