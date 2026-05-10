import { readChatTopicEvent } from "./chatTraceProjector";
import { RuntimeTraceNormalizer } from "./traceNormalize";

const traceNormalizer: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();

type AmRecallPhase = "idle" | "awaiting_memory_response" | "awaiting_inject_or_skip";

function strField(row: Record<string, unknown>, key: string): string {
  const v: unknown = row[key];
  return typeof v === "string" ? v : v === null || v === undefined ? "" : String(v);
}

function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function rowChatId(row: Record<string, unknown>): string {
  return strField(row, "chat_id");
}

/** UC-03 / C-HL-1: старт `memory.query_context` от Work к AgentMemory (anchor architecture §Highlight gating). */
export function isMemoryQueryStart(row: Record<string, unknown>, chatId: string): boolean {
  if (rowChatId(row) !== chatId) {
    return false;
  }
  if (strField(row, "type") !== "service.request") {
    return false;
  }
  if (strField(row, "from_agent") !== `AgentWork:${chatId}`) {
    return false;
  }
  const toAgent: string = strField(row, "to_agent");
  if (!toAgent.startsWith("AgentMemory:")) {
    return false;
  }
  const pl: Record<string, unknown> | null = asDict(row["payload"]);
  if (!pl) {
    return false;
  }
  return String(pl["service"] ?? "") === "memory.query_context";
}

function isMemoryToWorkServiceRow(row: Record<string, unknown>, chatId: string): boolean {
  if (rowChatId(row) !== chatId) {
    return false;
  }
  if (strField(row, "type") !== "service.request") {
    return false;
  }
  const from: string = strField(row, "from_agent");
  if (!from.startsWith("AgentMemory:")) {
    return false;
  }
  return strField(row, "to_agent") === `AgentWork:${chatId}`;
}

/**
 * C1: ответ `memory.query_context` Memory→Work в проде может не повторять `payload.service`
 * (есть только `memory_slice` / `agent_memory_result`).
 */
function isMemoryQueryContextResponsePayload(pl: Record<string, unknown> | null): boolean {
  if (pl == null) {
    return false;
  }
  if (String(pl["service"] ?? "") === "memory.query_context") {
    return true;
  }
  const slice: unknown = pl["memory_slice"];
  if (slice && typeof slice === "object" && !Array.isArray(slice)) {
    return true;
  }
  const amr: unknown = pl["agent_memory_result"];
  if (amr && typeof amr === "object" && !Array.isArray(amr)) {
    return true;
  }
  return false;
}

function readWorkChatTopic(
  row: Record<string, unknown>,
  chatId: string
): { readonly eventName: string } | null {
  if (rowChatId(row) !== chatId) {
    return null;
  }
  if (strField(row, "from_agent") !== `AgentWork:${chatId}`) {
    return null;
  }
  const ev: ReturnType<typeof readChatTopicEvent> = readChatTopicEvent(row);
  if (!ev) {
    return null;
  }
  return { eventName: ev.eventName };
}

function memoryResponseClosesAwaiting(
  row: Record<string, unknown>,
  chatId: string
): "fail" | "ok_with_slice" | "ok_other" | null {
  if (!isMemoryToWorkServiceRow(row, chatId)) {
    return null;
  }
  const pl: Record<string, unknown> | null = asDict(row["payload"]);
  if (!isMemoryQueryContextResponsePayload(pl)) {
    return null;
  }
  const ok: unknown = row["ok"];
  if (typeof ok !== "boolean") {
    return null;
  }
  if (!ok) {
    return "fail";
  }
  const slice: unknown = pl?.["memory_slice"];
  if (slice && typeof slice === "object" && !Array.isArray(slice)) {
    return "ok_with_slice";
  }
  return "ok_other";
}

/**
 * Финальное событие ответа памяти к Work: envelope `service.request` Memory→Work
 * или строка audit с `event=memory.response`, `topic=to_agent_work`, `service=memory.query_context`.
 */
export function isMemoryQueryContextResponseToWorkForUi(
  row: Record<string, unknown>,
  chatId: string
): boolean {
  if (rowChatId(row) !== chatId) {
    return false;
  }
  if (memoryResponseClosesAwaiting(row, chatId) !== null) {
    return true;
  }
  const ev: string = strField(row, "event");
  if (ev === "memory.response") {
    return (
      strField(row, "topic") === "to_agent_work" && strField(row, "service") === "memory.query_context"
    );
  }
  return false;
}

type MemoryWaitUiPhase = "idle" | "awaiting_memory";

/**
 * Строка статуса «Ailit вспоминает»: между Work→Memory `memory.query_context` и ответом Memory→Work
 * (`memory.response` / envelope с `ok`); UC-03 подсветка — отдельно {@link isUc03HighlightAllowedAtRowIndex}.
 *
 * Сброс при `user_prompt`, `memory.actor_unavailable` от Work во время ожидания, и при ответе памяти.
 */
export function projectBrokerMemoryRecallActive(rows: readonly Record<string, unknown>[], chatId: string): boolean {
  if (typeof chatId !== "string" || chatId.length === 0) {
    return false;
  }
  let phase: MemoryWaitUiPhase = "idle";
  for (const row of rows) {
    if (rowChatId(row) !== chatId) {
      continue;
    }
    const nk = traceNormalizer.normalizeLine(row).kind;
    if (nk === "user_prompt") {
      phase = "idle";
    }
    const topicEv: { readonly eventName: string } | null = readWorkChatTopic(row, chatId);
    if (topicEv && phase === "awaiting_memory") {
      if (topicEv.eventName === "memory.actor_unavailable") {
        phase = "idle";
      }
    }
    if (isMemoryQueryStart(row, chatId)) {
      phase = "awaiting_memory";
    }
    if (isMemoryQueryContextResponseToWorkForUi(row, chatId)) {
      phase = "idle";
    }
  }
  return phase === "awaiting_memory";
}

/**
 * UC-03 / C-HL-1: подсветка разрешена на строке `rowIndex`, если (recall окно открыто) ∧ (цикл открыт триггером A или B).
 * Порядок обработки строк совпадает с {@link projectBrokerMemoryRecallActive}.
 */
export function isUc03HighlightAllowedAtRowIndex(
  rows: readonly Record<string, unknown>[],
  chatId: string,
  rowIndex: number
): boolean {
  if (typeof chatId !== "string" || chatId.length === 0 || rowIndex < 0 || rowIndex >= rows.length) {
    return false;
  }
  let phase: AmRecallPhase = "idle";
  let cycleEligible: boolean = false;
  let seenFirstMemoryQuery: boolean = false;
  let pendingBTrigger: boolean = false;

  const goIdle = (): void => {
    phase = "idle";
    cycleEligible = false;
  };

  for (let j: number = 0; j <= rowIndex; j += 1) {
    const row: Record<string, unknown> = rows[j]! as Record<string, unknown>;
    if (rowChatId(row) !== chatId) {
      continue;
    }
    const nk = traceNormalizer.normalizeLine(row).kind;
    if (nk === "user_prompt") {
      goIdle();
      pendingBTrigger = true;
    }
    const topicEv: { readonly eventName: string } | null = readWorkChatTopic(row, chatId);
    if (topicEv) {
      const en: string = topicEv.eventName;
      if (phase === "awaiting_memory_response") {
        if (en === "memory.actor_unavailable") {
          goIdle();
        }
      } else if (phase === "awaiting_inject_or_skip") {
        if (
          en === "context.memory_injected" ||
          en === "memory.actor_slice_skipped" ||
          en === "memory.actor_unavailable"
        ) {
          goIdle();
        }
      }
    }
    if (isMemoryQueryStart(row, chatId)) {
      const triggerA: boolean = !seenFirstMemoryQuery;
      const triggerB: boolean = pendingBTrigger;
      seenFirstMemoryQuery = true;
      pendingBTrigger = false;
      cycleEligible = triggerA || triggerB;
      phase = "awaiting_memory_response";
    }
    const memClose: "fail" | "ok_with_slice" | "ok_other" | null = memoryResponseClosesAwaiting(row, chatId);
    if (memClose === "fail") {
      if (phase === "awaiting_memory_response" || phase === "awaiting_inject_or_skip") {
        goIdle();
      }
    } else if (memClose === "ok_with_slice") {
      if (phase === "awaiting_memory_response") {
        phase = "awaiting_inject_or_skip";
      }
    } else if (memClose === "ok_other") {
      if (phase === "awaiting_memory_response") {
        goIdle();
      }
    }
  }
  return phase !== "idle" && cycleEligible;
}
