/**
 * Локальное хранение списка чат-сессий и последней пары агентов (Команда).
 */
export const PERSISTED_UI_KEY = "ailit.desktop.ui.v1";

const LEGACY_CHAT_ID = "ailit-desktop-1";

export type ChatSessionRecordV1 = {
  readonly id: string;
  /** Идентификатор в broker / trace. */
  readonly chatId: string;
  readonly label: string;
  readonly projectIds: readonly string[];
  readonly createdAt: string;
};

export type LastAgentPairV1 = {
  readonly a: string;
  readonly b: string;
};

/** Как показывать tool.* (batch, exposure, …) в чате; shell/bash обычно оставляем видимыми. */
export type ChatToolDisplayV1 = "normal" | "compact" | "hidden";
export type MemoryPanelTabV1 = "3d" | "journal";

export type PersistedUiStateV1 = {
  readonly version: 1;
  readonly sessions: readonly ChatSessionRecordV1[];
  readonly activeSessionId: string;
  readonly lastAgentPair: LastAgentPairV1 | null;
  readonly toolDisplay: ChatToolDisplayV1;
  readonly memoryPanelOpen: boolean;
  readonly memoryPanelTab: MemoryPanelTabV1;
  readonly memorySplitRatio: number;
};

export function normalizeMemorySplitRatio(raw: unknown): number {
  const n: number = typeof raw === "number" && Number.isFinite(raw) ? raw : 0.5;
  return Math.max(0.28, Math.min(0.72, n));
}

function newId(): string {
  return `s-${globalThis.crypto?.randomUUID?.() ?? String(Date.now())}`;
}

function defaultState(): PersistedUiStateV1 {
  const sid: string = newId();
  return {
    version: 1,
    sessions: [
      {
        id: sid,
        chatId: LEGACY_CHAT_ID,
        label: "Session 1",
        projectIds: [],
        createdAt: new Date().toISOString()
      }
    ],
    activeSessionId: sid,
    lastAgentPair: null,
    toolDisplay: "normal",
    memoryPanelOpen: false,
    memoryPanelTab: "3d",
    memorySplitRatio: 0.5
  };
}

export function loadPersistedUi(): PersistedUiStateV1 {
  try {
    const raw: string | null = localStorage.getItem(PERSISTED_UI_KEY);
    if (!raw) {
      return defaultState();
    }
    const o: unknown = JSON.parse(raw) as unknown;
    if (typeof o !== "object" || o === null) {
      return defaultState();
    }
    const p = o as Partial<PersistedUiStateV1>;
    if (p.version !== 1 || !Array.isArray(p.sessions) || p.sessions.length === 0 || !p.activeSessionId) {
      return defaultState();
    }
    const toolDisplay: ChatToolDisplayV1 =
      p.toolDisplay === "compact" || p.toolDisplay === "hidden" || p.toolDisplay === "normal"
        ? p.toolDisplay
        : "normal";
    const memoryPanelTab: MemoryPanelTabV1 = p.memoryPanelTab === "journal" ? "journal" : "3d";
    return {
      ...p,
      toolDisplay,
      memoryPanelOpen: Boolean(p.memoryPanelOpen),
      memoryPanelTab,
      memorySplitRatio: normalizeMemorySplitRatio(p.memorySplitRatio)
    } as PersistedUiStateV1;
  } catch {
    return defaultState();
  }
}

export function savePersistedUi(state: PersistedUiStateV1): void {
  try {
    localStorage.setItem(PERSISTED_UI_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

export function newChatSession(
  projectIds: readonly string[],
  label: string
): ChatSessionRecordV1 {
  const id: string = newId();
  const chatId: string = `ailit-desk-${globalThis.crypto?.randomUUID?.() ?? String(Date.now())}`;
  return {
    id,
    chatId,
    label,
    projectIds: [...projectIds],
    createdAt: new Date().toISOString()
  };
}
