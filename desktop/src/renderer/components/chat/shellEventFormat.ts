/**
 * Читаемая проекция bash/tool событий из topic.publish (без сырого JSON в чате).
 */

/**
 * Внутренний payload события topic.publish: payload.payload.
 */
export function extractToolEventInner(raw: Readonly<Record<string, unknown>>): Record<string, unknown> {
  const top = raw["payload"];
  if (top == null || typeof top !== "object" || Array.isArray(top)) {
    return {};
  }
  const pl = top as Record<string, unknown>;
  if (pl["type"] === "topic.publish" && pl["payload"] != null && typeof pl["payload"] === "object" && !Array.isArray(pl["payload"])) {
    return pl["payload"] as Record<string, unknown>;
  }
  return {};
}

/**
 * Снимает питоновский b'...' / лишние кавычки в stdout из chunk.
 */
export function normalizeBashOutputChunk(s: string): string {
  const t: string = s.trim();
  if (t.length === 0) {
    return "";
  }
  if (t.startsWith("b'") && t.length > 2) {
    const unquote: string = t.slice(2);
    if (unquote.endsWith("'")) {
      return unquote.slice(0, -1).replace(/\\n/g, "\n").replace(/\\'/g, "'") + (s.endsWith("\n") ? "\n" : "");
    }
  }
  if (t.startsWith("b\"") && t.length > 2) {
    const u: string = t.slice(2);
    if (u.endsWith("\"")) {
      return u.slice(0, -1).replace(/\\n/g, "\n") + (s.endsWith("\n") ? "\n" : "");
    }
  }
  return s;
}

/**
 * true — события bash.*, объединяем в один блок по call_id.
 */
export function isBashEventName(humanEventName: string): boolean {
  return /^bash\./i.test(humanEventName.trim());
}

/**
 * Сводка длину для не-bash tool.* без длинного JSON.
 */
export function shortToolLine(eventName: string, inner: Readonly<Record<string, unknown>>): string {
  if (Object.keys(inner).length === 0) {
    return eventName;
  }
  if (eventName === "tool.run" && typeof inner["name"] === "string") {
    return `${eventName} — ${inner["name"] as string}`;
  }
  if (eventName === "tool.result" && typeof inner["ok"] === "boolean") {
    return `${eventName} — ${(inner["ok"] as boolean) ? "ok" : "error"}`;
  }
  return eventName;
}

const TOOL_FOR_CONSOLE_SKIP: ReadonlySet<string> = new Set([
  "call_id",
  "message_id",
  "type",
  "messageId",
  "tool",
  "ok"
]);

const TOOL_FOR_CONSOLE_PREFERRED: readonly string[] = [
  "name",
  "relative_path",
  "file_change_kind",
  "text",
  "message",
  "detail",
  "path",
  "error",
  "reason"
];

/**
 * Многострочный текст для консольного блока tool.* (тот же парсер, что и для shell).
 */
export function formatToolEventForConsole(eventName: string, inner: Readonly<Record<string, unknown>>): string {
  const tool: string = typeof inner["tool"] === "string" ? (inner["tool"] as string) : "";
  const baseFirst: string = tool ? `${eventName} — ${tool}` : eventName;
  const fail: boolean = eventName === "tool.call_finished" && inner["ok"] === false;
  const first: string = fail ? `FAIL: ${baseFirst}` : baseFirst;
  const out: string[] = [];
  const used: Set<string> = new Set(TOOL_FOR_CONSOLE_SKIP);
  const clip: (s: string, m: number) => string = (s: string, m: number): string =>
    s.length > m ? `${s.slice(0, m)}…` : s;
  const addLine: (k: string, v: string | number | boolean) => void = (k: string, v: string | number | boolean): void => {
    if (k === "name" && typeof v === "string" && v === tool) {
      used.add("name");
      return;
    }
    const t: string = String(v);
    if (k === "error" || t.includes("\n")) {
      out.push(clip(t, 4000));
    } else {
      out.push(clip(t, 2000));
    }
    used.add(k);
  };
  for (const k of TOOL_FOR_CONSOLE_PREFERRED) {
    const v: unknown = inner[k];
    if (v == null) {
      continue;
    }
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      addLine(k, v);
    }
  }
  for (const k of Object.keys(inner).sort()) {
    if (used.has(k)) {
      continue;
    }
    const v: unknown = inner[k];
    if (v == null) {
      continue;
    }
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      if (k === "ok" && (v === true || v === "true")) {
        continue;
      }
      addLine(k, v);
    }
  }
  if (inner["ok"] === false) {
    const haveErr: boolean = typeof inner["error"] === "string" && (inner["error"] as string).length > 0;
    if (!haveErr) {
      out.push("Сбой выполнения");
    }
  }
  if (out.length === 0) {
    return first;
  }
  return [first, ...out].join("\n");
}

export function buildBashLineDelta(
  eventName: string,
  inner: Readonly<Record<string, unknown>>,
  accBefore: string
): { readonly next: string; readonly didChange: boolean } {
  if (eventName === "bash.execution") {
    const rawCmd: string = String(inner["command"] ?? "").trim() || "…";
    const firstLine: string = (accBefore.split(/\r?\n/)[0] ?? "").replace(/^\s*▸\s+/, "");
    if (firstLine.trim() === rawCmd.trim() && accBefore.length > 0) {
      return { next: accBefore, didChange: false };
    }
    if (accBefore.length === 0) {
      return { next: `${rawCmd}\n\n`, didChange: true };
    }
    return { next: `${rawCmd}\n\n${accBefore}`, didChange: true };
  }
  if (eventName === "bash.output_delta") {
    const chunk: string = inner["chunk"] == null ? "" : normalizeBashOutputChunk(String(inner["chunk"]));
    if (chunk.length === 0) {
      return { next: accBefore, didChange: false };
    }
    return { next: accBefore + chunk, didChange: true };
  }
  if (eventName === "bash.finished" || /bash\.(end|close)/i.test(eventName)) {
    const ok: boolean = inner["ok"] === true;
    if (ok && /(^|\n)—\nГотово\s*$/.test(accBefore)) {
      return { next: accBefore, didChange: false };
    }
    if (ok) {
      return { next: accBefore + "\n\n—\nГотово", didChange: true };
    }
    return { next: accBefore + "\n\n—\nОшибка: " + String(inner["error"] ?? "—"), didChange: true };
  }
  if (isBashEventName(eventName)) {
    if (Object.keys(inner).length === 0) {
      return { next: accBefore, didChange: false };
    }
    return { next: accBefore, didChange: false };
  }
  return { next: accBefore, didChange: false };
}

export function callIdForBashEvent(inner: Readonly<Record<string, unknown>>, messageId: string): string {
  const c: unknown = inner["call_id"];
  if (typeof c === "string" && c.length > 0) {
    return c;
  }
  return `msg-${messageId}`;
}
