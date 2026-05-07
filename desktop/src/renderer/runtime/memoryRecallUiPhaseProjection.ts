import { projectBrokerMemoryRecallActive } from "./chatTraceAmPhase";
import {
  CHAT_STATUS_PHRASE_MAX_MS,
  CHAT_STATUS_PHRASE_MIN_MS,
  RECALL_UI_PHRASE_WHITELIST,
  THINKING_UI_PHRASE_WHITELIST,
  type ChatStatusPhraseEntry
} from "./chatStatusPhraseLists";

export type { ChatStatusPhraseEntry };

/** @deprecated Используйте CHAT_STATUS_PHRASE_MIN_MS / CHAT_STATUS_PHRASE_MAX_MS. */
export const RECALL_PHRASE_ROTATION_MS: number = CHAT_STATUS_PHRASE_MIN_MS;

export { RECALL_UI_PHRASE_WHITELIST, THINKING_UI_PHRASE_WHITELIST };

/** Допущение ТЗ: акцент синего через токен shell брендбука. */
export const BROKER_MEMORY_RECALL_STYLE_TOKEN = "--candy-code" as const;

export type BrokerMemoryRecallUiPhase = {
  readonly active: boolean;
  readonly phraseIndex: number;
  readonly styleToken: typeof BROKER_MEMORY_RECALL_STYLE_TOKEN;
};

export type BrokerAgentThinkingUiPhase = {
  readonly active: boolean;
  readonly phraseIndex: number;
  readonly styleToken: typeof BROKER_MEMORY_RECALL_STYLE_TOKEN;
};

export function buildBrokerMemoryRecallUiPhase(
  active: boolean,
  phraseIndex: number
): BrokerMemoryRecallUiPhase {
  const n: number = RECALL_UI_PHRASE_WHITELIST.length;
  const idx: number = active ? ((phraseIndex % n) + n) % n : 0;
  return {
    active,
    phraseIndex: idx,
    styleToken: BROKER_MEMORY_RECALL_STYLE_TOKEN
  };
}

export function buildBrokerAgentThinkingUiPhase(
  active: boolean,
  phraseIndex: number
): BrokerAgentThinkingUiPhase {
  const n: number = THINKING_UI_PHRASE_WHITELIST.length;
  const idx: number = active ? ((phraseIndex % n) + n) % n : 0;
  return {
    active,
    phraseIndex: idx,
    styleToken: BROKER_MEMORY_RECALL_STYLE_TOKEN
  };
}

export function recallPhraseTextAtIndex(phraseIndex: number): string {
  const n: number = RECALL_UI_PHRASE_WHITELIST.length;
  const idx: number = ((phraseIndex % n) + n) % n;
  return RECALL_UI_PHRASE_WHITELIST[idx]?.text ?? "";
}

export function recallPhraseIdAtIndex(phraseIndex: number): string {
  const n: number = RECALL_UI_PHRASE_WHITELIST.length;
  const idx: number = ((phraseIndex % n) + n) % n;
  return RECALL_UI_PHRASE_WHITELIST[idx]?.id ?? "recall_01";
}

export function thinkingPhraseTextAtIndex(phraseIndex: number): string {
  const n: number = THINKING_UI_PHRASE_WHITELIST.length;
  const idx: number = ((phraseIndex % n) + n) % n;
  return THINKING_UI_PHRASE_WHITELIST[idx]?.text ?? "";
}

export function thinkingPhraseIdAtIndex(phraseIndex: number): string {
  const n: number = THINKING_UI_PHRASE_WHITELIST.length;
  const idx: number = ((phraseIndex % n) + n) % n;
  return THINKING_UI_PHRASE_WHITELIST[idx]?.id ?? "think_01";
}

/**
 * UC-06: проекция broker trace + индекс ротации фраз (случайный интервал 2–7 с задаётся в DesktopSessionContext).
 */
export function projectBrokerMemoryRecallPhase(
  rows: readonly Record<string, unknown>[],
  chatId: string,
  phraseIndex: number
): BrokerMemoryRecallUiPhase {
  const active: boolean = projectBrokerMemoryRecallActive(rows, chatId);
  return buildBrokerMemoryRecallUiPhase(active, phraseIndex);
}

export { CHAT_STATUS_PHRASE_MIN_MS, CHAT_STATUS_PHRASE_MAX_MS };
