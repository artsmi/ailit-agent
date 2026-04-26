import React from "react";

import type { ProjectRegistryEntry, RuntimeResponseEnvelope } from "@shared/ipc";

import { DEFAULT_AGENT_MANIFEST_V1 } from "../state/agentManifest";
import {
  loadPersistedUi,
  newChatSession,
  type LastAgentPairV1,
  type ChatSessionRecordV1,
  type ChatToolDisplayV1,
  savePersistedUi,
  type PersistedUiStateV1
} from "../state/persistedUi";
import { buildUserPromptAction } from "./envelopeFactory";
import {
  buildAgentDialogueMessages,
  deriveAgentLinkKeysFromTrace,
  type AgentDialogueMessage
} from "./agentDialogueProjection";
import {
  buildBashLineDelta,
  callIdForBashEvent,
  extractToolEventInner,
  isBashEventName,
  shortToolLine
} from "../components/chat/shellEventFormat";
import { formatTraceProjectionDiagnosticLine } from "./desktopSessionDiagnosticLog";
import { dedupKeyForRow, RuntimeTraceNormalizer, type NormalizedTraceProjection } from "./traceNormalize";
import { newMessageId } from "./uuid";

const GOAL: string = "g-desktop";

type ConnState = "idle" | "connecting" | "ready" | "error";

export type ChatLine = {
  readonly id: string;
  readonly from: "user" | "assistant" | "system";
  readonly text: string;
  readonly atIso: string;
  /** Порядок появления в trace (стабильная сортировка в UI). */
  readonly order: number;
  /** Сообщение-консоль (tool/shell) — рендер как в minimalist candy ref. */
  readonly lineKind?: "message" | "console" | "reasoning";
  readonly consoleShell?: string;
  /** Для console: shell/bash vs служебные tool.* */
  readonly consoleChannel?: "shell" | "tool";
};

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
  readonly requestStopAgent: () => Promise<void>;
};

const Ctx = React.createContext<DesktopSessionValue | null>(null);

function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function nfc(s: string): string {
  return s.normalize("NFC");
}

/** Склейка строки чата: рантайм эмитит `incremental` дельты; `snapshot` — на редких путях. */
function nextStreamLineText(
  mode: NormalizedTraceProjection["textMode"],
  prev: string,
  humanLine: string
): string {
  const m: "incremental" | "snapshot" = mode === "snapshot" ? "snapshot" : "incremental";
  if (m === "snapshot") {
    return nfc(humanLine);
  }
  return nfc(prev) + nfc(humanLine);
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

const normalizer: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();

function chatLineId(kind: "user" | "assistant" | "system", messageId: string): string {
  return `${kind}:${messageId}`;
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
  const [runtimeDir, setRuntimeDir] = React.useState<string | null>(null);
  const [supervisorSummary, setSupervisorSummary] = React.useState<string | null>(null);
  const [brokerEndpoint, setBrokerEndpoint] = React.useState<string | null>(null);
  const [lastError, setLastError] = React.useState<string | null>(null);
  const [registry, setRegistry] = React.useState<readonly ProjectRegistryEntry[]>([]);
  const [rawTraceRows, setRawTraceRows] = React.useState<Record<string, unknown>[]>([]);
  const [chatLines, setChatLines] = React.useState<ChatLine[]>([]);
  const [reconnectAttempt, setReconnectAttempt] = React.useState(0);
  const seenRowKeys: React.MutableRefObject<Set<string>> = React.useRef<Set<string>>(new Set());
  const seenChatIds: React.MutableRefObject<Set<string>> = React.useRef<Set<string>>(new Set());
  const registryWasEmpty: React.MutableRefObject<boolean> = React.useRef(true);
  const subChatIdRef: React.MutableRefObject<string | null> = React.useRef(null);
  const activeChatIdRef: React.MutableRefObject<string> = React.useRef("");
  /**
   * Монотонный «слот» = порядок строки trace (JSONL), в том числе дельт одного turn.
   * `order` у ChatLine = slot первого появления id, обновления сохраняют order.
   */
  const traceEventSeqRef: React.MutableRefObject<number> = React.useRef(0);
  /** Текущая сегментированная «мысль» (тот же user-turn может иметь: мысль → tool → мысль). */
  const openReasoningLineIdRef: React.MutableRefObject<string | null> = React.useRef(null);
  /** Индекс сегмента s0, s1, … внутри trace assistant message_id. */
  const nextReasoningSegRef: React.MutableRefObject<number> = React.useRef(0);
  /**
   * Накопление дельт стрима (reasoning / assistant). Вне state: merge в setChatLines
   * смотрел бы на устаревший found.text; при bulk-replay (connect/resubscribe) дельты
   * накладывались на уже полный текст и давали «Давайтевайте».
   */
  const streamTextAccRef: React.MutableRefObject<Map<string, string>> = React.useRef(new Map());
  /** Склейка bash.* по call_id: без сырого JSON, один блок в ленте. */
  const bashTextByCallRef: React.MutableRefObject<Map<string, string>> = React.useRef(new Map());
  const [agentTurnInProgress, setAgentTurnInProgress] = React.useState(false);

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

  const projectChatFromTrace: (rows: readonly Record<string, unknown>[]) => void = React.useCallback(
    (rows) => {
      const isBulkReplay: boolean = rows.length > 1;
      if (isBulkReplay) {
        streamTextAccRef.current = new Map();
        bashTextByCallRef.current = new Map();
        openReasoningLineIdRef.current = null;
        nextReasoningSegRef.current = 0;
        traceEventSeqRef.current = 0;
        seenChatIds.current = new Set();
        setChatLines([]);
      }
      const closeReasoningSegment: () => void = (): void => {
        if (openReasoningLineIdRef.current !== null) {
          openReasoningLineIdRef.current = null;
          nextReasoningSegRef.current += 1;
        }
      };
      const pushLine: (line: Omit<ChatLine, "order">, slotOrder: number) => void = (line, slotOrder): void => {
        if (seenChatIds.current.has(line.id)) {
          return;
        }
        seenChatIds.current.add(line.id);
        const full: ChatLine = { ...line, order: slotOrder };
        setChatLines((c) => [...c, full]);
      };
      const upsert: (line: Omit<ChatLine, "order">, slotOrder: number) => void = (line, slotOrder): void => {
        if (!seenChatIds.current.has(line.id)) {
          seenChatIds.current.add(line.id);
          setChatLines((c) => [...c, { ...line, order: slotOrder }]);
          return;
        }
        setChatLines((c) =>
          c.map((x) => (x.id === line.id ? { ...line, order: x.order, atIso: line.atIso } : x))
        );
      };
      const rd: string | null = runtimeDir;
      const cid0: string = activeChatIdRef.current;
      const diagnosticLines: string[] = [];
      for (const row of rows) {
        traceEventSeqRef.current += 1;
        const eventSeq: number = traceEventSeqRef.current;
        const n: NormalizedTraceProjection = normalizer.normalizeLine(row);
        diagnosticLines.push(formatTraceProjectionDiagnosticLine(eventSeq, n));
        if (n.kind === "user_prompt") {
          openReasoningLineIdRef.current = null;
          nextReasoningSegRef.current = 0;
          streamTextAccRef.current.clear();
          bashTextByCallRef.current = new Map();
          pushLine(
            {
              id: chatLineId("user", n.messageId),
              from: "user",
              text: n.humanLine,
              atIso: n.createdAt || new Date().toISOString()
            },
            eventSeq
          );
        } else if (n.kind === "assistant_delta") {
          closeReasoningSegment();
          const id: string = chatLineId("assistant", n.messageId);
          const acc: Map<string, string> = streamTextAccRef.current;
          const prevText: string = acc.get(id) ?? "";
          const nextText: string = nextStreamLineText(n.textMode, prevText, n.humanLine);
          acc.set(id, nextText);
          setChatLines((cur) => {
            const found: ChatLine | undefined = cur.find((x) => x.id === id);
            const next: ChatLine = {
              id,
              from: "assistant",
              text: nextText,
              atIso: n.createdAt || new Date().toISOString(),
              order: found ? found.order : eventSeq
            };
            if (!found) {
              seenChatIds.current.add(id);
              return [...cur, next];
            }
            return cur.map((x) => (x.id === id ? next : x));
          });
        } else if (n.kind === "assistant_thinking_delta") {
          const mid: string = n.messageId;
          let lineId: string;
          if (openReasoningLineIdRef.current === null) {
            lineId = `assistant-think:${mid}:s${nextReasoningSegRef.current}`;
            openReasoningLineIdRef.current = lineId;
          } else {
            lineId = openReasoningLineIdRef.current;
          }
          const acc: Map<string, string> = streamTextAccRef.current;
          const prevText: string = acc.get(lineId) ?? "";
          const nextText: string = nextStreamLineText(n.textMode, prevText, n.humanLine);
          acc.set(lineId, nextText);
          setChatLines((cur) => {
            const found: ChatLine | undefined = cur.find((x) => x.id === lineId);
            const next: ChatLine = {
              id: lineId,
              from: "assistant",
              text: nextText,
              atIso: n.createdAt || new Date().toISOString(),
              lineKind: "reasoning",
              order: found ? found.order : eventSeq
            };
            if (!found) {
              seenChatIds.current.add(lineId);
              return [...cur, next];
            }
            return cur.map((x) => (x.id === lineId ? next : x));
          });
        } else if (n.kind === "assistant_final") {
          closeReasoningSegment();
          setAgentTurnInProgress(false);
          const asstId: string = chatLineId("assistant", n.messageId);
          streamTextAccRef.current.set(asstId, nfc(n.humanLine));
          upsert(
            {
              id: asstId,
              from: "assistant",
              text: n.humanLine,
              atIso: n.createdAt || new Date().toISOString()
            },
            eventSeq
          );
        } else if (n.kind === "error_row") {
          setAgentTurnInProgress(false);
          closeReasoningSegment();
          pushLine(
            {
              id: chatLineId("system", n.messageId),
              from: "system",
              text: n.humanLine,
              atIso: n.createdAt || new Date().toISOString()
            },
            eventSeq
          );
        } else if (n.kind === "tool_event") {
          closeReasoningSegment();
          const evName: string = n.humanLine.trim();
          const inner: Record<string, unknown> = extractToolEventInner(n.raw);
          const isShellChannel: boolean = /bash|tool\.(bash|sh)|^bash\./i.test(evName);
          if (isShellChannel && isBashEventName(evName)) {
            const callId: string = callIdForBashEvent(inner, n.messageId);
            const lineId: string = `console:bash:call:${callId}`;
            const prev: string = bashTextByCallRef.current.get(callId) ?? "";
            const { next, didChange }: { next: string; didChange: boolean } = buildBashLineDelta(evName, inner, prev);
            bashTextByCallRef.current.set(callId, next);
            const atIso2: string = n.createdAt || new Date().toISOString();
            if (next.length > 0 && (didChange || !seenChatIds.current.has(lineId))) {
              if (!seenChatIds.current.has(lineId)) {
                seenChatIds.current.add(lineId);
                setChatLines((c) => [
                  ...c,
                  {
                    id: lineId,
                    from: "assistant",
                    text: next,
                    atIso: atIso2,
                    lineKind: "console",
                    consoleShell: "bash",
                    consoleChannel: "shell",
                    order: eventSeq
                  }
                ]);
              } else {
                setChatLines((c) => c.map((x) => (x.id === lineId ? { ...x, text: next, atIso: atIso2 } : x)));
              }
            }
          } else {
            const body: string = shortToolLine(evName, inner) || evName;
            const isShell: boolean = isShellChannel;
            const ch: "shell" | "tool" = isShell ? "shell" : "tool";
            const sh: string = isShell && /bash/i.test(evName) ? "bash" : isShell ? "sh" : "sh";
            pushLine(
              {
                id: `console:${n.messageId}:${evName}`,
                from: "assistant",
                text: body,
                atIso: n.createdAt || new Date().toISOString(),
                lineKind: "console",
                consoleShell: sh,
                consoleChannel: ch
              },
              eventSeq
            );
          }
        }
      }
      if (rd && diagnosticLines.length > 0) {
        const chunk: number = 500;
        for (let i: number = 0; i < diagnosticLines.length; i += chunk) {
          const part: string[] = diagnosticLines.slice(i, i + chunk);
          void window.ailitDesktop.appendSessionDiagnostic({ runtimeDir: rd, chatId: cid0, lines: part });
        }
      }
    },
    [runtimeDir]
  );

  const normalizedRows: NormalizedTraceProjection[] = React.useMemo(
    () => rawTraceRows.map((r) => normalizer.normalizeLine(r)),
    [rawTraceRows]
  );

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
    const byId: Map<string, ProjectRegistryEntry> = new Map(registry.map((e) => [e.projectId, e]));
    const chain: string[] = selectedProjectIds.length ? [...selectedProjectIds] : [];
    if (chain.length === 0 && registry[0]) {
      chain.push(registry[0].projectId);
    }
    const pids: string[] = [];
    for (const id of chain) {
      const ro: ProjectRegistryEntry | undefined = byId.get(id);
      if (ro) {
        pids.push(ro.projectId);
      }
    }
    if (!pids.length) {
      return null;
    }
    const first: ProjectRegistryEntry | undefined = byId.get(pids[0] ?? "");
    if (!first) {
      return null;
    }
    return {
      namespace: first.namespace,
      projectRoot: first.path,
      pids,
      roots: pids.map((pid) => (byId.get(pid) as ProjectRegistryEntry).path) as readonly string[]
    };
  }, [registry, selectedProjectIds]);

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
      projectChatFromTrace(dur.rows);
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
  }, [brokerEndpoint, mergeRows, projectChatFromTrace, runtimeDir]);

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
    const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null = pickWorkspace();
    if (!ws0) {
      setLastError("Нет выбранных проектов. Добавьте проекты (CLI) и создайте диалог.");
      setConnection("error");
      return;
    }
    const created: unknown = await window.ailitDesktop.supervisorCreateOrGetBroker({
      chatId: cid,
      namespace: ws0.namespace,
      projectRoot: ws0.projectRoot
    });
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
      projectChatFromTrace(dur1.rows);
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
  }, [activeSession.chatId, activeSession.id, mergeRows, pickWorkspace, projectChatFromTrace, refreshStatus]);

  React.useEffect(() => {
    void refreshStatus();
    void loadProjects();
  }, [loadProjects, refreshStatus]);

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
    seenChatIds.current = new Set();
    traceEventSeqRef.current = 0;
    openReasoningLineIdRef.current = null;
    nextReasoningSegRef.current = 0;
    streamTextAccRef.current = new Map();
    bashTextByCallRef.current = new Map();
    setAgentTurnInProgress(false);
    setRawTraceRows([]);
    setChatLines([]);
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
      setAgentTurnInProgress(true);
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
      if (!seenChatIds.current.has(userId)) {
        seenChatIds.current.add(userId);
        traceEventSeqRef.current += 1;
        const userOrder: number = traceEventSeqRef.current;
        setChatLines((c) => [
          ...c,
          {
            id: userId,
            from: "user",
            text: t,
            atIso: new Date().toISOString(),
            order: userOrder
          }
        ]);
      }
      const r: { readonly ok: true; readonly response: RuntimeResponseEnvelope } | { readonly ok: false; readonly error: string } =
        await window.ailitDesktop.brokerRequest({ endpoint: ep, request: built.envelope });
      if (!r.ok) {
        setAgentTurnInProgress(false);
        setLastError(r.error);
        return;
      }
      if (!r.response.ok) {
        setAgentTurnInProgress(false);
        const asstIdErr: string = r.response.message_id;
        const errId: string = chatLineId("system", asstIdErr);
        if (!seenChatIds.current.has(errId)) {
          seenChatIds.current.add(errId);
          traceEventSeqRef.current += 1;
          const errOrder: number = traceEventSeqRef.current;
          setChatLines((c) => [
            ...c,
            {
              id: errId,
              from: "system",
              text: `Broker: ${JSON.stringify(r.response.error)}`,
              atIso: r.response.created_at,
              order: errOrder
            }
          ]);
        }
      }
    },
    [activeSession.chatId, brokerEndpoint, pickWorkspace]
  );

  const requestStopAgent: () => Promise<void> = React.useCallback(async () => {
    setAgentTurnInProgress(false);
    openReasoningLineIdRef.current = null;
    const cid: string = activeSession.chatId;
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
  }, [activeSession.chatId, connectToBroker]);

  React.useEffect(() => {
    const offRow: (() => void) | void = window.ailitDesktop.onTraceRow((evt) => {
      if (evt.chatId !== activeChatIdRef.current) {
        return;
      }
      mergeRows([evt.row]);
      projectChatFromTrace([evt.row]);
    });
    const offCh: (() => void) | void = window.ailitDesktop.onTraceChannel((ch) => {
      if (ch.chatId !== activeChatIdRef.current) {
        return;
      }
      if (ch.kind === "error" || ch.kind === "end") {
        void (async () => {
          setReconnectAttempt((a) => a + 1);
          await new Promise((r) => {
            setTimeout(r, 800);
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
  }, [mergeRows, projectChatFromTrace, resubscribeTrace]);

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
    requestStopAgent
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
