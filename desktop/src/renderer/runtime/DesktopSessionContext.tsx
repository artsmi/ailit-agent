import React from "react";

import type { ProjectRegistryEntry, RuntimeResponseEnvelope } from "@shared/ipc";

import { DEFAULT_AGENT_MANIFEST_V1 } from "../state/agentManifest";
import { buildUserPromptAction } from "./envelopeFactory";
import {
  buildAgentDialogueMessages,
  deriveAgentLinkKeysFromTrace,
  type AgentDialogueMessage
} from "./agentDialogueProjection";
import { dedupKeyForRow, RuntimeTraceNormalizer, type NormalizedTraceProjection } from "./traceNormalize";
import { newMessageId } from "./uuid";

const CHAT_ID: string = "ailit-desktop-1";
const GOAL: string = "g-desktop";

type ConnState = "idle" | "connecting" | "ready" | "error";

export type ChatLine = {
  readonly id: string;
  readonly from: "user" | "assistant" | "system";
  readonly text: string;
  readonly atIso: string;
};

export type DesktopSessionValue = {
  readonly chatId: string;
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
  readonly setSelectedProjects: (ids: readonly string[]) => void;
  readonly toggleProject: (projectId: string) => void;
  readonly connectToBroker: () => Promise<void>;
  readonly sendUserPrompt: (text: string) => Promise<void>;
  readonly resubscribeTrace: () => Promise<void>;
};

const Ctx = React.createContext<DesktopSessionValue | null>(null);

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

function extractBroker(r: unknown): { readonly endpoint: string; readonly project_root: string; readonly namespace: string } | null {
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

function pushChatIfNew(
  setChat: React.Dispatch<React.SetStateAction<ChatLine[]>>,
  seen: React.MutableRefObject<Set<string>>,
  line: ChatLine
): void {
  if (seen.current.has(line.id)) {
    return;
  }
  seen.current.add(line.id);
  setChat((c) => [...c, line]);
}

function upsertChatLine(
  setChat: React.Dispatch<React.SetStateAction<ChatLine[]>>,
  seen: React.MutableRefObject<Set<string>>,
  line: ChatLine
): void {
  if (!seen.current.has(line.id)) {
    seen.current.add(line.id);
    setChat((c) => [...c, line]);
    return;
  }
  setChat((c) => c.map((x) => (x.id === line.id ? line : x)));
}

function chatLineId(kind: "user" | "assistant" | "system", messageId: string): string {
  return `${kind}:${messageId}`;
}

export function DesktopSessionProvider({ children }: { readonly children: React.ReactNode }): React.JSX.Element {
  const [connection, setConnection] = React.useState<ConnState>("idle");
  const [runtimeDir, setRuntimeDir] = React.useState<string | null>(null);
  const [supervisorSummary, setSupervisorSummary] = React.useState<string | null>(null);
  const [brokerEndpoint, setBrokerEndpoint] = React.useState<string | null>(null);
  const [lastError, setLastError] = React.useState<string | null>(null);
  const [registry, setRegistry] = React.useState<readonly ProjectRegistryEntry[]>([]);
  const [selectedProjectIds, setSelectedProjectIds] = React.useState<readonly string[]>([]);
  const [rawTraceRows, setRawTraceRows] = React.useState<Record<string, unknown>[]>([]);
  const [chatLines, setChatLines] = React.useState<ChatLine[]>([]);
  const [reconnectAttempt, setReconnectAttempt] = React.useState(0);
  const seenRowKeys: React.MutableRefObject<Set<string>> = React.useRef<Set<string>>(new Set());
  const seenChatIds: React.MutableRefObject<Set<string>> = React.useRef<Set<string>>(new Set());
  const registryWasEmpty: React.MutableRefObject<boolean> = React.useRef(true);

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
      for (const row of rows) {
        const n: NormalizedTraceProjection = normalizer.normalizeLine(row);
        if (n.kind === "user_prompt") {
          pushChatIfNew(setChatLines, seenChatIds, {
            id: chatLineId("user", n.messageId),
            from: "user",
            text: n.humanLine,
            atIso: n.createdAt || new Date().toISOString()
          });
        } else if (n.kind === "assistant_delta") {
          const id = chatLineId("assistant", n.messageId);
          setChatLines((cur) => {
            const found = cur.find((x) => x.id === id);
            const prevText = found ? found.text : "";
            const next: ChatLine = {
              id,
              from: "assistant",
              text: prevText + n.humanLine,
              atIso: n.createdAt || new Date().toISOString()
            };
            if (!seenChatIds.current.has(id)) {
              seenChatIds.current.add(id);
              return [...cur, next];
            }
            return cur.map((x) => (x.id === id ? next : x));
          });
        } else if (n.kind === "assistant_final") {
          upsertChatLine(setChatLines, seenChatIds, {
            id: chatLineId("assistant", n.messageId),
            from: "assistant",
            text: n.humanLine,
            atIso: n.createdAt || new Date().toISOString()
          });
        } else if (n.kind === "error_row") {
          pushChatIfNew(setChatLines, seenChatIds, {
            id: chatLineId("system", n.messageId),
            from: "system",
            text: n.humanLine,
            atIso: n.createdAt || new Date().toISOString()
          });
        }
      }
    },
    []
  );

  const normalizedRows: NormalizedTraceProjection[] = React.useMemo(
    () => rawTraceRows.map((r) => normalizer.normalizeLine(r)),
    [rawTraceRows]
  );

  const agentDialogueMessages: readonly AgentDialogueMessage[] = React.useMemo(
    () => buildAgentDialogueMessages(rawTraceRows, DEFAULT_AGENT_MANIFEST_V1, selectedProjectIds),
    [rawTraceRows, selectedProjectIds]
  );

  const agentLinkKeys = React.useMemo(
    () => deriveAgentLinkKeysFromTrace(rawTraceRows),
    [rawTraceRows]
  );

  const refreshStatus: () => Promise<void> = React.useCallback(async () => {
    const st: unknown = await window.ailitDesktop.supervisorStatus();
    setRuntimeDir(getRuntimeDirFromStatus(st));
    setSupervisorSummary(JSON.stringify(st, null, 0).slice(0, 2000));
  }, []);

  const loadProjects: () => Promise<void> = React.useCallback(async () => {
    const res: Awaited<ReturnType<typeof window.ailitDesktop.projectRegistryList>> = await window.ailitDesktop.projectRegistryList({});
    if (res.ok) {
      setRegistry(res.entries);
      setSelectedProjectIds((prev) => {
        if (prev.length) {
          return prev;
        }
        const act: string[] = res.entries.filter((e) => e.active).map((e) => e.projectId);
        if (act.length) {
          return act;
        }
        return res.entries[0] ? [res.entries[0].projectId] : [];
      });
    }
  }, []);

  const pickWorkspace: () => { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null = React.useCallback(() => {
    const byId: Map<string, ProjectRegistryEntry> = new Map(registry.map((e) => [e.projectId, e]));
    const chain: string[] = selectedProjectIds.length ? [...selectedProjectIds] : registry.filter((e) => e.active).map((e) => e.projectId);
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
      roots: pids.map((pid) => byId.get(pid)!.path) as readonly string[]
    };
  }, [registry, selectedProjectIds]);

  const resubscribeTrace: () => Promise<void> = React.useCallback(async () => {
    if (!brokerEndpoint || !runtimeDir) {
      return;
    }
    await window.ailitDesktop.traceUnsubscribe({ chatId: CHAT_ID });
    const dur: Awaited<ReturnType<typeof window.ailitDesktop.traceReadDurable>> = await window.ailitDesktop.traceReadDurable({ runtimeDir, chatId: CHAT_ID });
    if (dur.ok) {
      mergeRows(dur.rows);
      projectChatFromTrace(dur.rows);
    }
    const sub: { readonly ok: true } | { readonly ok: false; readonly error: string } = await window.ailitDesktop.traceSubscribe({ chatId: CHAT_ID, endpoint: brokerEndpoint });
    if (!sub.ok) {
      setLastError(sub.error);
      setConnection("error");
    } else {
      setConnection("ready");
    }
  }, [brokerEndpoint, mergeRows, projectChatFromTrace, runtimeDir]);

  const connectToBroker: () => Promise<void> = React.useCallback(async () => {
    setConnection("connecting");
    setLastError(null);
    await refreshStatus();
    const st0: unknown = await window.ailitDesktop.supervisorStatus();
    const rd0: string | null = getRuntimeDirFromStatus(st0);
    if (rd0) {
      setRuntimeDir(rd0);
    }
    const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null = pickWorkspace();
    if (!ws0) {
      setLastError("Нет выбранных проектов: `ailit project add`, затем выбор в «Проекты»/чате.");
      setConnection("error");
      return;
    }
    const created: unknown = await window.ailitDesktop.supervisorCreateOrGetBroker({
      chatId: CHAT_ID,
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
      setLastError("Не удалось получить runtime_dir из status.");
      return;
    }
    setRuntimeDir(rd1);
    const dur1: Awaited<ReturnType<typeof window.ailitDesktop.traceReadDurable>> = await window.ailitDesktop.traceReadDurable({ runtimeDir: rd1, chatId: CHAT_ID });
    if (dur1.ok) {
      mergeRows(dur1.rows);
      projectChatFromTrace(dur1.rows);
    }
    const sub1: { readonly ok: true } | { readonly ok: false; readonly error: string } = await window.ailitDesktop.traceSubscribe({ chatId: CHAT_ID, endpoint: br.endpoint });
    if (!sub1.ok) {
      setLastError(sub1.error);
      setConnection("error");
      return;
    }
    setConnection("ready");
  }, [mergeRows, pickWorkspace, projectChatFromTrace, refreshStatus]);

  React.useEffect(() => {
    void refreshStatus();
    void loadProjects();
  }, [loadProjects, refreshStatus]);

  React.useEffect(() => {
    if (registry.length > 0 && registryWasEmpty.current) {
      registryWasEmpty.current = false;
      void connectToBroker();
    }
    if (registry.length === 0) {
      registryWasEmpty.current = true;
    }
  }, [connectToBroker, registry.length]);

  const sendUserPrompt: (text: string) => Promise<void> = React.useCallback(
    async (text) => {
      const t: string = text.trim();
      if (!t) {
        return;
      }
      const ep: string | null = brokerEndpoint;
      if (!ep) {
        setLastError("Нет endpoint broker-а. Запустите supervisor и дождитесь connect.");
        return;
      }
      const ws0: { namespace: string; projectRoot: string; pids: string[]; roots: readonly string[] } | null = pickWorkspace();
      if (!ws0) {
        setLastError("Нет выбранных проектов.");
        return;
      }
      const built: ReturnType<typeof buildUserPromptAction> = buildUserPromptAction({
        chatId: CHAT_ID,
        brokerId: `broker-${CHAT_ID}`,
        namespace: ws0.namespace,
        goalId: GOAL,
        traceId: newMessageId(),
        prompt: t,
        workspace: { projectIds: ws0.pids, projectRoots: [...ws0.roots] }
      });
      pushChatIfNew(setChatLines, seenChatIds, {
        id: chatLineId("user", built.messageId),
        from: "user",
        text: t,
        atIso: new Date().toISOString()
      });
      const r: { readonly ok: true; readonly response: RuntimeResponseEnvelope } | { readonly ok: false; readonly error: string } = await window.ailitDesktop.brokerRequest({ endpoint: ep, request: built.envelope });
      if (!r.ok) {
        setLastError(r.error);
        return;
      }
      if (!r.response.ok) {
        const asstIdErr: string = r.response.message_id;
        const errLine: ChatLine = {
          id: chatLineId("system", asstIdErr),
          from: "system",
          text: `Broker: ${JSON.stringify(r.response.error)}`,
          atIso: r.response.created_at
        };
        pushChatIfNew(setChatLines, seenChatIds, errLine);
        return;
      }
      // Успех: не дублируем JSON ack в чате — ответ идёт из trace (assistant.delta / final).
    },
    [brokerEndpoint, pickWorkspace]
  );

  React.useEffect(() => {
    const offRow: (() => void) | void = window.ailitDesktop.onTraceRow((evt) => {
      if (evt.chatId !== CHAT_ID) {
        return;
      }
      mergeRows([evt.row]);
      projectChatFromTrace([evt.row]);
    });
    const offCh: (() => void) | void = window.ailitDesktop.onTraceChannel((ch) => {
      if (ch.chatId !== CHAT_ID) {
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

  const setSelectedProjects = React.useCallback((ids: readonly string[]) => {
    setSelectedProjectIds(ids);
  }, []);

  const toggleProject: (projectId: string) => void = React.useCallback((projectId) => {
    setSelectedProjectIds((cur) => {
      const s: Set<string> = new Set(cur);
      if (s.has(projectId)) {
        s.delete(projectId);
      } else {
        s.add(projectId);
      }
      return [...s];
    });
  }, []);

  const v: DesktopSessionValue = {
    chatId: CHAT_ID,
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
    setSelectedProjects,
    toggleProject,
    connectToBroker,
    sendUserPrompt,
    resubscribeTrace
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
