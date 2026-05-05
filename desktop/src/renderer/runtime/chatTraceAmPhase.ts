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
  if (String(pl?.["service"] ?? "") !== "memory.query_context") {
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
 * Производное «AM активен» для UC 2.4: между Work→Memory `memory.query_context`
 * и завершением цикла (`context.memory_injected` | `memory.actor_slice_skipped` | `memory.actor_unavailable`)
 * после ответа памяти; не опирается на `assistant.thinking`.
 *
 * Сброс незавершённой фазы при новом user turn (`user_prompt` в нормализации trace).
 */
export function projectBrokerMemoryRecallActive(rows: readonly Record<string, unknown>[], chatId: string): boolean {
  if (typeof chatId !== "string" || chatId.length === 0) {
    return false;
  }
  let phase: AmRecallPhase = "idle";
  for (const row of rows) {
    if (rowChatId(row) !== chatId) {
      continue;
    }
    const nk = traceNormalizer.normalizeLine(row).kind;
    if (nk === "user_prompt") {
      phase = "idle";
    }
    const topicEv: { readonly eventName: string } | null = readWorkChatTopic(row, chatId);
    if (topicEv) {
      const en: string = topicEv.eventName;
      if (phase === "awaiting_memory_response") {
        if (en === "memory.actor_unavailable") {
          phase = "idle";
        }
      } else if (phase === "awaiting_inject_or_skip") {
        if (
          en === "context.memory_injected" ||
          en === "memory.actor_slice_skipped" ||
          en === "memory.actor_unavailable"
        ) {
          phase = "idle";
        }
      }
    }
    if (isMemoryQueryStart(row, chatId)) {
      phase = "awaiting_memory_response";
    }
    const memClose: "fail" | "ok_with_slice" | "ok_other" | null = memoryResponseClosesAwaiting(row, chatId);
    if (memClose === "fail") {
      if (phase === "awaiting_memory_response" || phase === "awaiting_inject_or_skip") {
        phase = "idle";
      }
    } else if (memClose === "ok_with_slice") {
      if (phase === "awaiting_memory_response") {
        phase = "awaiting_inject_or_skip";
      }
    } else if (memClose === "ok_other") {
      if (phase === "awaiting_memory_response") {
        phase = "idle";
      }
    }
  }
  return phase !== "idle";
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
