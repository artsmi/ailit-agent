import type { AgentManifestV1 } from "../state/agentManifest";
import { agentTypeFromRef, displayLabelForRef } from "../state/agentManifest";

export type AgentDialogueSeverity = "info" | "warning" | "error";

/**
 * Проекция trace row → `ailit_desktop_trace_projection_v1` (G9.7.2).
 */
export type AgentDialogueMessage = {
  readonly kind: "agent_dialogue_message";
  readonly chatId: string;
  readonly projectIds: readonly string[];
  readonly fromAgent: string;
  readonly toAgent: string;
  readonly fromDisplay: string;
  readonly toDisplay: string;
  readonly humanText: string;
  readonly technicalSummary: string;
  readonly severity: AgentDialogueSeverity;
  readonly rawRef: { readonly traceId: string; readonly messageId: string };
  readonly createdAt: string;
  readonly raw: Record<string, unknown>;
};

function strField(row: Record<string, unknown>, key: string): string {
  const v: unknown = row[key];
  if (typeof v === "string") {
    return v;
  }
  if (v === null || v === undefined) {
    return "";
  }
  return String(v);
}

function isResponseRow(row: Record<string, unknown>): boolean {
  return typeof row["ok"] === "boolean" && "payload" in row;
}

function payloadObj(row: Record<string, unknown>): Record<string, unknown> {
  const p: unknown = row["payload"];
  if (p && typeof p === "object" && !Array.isArray(p)) {
    return p as Record<string, unknown>;
  }
  return {};
}

function isSkippableUserOnly(row: Record<string, unknown>, typ: string): boolean {
  const from: string = strField(row, "from_agent");
  if (from.startsWith("User:") || from === "User:desktop") {
    if (typ === "action.start" || typ === "action.end") {
      return true;
    }
  }
  return false;
}

/**
 * Построить список человекочитаемых реплик между агентами (без user-only строк).
 */
export function buildAgentDialogueMessages(
  rows: readonly Record<string, unknown>[],
  manifest: AgentManifestV1,
  projectIds: readonly string[]
): readonly AgentDialogueMessage[] {
  const out: AgentDialogueMessage[] = [];
  for (const row of rows) {
    const msg: AgentDialogueMessage | null = rowToDialogueMessage(row, manifest, projectIds);
    if (msg) {
      out.push(msg);
    }
  }
  return out.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export function rowToDialogueMessage(
  row: Record<string, unknown>,
  manifest: AgentManifestV1,
  projectIds: readonly string[]
): AgentDialogueMessage | null {
  const typ: string = strField(row, "type");
  if (isSkippableUserOnly(row, typ)) {
    return null;
  }
  if (isResponseRow(row)) {
    return fromResponseRow(row, manifest, projectIds);
  }
  if (typ === "service.request" || typ === "topic.publish") {
    return fromRequestLikeRow(row, typ, manifest, projectIds);
  }
  if (typ === "action.start") {
    return fromActionStartRow(row, manifest, projectIds);
  }
  return null;
}

function fromActionStartRow(
  row: Record<string, unknown>,
  manifest: AgentManifestV1,
  projectIds: readonly string[]
): AgentDialogueMessage | null {
  const to: string = strField(row, "to_agent");
  if (!to || to === "null") {
    return null;
  }
  if (!to.startsWith("Agent")) {
    return null;
  }
  const pl: Record<string, unknown> = payloadObj(row);
  const action: string = String(pl["action"] ?? "");
  if (action === "work.handle_user_prompt") {
    const from: string = strField(row, "from_agent");
    return mk(
      row,
      manifest,
      projectIds,
      {
        fromAgent: from,
        toAgent: to,
        humanText: "Передаю пользовательский запрос в агент исполнения (Work), чтобы тот дальше взаимодействовал с памятью и инструментами.",
        technical: `action.start work.handle_user_prompt`,
        sev: "info"
      }
    );
  }
  return null;
}

function fromRequestLikeRow(
  row: Record<string, unknown>,
  typ: string,
  manifest: AgentManifestV1,
  projectIds: readonly string[]
): AgentDialogueMessage | null {
  const from: string = strField(row, "from_agent");
  const to: string = strField(row, "to_agent");
  if (!to || to === "null" || to === '""') {
    return null;
  }
  const toT: string = agentTypeFromRef(to);
  if (!toT.startsWith("Agent")) {
    return null;
  }
  const pl: Record<string, unknown> = payloadObj(row);
  const service: string = String(pl["service"] ?? "");
  if (typ === "service.request" && service === "memory.query_context") {
    const path: string = String(pl["path"] ?? pl["hint_path"] ?? "");
    const level: string = pl["level"] != null ? String(pl["level"]) : "";
    const topK: string = pl["top_k"] != null ? String(pl["top_k"]) : "";
    const parts: string[] = [];
    if (path) {
      parts.push(`файл/путь «${path}»`);
    }
    if (level) {
      parts.push(`уровень ${level}`);
    }
    if (topK) {
      parts.push(`top_k=${topK}`);
    }
    const detail: string = parts.length ? ` (${parts.join(", ")})` : "";
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: `Нужен релевантный контекст в PAG${detail}. Проверь граф и предложи точки чтения.`,
      technical: `service.request memory.query_context${path ? ` path=${path}` : ""}`,
      sev: "info"
    });
  }
  if (typ === "topic.publish") {
    const topic: string = String(pl["topic"] ?? pl["event_name"] ?? "");
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: topic
        ? `Событие в канале: ${topic}.`
        : "Публикация события в topic-канал.",
      technical: `topic.publish ${topic || "?"}`,
      sev: "info"
    });
  }
  return null;
}

function fromResponseRow(
  row: Record<string, unknown>,
  manifest: AgentManifestV1,
  projectIds: readonly string[]
): AgentDialogueMessage | null {
  const from: string = strField(row, "from_agent");
  const to: string = strField(row, "to_agent");
  const pl: Record<string, unknown> = payloadObj(row);
  const action: string = String(pl["action"] ?? "");
  const ok: boolean = Boolean((row as { ok?: boolean }).ok);
  if (action === "work.handle_user_prompt" && ok) {
    if (!to) {
      return null;
    }
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: "Work подтвердил приём пользовательского запроса; дальше — шаги по цели и обращения к памяти.",
      technical: `ack work.handle_user_prompt action_id=${String(pl["action_id"] ?? "")}`,
      sev: "info"
    });
  }
  if (pl["grants"] && Array.isArray(pl["grants"]) && (pl["grants"] as unknown[]).length) {
    if (!ok) {
      return mk(row, manifest, projectIds, {
        fromAgent: from,
        toAgent: to,
        humanText: fromError(row, pl),
        technical: "MemoryGrant / response error",
        sev: "error"
      });
    }
    const paths: string[] = [];
    for (const g of pl["grants"] as readonly unknown[]) {
      if (g && typeof g === "object" && g !== null && "path" in (g as object)) {
        const p2: string = String((g as { path?: string }).path ?? "");
        if (p2) {
          paths.push(p2);
        }
      }
    }
    const pathLine: string =
      paths.length > 0
        ? ` Файлы: ${paths.slice(0, 6).join(", ")}${paths.length > 6 ? "…" : ""}.`
        : "";
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: `Память выдала grant на чтение.${pathLine}`.trim(),
      technical: "MemoryGrant (response)",
      sev: "info"
    });
  }
  if (!ok) {
    if (!to && !from) {
      return null;
    }
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: fromError(row, pl),
      technical: "runtime error / failed response",
      sev: "error"
    });
  }
  if (pl["message"] && String(pl["message"]).toLowerCase().includes("unavailable")) {
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: "Сервис памяти временно недоступен; без «тихого» сырого чтения — проверьте PAG index и рантайм.",
      technical: "memory_unavailable (payload heuristics)",
      sev: "error"
    });
  }
  if (strField(row, "type") === "service.request" && String(pl["service"] ?? "") === "memory.query_context" && !ok) {
    return mk(row, manifest, projectIds, {
      fromAgent: from,
      toAgent: to,
      humanText: fromError(row, pl),
      technical: "memory.query_context failed",
      sev: "error"
    });
  }
  return null;
}

function fromError(row: Record<string, unknown>, pl: Record<string, unknown>): string {
  const er: unknown = (row as { error?: unknown }).error;
  if (er && typeof er === "object" && !Array.isArray(er)) {
    const code: string = String((er as { code?: string }).code ?? "");
    const message: string = String((er as { message?: string }).message ?? "");
    if (code || message) {
      if (code === "timeout" || message.toLowerCase().includes("timeout")) {
        return "Тайм-аут: ответ агента не пришёл в срок. Повторите запрос или снизьте нагрузку.";
      }
      return `Ошибка: ${[code, message].filter(Boolean).join(" — ")}`;
    }
  }
  const pMsg: string = String(pl["message"] ?? pl["error"] ?? "");
  if (pMsg.toLowerCase().includes("unavailable") || pMsg.toLowerCase().includes("memory")) {
    return "Память/контекст сейчас недоступны; сначала индексация или статус рантайма.";
  }
  return "Сбой в ответе агента. Подробности в технической строке и в раскрытом JSON.";
}

function mk(
  row: Record<string, unknown>,
  manifest: AgentManifestV1,
  projectIds: readonly string[],
  p: { readonly fromAgent: string; readonly toAgent: string; readonly humanText: string; readonly technical: string; readonly sev: AgentDialogueSeverity }
): AgentDialogueMessage {
  const fDisp: string = displayLabelForRef(manifest, p.fromAgent).displayName;
  const tDisp: string = displayLabelForRef(manifest, p.toAgent).displayName;
  return {
    kind: "agent_dialogue_message",
    chatId: strField(row, "chat_id"),
    projectIds: [...projectIds],
    fromAgent: p.fromAgent,
    toAgent: p.toAgent,
    fromDisplay: fDisp,
    toDisplay: tDisp,
    humanText: p.humanText,
    technicalSummary: p.technical,
    severity: p.sev,
    rawRef: { traceId: strField(row, "trace_id"), messageId: strField(row, "message_id") || "?" },
    createdAt: strField(row, "created_at") || new Date().toISOString(),
    raw: row
  };
}

/**
 * Пары (тип → тип) из trace для секции «текущие агенты / связи».
 */
export type AgentLinkKey = { readonly fromType: string; readonly toType: string };

export function endpointTypeForLink(ref: string): string {
  if (ref.startsWith("client:") || ref.startsWith("Client:")) {
    return "Broker";
  }
  return agentTypeFromRef(ref);
}

/**
 * Сообщение относится к выбранной паре (двунаправлено). Пустые/одинарные фильтры — «всё».
 */
export function pairCoversMessage(
  left: string,
  right: string,
  m: AgentDialogueMessage
): boolean {
  if (!left.trim() || !right.trim()) {
    return true;
  }
  const ft: string = endpointTypeForLink(m.fromAgent);
  const tt: string = endpointTypeForLink(m.toAgent);
  if (new Set([left, right]).size < 2) {
    return ft === left || tt === left;
  }
  return new Set([left, right]).size === 2 && new Set([ft, tt]).size === 2
    && left !== right
    && new Set([ft, tt]).has(left) && new Set([ft, tt]).has(right);
}

export function deriveAgentLinkKeysFromTrace(
  rows: readonly Record<string, unknown>[]
): readonly AgentLinkKey[] {
  const seen: Set<string> = new Set();
  const acc: AgentLinkKey[] = [];
  for (const r of rows) {
    const fa: string = strField(r, "from_agent");
    const ta: string = strField(r, "to_agent");
    if (!ta || ta === "null" || !fa) {
      continue;
    }
    if (fa.startsWith("User:") || fa.startsWith("User:desktop")) {
      continue;
    }
    const ft: string = endpointTypeForLink(fa);
    const tt: string = agentTypeFromRef(ta);
    if (!tt.startsWith("Agent")) {
      continue;
    }
    if (ft !== "Broker" && !ft.startsWith("Agent")) {
      continue;
    }
    const k: string = `${ft}→${tt}`;
    if (!seen.has(k)) {
      seen.add(k);
      acc.push({ fromType: ft, toType: tt });
    }
  }
  return acc;
}
