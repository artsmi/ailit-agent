import {
  buildBashLineDelta,
  callIdForBashEvent,
  extractToolEventInner,
  formatToolEventForConsole,
  isBashEventName
} from "../components/chat/shellEventFormat";
import { RuntimeTraceNormalizer, type NormalizedTraceProjection } from "./traceNormalize";

export type ChatLine = {
  readonly id: string;
  readonly from: "user" | "assistant" | "system";
  readonly text: string;
  readonly atIso: string;
  /** Порядок появления в trace (стабильная сортировка в UI). */
  readonly order: number;
  /** Сообщение-консоль (tool/shell) — рендер как в minimalist candy ref. */
  readonly lineKind?: "message" | "console" | "reasoning" | "plan";
  readonly consoleShell?: string;
  /** Для console: shell/bash vs служебные tool.* */
  readonly consoleChannel?: "shell" | "tool";
};

export type ToolApprovalPending = {
  readonly callId: string;
  readonly tool: string;
};

export type ContextFillState = {
  readonly turnId: string;
  readonly model: string;
  readonly usageState: "estimated" | "confirmed";
  readonly estimatedContextTokens: number;
  readonly confirmedContextTokens: number | null;
  readonly effectiveContextLimit: number;
  readonly modelContextLimit: number;
  readonly reservedOutputTokens: number;
  readonly contextUsagePercent: number;
  readonly warningState: "normal" | "warning" | "compact_recommended" | "overflow_risk";
  readonly breakdown: Readonly<Record<string, number>>;
};

export type ChatTraceProjection = {
  readonly chatLines: readonly ChatLine[];
  readonly agentTurnInProgress: boolean;
  readonly permModeLabel: string | null;
  readonly permModeGateId: string | null;
  readonly toolApproval: ToolApprovalPending | null;
  readonly contextFill: ContextFillState | null;
  readonly normalizedRows: readonly NormalizedTraceProjection[];
};

type ChatTopicEvent = {
  readonly eventName: string;
  readonly inner: Record<string, unknown>;
};

const normalizer: RuntimeTraceNormalizer = new RuntimeTraceNormalizer();

function asDict(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return null;
}

function nfc(s: string): string {
  return s.normalize("NFC");
}

export function chatLineId(kind: "user" | "assistant" | "system", messageId: string): string {
  return `${kind}:${messageId}`;
}

/** ID строки тела ассистента: до первого `run_shell` с текстом — `assistant:…`, далее `asst-frag:…`. */
function assistantStreamLineId(assistantMessageId: string, part: number): string {
  if (part <= 0) {
    return chatLineId("assistant", assistantMessageId);
  }
  return `asst-frag:${assistantMessageId}:p${String(part)}`;
}

/** Событие `topic.publish` / chat: event_name + внутренний payload. */
export function readChatTopicEvent(row: Record<string, unknown>): ChatTopicEvent | null {
  if (row["type"] !== "topic.publish") {
    return null;
  }
  const pl: Record<string, unknown> | null = asDict(row["payload"]);
  if (!pl || pl["type"] !== "topic.publish") {
    return null;
  }
  const en: unknown = pl["event_name"];
  const inner: Record<string, unknown> | null = asDict(pl["payload"]);
  if (typeof en !== "string" || !inner) {
    return null;
  }
  return { eventName: en, inner };
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

function setLine(lines: Map<string, ChatLine>, line: ChatLine): void {
  const found: ChatLine | undefined = lines.get(line.id);
  lines.set(line.id, found ? { ...line, order: found.order } : line);
}

function appendLine(lines: Map<string, ChatLine>, line: ChatLine): void {
  if (!lines.has(line.id)) {
    lines.set(line.id, line);
  }
}

function shouldMarkTurnActive(eventName: string): boolean {
  return (
    eventName === "model.request" ||
    eventName === "model.response" ||
    eventName === "session.waiting_approval" ||
    eventName === "tool.call_started" ||
    eventName === "tool.batch" ||
    eventName.startsWith("bash.")
  );
}

function readApprovalResolve(row: Record<string, unknown>): { readonly callId: string; readonly ok: boolean | null } | null {
  if (row["type"] !== "service.request") {
    return null;
  }
  const payload: Record<string, unknown> | null = asDict(row["payload"]);
  if (!payload || payload["action"] !== "work.approval_resolve") {
    return null;
  }
  const callId: unknown = payload["call_id"];
  if (typeof callId !== "string" || callId.length === 0) {
    return null;
  }
  const ok: unknown = row["ok"];
  return { callId, ok: typeof ok === "boolean" ? ok : null };
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function warningState(v: unknown): ContextFillState["warningState"] {
  const s: string = str(v);
  if (s === "warning" || s === "compact_recommended" || s === "overflow_risk") {
    return s;
  }
  return "normal";
}

function numericBreakdown(v: unknown): Readonly<Record<string, number>> {
  const d: Record<string, unknown> | null = asDict(v);
  const out: Record<string, number> = {};
  if (!d) {
    return out;
  }
  for (const [k, raw] of Object.entries(d)) {
    const n: number | null = num(raw);
    if (n !== null) {
      out[k] = n;
    }
  }
  return out;
}

function contextSnapshotFromInner(inner: Record<string, unknown>): ContextFillState | null {
  if (inner["schema"] !== "context.snapshot.v1") {
    return null;
  }
  const turnId: string = str(inner["turn_id"]);
  const model: string = str(inner["model"]);
  const estimated: number | null = num(inner["estimated_context_tokens"]);
  const effective: number | null = num(inner["effective_context_limit"]);
  const modelLimit: number | null = num(inner["model_context_limit"]);
  const reserved: number | null = num(inner["reserved_output_tokens"]);
  const pct: number | null = num(inner["context_usage_percent"]);
  if (!turnId || estimated === null || effective === null || modelLimit === null || reserved === null) {
    return null;
  }
  return {
    turnId,
    model,
    usageState: "estimated",
    estimatedContextTokens: estimated,
    confirmedContextTokens: null,
    effectiveContextLimit: effective,
    modelContextLimit: modelLimit,
    reservedOutputTokens: reserved,
    contextUsagePercent: pct ?? 0,
    warningState: warningState(inner["warning_state"]),
    breakdown: numericBreakdown(inner["breakdown"])
  };
}

function applyConfirmedUsage(
  cur: ContextFillState | null,
  inner: Record<string, unknown>
): ContextFillState | null {
  if (inner["schema"] !== "context.provider_usage_confirmed.v1" || cur === null) {
    return cur;
  }
  const confirmed: number | null = num(inner["confirmed_context_tokens"]);
  const nextPct: number =
    confirmed === null
      ? cur.contextUsagePercent
      : Math.round((confirmed / Math.max(1, cur.effectiveContextLimit)) * 10000) / 100;
  return {
    ...cur,
    usageState: "confirmed",
    confirmedContextTokens: confirmed,
    contextUsagePercent: nextPct
  };
}

export function projectChatTraceRows(
  rows: readonly Record<string, unknown>[],
  opts: { readonly suppressedToolApprovalCallId?: string | null } = {}
): ChatTraceProjection {
  const lines: Map<string, ChatLine> = new Map();
  const normalizedRows: NormalizedTraceProjection[] = [];
  const streamTextByLineId: Map<string, string> = new Map();
  const bashTextByCallId: Map<string, string> = new Map();
  const bashOrderByCallId: Map<string, number> = new Map();
  const runShellSplitDoneCallIds: Set<string> = new Set();
  const asstPartByMsg: Map<string, number> = new Map();
  let openReasoningLineId: string | null = null;
  let nextReasoningSeg: number = 0;
  let agentTurnInProgress: boolean = false;
  let permModeLabel: string | null = null;
  let permModeGateId: string | null = null;
  let toolApproval: ToolApprovalPending | null = null;
  let contextFill: ContextFillState | null = null;

  const closeReasoningSegment: () => void = (): void => {
    if (openReasoningLineId !== null) {
      openReasoningLineId = null;
      nextReasoningSeg += 1;
    }
  };

  for (let index: number = 0; index < rows.length; index += 1) {
    const row: Record<string, unknown> = rows[index]!;
    const order: number = index + 1;
    const n: NormalizedTraceProjection = normalizer.normalizeLine(row);
    normalizedRows.push(n);
    const approvalResolve: { readonly callId: string; readonly ok: boolean | null } | null =
      readApprovalResolve(row);
    if (approvalResolve && toolApproval?.callId === approvalResolve.callId) {
      toolApproval = null;
      if (approvalResolve.ok === false) {
        agentTurnInProgress = false;
      }
    }
    const ev: ChatTopicEvent | null = readChatTopicEvent(row);
    if (ev) {
      if (ev.eventName === "context.snapshot") {
        contextFill = contextSnapshotFromInner(ev.inner) ?? contextFill;
      } else if (ev.eventName === "context.provider_usage_confirmed") {
        contextFill = applyConfirmedUsage(contextFill, ev.inner);
      }
      if (shouldMarkTurnActive(ev.eventName)) {
        agentTurnInProgress = true;
      }
      if (ev.eventName === "session.cancelled") {
        agentTurnInProgress = false;
        toolApproval = null;
        closeReasoningSegment();
      } else if (ev.eventName === "session.perm_mode.settled") {
        const pm: unknown = ev.inner["perm_mode"];
        permModeLabel = typeof pm === "string" ? pm : "—";
        permModeGateId = null;
      } else if (ev.eventName === "session.perm_mode.need_user_choice") {
        const gateId: unknown = ev.inner["gate_id"];
        if (typeof gateId === "string" && gateId.length > 0) {
          permModeGateId = gateId;
        }
      } else if (ev.eventName === "session.waiting_approval") {
        const callId: unknown = ev.inner["call_id"];
        const tool: unknown = ev.inner["tool"];
        if (typeof callId === "string" && callId.length > 0) {
          toolApproval = {
            callId,
            tool: typeof tool === "string" && tool.length > 0 ? tool : "tool"
          };
        }
      } else if (ev.eventName === "tool.call_finished") {
        const callId: unknown = ev.inner["call_id"];
        if (typeof callId === "string" && toolApproval?.callId === callId) {
          toolApproval = null;
        }
      }
    }

    if (n.kind === "user_prompt") {
      agentTurnInProgress = true;
      openReasoningLineId = null;
      nextReasoningSeg = 0;
      streamTextByLineId.clear();
      bashTextByCallId.clear();
      bashOrderByCallId.clear();
      runShellSplitDoneCallIds.clear();
      asstPartByMsg.clear();
      appendLine(lines, {
        id: chatLineId("user", n.messageId),
        from: "user",
        text: n.humanLine,
        atIso: n.createdAt || new Date(0).toISOString(),
        order
      });
    } else if (n.kind === "assistant_delta") {
      closeReasoningSegment();
      agentTurnInProgress = true;
      const part: number = asstPartByMsg.get(n.messageId) ?? 0;
      const id: string = assistantStreamLineId(n.messageId, part);
      const prevText: string = streamTextByLineId.get(id) ?? "";
      const nextText: string = nextStreamLineText(n.textMode, prevText, n.humanLine);
      streamTextByLineId.set(id, nextText);
      setLine(lines, {
        id,
        from: "assistant",
        text: nextText,
        atIso: n.createdAt || new Date(0).toISOString(),
        order
      });
    } else if (n.kind === "assistant_thinking_delta") {
      agentTurnInProgress = true;
      const mid: string = n.messageId;
      const lineId: string =
        openReasoningLineId ?? `assistant-think:${mid}:s${String(nextReasoningSeg)}`;
      openReasoningLineId = lineId;
      const prevText: string = streamTextByLineId.get(lineId) ?? "";
      const nextText: string = nextStreamLineText(n.textMode, prevText, n.humanLine);
      streamTextByLineId.set(lineId, nextText);
      setLine(lines, {
        id: lineId,
        from: "assistant",
        text: nextText,
        atIso: n.createdAt || new Date(0).toISOString(),
        lineKind: "reasoning",
        order
      });
    } else if (n.kind === "assistant_final") {
      closeReasoningSegment();
      agentTurnInProgress = false;
      const messageId: string = n.messageId;
      const asstId: string = chatLineId("assistant", messageId);
      const removed: ChatLine[] = [...lines.values()].filter(
        (c) => c.id === asstId || c.id.startsWith(`asst-frag:${messageId}:`)
      );
      for (const c of removed) {
        lines.delete(c.id);
      }
      const orderFinal: number = removed.length > 0 ? Math.min(...removed.map((c) => c.order)) : order;
      lines.set(asstId, {
        id: asstId,
        from: "assistant",
        text: nfc(n.humanLine),
        atIso: n.createdAt || new Date(0).toISOString(),
        order: orderFinal
      });
      asstPartByMsg.set(messageId, 0);
    } else if (n.kind === "micro_plan" || n.kind === "verify_result") {
      closeReasoningSegment();
      if (n.kind === "micro_plan") {
        agentTurnInProgress = true;
      }
      appendLine(lines, {
        id: `${n.kind}:${n.messageId}:${String(order)}`,
        from: "assistant",
        text: n.humanLine,
        atIso: n.createdAt || new Date(0).toISOString(),
        lineKind: "plan",
        order
      });
    } else if (n.kind === "turn_completed") {
      agentTurnInProgress = false;
    } else if (n.kind === "turn_failed") {
      agentTurnInProgress = false;
      closeReasoningSegment();
      appendLine(lines, {
        id: chatLineId("system", `failed-${n.messageId}`),
        from: "system",
        text: n.humanLine,
        atIso: n.createdAt || new Date(0).toISOString(),
        order
      });
    } else if (n.kind === "error_row") {
      agentTurnInProgress = false;
      closeReasoningSegment();
      appendLine(lines, {
        id: chatLineId("system", n.messageId),
        from: "system",
        text: n.humanLine,
        atIso: n.createdAt || new Date(0).toISOString(),
        order
      });
    } else if (n.kind === "tool_event") {
      closeReasoningSegment();
      const evName: string = n.humanLine.trim();
      const inner: Record<string, unknown> = extractToolEventInner(n.raw);
      const toolName: string = String(inner["tool"] ?? "");
      if (evName === "tool.call_started" && toolName === "run_shell") {
        const callId: string = callIdForBashEvent(inner, n.messageId);
        if (!bashOrderByCallId.has(callId)) {
          bashOrderByCallId.set(callId, order);
        }
        const am: string = String(inner["message_id"] ?? "");
        if (am.length > 0 && !runShellSplitDoneCallIds.has(callId)) {
          runShellSplitDoneCallIds.add(callId);
          const p0: number = asstPartByMsg.get(am) ?? 0;
          const sk0: string = assistantStreamLineId(am, p0);
          if ((streamTextByLineId.get(sk0) ?? "").length > 0) {
            asstPartByMsg.set(am, p0 + 1);
          }
        }
        continue;
      }
      if (evName === "tool.call_finished" && toolName === "run_shell" && inner["ok"] !== false) {
        continue;
      }
      const isShellChannel: boolean = /bash|tool\.(bash|sh)|^bash\./i.test(evName);
      if (isShellChannel && isBashEventName(evName)) {
        const callId: string = callIdForBashEvent(inner, n.messageId);
        const lineId: string = `console:bash:call:${callId}`;
        const prev: string = bashTextByCallId.get(callId) ?? "";
        const { next, didChange }: { next: string; didChange: boolean } = buildBashLineDelta(
          evName,
          inner,
          prev
        );
        bashTextByCallId.set(callId, next);
        if (next.length > 0 && (didChange || !lines.has(lineId))) {
          setLine(lines, {
            id: lineId,
            from: "assistant",
            text: next,
            atIso: n.createdAt || new Date(0).toISOString(),
            lineKind: "console",
            consoleShell: "bash",
            consoleChannel: "shell",
            order: bashOrderByCallId.get(callId) ?? order
          });
        }
      } else {
        const body: string = formatToolEventForConsole(evName, inner) || evName;
        const isShell: boolean = isShellChannel;
        appendLine(lines, {
          id: `console:${n.messageId}:${evName}`,
          from: "assistant",
          text: body,
          atIso: n.createdAt || new Date(0).toISOString(),
          lineKind: "console",
          consoleShell: isShell && /bash/i.test(evName) ? "bash" : "sh",
          consoleChannel: isShell ? "shell" : "tool",
          order
        });
      }
    }
  }

  if (opts.suppressedToolApprovalCallId && toolApproval?.callId === opts.suppressedToolApprovalCallId) {
    toolApproval = null;
  }

  return {
    chatLines: [...lines.values()].sort((a, b) => {
      const d: number = a.order - b.order;
      if (d !== 0) {
        return d;
      }
      return a.atIso.localeCompare(b.atIso);
    }),
    agentTurnInProgress,
    permModeLabel,
    permModeGateId,
    toolApproval,
    contextFill,
    normalizedRows
  };
}
