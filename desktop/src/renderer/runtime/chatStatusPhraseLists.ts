/** Фразы статуса чата: «думает» (AgentWork) и «вспоминает» (ожидание AgentMemory). */

export const CHAT_STATUS_PHRASE_MIN_MS: number = 2000;
export const CHAT_STATUS_PHRASE_MAX_MS: number = 7000;

export type ChatStatusPhraseEntry = {
  readonly id: string;
  readonly text: string;
};

/** Следующий индекс [0, length), не совпадающий с prev (при length > 1). */
export function pickNextPhraseIndex(prev: number, length: number): number {
  if (length <= 1) {
    return 0;
  }
  const p: number = ((prev % length) + length) % length;
  let n: number = Math.floor(Math.random() * (length - 1));
  if (n >= p) {
    n += 1;
  }
  return n;
}

export function randomPhraseRotationDelayMs(): number {
  const span: number = CHAT_STATUS_PHRASE_MAX_MS - CHAT_STATUS_PHRASE_MIN_MS + 1;
  return CHAT_STATUS_PHRASE_MIN_MS + Math.floor(Math.random() * span);
}

/** AgentWork без вызова памяти — короткие варианты строки статуса. */
export const THINKING_UI_PHRASE_WHITELIST: readonly ChatStatusPhraseEntry[] = [
  { id: "think_01", text: "Ailit думает" },
  { id: "think_02", text: "Ailit в раздумье" },
  { id: "think_03", text: "Ailit обдумывает ответ" },
  { id: "think_04", text: "Ailit собирает мысли" },
  { id: "think_05", text: "Ailit прикидывает варианты" },
  { id: "think_06", text: "Ailit настраивает ход" },
  { id: "think_07", text: "Ailit оценивает задачу" },
  { id: "think_08", text: "Ailit выстраивает план" },
  { id: "think_09", text: "Ailit проверяет контекст" },
  { id: "think_10", text: "Ailit уточняет детали" },
  { id: "think_11", text: "Ailit готовит ответ" },
  { id: "think_12", text: "Ailit внимательно читает" },
  { id: "think_13", text: "Ailit сопоставляет факты" },
  { id: "think_14", text: "Ailit ищет лучший ход" },
  { id: "think_15", text: "Ailit держит нить разговора" },
  { id: "think_16", text: "Ailit не спешит" },
  { id: "think_17", text: "Ailit вдумчиво молчит" },
  { id: "think_18", text: "Ailit наводит порядок в мыслях" },
  { id: "think_19", text: "Ailit выбирает формулировки" },
  { id: "think_20", text: "Ailit сверяется с целью" },
  { id: "think_21", text: "Ailit держит фокус" },
  { id: "think_22", text: "Ailit прокручивает варианты" },
  { id: "think_23", text: "Ailit взвешивает шаги" },
  { id: "think_24", text: "Ailit настраивает тон" },
  { id: "think_25", text: "Ailit уточняет рамку задачи" },
  { id: "think_26", text: "Ailit собирает аргументы" },
  { id: "think_27", text: "Ailit проверяет логику" },
  { id: "think_28", text: "Ailit смотрит на цель сверху" },
  { id: "think_29", text: "Ailit чуть замедлился" },
  { id: "think_30", text: "Ailit в рабочем темпе" },
  { id: "think_31", text: "Ailit держит паузу осмысленно" },
  { id: "think_32", text: "Ailit наводит ясность" },
  { id: "think_33", text: "Ailit подбирает слова" },
  { id: "think_34", text: "Ailit структурирует ответ" },
  { id: "think_35", text: "Ailit не теряет нить" },
  { id: "think_36", text: "Ailit в режиме размышления" },
  { id: "think_37", text: "Ailit аккуратно думает" },
  { id: "think_38", text: "Ailit сверяется с запросом" },
  { id: "think_39", text: "Ailit готовит вывод" },
  { id: "think_40", text: "Ailit в процессе размышления" }
] as const;

/** Ожидание ответа AgentMemory после Work→Memory. */
export const RECALL_UI_PHRASE_WHITELIST: readonly ChatStatusPhraseEntry[] = [
  { id: "recall_01", text: "Ailit вспоминает" },
  { id: "recall_02", text: "Ailit обращается к памяти" },
  { id: "recall_03", text: "Ailit ищет в долговременной памяти" },
  { id: "recall_04", text: "Ailit просматривает граф знаний" },
  { id: "recall_05", text: "Ailit подтягивает контекст из PAG" },
  { id: "recall_06", text: "Ailit сверяется с прошлыми сессиями" },
  { id: "recall_07", text: "Ailit собирает релевантные узлы" },
  { id: "recall_08", text: "Ailit прокладывает связи в памяти" },
  { id: "recall_09", text: "Ailit уточняет картину репозитория" },
  { id: "recall_10", text: "Ailit читает память проекта" },
  { id: "recall_11", text: "Ailit достаёт нужные файлы из графа" },
  { id: "recall_12", text: "Ailit сопоставляет цель и память" },
  { id: "recall_13", text: "Ailit обходит релевантные рёбра" },
  { id: "recall_14", text: "Ailit углубляется в контекст" },
  { id: "recall_15", text: "Ailit запрашивает срез памяти" },
  { id: "recall_16", text: "Ailit ждёт ответа памяти" },
  { id: "recall_17", text: "Ailit в режиме recall" },
  { id: "recall_18", text: "Ailit подключает AgentMemory" },
  { id: "recall_19", text: "Ailit синхронизируется с памятью" },
  { id: "recall_20", text: "Ailit обновляет картину данных" },
  { id: "recall_21", text: "Ailit ищет опорные узлы" },
  { id: "recall_22", text: "Ailit проверяет актуальность памяти" },
  { id: "recall_23", text: "Ailit собирает backbone контекста" },
  { id: "recall_24", text: "Ailit наводит мосты к фактам" },
  { id: "recall_25", text: "Ailit вытягивает краткий лист файлов" },
  { id: "recall_26", text: "Ailit уточняет namespace" },
  { id: "recall_27", text: "Ailit сопоставляет цель и граф" },
  { id: "recall_28", text: "Ailit в чертогах разума" },
  { id: "recall_29", text: "Ailit просеивает память" },
  { id: "recall_30", text: "Ailit настраивает retrieval" },
  { id: "recall_31", text: "Ailit держит связь с памятью" },
  { id: "recall_32", text: "Ailit запрашивает контекст у Memory" },
  { id: "recall_33", text: "Ailit обогащает запрос из PAG" },
  { id: "recall_34", text: "Ailit ищет якоря в графе" },
  { id: "recall_35", text: "Ailit подбирает релевантные B-узлы" },
  { id: "recall_36", text: "Ailit проверяет границы памяти" },
  { id: "recall_37", text: "Ailit аккуратно читает store" },
  { id: "recall_38", text: "Ailit собирает подсказки из памяти" },
  { id: "recall_39", text: "Ailit в фазе памяти" },
  { id: "recall_40", text: "Ailit подгружает смысловой слой" }
] as const;
