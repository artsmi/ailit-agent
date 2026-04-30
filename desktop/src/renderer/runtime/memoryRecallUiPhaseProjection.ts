import { projectBrokerMemoryRecallActive } from "./chatTraceAmPhase";

/** UC-06 / ТЗ §5.1: фиксированный whitelist (минимум две фразы). */
export const RECALL_UI_PHRASE_WHITELIST: readonly { readonly id: string; readonly text: string }[] = [
  { id: "recall_remembers_v1", text: "Ailit вспоминает" },
  { id: "recall_mind_halls_v1", text: "Ailit в чертогах разума" }
] as const;

/** UC-06 A1: минимальный интервал смены фразы в UI (мс). */
export const RECALL_PHRASE_ROTATION_MS: number = 1500;

/** Допущение ТЗ: акцент синего через токен shell брендбука. */
export const BROKER_MEMORY_RECALL_STYLE_TOKEN = "--candy-code" as const;

export type BrokerMemoryRecallUiPhase = {
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

export function recallPhraseTextAtIndex(phraseIndex: number): string {
  const n: number = RECALL_UI_PHRASE_WHITELIST.length;
  const idx: number = ((phraseIndex % n) + n) % n;
  return RECALL_UI_PHRASE_WHITELIST[idx]?.text ?? "";
}

export function recallPhraseIdAtIndex(phraseIndex: number): string {
  const n: number = RECALL_UI_PHRASE_WHITELIST.length;
  const idx: number = ((phraseIndex % n) + n) % n;
  return RECALL_UI_PHRASE_WHITELIST[idx]?.id ?? "recall_remembers_v1";
}

/**
 * UC-06: проекция broker trace + индекс ротации фраз (индекс задаётся UI-слоем с шагом ≥ RECALL_PHRASE_ROTATION_MS).
 */
export function projectBrokerMemoryRecallPhase(
  rows: readonly Record<string, unknown>[],
  chatId: string,
  phraseIndex: number
): BrokerMemoryRecallUiPhase {
  const active: boolean = projectBrokerMemoryRecallActive(rows, chatId);
  return buildBrokerMemoryRecallUiPhase(active, phraseIndex);
}
