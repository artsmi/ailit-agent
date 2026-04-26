export type NormalizedKind =
  | "user_prompt"
  | "assistant_response"
  | "assistant_delta"
  | "assistant_thinking_delta"
  | "assistant_final"
  | "tool_event"
  | "usage"
  | "pag"
  | "error_row"
  | "unknown";

export type TextModeTrace = "incremental" | "snapshot";

export type NormalizedTraceProjection = {
  readonly kind: NormalizedKind;
  readonly messageId: string;
  readonly chatId: string;
  readonly namespace: string;
  readonly createdAt: string;
  readonly humanLine: string;
  readonly technicalLine: string;
  readonly raw: Record<string, unknown>;
  readonly redacted: boolean;
  /** Режим `text` из `topic.publish` (agent_core 2026): дельта или снимок. */
  readonly textMode?: TextModeTrace;
};

const SENSITIVE_KEYS: ReadonlySet<string> = new Set([
  "api_key",
  "apikey",
  "token",
  "password",
  "secret",
  "authorization"
]);

function redactObject(value: unknown, depth: number): unknown {
  if (depth > 6) {
    return "[max_depth]";
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const low: string = k.toLowerCase();
      if (SENSITIVE_KEYS.has(low)) {
        out[k] = "[REDACTED]";
      } else {
        out[k] = redactObject(v, depth + 1);
      }
    }
    return out;
  }
  if (Array.isArray(value)) {
    return value.map((x) => redactObject(x, depth + 1));
  }
  return value;
}

function strField(row: Record<string, unknown>, key: string): string {
  const v = row[key];
  return typeof v === "string" ? v : v === null || v === undefined ? "" : String(v);
}

function isResponseRow(row: Record<string, unknown>): boolean {
  return typeof row["ok"] === "boolean" && "payload" in row;
}

function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function readTextMode(inner: Record<string, unknown>): TextModeTrace | undefined {
  const t: unknown = inner["text_mode"];
  if (t === "incremental" || t === "snapshot") {
    return t;
  }
  return undefined;
}

function normalizeTopicPublish(row: Record<string, unknown>): { readonly eventName: string; readonly payload: Record<string, unknown> } | null {
  const pl = asDict(row["payload"]);
  if (!pl || pl["type"] !== "topic.publish") {
    return null;
  }
  const eventName: unknown = pl["event_name"];
  const inner: Record<string, unknown> | null = asDict(pl["payload"]);
  if (typeof eventName !== "string" || !inner) {
    return null;
  }
  return { eventName, payload: inner };
}

/**
 * Нормализация `ailit_agent_runtime_v1` JSON-line row → проекция UI (G9.5.3).
 */
export class RuntimeTraceNormalizer {
  public normalizeLine(row: Record<string, unknown>): NormalizedTraceProjection {
    const redactedRaw = redactObject(row, 0) as Record<string, unknown>;
    const messageId: string = strField(row, "message_id") || strField(row, "messageId") || `anon-${strField(row, "created_at")}`;
    const chatId: string = strField(row, "chat_id");
    const namespace: string = strField(row, "namespace");
    const createdAt: string = strField(row, "created_at");
    const typ: string = strField(row, "type");
    const fromAgent: string = strField(row, "from_agent");
    const toAgent: string | null = typeof row["to_agent"] === "string" || row["to_agent"] === null ? (row["to_agent"] as string | null) : strField(row, "to_agent") || null;
    if (typ === "topic.publish") {
      const tp = normalizeTopicPublish(row);
      if (tp) {
        const innerMid: string = typeof tp.payload["message_id"] === "string" ? (tp.payload["message_id"] as string) : messageId;
        const txt: string = typeof tp.payload["text"] === "string" ? (tp.payload["text"] as string) : "";
        if (tp.eventName === "assistant.delta") {
          return {
            kind: "assistant_delta",
            messageId: innerMid,
            chatId,
            namespace,
            createdAt,
            humanLine: txt,
            technicalLine: "assistant.delta",
            raw: redactedRaw,
            redacted: true,
            textMode: readTextMode(tp.payload)
          };
        }
        if (tp.eventName === "assistant.thinking") {
          return {
            kind: "assistant_thinking_delta",
            messageId: innerMid,
            chatId,
            namespace,
            createdAt,
            humanLine: txt,
            technicalLine: "assistant.thinking",
            raw: redactedRaw,
            redacted: true,
            textMode: readTextMode(tp.payload)
          };
        }
        if (tp.eventName === "assistant.final") {
          return {
            kind: "assistant_final",
            messageId: innerMid,
            chatId,
            namespace,
            createdAt,
            humanLine: txt,
            technicalLine: "assistant.final",
            raw: redactedRaw,
            redacted: true
          };
        }
        if (tp.eventName === "model.response") {
          return {
            kind: "usage",
            messageId: innerMid,
            chatId,
            namespace,
            createdAt,
            humanLine: "usage",
            technicalLine: JSON.stringify(redactObject(tp.payload["usage"] ?? {}, 0)).slice(0, 200),
            raw: redactedRaw,
            redacted: true
          };
        }
        if (tp.eventName.startsWith("tool.") || tp.eventName.startsWith("bash.")) {
          return {
            kind: "tool_event",
            messageId: innerMid,
            chatId,
            namespace,
            createdAt,
            humanLine: tp.eventName,
            technicalLine: JSON.stringify(redactObject(tp.payload, 0)).slice(0, 200),
            raw: redactedRaw,
            redacted: true
          };
        }
      }
    }
    if (isResponseRow(row) && (typ === "action.start" || typ === "service.request" || typ === "topic.publish")) {
      const ok: boolean = Boolean((row as { ok?: boolean }).ok);
      const pl = (row as { payload?: unknown }).payload;
      const plobj = pl && typeof pl === "object" && !Array.isArray(pl) ? (pl as Record<string, unknown>) : {};
      return {
        kind: ok ? "assistant_response" : "error_row",
        messageId,
        chatId,
        namespace,
        createdAt,
        humanLine: ok
          ? `Answer: action=${String(plobj["action"] ?? "response")} ok=true`
          : `Error: ${
              (() => {
                const er: unknown = (row as { error?: unknown }).error;
                if (er && typeof er === "object" && !Array.isArray(er)) {
                  return strField(er as Record<string, unknown>, "message");
                }
                return "request failed";
              })()
            }`,
        technicalLine: `type=${typ} ok=${ok}`,
        raw: redactedRaw,
        redacted: true
      };
    }
    if (strField(row, "type") === "action.start") {
      const pl = row["payload"] && typeof row["payload"] === "object" && !Array.isArray(row["payload"])
        ? (row["payload"] as Record<string, unknown>)
        : {};
      const action: string = String(pl["action"] ?? "");
      const prompt: string = String(pl["prompt"] ?? pl["text"] ?? "");
      if (fromAgent.includes("User") || fromAgent === "User:desktop") {
        return {
          kind: "user_prompt",
          messageId,
          chatId,
          namespace,
          createdAt,
          humanLine: prompt || "user action",
          technicalLine: `action.start ${action}`,
          raw: redactedRaw,
          redacted: true
        };
      }
    }
    if (typ.toLowerCase().includes("usage") || strField(row, "type") === "usage") {
      return {
        kind: "usage",
        messageId,
        chatId,
        namespace,
        createdAt,
        humanLine: "usage",
        technicalLine: JSON.stringify(redactObject((row as { payload?: unknown }).payload ?? {}, 0)).slice(0, 200),
        raw: redactedRaw,
        redacted: true
      };
    }
    if (typ.toLowerCase().includes("tool") || strField(row, "type").includes("tool")) {
      return {
        kind: "tool_event",
        messageId,
        chatId,
        namespace,
        createdAt,
        humanLine: "tool",
        technicalLine: `${fromAgent} → ${toAgent ?? "?"}`,
        raw: redactedRaw,
        redacted: true
      };
    }
    if (strField(row, "type").includes("memory") || strField(row, "type").includes("pag")) {
      return {
        kind: "pag",
        messageId,
        chatId,
        namespace,
        createdAt,
        humanLine: "PAG / memory",
        technicalLine: typ,
        raw: redactedRaw,
        redacted: true
      };
    }
    return {
      kind: "unknown",
      messageId,
      chatId,
      namespace,
      createdAt,
      humanLine: "unknown event",
      technicalLine: `${typ} ${fromAgent}→${toAgent ?? ""}`.trim(),
      raw: redactedRaw,
      redacted: true
    };
  }
}

/**
 * Стабильный ключ дедупликации: message_id, иначе json canonical (ограниченно).
 */
export function dedupKeyForRow(row: Record<string, unknown>): string {
  const mid: string = strField(row, "message_id");
  if (mid) {
    return `id:${mid}`;
  }
  try {
    return `hash:${JSON.stringify(row).slice(0, 2000)}`;
  } catch {
    return `t:${strField(row, "created_at")}`;
  }
}
